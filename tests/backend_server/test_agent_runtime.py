"""
Agent Runtime Routes Tests

Covers backend_server/src/routes/agent_runtime_routes.py (blueprint:
/server/runtime). POST /start and POST /stop toggle the *global* agent
runtime system shared by every client of this server, so they are skipped
to avoid disrupting concurrent CI jobs or a live deployment; everything
else here is either pure read-only introspection or a mutation guarded by
validation/not-found checks that return before any real instance is
touched.
"""

import requests


def test_list_instances(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/runtime/instances",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("instances"), list)
    assert body.get("count") == len(body["instances"])


def test_get_instance_status_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/runtime/instances/__nonexistent_instance__",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("error") == "Instance not found"


def test_start_agent_instance_requires_agent_id(base_url, request_timeout, verify_ssl, api_headers):
    """Missing agent_id returns 400 before the runtime is started or an agent
    instance is spawned."""
    response = requests.post(
        f"{base_url}/server/runtime/instances/start",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "agent_id required"


def test_stop_agent_instance_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/runtime/instances/__nonexistent_instance__/stop",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("error") == "Instance not found"


def test_pause_agent_instance_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/runtime/instances/__nonexistent_instance__/pause",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "Instance not found or cannot be paused"


def test_resume_agent_instance_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/runtime/instances/__nonexistent_instance__/resume",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "Instance not found or not paused"


def test_get_runtime_status(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/runtime/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("running"), bool)
    assert isinstance(body.get("total_instances"), int)
    assert isinstance(body.get("active_tasks"), int)
    assert isinstance(body.get("event_bus_connected"), bool)


