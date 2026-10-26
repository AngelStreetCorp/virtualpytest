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
START_RETRY_SECONDS = 20
START_RETRIES = 4       # host briefly not accepting connections (busy with another run)
HOSTS_RETRY_SECONDS = 10
HOSTS_RETRIES = 30      # ~5 min: a deploy restarting the server answers 5xx for a few minutes
LOCK_RETRIES = 18       # ~3 min of waiting out another run's device lock


def _api(method, path, **kwargs):
    sep = "&" if "?" in path else "?"
    url = f"{SERVER_URL}{path}{sep}team_id={TEAM_ID}"
    return requests.request(method, url, headers=HEADERS, verify=VERIFY_SSL,
                            timeout=kwargs.pop("timeout", 30), **kwargs)


def _get_all_hosts():
    """GET getAllHosts, retrying while the server is down or answering 5xx (deploy restart)."""
    for attempt in range(HOSTS_RETRIES + 1):
        try:
            resp = _api("GET", "/server/system/getAllHosts")
            if resp.status_code < 500:
                return resp
            why = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            resp, why = None, type(exc).__name__
        if attempt == HOSTS_RETRIES:
            if resp is None:
                sys.exit(f"ERROR: getAllHosts unreachable after {HOSTS_RETRIES} retries ({why})")
            return resp
        print(f"getAllHosts -> {why}; server restarting? retry {attempt + 1}/{HOSTS_RETRIES} in {HOSTS_RETRY_SECONDS}s")
        time.sleep(HOSTS_RETRY_SECONDS)


def _probe_host_forwarder(host_name: str) -> bool:
    """Reachability probe via the runner's server-side `/host/<name>/health` forwarder.

    The smoke runner can usually reach the backend server even when the
    runner's network cannot reach the host's `host_api_url` directly. A
    down-or-unreachable host would otherwise make every smoke script time
    out at the 120 s host read, masking the platform-level pass. Any HTTP
    response (200, 401, 404, …) counts as reachable: a 401 is auth, not
    connectivity. ConnectionError / Timeout means we can't get there in 5 s
    and the smoke would only ever come back as `host reported no script result`.
    """
    if not host_name:
        return False
    url = f"{SERVER_URL}/host/{host_name}/health"
    try:
        requests.get(url, headers=HEADERS, verify=VERIFY_SSL, timeout=5)
        return True
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectTimeout):
        return False


def _fetch_locked_device_keys() -> set:
    """Set of ``host_name:device_id`` strings that are currently locked.

    /server/system/getAllHosts (the endpoint this runner already uses) does
    not surface per-device lock info; the public locks endpoint at
    /server/control/lockedDevices does. A failure here is non-fatal —
    falling back to "everyone looks free" is strictly better than crashing
    the gate over a list we cannot reach.
    """
    try:
        resp = _api("GET", "/server/control/lockedDevices", timeout=10)
    except requests.exceptions.RequestException:
        return set()
    if resp.status_code != 200:
        return set()
    return set((resp.json() or {}).get("locked_devices") or {})


def pick_target(host_arg, device_arg, skip_host=None):
    """First free online host with at least one device, unless told otherwise.

    Probes each candidate through the server's `/host/<name>/health`
    forwarder so a host the runner cannot reach is skipped before the
    first script starts — otherwise every smoke in the suite waits 120 s
    for an unreachable host and the whole gate fails on a runner-side
    network issue, not a platform regression.

    Skips candidates whose first device is currently locked by someone
    else (Take Control, a script, a campaign) — those would otherwise
    ``stayed locked`` on the first execute and turn the gate red on a
    neighbour, not on us. ``skip_host`` is the host that just failed so
    a retry can pick the *next* free host. If every reachable candidate
    is locked, the first one is still used (the suite must run) and a
    warning tells the operator that the lock held by someone else is
    what made us land on it.
    """
    if host_arg and device_arg:
        return host_arg, device_arg

    resp = _get_all_hosts()
    if resp.status_code != 200:
        sys.exit(f"ERROR: getAllHosts -> HTTP {resp.status_code}: {resp.text[:200]}")

    locked_keys = _fetch_locked_device_keys()
    skipped_unreachable: list[str] = []
    locked_candidates: list[tuple[str, str]] = []
    for host in (resp.json() or {}).get("hosts", []):
        if host_arg and host.get("host_name") != host_arg:
            continue
        if skip_host and host.get("host_name") == skip_host:
            continue
        devices = host.get("devices") or []
        if not devices:
            continue
        name = host.get("host_name")
        device_id = devices[0].get("device_id")
        if f"{name}:{device_id}" in locked_keys:
            # Defer the choice: a free reachable host is always preferred,
            # but if none comes up we still want a "best effort" answer.
            locked_candidates.append((name, device_id))
            continue
        if not _probe_host_forwarder(name):
            skipped_unreachable.append(name)
            continue
        return name, device_arg or device_id

    if locked_candidates:
        picked_name, picked_device = locked_candidates[0]
        print(
            f"[run_vpt_smoke] WARNING: every reachable host's first device "
            f"is currently locked (hosts: "
            f"{', '.join(n for n, _ in locked_candidates)}); proceeding with "
            f"{picked_name}:{picked_device}",
            flush=True,
        )
    if skipped_unreachable:
        print(f"[run_vpt_smoke] skipped unreachable hosts: {', '.join(skipped_unreachable)}", flush=True)

    if locked_candidates:
        return locked_candidates[0]
    sys.exit("ERROR: no online host with a device found")


# A run another session killed (force_unlock / abortRunning on a shared device) comes
# back SIGTERM/SIGKILL (-15/-9, or 143/137 through bash) with no SCRIPT_SUCCESS marker.
# That is the environment, not the platform: run it again instead of failing the gate.
KILLED_EXIT_CODES = {-15, -9, 143, 137}
INTERRUPT_RETRIES = 2   # extra attempts after an interrupted run
INTERRUPT_WAIT_SECONDS = 20


def judge_task(task):
    """Turn a finished status task into (ok, detail, interrupted).

    `interrupted` is True when the run was cut short from outside (killed, or the
    host reported nothing at all) rather than judged by the script itself.
    """
    result = task.get("result") or {}
    error = task.get("error")
    exit_code = result.get("exit_code")
    killed = exit_code in KILLED_EXIT_CODES

    # script_success is the SCRIPT_SUCCESS: marker — the test outcome. Treat a
    # completion with no marker and no exit code as a failure, not a pass: the
    # host may never have run anything (BUG-0089).
    script_success = result.get("script_success")
    if script_success is not None and not killed:
        if script_success:
            return True, (result.get("report_url") or "")[:80], False
        # Never an empty reason: say what the host knows.
        why = error or (f"exit_code={exit_code}" if exit_code not in (None, 0) else "script reported failure")
        return False, str(why)[:160], False
    if killed:
        return False, f"run killed (exit_code={exit_code}) - another session aborted the device", True
    if error:
        return False, str(error)[:160], error == "host reported no script result"
    if exit_code not in (None, 0):
        return False, f"exit_code={exit_code}", False
    if not result:
        return False, "host returned no result (script may never have run)", True
    return True, (result.get("report_url") or "")[:80], False


def run_one(script, host, device, timeout):
    """Execute one script and wait for its verdict. Returns (ok, detail).

    Two retry layers keep the gate from going red on neighbours:

    - A run whose device stayed locked past LOCK_RETRIES (someone else
      is holding it) is retried once on a different free host. Picking
      the next free host costs a few ms of HTTP and usually clears the
      gate, instead of waiting it out on the same shared device.
    - A run that was interrupted from outside (SIGTERM/SIGKILL, no
      marker) is retried on the same host/device, bounded by
      INTERRUPT_RETRIES — a neighbour's force_unlock aborting the run
      isn't a platform regression.
    """
    ok, detail, interrupted = _run_once(script, host, device, timeout)

    # Device stayed locked under a non-manual lock: one chance on the next
    # free host before counting the run as failed. Manual-control locks
    # are returned as a `None` skip by ``_run_once`` and never reach here.
    if ok is False and not interrupted and detail.endswith("stayed locked"):
        try:
            retry_target = pick_target(None, None, skip_host=host)
        except SystemExit:
            retry_target = None
        if retry_target and retry_target != (host, device):
            next_host, next_device = retry_target
            print(
                f"  .. {script} stayed locked on {host}:{device}; "
                f"retrying once on {next_host}:{next_device}",
                flush=True,
            )
            ok, detail, interrupted = _run_once(script, next_host, next_device, timeout)

    if ok or not interrupted:
        return ok, detail
    for attempt in range(INTERRUPT_RETRIES):
        print(f"  .. {script} interrupted ({detail}); retry {attempt + 1}/{INTERRUPT_RETRIES} "
              f"in {INTERRUPT_WAIT_SECONDS}s", flush=True)
        time.sleep(INTERRUPT_WAIT_SECONDS)
        ok, detail, interrupted = _run_once(script, host, device, timeout)
        if ok or not interrupted:
            return ok, detail
    return False, detail


def _run_once(script, host, device, timeout):
    """One execute + poll cycle. Returns (ok, detail, interrupted); ok is None when the run was skipped.

    Never queued (queue_if_locked=false): a queued run would start on the device after this runner gave up.
    A device under someone's Take Control is skipped at once: that holder may keep it for an hour (TASK-135)."""
    body = {"host_name": host, "device_id": device, "script_name": script, "queue_if_locked": False}

    task_id = None
    start_failures = 0
    for _ in range(LOCK_RETRIES):
        resp = _api("POST", "/server/script/execute", json=body)
        data = resp.json() if resp.content else {}
        # The execute route answers 202 (accepted, runs in the background), not 200.
        if resp.status_code in (200, 202) and data.get("success"):
            task_id = data.get("task_id")
            break
        # Another run holds the device — that is normal on a shared environment.
        if data.get("errorType") == "device_locked":
            if data.get("owner_type") == "manual_control":
                return None, f"skipped: {host}:{device} is under Take Control ({data.get('owner_user_name') or 'someone'})", False
            time.sleep(LOCK_RETRY_SECONDS)
            continue
        # Host saturated for a moment (connect timeout / unreachable): wait and retry.
        if resp.status_code in (502, 503, 504) and start_failures < START_RETRIES:
            start_failures += 1
            time.sleep(START_RETRY_SECONDS)
            continue
        return False, f"could not start: HTTP {resp.status_code} {str(data)[:160]}", False

    if not task_id:
        return False, f"device {host}:{device} stayed locked", False

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        resp = _api("GET", f"/server/script/status/{task_id}")
        if resp.status_code != 200:
            continue
        task = (resp.json() or {}).get("task") or {}
        if task.get("status") not in ("completed", "failed", "error"):
            continue
        return judge_task(task)

    return False, f"timed out after {timeout}s", False


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
        print(f"  {'PASS' if ok else 'SKIP' if ok is None else 'FAIL'}  {script.ljust(width)}  {secs:>6.1f}s  {detail}")
        results.append({"script": script, "ok": ok, "skipped": ok is None, "seconds": secs, "detail": detail})
        if ok is False:
            failures += 1

    skipped = sum(1 for r in results if r["skipped"])
    print(f"\n{len(args.scripts) - failures - skipped}/{len(args.scripts)} passed, {skipped} skipped")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"host": host, "device": device, "results": results}, handle, indent=2)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
