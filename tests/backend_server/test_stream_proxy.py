"""
Tests for server_stream_proxy_routes.py (/server/stream/*)

All three endpoints forward requests to a host via call_host(), but each
validates host_name and looks it up in the host manager BEFORE ever making
an outbound request, so the "missing host_name" (400) and "unknown host"
(404) paths are safe to exercise without a live device/host stream.
The success path (an actual proxied screenshot/stream/verification call)
needs a real registered host and is intentionally not covered here.
"""
import requests

UNKNOWN_HOST = "__nonexistent_host_for_ci__"


def test_screenshot_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/av/screenshot",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert "host_name" in response.json().get("error", "")


def test_screenshot_rejects_unknown_host(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/av/screenshot",
        json={"host_name": UNKNOWN_HOST},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert UNKNOWN_HOST in response.json().get("error", "")


def test_stream_url_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/av/streamUrl",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert "host_name" in response.json().get("error", "")


def test_stream_url_rejects_unknown_host(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/av/streamUrl",
        json={"host_name": UNKNOWN_HOST},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert UNKNOWN_HOST in response.json().get("error", "")


def test_verification_execute_requires_host_name(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/verification/execute",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert "host_name" in response.json().get("error", "")


def test_verification_execute_rejects_unknown_host(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/stream/verification/execute",
        json={"host_name": UNKNOWN_HOST},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert UNKNOWN_HOST in response.json().get("error", "")
