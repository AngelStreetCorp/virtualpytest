"""
Server Actions Route Tests

server_actions_routes.py (blueprint url_prefix /server/action) proxies action
execution to a real connected host's NavigationExecutor. Endpoints:

  POST /server/action/executeBatch              -> proxies to /host/action/executeBatch
  GET  /server/action/execution/<id>/status      -> proxies to /host/action/execution/<id>/status
  POST /server/action/abortExecution             -> proxies to /host/action/abortExecution
  POST /server/action/execute                    -> proxies to /host/action/executeBatch (single action)
  POST /server/action/checkDependenciesBatch     -> deprecated stub, no host call, fixed response
  GET  /server/action/health                     -> static health payload, no host call

executeBatch/execute/abortExecution/status all validate required fields
(actions, host_name, device_id, team_id, execution_id as applicable) and, for
host_name, resolve it via get_host_from_request() *before* any proxy call is
made — an unknown/missing host_name returns 400 without touching a real
device. Those validation paths are safe to test live; actually running a
batch/single action against a real, known host_name would trigger real
execution and is skipped.

checkDependenciesBatch and health never reach a host and are always safe.
"""

import pytest
import requests


def test_health_check(get, api_headers):
    response = get("/server/action/health", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True


def test_check_dependencies_batch_returns_fixed_response(base_url, api_headers, verify_ssl, request_timeout):
    """Deprecated stub: always reports no shared actions, regardless of body."""
    response = requests.post(
        f"{base_url}/server/action/checkDependenciesBatch",
        json={"action_ids": ["whatever"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    assert body.get("has_shared_actions") is False
    assert body.get("edges") == []
    assert body.get("count") == 0


def test_execute_batch_requires_actions(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/executeBatch",
        params={"team_id": team_id},
        json={"host_name": "some_host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "actions are required"


def test_execute_batch_requires_host_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/executeBatch",
        params={"team_id": team_id},
        json={"actions": [{"action_type": "click"}]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "host_name is required"


def test_execute_batch_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/executeBatch",
        json={"actions": [{"action_type": "click"}], "host_name": "some_host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "team_id is required"


def test_execute_batch_unknown_host_returns_400(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """Validation passes but the host doesn't exist -> proxy layer rejects before executing."""
    response = requests.post(
        f"{base_url}/server/action/executeBatch",
        params={"team_id": team_id},
        json={
            "actions": [{"action_type": "click"}],
            "host_name": "__nonexistent_host_for_tests__",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text


def test_execute_single_requires_action(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/execute",
        params={"team_id": team_id},
        json={"host_name": "some_host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "action is required"


def test_execute_single_requires_host_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/execute",
        params={"team_id": team_id},
        json={"action": {"action_type": "click"}},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "host_name is required"


def test_abort_execution_requires_fields(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/action/abortExecution",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "host_name is required"


def test_get_execution_status_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/action/execution/some-execution-id/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "host_name query parameter is required"


@pytest.mark.skip(
    reason="Hosts/devices ARE online right now (see GET /server/system/getAllHosts), "
    "so this isn't blocked by missing hardware. It's excluded from the every-push "
    "regression suite because it executes a real action against a real, "
    "possibly-shared device; candidate for a separate, manually- or "
    "schedule-triggered hardware suite instead of a permanent skip — see "
    "tests/docs/testing-strategy.md."
)
def test_execute_batch_runs_on_real_device():
    """Happy path: proxies a real action batch to a live host's NavigationExecutor."""
    pass
