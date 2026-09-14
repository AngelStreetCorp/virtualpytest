"""
Tests for backend_server/src/routes/server_campaign_execution_routes.py

Most endpoints here acquire real device locks and proxy to a host that
drives physical hardware (execute, abortRunning, execution/<id>/status,
executionComplete's DB/webhook side effects). Per the request-validation
order in the route source, every one of those endpoints checks required
fields — and, for execute/abortRunning, checks whether host_name is a
registered host — *before* touching any lock or hardware. Those validation
paths are pure input checks and are safe to exercise live; the actual
hardware-driving paths are skipped.

/results and /results/<id> are plain DB reads and are fully exercised.
"""

import uuid

import pytest
import requests


# ---------------------------------------------------------------------------
# GET /server/campaigns/execution/<execution_id>/status
# ---------------------------------------------------------------------------


def test_get_execution_status_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/campaigns/execution/{uuid.uuid4()}/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False


def test_get_execution_status_requires_host_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """No host_name in query/body means the proxy layer refuses before ever
    contacting a host."""
    response = requests.get(
        f"{base_url}/server/campaigns/execution/{uuid.uuid4()}/status",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False


# ---------------------------------------------------------------------------
# POST /server/campaigns/abortRunning
# ---------------------------------------------------------------------------


def test_abort_running_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/abortRunning",
        json={"host_name": "test-host", "device_id": "test-device"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_abort_running_requires_host_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/abortRunning",
        params={"team_id": team_id},
        json={"device_id": "test-device"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_abort_running_requires_device_or_execution_id(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/abortRunning",
        params={"team_id": team_id},
        json={"host_name": "test-host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_abort_running_unknown_host_returns_404(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """Unregistered host_name is rejected via the host registry lookup, which
    happens before any lock/hardware interaction."""
    response = requests.post(
        f"{base_url}/server/campaigns/abortRunning",
        params={"team_id": team_id},
        json={
            "host_name": f"nonexistent-host-{uuid.uuid4()}",
            "device_id": "test-device",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("success") is False


# ---------------------------------------------------------------------------
# POST /server/campaigns/execute
# ---------------------------------------------------------------------------


def test_execute_campaign_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        json={"campaign_id": "x", "name": "x", "script_configurations": [{"script_name": "x"}]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_campaign_requires_required_fields(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_campaign_requires_script_configurations(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        params={"team_id": team_id},
        json={"campaign_id": "x", "name": "x", "script_configurations": []},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_campaign_requires_script_name_in_configs(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        params={"team_id": team_id},
        json={"campaign_id": "x", "name": "x", "script_configurations": [{}]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_campaign_requires_host_and_device(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        params={"team_id": team_id},
        json={
            "campaign_id": "x",
            "name": "x",
            "script_configurations": [{"script_name": "x"}],
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_campaign_unknown_host_returns_404(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """A fully-shaped request against an unregistered host is rejected by the
    host registry lookup before any lock is acquired or hardware touched."""
    response = requests.post(
        f"{base_url}/server/campaigns/execute",
        params={"team_id": team_id},
        json={
            "campaign_id": "x",
            "name": "x",
            "script_configurations": [{"script_name": "x"}],
            "host_name": f"nonexistent-host-{uuid.uuid4()}",
            "device_id": "test-device",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("success") is False


@pytest.mark.skip(
    reason="Hosts/devices ARE online right now (see GET /server/system/getAllHosts), "
    "so this isn't blocked by missing hardware. It's excluded from the every-push "
    "regression suite because it locks a real device and drives a full campaign/host "
    "flow for real; candidate for a separate, manually- or schedule-triggered "
    "hardware suite instead of a permanent skip — see tests/docs/testing-strategy.md."
)
def test_execute_campaign_full_flow_on_real_device():
    """Actual campaign execution locks a real device and drives a host —
    not safely testable without hardware in CI."""


# ---------------------------------------------------------------------------
# POST /server/campaigns/executionComplete
# ---------------------------------------------------------------------------


def test_execution_complete_requires_execution_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/campaigns/executionComplete",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


@pytest.mark.skip(
    reason="Hosts/devices ARE online right now (see GET /server/system/getAllHosts), "
    "so this isn't blocked by missing hardware. It's excluded from the every-push "
    "regression suite because it locks a real device and drives a full campaign/host "
    "flow for real; candidate for a separate, manually- or schedule-triggered "
    "hardware suite instead of a permanent skip — see tests/docs/testing-strategy.md."
)
def test_execution_complete_full_callback_flow():
    """This is the completion webhook a real host calls after a campaign
    finishes; invoking it with synthetic data would release real locks /
    write real deployment_execution rows without an actual run behind it."""


# ---------------------------------------------------------------------------
# GET /server/campaigns/results
# ---------------------------------------------------------------------------


def test_get_all_campaign_results_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/campaigns/results",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


@pytest.mark.xfail(
    reason=(
        "known bug: get_all_campaign_results() reads results['campaign_results'] "
        "and results['count'], but shared.src.lib.database.campaign_executions_db"
        ".get_campaign_results() only ever returns {'success', 'data'} (or "
        "{'success': False, 'error'}) — the KeyError is caught by "
        "handle_route_exceptions and surfaces as a 500 on every call, even with "
        "a valid team_id. See server_campaign_execution_routes.py:446-463."
    ),
    strict=False,
)
def test_get_all_campaign_results_returns_expected_shape(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/campaigns/results",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("campaign_results"), list)
    assert isinstance(body.get("count"), int)


# ---------------------------------------------------------------------------
# GET /server/campaigns/results/<campaign_result_id>
# ---------------------------------------------------------------------------


def test_get_campaign_result_details_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/campaigns/results/{uuid.uuid4()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_get_campaign_result_details_unknown_id_returns_404(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.get(
        f"{base_url}/server/campaigns/results/{uuid.uuid4()}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("success") is False
