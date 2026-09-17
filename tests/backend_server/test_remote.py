"""
Tests for backend_server/src/routes/server_remote_routes.py

Every endpoint here proxies to a real host's remote controller to drive
physical hardware (tap/click/screenshot/command on a real device).
`proxy_to_host_with_params()` / `get_host_from_request()` always validate
that `host_name` is present *before* any host is contacted (see
route_utils.py), so the "host_name missing" 400 path is pure input
validation and safe to run live for every route in this file regardless of
hardware availability.

Set REMOTE_TEST_HOST and optionally REMOTE_TEST_DEVICE_ID to an Android TV
host in your own lab. Hardware reads are skipped when no host is configured.
Only read-only actions are exercised; input actions remain skipped.
"""

import os

import pytest
import requests

REAL_HOST = os.environ.get("REMOTE_TEST_HOST", "")
REAL_DEVICE_ID = os.environ.get("REMOTE_TEST_DEVICE_ID", "device1")


@pytest.mark.parametrize("path", [
    "/server/remote/takeScreenshot",
    "/server/remote/screenshotAndDump",
    "/server/remote/getApps",
    "/server/remote/clickElement",
    "/server/remote/tapCoordinates",
    "/server/remote/executeCommand",
    "/server/remote/dumpUi",
])
def test_remote_endpoint_requires_host_name(path, base_url, api_headers, verify_ssl, request_timeout):
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


def test_stream_tap_unknown_host_returns_400(base_url, api_headers, verify_ssl, request_timeout):
    """stream_tap() used to reference an undefined `host` name in its
    validation guard, raising a NameError on every call regardless of
    payload (a 500, not the intended 400) — fixed 2026-09-07 to resolve the
    host via get_host_from_request() like every other route in this file.
    Not live-verified against the deployed server yet (fix not deployed at
    write time), but this now matches every other "unknown host" test in
    this suite, which are live-verified."""
    response = requests.post(
        f"{base_url}/server/remote/streamTap",
        json={
            "host_name": "__definitely_not_a_real_host__",
            "stream_x": 10,
            "stream_y": 10,
            "stream_width": 100,
            "stream_height": 100,
            "device_width": 200,
            "device_height": 200,
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


@pytest.mark.manual  # hardware read: set REMOTE_TEST_HOST and run with -m manual
def test_take_screenshot_from_real_device(base_url, api_headers, verify_ssl, request_timeout):
    """The configured Android TV device returns a base64 PNG screenshot."""
    response = requests.post(
        f"{base_url}/server/remote/takeScreenshot",
        json={"host_name": REAL_HOST, "device_id": REAL_DEVICE_ID},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("screenshot"), str)
    assert len(body["screenshot"]) > 100


@pytest.mark.manual  # hardware read: set REMOTE_TEST_HOST and run with -m manual
def test_screenshot_and_dump_from_real_device(base_url, api_headers, verify_ssl, request_timeout):
    """Only asserts the
    screenshot field — this controller type doesn't include a separate UI
    dump in the response (that's Appium-specific), so the exact shape may
    differ for other device types."""
    response = requests.post(
        f"{base_url}/server/remote/screenshotAndDump",
        json={"host_name": REAL_HOST, "device_id": REAL_DEVICE_ID},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("screenshot"), str)


@pytest.mark.manual  # hardware read: set REMOTE_TEST_HOST and run with -m manual
def test_get_apps_from_real_device(base_url, api_headers, verify_ssl, request_timeout):
    """Regression for an Android TV app-listing bug:
    android_tv.py's get_installed_apps() pre-converted to
    {'packageName': ..., 'label': ...} dicts, but host_remote_routes.py's
    /getApps does `app.package_name`/`app.label` attribute access on
    whatever it gets back — a 500 ("'dict' object has no attribute
    'package_name'") on every call, for every android_tv device, always.
    Fixed the same day to return AndroidApp objects instead, matching
    android_mobile.py/appium_remote.py's already-correct contract. Not
    live-verified against the deployed server yet (backend_host fix not
    deployed at write time)."""
    response = requests.post(
        f"{base_url}/server/remote/getApps",
        json={"host_name": REAL_HOST, "device_id": REAL_DEVICE_ID},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    apps = body.get("apps")
    assert isinstance(apps, list)
    if apps:
        assert "packageName" in apps[0]

