"""
Tests for server_monitoring_routes.py (/server/monitoring/*)

These endpoints proxy to a host monitoring controller via
proxy_to_host_with_params(), which calls get_host_from_request(): when the
request carries no host_name (body or query), it short-circuits with a 400
before ever attempting a network call to a host — that's the only path we
can exercise safely without a live registered host.

/proxyImage also validates its host_ip query param against a registered-host
allowlist (SSRF protection) before ever making an outbound request, so its
missing-param and not-allowlisted paths are safe to test directly.
"""
import requests


def test_list_captures_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/monitoring/listCaptures",
        json={"device_id": "device1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_latest_json_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/monitoring/latest-json",
        json={"device_id": "device1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_json_by_time_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/monitoring/json-by-time",
        json={"device_id": "device1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_live_events_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/monitoring/live-events",
        json={"device_id": "device1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_proxy_image_requires_host_ip(get, api_headers):
    response = get(
        "/server/monitoring/proxyImage/screenshot.jpg",
        headers=api_headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "host_ip" in body.get("error", "")


def test_proxy_image_rejects_unregistered_host_ip(get, api_headers):
    """SSRF guard: host_ip must match localhost or a registered host."""
    response = get(
        "/server/monitoring/proxyImage/screenshot.jpg",
        headers=api_headers,
        params={"host_ip": "8.8.8.8"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body.get("success") is False
    assert "not authorized" in body.get("error", "").lower()
