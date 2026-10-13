# TASK-76 — hourly BLE health monitoring on vpt-mf1

This folder is the runtime surface for the vpt-mf1 BLE hourly checks. It
ships **read-only** — no service restarts, no bond wipes. The only writes are
to `/var/log/vpt-ble/` and the per-adapter FIFO passes through the existing
daemon, never around it.

## Files

| Path | Purpose |
|---|---|
| `vpt-ble-hourly.sh` | The hourly probe. Modes: `--once` (the cron tick), `--print` (stdout-only dry run), `--post-mortem` (copy + redact to incidents/). |
| `ble_status.py` | The classifier. Reads `btmgmt`, status JSON, FIFO state, journal, daemon processes. Emits `OK` / `DEGRADED(<reason>)` / `DOWN(<reason>)` with a re-subscribe nudge when a bonded adapter is missing its `2a4d` subscription. |
| `vpt-ble-sendkey-test.sh` | Power-on test for one STB. Refuses to send POWER if the box is already awake (BUG-0271 carry-over). Records before/after state in `/var/log/vpt-ble/hourly/sendkey-<TS>.log`. |
| `etc/vpt-ble-hourly.cron` | Cron snippet — `01 * * * *` — installs at `/etc/cron.d/vpt-ble-hourly`. |
| `etc/stb-aliases.conf` | Small table of `<alias>|<hciN>|<peer-MAC>|<description>` rows. Read by `vpt-ble-sendkey-test.sh --list`. |
| `systemd/vpt-ble-hourly.service` | systemd unit alternative to cron — `Type=oneshot`, `Restart=no`, `StandardError=journal`. Triggered by the .timer. |
| `systemd/vpt-ble-hourly.timer` | `OnCalendar=hourly` (persistent), `AccuracySec=1min`, `WantedBy=timers.target`. |
| `systemd/vpt-ble-btmon@.service` | Per-adapter `btmon` ring-buffer (`/var/log/vpt-ble/btmon/hci<N>.bin`, 10 MB cap). Triggered AFTER `vpt-ble-hourly.service` so the wire capture keeps one full tick of evidence. |

## Installation (owner-only)

```bash
# 1. Push the worktree files to /opt/virtualpytest/ on vpt-mf1
rsync -a infra/monitoring/ble/ vpt-mf1:/opt/virtualpytest/infra/monitoring/ble/

# 2. Ensure the deploy user can write the logs (chown by install step)
ssh vpt-mf1 "sudo install -d -m 750 -o root -g vpt_user /var/log/vpt-ble/{hourly,incidents,btmon}"

# 3a. Cron install (owner-direct)
ssh vpt-mf1 "sudo install -m 644 -o root -g root /opt/virtualpytest/infra/monitoring/ble/etc/vpt-ble-hourly.cron /etc/cron.d/vpt-ble-hourly"

# OR

# 3b. systemd alternative
ssh vpt-mf1 "sudo install -m 644 -o root -g root /opt/virtualpytest/infra/monitoring/ble/systemd/vpt-ble-hourly.service /etc/systemd/system/
sudo install -m 644 -o root -g root /opt/virtualpytest/infra/monitoring/ble/systemd/vpt-ble-hourly.timer    /etc/systemd/system/
sudo install -m 644 -o root -g root /opt/virtualpytest/infra/monitoring/ble/systemd/vpt-ble-btmon@.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vpt-ble-hourly.timer
sudo systemctl enable --now vpt-ble-btmon@hci1.service vpt-ble-btmon@hci2.service"

# 4. Smoke-test
ssh vpt-mf1 "sudo bash /opt/virtualpytest/infra/monitoring/ble/vpt-ble-hourly.sh --print | tail -50"
ssh vpt-mf1 "sudo python3 /opt/virtualpytest/infra/monitoring/ble/ble_status.py --mode=classify"
```

## Mapping to the task MD

| Task §  | What this folder delivers |
|---|---|
| §1 inventory + map | Inventory captured in TASK-76 § results; per-adapter surface already exists on vpt-mf1. |
| §2 hourly cron | `vpt-ble-hourly.sh --once` + `vpt-ble-hourly.cron` or `vpt-ble-hourly.timer` → `/var/log/vpt-ble/hourly/`, kept 14 days. |
| §3 hourly probe contents | Sections 01–10 in `vpt-ble-hourly.sh` populate each row of the MD table. |
| §4 outage detection | `ble_status.py` emits OK / DEGRADED / DOWN; the probe writes `status:` line in tail. ntfy wiring is owner-only (channel not installed by this PR). |
| §5 structured diagnostics | `vpt-ble-hourly.sh --post-mortem` copies + redacts to `/var/log/vpt-ble/incidents/<TS>/`. Existing `diagnose_ble.sh` is the on-demand equivalent. |
| §6 send-key test | `vpt-ble-sendkey-test.sh` with `etc/stb-aliases.conf`. Records in `/var/log/vpt-ble/hourly/sendkey-<TS>.log`. |
| §7 log channels | `bluetoothd -d` already enabled globally via override.conf on vpt-mf1. Per-adapter granularity would require forking the bluez invocation; surface for follow-up. `vpt-ble-btmon@.service` adds the 10 MB ring buffer per adapter. |
| §8 recovery rehearsal | Out of scope for this PR — auto-resume.sh policy lives in a separate task per owner. Manual `resume.sh` is owner-only and self-contained. |
| §9 docs | This file + a follow-up append to `docs/agent/devices/BLUETOOTH.md` (still TODO until the work is committed). |

## Owner-direct carve-outs (per TASK-76 scope)

- `systemctl daemon-reload`
- `systemctl enable --now`
- `crontab`/`/etc/cron.d/` writes
- Any `update_core.sh` deploy
- Any `start.sh` (wipes bonds; used only for a deliberate fresh pair)
- Any restart of `bluetooth.service` (use it only via the §8 auto-resume
  policy and never twice in 24 h)

## Hard constraints (TASK-76)

- **Read-only by default.** No new BLE state is created. The probe only
  writes to `/var/log/vpt-ble/hourly/` and (when `--post-mortem` is invoked)
  to `/var/log/vpt-ble/incidents/<TS>/`. The sendkey test writes to the
  pre-existing FIFO under `/tmp/hid_remote-<hci>.fifo` via a run-locked
  write — never spawns a parallel daemon (BUG-0027 follow-on).
- **No BLE protocol changes.** `hid_remote.py` / `agent.py` are untouched.
  IR / Flirc controllers are untouched.
- **LTK/IRK/CSRK redaction.** Any output that could leave vpt-mf1 (the
  hourly log included — see section 08 below) is passed through
  `redact_ltkirk()` in `vpt-ble-hourly.sh` and `--post-mortem` writes a
  redacted index, so the manager can scp an incident folder without
  leaking pair keys. § 6.7.28 hardening carries over.
- **`resume.sh` policy.** Auto-resume is gated on DOWN×2 within 24 h, max
  one auto-resume per 24 h. Second failure pages the operator. This is
  owner-direct at this PR — there is no auto-resume toggle in the cron.
- **vpt-mf1 stays untouched until a separate deploy go.**

## What this PR is NOT doing

- Not enabling `vpt-ble-remote@<hci{1,2}>.service` (currently `failed`).
- Not un-wedging `hci0` (kernel-up, MGMT-detached; needs a physical replug
  or a fresh `start.sh hci0`).
- Not reinstalling the legacy singleton `vpt-ble-remote.service` (currently
  active against the wedged hci0 — cleanup is a separate task).
- Not installing / configuring ntfy (channel is owner-only).
- Not deleting the 8 stale bond dirs under `/var/lib/bluetooth/`.

## Smoke-test commands (run as root on vpt-mf1 after install)

```bash
# The probe, no side effects:
sudo bash /opt/virtualpytest/infra/monitoring/ble/vpt-ble-hourly.sh --print

# The classifier:
sudo python3 /opt/virtualpytest/infra/monitoring/ble/ble_status.py --mode=classify

# Full hourly tick + tail the log:
sudo bash /opt/virtualpytest/infra/monitoring/ble/vpt-ble-hourly.sh --once
sudo tail -n 60 /var/log/vpt-ble/hourly/$(date -u +%Y-%m-%dT%H).log

# Power-on a known-sleeping STB:
sudo bash /opt/virtualpytest/infra/monitoring/ble/vpt-ble-sendkey-test.sh stb-A
sudo tail -n 20 /var/log/vpt-ble/hourly/sendkey-*.log | tail -20
```

## Cross-references

- BUG-0003 — `bluetoothd` restart wipes GATT registration → §10 in
  `vpt-ble-hourly.sh` + `_btmon_nudge()` in `ble_status.py`.
- BUG-0027 — duplicate `hid_remote.py` halves the key rate → §09 in the
  probe + `_adapter_for_pid()` / `_pgrep()` paths in `ble_status.py`.
- BUG-0029 — wake picker targets the wrong bond → `vpt-ble-sendkey-test.sh`
  refuses to send when the box is already on.
- BUG-0271 — FIFO write succeeds with no peer connected → the
  `_status_json()` `hid_ready` gate is the canonical mitigation.
- §6.7.28 — GATT-wipe recipe (bluetoothd monotonic > daemon monotonic).
- §6.7.29 — bond picker prefers the HID-CCC bond (search for `has_2a4d`).
- §6.7.30 — foreign-central grabs the adapter (gate via `_pairing_allowed`
  in the existing `agent.py`; not modified by this PR).
- §6.7.31 — LE filter accept list (existing `resume.sh` behaviour;
  preserved).
- §6.7.32 — caller audit (existing `/var/log/vpt-ble-pairing.log`;
  preserved).
