#!/usr/bin/env python3
"""
Run the VirtualPyTest self-test smoke scripts (test_scripts/vpt/smoke_*) against a
deployed environment and report a pass/fail per script.

These scripts check the platform's own control plane — hosts registered, host API
reachable, devices addressable, UI pages served, HLS pipeline alive. They cannot
run standalone on a CI runner: the @script decorator needs a host and a device, so
they are driven the way a user drives them — POST /server/script/execute, then poll
/server/script/status/<task_id>.

Two of the five were broken for an unknown length of time because nothing ran them
(BUG-0091). That is what this exists to prevent.

─────────────────────────────────────────────────────────────────────────────
RUN
─────────────────────────────────────────────────────────────────────────────
  SERVER_URL=https://virtualpytest.example TEAM_ID=<uuid> API_KEY=<key> \
  python3 tests/test_scripts/run_vpt_smoke.py

  # pick the host/device explicitly (default: first online host with a device)
  ... --host host-clone-1 --device host

Exit code 0 only when every selected script passes.
"""

import argparse
import json
import os
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_URL = os.environ.get("SERVER_URL", "http://192.168.0.103:5109").rstrip("/")
TEAM_ID = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
API_KEY = os.environ.get("API_KEY", "")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() in {"1", "true", "yes"}

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
    HEADERS["Authorization"] = f"Bearer {API_KEY}"

# Kept explicit rather than globbed: this list is the contract of what the
# platform promises to self-check, and a new smoke script should be an
# intentional addition here.
SMOKE_SCRIPTS = [
    "vpt/smoke_ui",
    "vpt/smoke_device_control",
    "vpt/smoke_network_server",
    "vpt/smoke_heatmap",
    "vpt/smoke_video_stream",
]

POLL_SECONDS = 5
DEFAULT_TIMEOUT = 300
LOCK_RETRY_SECONDS = 10
LOCK_RETRIES = 18       # ~3 min of waiting out another run's device lock


def _api(method, path, **kwargs):
    sep = "&" if "?" in path else "?"
    url = f"{SERVER_URL}{path}{sep}team_id={TEAM_ID}"
    return requests.request(method, url, headers=HEADERS, verify=VERIFY_SSL,
                            timeout=kwargs.pop("timeout", 30), **kwargs)


def pick_target(host_arg, device_arg):
    """First online host with at least one device, unless told otherwise."""
    if host_arg and device_arg:
        return host_arg, device_arg

    resp = _api("GET", "/server/system/getAllHosts")
    if resp.status_code != 200:
        sys.exit(f"ERROR: getAllHosts -> HTTP {resp.status_code}: {resp.text[:200]}")

    for host in (resp.json() or {}).get("hosts", []):
        if host_arg and host.get("host_name") != host_arg:
            continue
        devices = host.get("devices") or []
        if devices:
            return host.get("host_name"), device_arg or devices[0].get("device_id")

    sys.exit("ERROR: no online host with a device found")


def run_one(script, host, device, timeout):
    """Execute one script and wait for its verdict. Returns (ok, detail)."""
    body = {"host_name": host, "device_id": device, "script_name": script}

    task_id = None
    for _ in range(LOCK_RETRIES):
        resp = _api("POST", "/server/script/execute", json=body)
        data = resp.json() if resp.content else {}
        # The execute route answers 202 (accepted, runs in the background), not 200.
        if resp.status_code in (200, 202) and data.get("success"):
            task_id = data.get("task_id")
            break
        # Another run holds the device — that is normal on a shared environment.
        if data.get("errorType") == "device_locked":
            time.sleep(LOCK_RETRY_SECONDS)
            continue
        return False, f"could not start: HTTP {resp.status_code} {str(data)[:160]}"

    if not task_id:
        return False, f"device {host}:{device} stayed locked"

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        resp = _api("GET", f"/server/script/status/{task_id}")
        if resp.status_code != 200:
            continue
        task = (resp.json() or {}).get("task") or {}
        if task.get("status") not in ("completed", "failed", "error"):
            continue

        result = task.get("result") or {}
        error = task.get("error")
        # script_success is the SCRIPT_SUCCESS: marker — the test outcome. Treat a
        # completion with no marker and no exit code as a failure, not a pass: the
        # host may never have run anything (BUG-0089).
        script_success = result.get("script_success")
        if script_success is not None:
            return bool(script_success), (result.get("report_url") or "")[:80]
        if error:
            return False, str(error)[:160]
        if result.get("exit_code") not in (None, 0):
            return False, f"exit_code={result.get('exit_code')}"
        if not result:
            return False, "host returned no result (script may never have run)"
        return True, (result.get("report_url") or "")[:80]

    return False, f"timed out after {timeout}s"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", help="host_name to run on (default: first online)")
    parser.add_argument("--device", help="device_id to run on (default: first on that host)")
    parser.add_argument("--scripts", nargs="+", default=SMOKE_SCRIPTS,
                        help="override the script list")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"per-script timeout in seconds (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--json-out", help="write a machine-readable summary here")
    args = parser.parse_args()

    host, device = pick_target(args.host, args.device)
    print(f"VPT smoke suite -> {SERVER_URL}  host={host} device={device}\n")

    results, failures = [], 0
    width = max(len(s) for s in args.scripts)
    for script in args.scripts:
        t0 = time.time()
        ok, detail = run_one(script, host, device, args.timeout)
        secs = round(time.time() - t0, 1)
        print(f"  {'PASS' if ok else 'FAIL'}  {script.ljust(width)}  {secs:>6.1f}s  {detail}")
        results.append({"script": script, "ok": ok, "seconds": secs, "detail": detail})
        if not ok:
            failures += 1

    print(f"\n{len(args.scripts) - failures}/{len(args.scripts)} passed")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"host": host, "device": device, "results": results}, handle, indent=2)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
