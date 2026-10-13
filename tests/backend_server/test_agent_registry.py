"""
Agent Registry Routes Tests

Covers backend_server/src/routes/agent_registry_routes.py (blueprint:
/server/agents). Agents here are global system resources loaded from YAML
templates on disk - no team_id, no per-request mutation of durable state.
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
