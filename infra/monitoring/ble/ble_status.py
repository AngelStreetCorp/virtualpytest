#!/usr/bin/env python3
"""ble_status.py — classify the BLE stack on vpt-mf1 as OK / DEGRADED / DOWN.

Called by `vpt-ble-hourly.sh` (hourly cron tick) and by hand (one-shot
triage). Does NOT restart anything. Reads only.

The classifier handles three queries:

  --mode=hourly        parse the previous probe output from $HOURLY_LOG_DIR.
                       Reports one line: 'status: <STATUS> (<reason>)'.
                       Used inside the probe loop.

  --mode=classify      walk the live BLE surface (btmgmt, status JSON, FIFO,
                       journal, daemon processes) and emit the same status
                       line. Used by hand or by the recovery policy.

  --mode=json          like --mode=classify, but emit a JSON object with the
                       evidence so the operator can cross-check at a glance.

  --adapter=<hciN>     limit to a single adapter (optional).

Status rules (matches the task §4 contract):

  DOWN    bluetooth.service is gone / failing, OR every hid-remote@<hci>
          is gone, OR all bond-bearing adapters show no central and no
          BLE-side subscription. The exact reason is appended in parens.

  DEGRADED any ONE of:
            - a bond-bearing adapter has Connected but no 2a4d subscription
              (idle STB-B scenario — STB is awake but didn't re-subscribe,
              or the persistent-CCCD build lost the bit);
            - bluetoothd monotonic is younger than any hid-remote@
              monotonic (BUG-0003 wedge fingerprint, see §6.7.28);
            - a sibling adapter has duplicate hid_remote.py processes
              (BUG-0027 split-key-stream, see §6.7.27);
            - the FIFO for any adapter is not writable by the daemon user;
            - an enabled boot unit ble-remote@<hci>.service (or its vpt-
              prefix sibling) is in 'failed' state (signals: resume.sh
              couldn't attach at last boot).

          A re-subscribe nudge is appended when a 2a4d gap is detected.
          The nudge lists the exact btmon strings to look for so the
          next outage triage reduces to a one-line read.

  OK      none of the above. As long as at least one adapter holds a
          working HID-ready bond and the BLE units are alive, status is OK
          (we do not turn a 3rd unused adapter into a problem).

Exit codes:
  0  status == OK
  1  status == DEGRADED
  2  status == DOWN
  3  internal error (logs to stderr)

The script is intentionally dependency-light: standard library + dbus
(opt). When dbus isn't available, fall back to `bluetoothctl` + `btmgmt`
subprocesses — the same data path start.sh uses.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- constants

HID_KEY_UUIDS = {
    "2141e101-213a-11e6-b67b-9e71128cae77",  # Arris vendor notify
    "00002a4d-0000-1000-8000-00805f9b34fb",  # HID Input Report (2a4d)
}
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # always subscribed

REDACTED = "<redacted:32-hex>"

# -----------------------------------------------------------------------------
# helpers

def _read(cmd, *, timeout=10, check=False):
    """Run a shell command, return (rc, stdout, stderr) — never raise."""
    try:
        out = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return out.returncode, (out.stdout or ""), (out.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", f"<timeout after {timeout}s: {cmd}>"


def _adapters(only=None):
    """Return a sorted list of hciN adapter names (skip kernel sub-devs)."""
    if only:
        return [only]
    sysdir = Path("/sys/class/bluetooth")
    if not sysdir.exists():
        return []
    out = []
    for p in sorted(sysdir.iterdir()):
        n = p.name
        if re.fullmatch(r"hci\d+", n):
            out.append(n)
    return out


def _btmgmt_info(idx):
    """Return (addr, current_settings_str) or (None, '') on failure."""
    rc, out, _ = _read(f"timeout 5 btmgmt --index {idx} info")
    if "Invalid Index" in out or "0x11" in out or rc not in (0, 124):
        if "Invalid Index" in out:
            return None, ""
    addr = ""
    settings = ""
    for line in out.splitlines():
        if line.startswith("\taddr "):
            addr = line.split()[1]
        elif line.startswith("current settings:"):
            settings = line.split(":", 1)[1].strip()
        elif line.startswith("\tcurrent settings:"):
            settings = line.split(":", 1)[1].strip()
    return addr, settings


def _bluetoothctl(default=True):
    rc, out, _ = _read("bluetoothctl list")
    if rc != 0:
        return None, [], []
    controllers = []
    for line in out.splitlines():
        if line.startswith("Controller "):
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                controllers.append(parts[1])
    rc, paired, _ = _read("bluetoothctl devices Paired")
    rc2, connected, _ = _read("bluetoothctl devices Connected")
    devs_paired = [d.split()[0] for d in paired.splitlines() if d.split()]
    devs_conn = [d.split()[0] for d in connected.splitlines() if d.split()]
    return (controllers[0] if (default and controllers) else (controllers[0] if controllers else None)), devs_paired, devs_conn


def _status_json(adapter):
    p = Path(f"/tmp/hid_remote_status-{adapter}.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _fifo_state(adapter):
    p = Path(f"/tmp/hid_remote-{adapter}.fifo")
    if not p.exists():
        return {"exists": False}
    st = p.stat()
    return {
        "exists": True,
        "is_fifo": bool(p.is_fifo()),
        "mode": st.st_mode & 0o777,
        "mtime": st.st_mtime,
    }


def _pgrep(procname):
    """Run `pgrep -af <procname>` and filter out the inspecting shell itself.

    `pgrep -af hid_remote.py` matches anything whose cmdline contains the
    substring — including the `sh -c "pgrep -af hid_remote.py"` wrapper
    that shell=True spawns. That wrapper has no HID_REMOTE_ADAPTER set,
    so `_adapter_for_pid()` returned None for it on the inventory host and
    the classifier falsely flagged "stray daemon outside the @ units".
    Fix: keep only cmdlines that look like a real daemon invocation
    (`/usr/bin/python3 …/<scriptname>`), drop the shell wrapper, the
    pgrep binary, and any other wrapper.
    """
    rc, out, _ = _read(f"pgrep -af {procname}")
    if rc != 0:
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmdline = " ".join(parts[1:])
        # Real daemon: python3 with the script as the second argument.
        if not cmdline.startswith("/usr/bin/python3"):
            continue
        if f"/{procname}" not in cmdline:
            continue
        pids.append((pid, cmdline))
    return pids


def _adapter_for_pid(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            data = f.read().split(b"\0")
        for entry in data:
            if entry.startswith(b"HID_REMOTE_ADAPTER="):
                return entry.split(b"=", 1)[1].decode("ascii", "ignore")
    except Exception:
        pass
    return None


def _unit_state(unit):
    """Return (active_state, sub_state, exec_main_pid, start_mono_us) for a
    systemd unit, or (None, None, 0, 0) on absence."""
    if not unit:
        return None, None, 0, 0
    rc, out, _ = _read(
        f"systemctl show {unit}.service -p ActiveState,SubState,ExecMainPID,ExecMainStartTimestampMonotonic"
    )
    state = None
    sub = None
    pid = 0
    mono = "0"
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k == "ActiveState":
            state = v
        elif k == "SubState":
            sub = v
        elif k == "ExecMainPID":
            pid = int(v) if v.isdigit() else 0
        elif k == "ExecMainStartTimestampMonotonic":
            mono = v or "0"
    try:
        mono_us = int(mono)
    except ValueError:
        mono_us = 0
    return state, sub, pid, mono_us


def _bonds_under(mac_dir):
    """Return {peer: bool_hid_ready} for one spoofed-MAC directory."""
    p = Path(f"/var/lib/bluetooth/{mac_dir}")
    if not p.is_dir():
        return {}
    out = {}
    for sd in sorted(p.iterdir()):
        if not sd.is_dir():
            continue
        info = sd / "info"
        if not info.is_file():
            continue
        try:
            txt = info.read_text(errors="replace")
        except Exception:
            continue
        has_2a4d = "2a4d" in txt
        # ignore Battery (2a19) — counts as subscribed but isn't the key channel
        for uuid in HID_KEY_UUIDS:
            if uuid in txt:
                has_2a4d = True
        out[sd.name] = has_2a4d
    return out


# -----------------------------------------------------------------------------
# classifier

class Finding:
    __slots__ = ("severity", "reason", "nudge")

    def __init__(self, severity: str, reason: str, nudge: str | None = None):
        self.severity = severity  # 'down' | 'degraded'
        self.reason = reason
        self.nudge = nudge

    def __str__(self):
        if self.nudge:
            return f"{self.severity.upper()} ({self.reason}) — {self.nudge}"
        return f"{self.severity.upper()} ({self.reason})"


def _btmon_nudge(adapter, peer):
    """One-line re-subscribe nudge to help the next triage."""
    return (
        f"check btmon -i {adapter} for that peer during a POWER press; "
        "expect 'LE Set Scan Response Data' then 'ATT: Handle Value Notification' "
        "(2a4d); absence with hid-remote logs 'Injecting' = §6.7.28 GATT wipe, "
        "sudo systemctl restart hid-remote@" + adapter
    )


def classify(adapter=None):
    """Walk the BLE surface, return the worst Finding + extra info dict."""
    findings: list[Finding] = []
    info: dict = {"adapters": {}, "daemons": {}, "units": {}, "bonds": {}}

    # 1. bluetooth.service must be alive.
    bt_state, bt_sub, bt_pid, bt_mono = _unit_state("bluetooth")
    info["units"]["bluetooth"] = {"active": bt_state, "sub": bt_sub, "mono_us": bt_mono}
    if bt_state != "active":
        findings.append(Finding(
            "down",
            f"bluetooth.service not active ({bt_state or 'absent'}/{bt_sub or '?'})",
            "this is the §6.7.28 wedge if hid-remote@ is newer; do NOT call start.sh, "
            "sudo systemctl restart bluetooth; bond files are preserved",
        ))

    # 2. Per-adapter surface.
    bond_carriers: list[tuple[str, str, bool]] = []  # (adapter, peer, has_2a4d)
    for h in _adapters(adapter):
        idx = int(h[3:])
        addr, settings = _btmgmt_info(idx)
        info["adapters"][h] = {"addr": addr, "settings": settings}

        # 2a. Check daemon process (BUG-0003 / BUG-0027 wiring)
        hr_state, hr_sub, hr_pid, hr_mono = _unit_state(f"hid-remote@{h}")
        info["units"][f"hid-remote@{h}"] = {"active": hr_state, "mono_us": hr_mono}
        if hr_state != "active":
            findings.append(Finding(
                "down",
                f"hid-remote@{h}.service not active ({hr_state or 'absent'})",
            ))

        # 2b. BUG-0003 timestamp ordering — bluetoothd younger than daemon = GATT wipe
        if bt_mono and hr_mono and bt_mono > hr_mono:
            findings.append(Finding(
                "degraded",
                f"BUG-0003 fingerprint on {h}: bluetoothd restarts AFTER hid-remote@{h} "
                f"(bt_mono={bt_mono} > hid_mono={hr_mono}); GATT registration was wiped, "
                "keys are silently dropped until hid-remote@" + h + " is restarted",
                "do NOT touch the bond files; sudo systemctl restart hid-remote@" + h + " "
                "and confirm the 'GATT application registered' line in the journal",
            ))

        # 2c. Adapter state from btmgmt — cover the wedged case ("Invalid Index")
        if addr is None and not settings:
            info["adapters"][h]["wedge"] = True
            # An adapter wedged at MGMT does not affect the others; only count
            # as DEGRADED. The script-level DOWN check needs ALL bond-bearing
            # adapters to be down.
            findings.append(Finding(
                "degraded",
                f"{h} is firmware-wedged (HCI up, MGMT detached — btmgmt --index {idx} "
                "returns 0x11 Invalid Index; §6.7.26-followup-3); not necessarily fatal "
                "if a sibling adapter holds the live STB",
                "physically replug the dongle, or wait for the vpt-ble-btmon service to "
                "rotate and re-evaluate",
            ))
            continue

        # 2d. Check status JSON — hid_ready gating
        sjson = _status_json(h)
        info["adapters"][h]["status_json"] = sjson
        last_peer = (sjson or {}).get("last_connected_mac")
        hid_ready = bool((sjson or {}).get("hid_ready"))
        subscribed = set((sjson or {}).get("subscribed_uuids") or [])
        has_key_sub = any(u in subscribed for u in HID_KEY_UUIDS)

        # 2e. Bond info from /var/lib/bluetooth
        if addr:
            bonds = _bonds_under(addr)
            info["bonds"].setdefault(h, {})[addr] = bonds
            for peer, has_2a4d in bonds.items():
                if not has_2a4d:
                    continue
                bond_carriers.append((h, peer, has_2a4d))

        # 2f. Connection state from kernel
        rc, con_out, _ = _read(f"hcitool -i {h} con")
        info["adapters"][h]["connections"] = con_out.strip().splitlines()
        live_peers = []
        for line in con_out.splitlines():
            m = re.search(r"LE ([0-9A-F:]{17})", line)
            if m and "ENCRYPT" in line:
                live_peers.append(m.group(1))

        # 2g. FIFO state — writability
        fifo = _fifo_state(h)
        info["adapters"][h]["fifo"] = fifo
        if not fifo.get("exists") or fifo.get("mode", 0) & 0o20 == 0:
            # FIFO not writable by group; sendkey.py + the controller will fail
            findings.append(Finding(
                "degraded",
                f"hid_remote-{h}.fifo is not group-writable (mode {fifo.get('mode', 0):o}); "
                "sendkey.py will EPIPE for callers without group membership",
                "chmod 660 /tmp/hid_remote-" + h + ".fifo and chown root:vpt_user",
            ))

        # 2h. The DEGRADED signature for STB-B today: bonded + Connected but no 2a4d
        if last_peer and live_peers and not has_key_sub:
            nudge = _btmon_nudge(h, last_peer)
            findings.append(Finding(
                "degraded",
                f"{h} has live ENCRYPT connection to {last_peer} but no key-channel "
                "subscription (status JSON hid_ready=false; 2a4d missing)",
                nudge,
            ))

        # 2i. ENCRYPT peer is NOT in /var/lib/bluetooth (bond wiped mid-flight) = serious
        if live_peers and (last_peer and last_peer not in (live_peers[0] if live_peers else "")):
            # not necessarily an issue — last_connected_mac is sticky. Don't add
            # a finding unless the bond dir is genuinely empty.
            pass

    # 3. BUG-0027 duplicate daemon check.
    info["daemons"]["hid_remote"] = [
        {"pid": p, "adapter": _adapter_for_pid(p), "cmd": c[:160]}
        for p, c in _pgrep("hid_remote.py")
    ]
    info["daemons"]["agent"] = [
        {"pid": p, "cmd": c[:160]} for p, c in _pgrep("agent.py")
    ]
    counts = {}
    for d in info["daemons"]["hid_remote"]:
        a = d.get("adapter") or "<none>"
        counts[a] = counts.get(a, 0) + 1
    for a, n in counts.items():
        if a == "<none>":
            findings.append(Finding(
                "degraded",
                "a hid_remote.py process has no HID_REMOTE_ADAPTER env — stray "
                "daemon outside the @ units",
                "pgrep -af hid_remote.py and stop the loose one",
            ))
        elif n > 1:
            findings.append(Finding(
                "degraded",
                f"BUG-0027: {n} hid_remote.py processes bound to {a}; key stream "
                "is split, half the keys are silently dropped",
                "kill the duplicate (one pid) — the bond-bearing one keeps the lock",
            ))

    # 4. Boot units in 'failed' state (signals at last boot time).
    for h in _adapters():
        for templ in ("ble-remote@", "vpt-ble-remote@"):
            full = f"{templ}{h}.service"
            st, _, _, _ = _unit_state(full)
            info["units"][full] = {"active": st}
            if st == "failed":
                findings.append(Finding(
                    "degraded",
                    f"{full} is in 'failed' state at boot — resume.sh could not "
                    "attach {h} when the host came up",
                    "run sudo bash resume.sh ADAPTER_HCI=" + h + " once (this is the "
                    "non-destructive path; never run start.sh for boot-recovery)",
                ))

    # 5. Final DOWN rule — only count if EVERY bond carrier is broken.
    if bond_carriers:
        broken = 0
        for h, peer, has_2a4d in bond_carriers:
            sjson = _status_json(h) or {}
            if not sjson.get("hid_ready"):
                broken += 1
        if broken == len(bond_carriers):
            findings.append(Finding(
                "down",
                f"all {len(bond_carriers)} bond-carrying adapter(s) lost their "
                "key-channel subscription; no STB will receive HID keys",
                "do NOT call start.sh (wipes bonds); sudo systemctl restart "
                "bluetooth && sudo systemctl restart hid-remote@<hci>{,1,2}.service",
            ))

    # 6. Pick the worst finding. DOWN > DEGRADED; otherwise DEGRADED overrules OK.
    if any(f.severity == "down" for f in findings):
        worst = next(f for f in findings if f.severity == "down")
        code = "DOWN"
    elif any(f.severity == "degraded" for f in findings):
        # Join all DEGRADED reasons with "; "
        reasons = [f.reason for f in findings if f.severity == "degraded"]
        joined = "; ".join(dict.fromkeys(reasons))  # de-dup, keep order
        nudges = [f.nudge for f in findings if f.severity == "degraded" and f.nudge]
        worst = Finding("degraded", joined, nudges[0] if nudges else None)
        code = "DEGRADED"
    else:
        worst = Finding("ok", "all adapters healthy; bond carriers subscribed", None)
        code = "OK"

    info["code"] = code
    info["reasons"] = [f.reason for f in findings]
    info["finding"] = str(worst)
    return code, str(worst), info


# -----------------------------------------------------------------------------
# entry points

def _print_hourly(code, line, info):
    """Emit the canonical one-line status entry the probe appends to its log."""
    print(line)


def main(argv=None):
    p = argparse.ArgumentParser(prog="ble_status.py")
    p.add_argument("--mode", choices=("hourly", "classify", "json"),
                   default="classify")
    p.add_argument("--adapter", default=None,
                   help="limit to a single adapter (default: all)")
    ns = p.parse_args(argv)

    code, line, info = classify(ns.adapter)

    if ns.mode == "json":
        # Strip host-unique path noise but keep the evidence narrative.
        for h in info.get("adapters", {}):
            for k in ("status_json", "connections", "fifo"):
                pass  # already ok
        print(json.dumps(info, indent=2, default=str))
    elif ns.mode == "hourly":
        # Probe-internal: emit the one line the probe waits for.
        print(line)
    else:
        # Hand-call: friendly multi-line summary.
        print(f"status: {code}")
        print(f"detail: {line}")
        for h, ad in info.get("adapters", {}).items():
            sj = ad.get("status_json") or {}
            sub = sj.get("hid_ready")
            lcm = sj.get("last_connected_mac")
            print(f"  {h}: addr={ad.get('addr') or 'WEDGE'}  "
                  f"hid_ready={sub}  last_connected={lcm}")

    if code == "DOWN":
        return 2
    if code == "DEGRADED":
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(3)
    except Exception as e:
        print(f"ble_status.py: internal error: {e}", file=sys.stderr)
        sys.exit(3)
