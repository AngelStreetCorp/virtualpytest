"""
Tests for backend_server/src/routes/server_power_routes.py

Both endpoints proxy to a real host's power controller (e.g. Tapo/uhubctl)
to act on physical hardware — not safely exercisable without a connected
device/host in CI. As with server_remote_routes.py, the proxy helpers
(`proxy_to_host_with_params()` / `get_host_from_request()`) validate that
`host_name` is present before contacting any host, so that validation path
is safe to run live.
"""

import os

import pytest
import requests


@pytest.mark.parametrize("path", [
    "/server/power/getStatus",
    "/server/power/executeCommand",
])
def test_power_endpoint_requires_host_name(path, base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}{path}",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


@pytest.mark.manual  # hardware read: set REMOTE_TEST_HOST and run with -m manual
def test_get_power_status_no_power_controller_configured(base_url, api_headers, verify_ssl, request_timeout):
    """Configure REMOTE_TEST_HOST to a lab device without a power controller."""
    host = os.environ.get("REMOTE_TEST_HOST")
    if not host:
        pytest.skip("Set REMOTE_TEST_HOST to a device host without a power controller")
    response = requests.post(
        f"{base_url}/server/power/getStatus",
        json={"host_name": host, "device_id": os.environ.get("REMOTE_TEST_DEVICE_ID", "device1")},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("success") is False
    assert "power controller" in body.get("error", "").lower()

