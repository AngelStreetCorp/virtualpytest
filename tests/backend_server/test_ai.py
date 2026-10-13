"""
Server AI Routes Tests

Covers backend_server/src/routes/server_ai_routes.py (blueprint: /server/ai).

Every endpoint in this module is a POST that either proxies to backend_host
(potentially triggering a real AI/LLM call) or mutates shared team data
(ai_graph_cache deletion). None of them have a dry-run/validate-only mode, so
each one is exercised here only through its validation failure path — which
returns before any proxy call or database mutation happens. The corresponding
happy-path (which would hit a live host and/or spend LLM cost) is left as an
explicit skip.

NOTE: getStatus, stopExecution, analyzePrompt, analyzeCompatibility and
saveDisambiguation were removed by TASK-36 (25caa8a5c) — they had no matching
/host/ai/* routes. Their tests are intentionally removed (no replacements).
"""

import requests


def test_generate_plan_requires_team_id(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/ai/generatePlan",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "team_id is required"


def test_reset_cache_requires_host_name(base_url, request_timeout, verify_ssl, api_headers):
    """host_name is validated before team_id and before any Supabase delete, so
    this never touches the ai_graph_cache table."""
    response = requests.post(
        f"{base_url}/server/ai/resetCache",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "host_name required"


# ---------------------------------------------------------------------------
# Happy paths intentionally skipped: each remaining endpoint proxies to a live
# backend_host and/or triggers a real AI/LLM call, and none exposes a
# dry-run mode. Running them in CI would require a live host and could spend
# real API credits on every run.
# ---------------------------------------------------------------------------