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
from test_scripts.vpt.smoke_common import headers as _headers, make_step

MONITORING_ENDPOINTS = [
    ("/server/heatmap/history",                 "Heatmap — history records"),
    ("/server/alerts/getAllAlerts",             "Incidents — all alerts"),
    ("/server/alerts/getActiveAlerts",         "Incidents — active alerts"),
    ("/server/deployment/executions/recent",   "Heatmap — recent executions"),
]


def test_endpoint(server_url: str, path: str, description: str, team_id: str) -> dict:
    t0 = time.time()
    try:
        resp = requests.get(
            f"{server_url}{path}",
            params={"team_id": team_id},
            headers=_headers(),
            timeout=12,
            verify=False,
        )
        ms = round((time.time() - t0) * 1000, 1)
        record_count = None
        ok = resp.status_code == 200
        if ok:
            try:
                body = resp.json()
                # Try to extract a record count for context
                for key in ("heatmaps", "alerts", "executions", "data", "results"):
                    val = body.get(key)
                    if isinstance(val, list):
                        record_count = len(val)
                        break
            except Exception:
                pass
        step = make_step(
            f"GET {path}", description, ok,
            error=None if ok else f"HTTP {resp.status_code}",
            status_code=resp.status_code,
            response_time_ms=ms,
            detail=f"{record_count} records" if record_count is not None else None,
        )
        step["record_count"] = record_count
        return step
    except requests.exceptions.Timeout:
        step = make_step(f"GET {path}", description, False,
                          error="Timeout (12s)", response_time_ms=(time.time() - t0) * 1000)
        step["record_count"] = None
        return step
    except Exception as e:
        step = make_step(f"GET {path}", description, False,
                          error=str(e), response_time_ms=(time.time() - t0) * 1000)
        step["record_count"] = None
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
        context.record_step_immediately(step)

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
