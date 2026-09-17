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
"""

import requests


def test_analyze_compatibility_requires_team_id(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/ai/analyzeCompatibility",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "team_id is required"


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


def test_get_status_requires_team_id(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/ai/getStatus",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "team_id is required"


def test_stop_execution_requires_team_id(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/ai/stopExecution",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "team_id is required"


def test_analyze_prompt_requires_team_id(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/ai/analyzePrompt",
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


def test_save_disambiguation_requires_json_body(base_url, request_timeout, verify_ssl, api_headers):
    """Sending a malformed JSON body trips require_json() before the proxy call
    (this endpoint has no team_id guard, so a syntactically valid body would
    proxy straight through to the host)."""
    response = requests.post(
        f"{base_url}/server/ai/saveDisambiguation",
        data="not-json",
        headers={**api_headers, "Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "No JSON data provided"


# ---------------------------------------------------------------------------
# Happy paths intentionally skipped: each of these proxies to a live
# backend_host and/or triggers a real AI/LLM call, and none exposes a
# dry-run mode. Running them in CI would require a live host and could spend
# real API credits on every run.
# ---------------------------------------------------------------------------


