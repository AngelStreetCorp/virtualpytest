#!/usr/bin/env python3
"""
VirtualPyTest Smoke — Device Control

Verifies the full device control stack:
  1. At least one host is registered and reachable
  2. The host exposes at least one device
  3. The host health endpoint responds (VPT host service is running)
  4. Device info can be retrieved from the host API

This script deliberately does NOT push any remote-control commands —
it only reads state to confirm the control plane is intact.

Usage:
    python test_scripts/vpt/smoke_device_control.py
    python test_scripts/vpt/smoke_device_control.py --server http://192.168.0.103:5109
"""

import sys
import os
import time
import requests

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context
from shared.src.lib.utils.build_url_utils import get_host_api_origin
from test_scripts.vpt.smoke_common import headers as _headers, make_step as _step


def capture_summary(context, server_url: str, host_info: dict = None) -> str:
    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))

    lines = [
        "-" * 60,
        "🎯 [VPT SMOKE DEVICE CONTROL] EXECUTION SUMMARY",
        "-" * 60,
        f"🌐 Server: {server_url}",
        f"⏱️ Total Time: {context.get_execution_time_ms() / 1000:.1f}s",
        f"📊 Checks: {total}  ✅ Passed: {passed}  ❌ Failed: {total - passed}",
    ]
    if host_info:
        lines.append(f"🖥️ Host: {host_info.get('host_name', 'N/A')} ({host_info.get('host_url', 'N/A')})")
        devices = host_info.get("devices", [])
        lines.append(f"📱 Devices on host: {len(devices)}")
        for d in devices:
            lines.append(f"   • {d.get('device_name', '?')} [{d.get('device_model', '?')}]")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if not context.overall_success and context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    lines.append("-" * 60)
    return "\n".join(lines)


@script("smoke_device_control", "Verify VirtualPyTest device control stack is operational")
def main():
    context = get_context()
    args = get_args()
    server_url = getattr(args, "server", None) or os.getenv("SERVER_URL", "http://localhost:5109")
    team_id = context.team_id

    print(f"🔍 [smoke_device_control] Checking device control stack at {server_url}")

    host_info = None

    # ── Step 1: List registered hosts ─────────────────────────────────────────
    try:
        t0 = time.time()
        resp = requests.get(
            f"{server_url}/server/system/getAllHosts",
            params={"team_id": team_id},
            headers=_headers(),
            timeout=10,
            verify=False,
        )
        ms = round((time.time() - t0) * 1000, 1)
        data = resp.json() if resp.status_code == 200 else {}
        hosts = data.get("hosts", [])
        ok = resp.status_code == 200 and len(hosts) > 0
        context.record_step_immediately(_step(
            "GET /server/system/getAllHosts",
            f"Hosts registered ({len(hosts)} found)",
            ok,
            error=None if ok else f"HTTP {resp.status_code}" if resp.status_code != 200 else "No hosts registered",
            status_code=resp.status_code,
            response_time_ms=ms,
        ))
        if ok:
            host_info = hosts[0]
    except Exception as e:
        context.record_step_immediately(_step("GET /server/system/getAllHosts", "Hosts registered", False, error=str(e)))
        context.error_message = str(e)
        context.overall_success = False
        context.execution_summary = capture_summary(context, server_url)
        return False

    if not host_info:
        context.error_message = "No hosts registered — cannot verify device control"
        context.overall_success = False
        context.execution_summary = capture_summary(context, server_url)
        return False

    # `host_url` is browser-relative (/host/<name>) — a reverse-proxy route. Prefixing
    # it with the backend server's origin gives http://<server>:5109/host/<name>, which
    # 404s: :5109 does not serve that path. Use the direct origin the server itself
    # calls hosts on (BUG-0091).
    host_url = get_host_api_origin(host_info)
    host_name = host_info.get("host_name", "unknown")

    if not host_url:
        context.error_message = (
            f"Host '{host_name}' publishes no absolute API URL "
            f"(host_api_url={host_info.get('host_api_url')!r}, host_url={host_info.get('host_url')!r})"
        )
        context.overall_success = False
        context.execution_summary = capture_summary(context, server_url, host_info)
        return False

    # ── Step 2: Host health check ──────────────────────────────────────────────
    try:
        t0 = time.time()
        resp = requests.get(f"{host_url}/health", timeout=8, verify=False)
        ms = round((time.time() - t0) * 1000, 1)
        ok = resp.status_code == 200
        body = resp.json() if ok else {}
        context.record_step_immediately(_step(
            f"GET {host_url}/health",
            f"Host '{host_name}' health endpoint",
            ok,
            error=None if ok else f"HTTP {resp.status_code}",
            status_code=resp.status_code,
            response_time_ms=ms,
        ))
    except Exception as e:
        context.record_step_immediately(_step(f"GET {host_url}/health", f"Host '{host_name}' health endpoint", False, error=str(e)))

    # ── Step 3: List devices on host ───────────────────────────────────────────
    try:
        t0 = time.time()
        resp = requests.get(
            f"{host_url}/host/devices",
            headers=_headers(),
            timeout=8,
            verify=False,
        )
        ms = round((time.time() - t0) * 1000, 1)
        data = resp.json() if resp.status_code == 200 else {}
        devices = data.get("devices", [])
        ok = resp.status_code == 200 and len(devices) > 0
        context.record_step_immediately(_step(
            f"GET {host_url}/host/devices",
            f"Devices accessible on '{host_name}' ({len(devices)} found)",
            ok,
            error=None if ok else f"HTTP {resp.status_code}" if resp.status_code != 200 else "No devices on host",
            status_code=resp.status_code,
            response_time_ms=ms,
        ))
        if ok:
            host_info["devices"] = devices
    except Exception as e:
        context.record_step_immediately(_step(
            f"GET {host_url}/host/devices",
            f"Devices accessible on '{host_name}'",
            False,
            error=str(e),
        ))

    # ── Step 4: Get device info for first device ───────────────────────────────
    devices = host_info.get("devices", [])
    if devices:
        device_id_probe = devices[0].get("device_id", "device1")
        device_name = devices[0].get("device_name", device_id_probe)
        # The host exposes no per-device *info* endpoint; the real per-device read
        # is is_busy, which proves the host can answer a question about this
        # specific device. Note the blueprint prefix is /host/system, and the
        # /host/* auth guard answers 401 before routing — so an unauthenticated
        # probe cannot tell a wrong path from a right one.
        endpoint = f"/host/system/device/{device_id_probe}/is_busy"
        try:
            t0 = time.time()
            resp = requests.get(
                f"{host_url}{endpoint}",
                headers=_headers(),
                timeout=8,
                verify=False,
            )
            ms = round((time.time() - t0) * 1000, 1)
            ok = resp.status_code == 200 and isinstance(resp.json().get("busy"), bool)
            context.record_step_immediately(_step(
                f"GET {endpoint}",
                f"Device addressable on host: '{device_name}'",
                ok,
                error=None if ok else f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_time_ms=ms,
            ))
        except Exception as e:
            context.record_step_immediately(_step(
                f"GET {endpoint}",
                f"Device addressable on host: '{device_name}'",
                False,
                error=str(e),
            ))

    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    context.overall_success = passed == total and total > 0

    context.execution_summary = capture_summary(context, server_url, host_info)
    print(f"\n{'✅' if context.overall_success else '❌'} [smoke_device_control] {passed}/{total} checks OK")
    return context.overall_success


main._script_args = [
    "--userinterface:str:virtualpytest_web",  # tags script_results so the Self-Test dashboard picks the run up
    "--server:str:",  # Override SERVER_URL env var
]

if __name__ == "__main__":
    main()
