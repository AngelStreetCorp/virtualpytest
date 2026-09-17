"""
Shared helpers for the VPT smoke test family (smoke_*.py in this directory).

Every smoke script records one "check" per step via record_step_immediately().
make_step() is the single place that turns a check's outcome into a report
step dict — it populates `verifications` (the same field the report renderer
uses for every other script's expandable step detail) so smoke test steps
show what was actually checked and why it passed/failed, instead of just a
flat PASS/FAIL line with a duration.
"""

import os
import time


def headers() -> dict:
    h = {"Content-Type": "application/json"}
    api_key = os.getenv("API_KEY", "")
    if api_key:
        h["X-API-Key"] = api_key
        h["Authorization"] = f"Bearer {api_key}"
    return h


def make_step(action: str, description: str, success: bool, *,
              error: str = None, status_code: int = None,
              response_time_ms: float = 0, detail: str = None) -> dict:
    """Build a report-ready step dict for one smoke check.

    `action` is the request performed (e.g. "GET /server/health"), `detail`
    is any extra context worth showing (record counts, resolved IP, segment
    size, etc). Both end up in the step's `verifications` entry so the
    report's expandable step body has something to show.
    """
    icon = "✅" if success else "❌"
    print(f"  {icon} {description}"
          + (f": {error}" if error else
             f": HTTP {status_code} ({response_time_ms:.0f}ms)" if status_code else "")
          + (f" — {detail}" if detail else ""))

    end_time = time.time()
    details_parts = []
    if detail:
        details_parts.append(detail)
    if status_code:
        details_parts.append(f"HTTP {status_code}")
    if response_time_ms:
        details_parts.append(f"{response_time_ms:.0f}ms")
    if error:
        details_parts.append(error)

    return {
        "action": action,
        "message": description,
        "description": description,
        "timestamp": end_time,
        "start_time": end_time - (response_time_ms / 1000.0),
        "end_time": end_time,
        "execution_time_ms": int(response_time_ms),
        "success": success,
        "error": error,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "actions": [{"command": action, "params": {}}],
        "verifications": [{
            "label": description,
            "details": " · ".join(details_parts),
            "success": success,
        }],
    }
