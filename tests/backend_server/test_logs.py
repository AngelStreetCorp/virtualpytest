"""
Logs Routes Tests

logs_routes.py (blueprint url_prefix /server/logs) exposes systemd service
logs (via journalctl) and a whitelist of service names. It sits under
/server/*, so the global frontend JWT auth guard in app.py applies to it when
enabled.

  POST /server/logs/view      -> tail logs for one service: local journalctl,
                                  or proxied to a backend_host for
                                  vpt-stream/device logs and HOST_FILE_LOGS
                                  (currently only 'deployments')
  GET  /server/logs/services  -> list ALLOWED_SERVICES with their live
                                  `systemctl is-active` status

Every /view validation branch below (missing service, disallowed service,
follow mode, vpt-stream/host-file logs without host_name) returns before any
host is contacted or subprocess spawned, so they're safe to call live.
Reading a real whitelisted service's local journalctl logs is also
exercised, but the assertion tolerates either outcome (200 success, or 500 if
journalctl/that service isn't present on this deployment) since that depends
on the actual server host's systemd/journald state, not on route logic.
"""

import requests


def test_view_logs_requires_service(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "service is required"
    assert isinstance(body.get("available_services"), list)


def test_view_logs_rejects_disallowed_service(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={"service": "__not_a_real_service__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert "not allowed" in body.get("error", "")


def test_view_logs_follow_mode_not_supported(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={"service": "vpt-server", "follow": True},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "Follow mode not supported via API."


def test_view_logs_vpt_stream_device_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={"service": "vpt-stream", "device_id": "device1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "host_name is required for vpt-stream device logs"


def test_view_logs_host_file_log_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={"service": "deployments"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "host_name is required for host file logs"


def test_view_logs_local_service(base_url, api_headers, verify_ssl, request_timeout):
    """Reads real local journalctl logs for a whitelisted service with no
    host_name given. Accepts either outcome since it depends on the deployed
    host's systemd/journald state, not on the route's own logic."""
    response = requests.post(
        f"{base_url}/server/logs/view",
        json={"service": "vpt-server", "lines": 5},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (200, 500), response.text
    body = response.json()
    assert isinstance(body.get("success"), bool)


def test_list_services(get, api_headers):
    response = get("/server/logs/services", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    services = body.get("services")
    assert isinstance(services, list)
    assert body.get("count") == len(services)
    for service in services:
        assert "name" in service
        assert "status" in service
        assert "active" in service
