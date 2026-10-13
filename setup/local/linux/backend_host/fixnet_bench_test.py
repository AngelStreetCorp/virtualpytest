#!/usr/bin/env python3
"""
fixnet_bench_test.py — exercise the Fixnet USB voice modems from the bench.

Run ON THE PFR from the repo root (/opt/virtualpytest), as the user that will
drive the tests:

    python3 setup/local/linux/backend_host/fixnet_bench_test.py all
    python3 setup/local/linux/backend_host/fixnet_bench_test.py call --number 5551234

This is the Phase A tool: it works against a raw serial line on one modem, with
no VPT service, no device model and no report — the things you want BEFORE the
controller exists.

It has no modem code of its own. VoiceModem, ATChannel and the DTMF strategy all
come from backend_host/src/controllers/remote/fx, the same modules the `fx`
remote controller uses, so a result here is a result about the shipped code and
not about a prototype that can drift away from it.

COMMANDS
    selftest        the PoC battery (USB/AT/FCLASS/VLS/VSM/VNH). No line needed.
    dtmf            try every plausible +VTS / in-call form and report which the
                    modem ACCEPTS. TASK-71 goal 2, the blocker.
    ring            wait for an incoming call (RING) on one modem.
    call            off-hook, dial, wait for CONNECT, hang up. PLACES A CALL.
    loop            repeat a call N times to measure stability. PLACES CALLS.
    audio           is voice audio reachable from the host at all?
    all             selftest + dtmf + audio; nothing that places a call.

    Every command takes --modem N (0-based). By default the port is
    /dev/fixnet/modemN; pass --port to point straight at /dev/fx1 instead.

SAFETY
    `call` and `loop` place real calls. They refuse to run without --number, and
    --number is never defaulted, so a mistyped invocation cannot dial something.
    `selftest`, `dtmf`, `ring` and `audio` never leave a call.
"""

import argparse
import os
import sys
import time

def _find_repo_root():
    """Walk up from this script until the tree holding the fx package is found.

    Counting "../" levels is brittle — this script has moved once already
    (scripts/ -> setup/local/linux/backend_host/). Searching for a marker is
    immune to the next move.

    The marker is the fx package itself, not merely a directory called
    `backend_host`: this script LIVES in setup/local/linux/backend_host/, and a
    name-only match resolves the root to the wrong tree and then fails to import
    anything useful.
    """
    marker = os.path.join("backend_host", "src", "controllers", "remote", "fx")
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(here, marker, "__init__.py")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


_REPO_ROOT = _find_repo_root()
if _REPO_ROOT is None:
    raise SystemExit(
        "cannot find the repo root (the directory holding backend_host/) from "
        f"{os.path.dirname(os.path.abspath(__file__))}.\n"
        "  run this from a checkout of the repo, e.g.\n"
        "    cd /opt/virtualpytest && python3 setup/local/linux/backend_host/fixnet_bench_test.py all"
    )
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from backend_host.src.controllers.remote.fx import ATError, VoiceModem
except ImportError as exc:  # pragma: no cover - depends on where it is run
    raise SystemExit(
        f"cannot import the fx modem modules: {exc}\n"
        f"  expected them under {_REPO_ROOT}\n"
        f"  e.g. cd {_REPO_ROOT} && python3 setup/local/linux/backend_host/fixnet_bench_test.py all"
    )

DEFAULT_MODEM_DIR = "/dev/fixnet"


def open_modem(args):
    """Build a VoiceModem for the requested modem, with a helpful failure."""
    port = args.port or os.path.join(args.modem_dir, f"modem{args.modem}")
    if not os.path.exists(port):
        raise SystemExit(
            f"{port} does not exist.\n"
            "  Run setup/local/linux/backend_host/check_fixnet_prereqs.sh first — the stable\n"
            "  names come from install_fixnet_prereqs.sh (udev + tmpfiles.d)."
        )
    return VoiceModem(port, timeout=args.timeout, verbose=args.verbose, name=f"modem{args.modem}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_selftest(args):
    vm = open_modem(args)
    print(f"\n--- {vm.name} ({vm.port}) ---")
    rows = vm.selftest()
    width = max(len(r[0]) for r in rows)
    for name, ok, detail in rows:
        mark = "ok  " if ok else "FAIL"
        print(f"  [{mark}] {name.ljust(width)}  {detail}")
    failed = [r for r in rows if not r[1]]
    print(f"  {len(rows)-len(failed)}/{len(rows)} passed")
    return 0 if not failed else 1


def cmd_dtmf(args):
    vm = open_modem(args)
    rows = vm.probe_dtmf(in_call=args.in_call)
    print(f"\n--- DTMF syntax probe on {vm.name} ({vm.port}) ---")
    width = max(len(r["label"]) for r in rows)
    accepted = 0
    for r in rows:
        ok = r.get("accepted")
        if ok is None:
            mark = "skip"
        elif ok:
            mark = "ok  "; accepted += 1
        else:
            mark = "no  "
        print(f"  [{mark}] {r['label'].ljust(width)}  {r['command'].ljust(26)} {r['reason']}")
    print(f"\n  {accepted} command form(s) accepted by the modem.")
    print(f"  strategy for this modem: {vm.dtmf.describe()}")
    print("  ACCEPTED IS NOT VERIFIED. A digit must be heard at the far end")
    print("  before goal 2 is done — this only says which command to try by ear.")
    return 0


def cmd_ring(args):
    vm = open_modem(args)
    print(f"\n--- waiting up to {args.timeout}s for RING on {vm.name} ---")
    print("  place an incoming call to this line now")
    res = vm.wait_ring(args.timeout)
    for line in res["seen"][-10:]:
        print(f"    < {line}")
    if res["ringing"]:
        print(f"  [ok  ] RING detected: {res['line']}")
        return 0
    print(f"  [FAIL] no RING in {args.timeout}s")
    print("         check: is the far end actually ringing, is the gateway")
    print("         registered to SIP, and does the FXS port have loop current?")
    return 1


def cmd_call(args):
    if not args.number:
        raise SystemExit(
            "refusing to place a call without --number.\n"
            "  e.g. ... call --number 5551234 --modem 0"
        )
    vm = open_modem(args)
    print(f"\n--- call on {vm.name} ({vm.port}) to {args.number} ---")
    print("  off-hook (ATA) ...")
    vm.off_hook()
    print("  dialling ...")
    vm.dial(args.number, args.timeout)
    print("  waiting for CONNECT ...")
    res = vm.wait_connected(args.timeout)
    for line in res["seen"][-10:]:
        print(f"    < {line}")
    if res["connected"]:
        print("  [ok  ] CONNECT — the full FXS path works")
    else:
        print("  [FAIL] no CONNECT")
        print("         the modem dialled, so the loop is closed, but nothing")
        print("         answered. Check the far end, SIP registration, and that")
        print("         the relay matrix is passing the pair (insertion loss).")
    time.sleep(args.hold)
    print("  hanging up ...")
    vm.hangup()
    return 0 if res["connected"] else 1


def cmd_loop(args):
    if not args.number:
        raise SystemExit("refusing to place calls without --number")
    ok_count = 0
    for i in range(1, args.count + 1):
        try:
            vm = open_modem(args)
            vm.off_hook()
            vm.dial(args.number, args.timeout)
            connected = vm.wait_connected(args.timeout)["connected"]
            vm.hangup()
        except (ATError, SystemExit) as exc:
            print(f"  cycle {i}/{args.count}: ERROR {exc}")
            connected = False
        print(f"  cycle {i}/{args.count}: {'ok' if connected else 'FAIL'}")
        ok_count += 1 if connected else 0
        time.sleep(args.gap)
    print(f"\n  {ok_count}/{args.count} cycles connected")
    return 0 if ok_count == args.count else 1


def cmd_audio(args):
    vm = open_modem(args)
    res = vm.probe_audio()
    print(f"\n--- audio probe on {vm.name} ---")
    print(f"  line codecs reported by +VSM: {len(res['line_codecs'])}")
    for c in res["line_codecs"][:10]:
        print(f"    {c}")
    print(f"  host sound devices in /dev/snd: {len(res['host_audio_devices'])}")
    for d in res["host_audio_devices"][:10]:
        print(f"    {d}")
    if not res["host_audio"]:
        print("\n  [WARN] no ALSA device — voice audio cannot be captured")
        print("         or played back on this host as it stands.")
        print("         Confirm the modem exposes a USB audio interface:")
        print("           lsusb | grep -i -A2 0572:1349")
        print("         A USB56KEMH2 is a fax/data modem: +VSM describes the")
        print("         ON-LINE codec, and that audio may terminate in the")
        print("         modem's analog jacks instead of reaching the host.")
        print("         If it does, goal 5 (record/playback) needs a line-side")
        print("         analyser or a loopback box, not more software.")
    return 0


def cmd_all(args):
    rc = cmd_selftest(args)
    print()
    rc |= cmd_dtmf(args)
    print()
    rc |= cmd_audio(args)
    return rc


def main():
    p = argparse.ArgumentParser(
        description="Bench-test the Fixnet USB voice modems.")
    p.add_argument("command",
                   choices=["selftest", "dtmf", "ring", "call", "loop", "audio", "all"])
    p.add_argument("--modem", type=int, default=0, help="0-based index")
    p.add_argument("--modem-dir", default=DEFAULT_MODEM_DIR)
    p.add_argument("--port", help="use this device node directly, e.g. /dev/fx1")
    p.add_argument("--number", help="number to dial (required for call/loop)")
    p.add_argument("--count", type=int, default=5, help="cycles for loop")
    p.add_argument("--timeout", type=float, default=30.0, help="seconds to wait")
    p.add_argument("--hold", type=float, default=2.0, help="seconds to hold a call")
    p.add_argument("--gap", type=float, default=1.0, help="seconds between loop cycles")
    p.add_argument("--in-call", action="store_true", help="dtmf: also try in-call dialling")
    p.add_argument("-v", "--verbose", action="store_true", help="show every AT exchange")
    args = p.parse_args()

    return {
        "selftest": cmd_selftest,
        "dtmf": cmd_dtmf,
        "ring": cmd_ring,
        "call": cmd_call,
        "loop": cmd_loop,
        "audio": cmd_audio,
        "all": cmd_all,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())