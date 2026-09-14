#!/usr/bin/env python3
"""
VirtualPyTest Smoke — Heatmap & Monitoring

Verifies the monitoring stack:
  1. Heatmap history endpoint returns a valid response
  2. Alerts endpoints (all + active) are accessible
  3. Recent deployment executions are queryable

This confirms the Heatmap and Incidents pages have working data sources.

Usage:
    python test_scripts/vpt/smoke_heatmap.py
    python test_scripts/vpt/smoke_heatmap.py --server http://192.168.0.103:5109
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

MONITORING_ENDPOINTS = [
    ("/server/heatmap/history",                 "Heatmap — history records"),
    ("/server/alerts/getAllAlerts",             "Incidents — all alerts"),
    ("/server/alerts/getActiveAlerts",         "Incidents — active alerts"),
    ("/server/deployment/executions/recent",   "Heatmap — recent executions"),
]


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    api_key = os.getenv("API_KEY", "")
    if api_key:
        h["X-API-Key"] = api_key
        h["Authorization"] = f"Bearer {api_key}"
    return h


def test_endpoint(server_url: str, path: str, description: str, team_id: str) -> dict:
    step = {
        "action": f"GET {path}",
        "description": description,
        "timestamp": time.time(),
        "success": False,
        "error": None,
        "response_time_ms": 0,
        "status_code": None,
        "record_count": None,
    }
    try:
        params = {"team_id": team_id}
        t0 = time.time()
        resp = requests.get(
            f"{server_url}{path}",
            params=params,
            headers=_headers(),
            timeout=12,
            verify=False,
        )
        step["response_time_ms"] = round((time.time() - t0) * 1000, 1)
        step["status_code"] = resp.status_code

        if resp.status_code == 200:
            step["success"] = True
            try:
                body = resp.json()
                # Try to extract a record count for context
                for key in ("heatmaps", "alerts", "executions", "data", "results"):
                    val = body.get(key)
                    if isinstance(val, list):
                        step["record_count"] = len(val)
                        break
            except Exception:
                pass
            count_str = f", {step['record_count']} records" if step["record_count"] is not None else ""
            print(f"  ✅ {description}: HTTP {resp.status_code} ({step['response_time_ms']:.0f}ms{count_str})")
        else:
            step["error"] = f"HTTP {resp.status_code}"
            print(f"  ❌ {description}: HTTP {resp.status_code}")
    except requests.exceptions.Timeout:
        step["error"] = "Timeout (12s)"
        print(f"  ❌ {description}: Timeout")
    except Exception as e:
        step["error"] = str(e)
        print(f"  ❌ {description}: {e}")
    return step


def capture_summary(context, server_url: str) -> str:
    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    times = [s["response_time_ms"] for s in context.step_results if s.get("response_time_ms")]
    avg_ms = sum(times) / len(times) if times else 0

    lines = [
        "-" * 60,
        "🎯 [VPT SMOKE HEATMAP] EXECUTION SUMMARY",
        "-" * 60,
        f"🌐 Server: {server_url}",
        f"⏱️ Total Time: {context.get_execution_time_ms() / 1000:.1f}s",
        f"⚡ Avg Response: {avg_ms:.0f}ms",
        f"📊 Endpoints Checked: {total}  ✅ {passed}  ❌ {total - passed}",
        "",
        "📋 Endpoint Results:",
    ]
    for s in context.step_results:
        icon = "✅" if s["success"] else "❌"
        count = f" ({s['record_count']} records)" if s.get("record_count") is not None else ""
        err = f" — {s['error']}" if s.get("error") else ""
        lines.append(f"   {icon} {s['description']}{count}{err}")
    lines += [
        "",
        f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}",
        "-" * 60,
    ]
    return "\n".join(lines)


@script("smoke_heatmap", "Verify VirtualPyTest heatmap and monitoring endpoints")
def main():
    context = get_context()
    args = get_args()
    server_url = getattr(args, "server", None) or os.getenv("SERVER_URL", "http://localhost:5109")
    team_id = context.team_id

    print(f"🔍 [smoke_heatmap] Checking monitoring stack at {server_url}")

    for path, description in MONITORING_ENDPOINTS:
        step = test_endpoint(server_url, path, description, team_id)
        context.step_results.append(step)

    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    context.overall_success = passed == total and total > 0

    context.execution_summary = capture_summary(context, server_url)
    print(f"\n{'✅' if context.overall_success else '❌'} [smoke_heatmap] {passed}/{total} monitoring checks OK")
    return context.overall_success


main._script_args = [
    "--userinterface:str:virtualpytest_web",  # tags script_results so the Self-Test dashboard picks the run up
    "--server:str:",  # Override SERVER_URL env var
]

if __name__ == "__main__":
    main()
