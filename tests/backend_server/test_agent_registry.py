"""
Agent Registry Routes Tests

Covers backend_server/src/routes/agent_registry_routes.py (blueprint:
/server/agents). Agents here are global system resources loaded from YAML
templates on disk - no team_id, no per-request mutation of durable state.
POST /reload re-parses those YAML templates (a local, deterministic,
no-cost operation) and POST /import only validates a YAML payload without
persisting it, so both are exercised for real.
"""

import requests


def test_list_agents(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/agents/",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("agents"), list)
    assert body.get("count") == len(body["agents"])


def test_list_agents_selectable_filter(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/agents/",
        params={"selectable": "true"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    assert isinstance(response.json().get("agents"), list)


def test_list_selectable_agents_convenience_endpoint(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/agents/selectable",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("agents"), list)
    assert body.get("count") == len(body["agents"])


def test_get_agent_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/agents/__nonexistent_agent__",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert "not found" in response.json().get("error", "").lower()


def test_get_agent_by_id_from_list(base_url, request_timeout, verify_ssl, api_headers):
    """Discover a real agent_id from the list endpoint, then fetch it directly."""
    list_response = requests.get(
        f"{base_url}/server/agents/",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert list_response.status_code == 200
    agents = list_response.json().get("agents", [])
    if not agents:
        import pytest
        pytest.skip("No system agents registered on this server")
    agent_id = agents[0]["metadata"]["id"]

    response = requests.get(
        f"{base_url}/server/agents/{agent_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    assert response.json().get("metadata", {}).get("id") == agent_id


def test_export_agent_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/agents/__nonexistent_agent__/export",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404


def test_get_agents_for_event(base_url, request_timeout, verify_ssl, api_headers):
    """Read-only lookup; an unrecognized event type is expected to just
    return an empty agent list rather than error."""
    response = requests.get(
        f"{base_url}/server/agents/events/__nonexistent_event__",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("event_type") == "__nonexistent_event__"
    assert isinstance(body.get("agents"), list)
    assert body.get("count") == len(body["agents"])


def test_reload_agents(base_url, request_timeout, verify_ssl, api_headers):
    """Re-parses the on-disk YAML templates into the in-memory registry - a
    deterministic, local, no-cost operation with no external calls."""
    response = requests.post(
        f"{base_url}/server/agents/reload",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("count"), int)
    assert isinstance(body.get("agents"), list)


def test_import_agent_yaml_requires_content(base_url, request_timeout, verify_ssl, api_headers):
    """No file upload and no raw body returns 400 before any YAML parsing."""
    response = requests.post(
        f"{base_url}/server/agents/import",
        headers={k: v for k, v in api_headers.items() if k.lower() != "content-type"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "No YAML content provided"


def test_import_agent_yaml_rejects_invalid_yaml(base_url, request_timeout, verify_ssl, api_headers):
    """Import only validates (never persists) - an incomplete agent
    definition must fail validate_agent_yaml() with a 400."""
    response = requests.post(
        f"{base_url}/server/agents/import",
        data="not: a valid agent definition",
        headers={**api_headers, "Content-Type": "text/plain"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert "error" in response.json()
