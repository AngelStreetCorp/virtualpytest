"""
Tests for backend_server/src/routes/server_control_routes.py

Device-lock bookkeeping (acquire/release/check/list/heartbeat/force-unlock)
lives entirely in an in-memory/DB lock table keyed by (host_name, device_id)
strings — none of it contacts a host or piece of hardware directly. The
route source confirms this: e.g. `acquire_execution_lock`/
`release_execution_lock` never call `get_host_manager()`, and
`abort_and_force_unlock()` skips the host-abort call entirely when the host
isn't registered (see lock_utils.abort_and_force_unlock). That makes those
paths safe to exercise live against a throwaway host_name/device_id pair
that will never collide with anything real, with immediate cleanup.

Endpoints that hand off to a *registered* host (takeControl's background
setup thread, releaseControl's host notification, takeover, navigation
execute/batchExecute) are only exercised for their input-validation paths
here; their hardware-driving paths are skipped.
"""

import uuid

import requests


def _post(base_url, path, json_body, api_headers, verify_ssl, request_timeout):
    return requests.post(
        f"{base_url}{path}",
        json=json_body,
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )


# ---------------------------------------------------------------------------
# Pure lock-table reads/writes — safe to run fully live
# ---------------------------------------------------------------------------


def test_get_all_controllers_returns_types(get, api_headers):
    response = get("/server/control/getAllControllers", headers=api_headers)
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    controller_types = body.get("controller_types")
    assert isinstance(controller_types, dict)
    for key in ("remote", "av", "verification", "power"):
        assert key in controller_types


def test_locked_devices_returns_dict(get, api_headers):
    response = get("/server/control/lockedDevices", headers=api_headers)
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("locked_devices"), dict)


def test_check_lock_for_never_locked_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/checkLock",
        {"host_name": f"nonexistent-host-{uuid.uuid4()}", "device_id": "test-device"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert body.get("is_locked") is False
    assert body.get("lock_info") is None


def test_force_unlock_never_locked_device_is_a_noop(base_url, api_headers, verify_ssl, request_timeout):
    """force_unlock on an unregistered host skips the host-abort call
    entirely (lock_utils.abort_and_force_unlock) and the underlying
    force_unlock() lock-table op reports released=False for a device with no
    lock — no hardware is touched."""
    response = _post(
        base_url,
        "/server/control/forceUnlock",
        {"host_name": f"nonexistent-host-{uuid.uuid4()}", "device_id": "test-device"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert body.get("released") is False
    assert body.get("aborted") is False


def test_acquire_and_release_execution_lock_roundtrip(base_url, api_headers, verify_ssl, request_timeout):
    host_name = f"test-host-{uuid.uuid4()}"
    device_id = f"test-device-{uuid.uuid4()}"
    owner_session_id = str(uuid.uuid4())

    acquire_response = _post(
        base_url,
        "/server/control/acquireExecutionLock",
        {
            "host_name": host_name,
            "device_id": device_id,
            "owner_type": "test_execution",
            "owner_session_id": owner_session_id,
        },
        api_headers, verify_ssl, request_timeout,
    )
    try:
        assert acquire_response.status_code == 200
        acquire_body = acquire_response.json()
        assert acquire_body.get("success") is True
        assert isinstance(acquire_body.get("lock_info"), dict)
    finally:
        release_response = _post(
            base_url,
            "/server/control/releaseExecutionLock",
            {
                "host_name": host_name,
                "device_id": device_id,
                "owner_session_id": owner_session_id,
                "owner_type": "test_execution",
            },
            api_headers, verify_ssl, request_timeout,
        )
        assert release_response.status_code == 200
        assert release_response.json().get("success") is True


def test_heartbeat_and_release_control_roundtrip(base_url, api_headers, verify_ssl, request_timeout):
    """heartbeat() acquires a manual_control lock purely in the lock table
    (owner_type='manual_control'); releaseControl() then releases it. Since
    the host_name is unregistered, releaseControl's host-notification thread
    is skipped entirely (host_data lookup returns None) — no hardware call
    is made."""
    host_name = f"test-host-{uuid.uuid4()}"
    device_id = f"test-device-{uuid.uuid4()}"
    session_id = str(uuid.uuid4())

    heartbeat_response = _post(
        base_url,
        "/server/control/heartbeat",
        {
            "devices": [{"host_name": host_name, "device_id": device_id}],
            "session_id": session_id,
        },
        api_headers, verify_ssl, request_timeout,
    )
    try:
        assert heartbeat_response.status_code == 200
        body = heartbeat_response.json()
        assert body.get("success") is True
        results = body.get("results")
        assert isinstance(results, list) and len(results) == 1
        assert results[0].get("success") is True
    finally:
        release_response = _post(
            base_url,
            "/server/control/releaseControl",
            {"host_name": host_name, "device_id": device_id, "session_id": session_id},
            api_headers, verify_ssl, request_timeout,
        )
        assert release_response.status_code == 200
        assert release_response.json().get("success") is True


# ---------------------------------------------------------------------------
# Input-validation-only coverage for hardware-driving endpoints
# ---------------------------------------------------------------------------


def test_take_control_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/takeControl", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_take_control_unknown_host_returns_404(base_url, api_headers, verify_ssl, request_timeout):
    """Host-registry lookup happens before any lock is acquired, so this is
    safe without hardware."""
    response = _post(
        base_url,
        "/server/control/takeControl",
        {"host_name": f"nonexistent-host-{uuid.uuid4()}", "device_id": "test-device"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 404
    assert response.json().get("success") is False


def test_release_control_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/releaseControl", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_release_control_requires_session_id(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/releaseControl",
        {"host_name": "test-host", "device_id": "test-device"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 400


def test_check_lock_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/checkLock", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_heartbeat_requires_devices(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/heartbeat", {"devices": []}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_force_unlock_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/forceUnlock", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_takeover_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/takeover", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400


def test_acquire_execution_lock_requires_fields(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/acquireExecutionLock", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_release_execution_lock_requires_host_and_device(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(base_url, "/server/control/releaseExecutionLock", {}, api_headers, verify_ssl, request_timeout)
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_execute_navigation_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/navigation/execute",
        {"navigation_data": {"steps": []}},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 400


def test_execute_navigation_requires_navigation_data(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/navigation/execute",
        {"host_name": "test-host"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 400


def test_batch_execute_navigation_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/navigationBatchExecute",
        {"batch_data": []},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 400


def test_batch_execute_navigation_requires_list_batch_data(base_url, api_headers, verify_ssl, request_timeout):
    response = _post(
        base_url,
        "/server/control/navigationBatchExecute",
        {"host_name": "test-host", "batch_data": "not-a-list"},
        api_headers, verify_ssl, request_timeout,
    )
    assert response.status_code == 400

