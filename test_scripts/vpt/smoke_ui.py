#!/usr/bin/env python3
"""
VirtualPyTest Smoke UI Verification

Tests that every major VPT page has a working backing API endpoint.
Each page in the frontend maps to one or more server routes — this script
hits all of them to confirm the platform is fully accessible.

Pages covered:
  Dashboard       → /server/health + /server/system/getAllHosts
  Device Control  → /server/devices/getAllDevices
  Run Tests       → /server/script/list
  Campaigns       → /server/campaigns/getAllCampaigns
  Test Cases      → /server/testcase/list
  Requirements    → /server/requirements/list
  Coverage        → /server/requirements/coverage/summary
  Incidents       → /server/alerts/getAllAlerts
  Code Deployment → /server/deployment/list
  Interface       → /server/userinterface/getAllUserInterfaces
  Models          → /server/devicemodel/getAllModels

Usage:
    python test_scripts/vpt/smoke_ui.py
    python test_scripts/vpt/smoke_ui.py --server http://192.168.0.103:5109
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

# Every VPT page and its backing API endpoint
VPT_PAGES = [
    ("/server/health",                              "Dashboard — server health"),
    ("/server/system/getAllHosts",                  "Dashboard — registered hosts"),
    ("/server/devices/getAllDevices",               "Device Control — device list"),
    ("/server/script/list",                         "Run Tests — script list"),
    ("/server/campaigns/getAllCampaigns",           "Campaigns — campaign list"),
    ("/server/testcase/list",                       "Test Cases — testcase list"),
    ("/server/requirements/list",                   "Requirements — requirement list"),
    ("/server/requirements/coverage/summary",       "Coverage — coverage summary"),
    ("/server/alerts/getAllAlerts",                 "Incidents — alert list"),
    ("/server/deployment/list",                     "Code Deployment — deployment list"),
    ("/server/userinterface/getAllUserInterfaces",  "Interface — user interface list"),
    ("/server/devicemodel/getAllModels",            "Models — device model list"),
]


def test_endpoint(server_url: str, path: str, description: str, context) -> dict:
    url = f"{server_url}{path}"
    step = {
        "action": f"GET {path}",
        "description": description,
        "timestamp": time.time(),
        "success": False,
        "error": None,
        "response_time_ms": 0,
        "status_code": None,
    }
    try:
        headers = {"Content-Type": "application/json"}
        api_key = os.getenv("API_KEY", "")
        if api_key:
            headers["X-API-Key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"

        params = {}
        if any(seg in path for seg in ["devices", "campaigns", "testcase", "requirements",
                                        "userinterface", "devicemodel", "deployment",
                                        "alerts", "script"]):
            params["team_id"] = context.team_id

        t0 = time.time()
        resp = requests.get(url, params=params, headers=headers, timeout=10, verify=False)
        step["response_time_ms"] = round((time.time() - t0) * 1000, 1)
        step["status_code"] = resp.status_code

        if resp.status_code == 200:
            step["success"] = True
            print(f"  ✅ {description}: {resp.status_code} ({step['response_time_ms']:.0f}ms)")
        else:
            step["error"] = f"HTTP {resp.status_code}"
            print(f"  ❌ {description}: {resp.status_code}")
    except requests.exceptions.Timeout:
        step["error"] = "Timeout (10s)"
        print(f"  ❌ {description}: Timeout")
    except Exception as e:
        step["error"] = str(e)
        print(f"  ❌ {description}: {e}")
    return step


def capture_summary(context, server_url: str) -> str:
    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    failed = total - passed
    times = [s["response_time_ms"] for s in context.step_results if s.get("response_time_ms")]
    avg_ms = sum(times) / len(times) if times else 0

    lines = [
        "-" * 60,
        "🎯 [VPT SMOKE UI] EXECUTION SUMMARY",
        "-" * 60,
        f"🌐 Server: {server_url}",
        f"⏱️ Total Time: {context.get_execution_time_ms() / 1000:.1f}s",
        f"⚡ Avg Response: {avg_ms:.0f}ms",
        f"📊 Pages Checked: {total}",
        f"✅ Passed: {passed}",
        f"❌ Failed: {failed}",
        f"🎯 Success Rate: {passed / total * 100:.0f}%" if total else "🎯 Success Rate: 0%",
        f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}",
    ]
    if failed:
        lines.append("\n❌ Failed Pages:")
        for s in context.step_results:
            if not s.get("success"):
                lines.append(f"   • {s['description']}: {s.get('error', 'unknown')}")
    lines.append("-" * 60)
    return "\n".join(lines)


@script("smoke_ui", "Verify all VirtualPyTest UI pages are accessible")
def main():
    context = get_context()
    args = get_args()
    server_url = getattr(args, "server", None) or os.getenv("SERVER_URL", "http://localhost:5109")

    print(f"🔍 [smoke_ui] Testing {len(VPT_PAGES)} VPT pages against {server_url}")

    for path, description in VPT_PAGES:
        step = test_endpoint(server_url, path, description, context)
        context.step_results.append(step)

    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    context.overall_success = (passed == total and total > 0)

    context.execution_summary = capture_summary(context, server_url)
    print(f"\n{'✅' if context.overall_success else '❌'} [smoke_ui] {passed}/{total} pages OK")
    return context.overall_success


main._script_args = [
    "--userinterface:str:virtualpytest_web",  # tags script_results so the Self-Test dashboard picks the run up
    "--server:str:",  # Override SERVER_URL env var
]

if __name__ == "__main__":
    main()
