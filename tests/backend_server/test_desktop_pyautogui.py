"""
Server Desktop PyAutoGUI Route Tests

server_desktop_pyautogui_routes.py exposes a single proxy endpoint that
forwards PyAutoGUI input-simulation commands to a real connected desktop host
(POST /server/desktop/pyautogui/executeCommand -> /host/desktop/pyautogui/executeCommand).

Because this endpoint drives real mouse/keyboard input on a real desktop
device, the happy path is skipped in this sandbox (no live server/device
reachable). Only the safe, pre-proxy validation path is exercised:
proxy_to_host() (backend_server/src/lib/utils/route_utils.py::get_host_from_request)
requires a host_name in the JSON body or query params and returns 400 *before*
any request reaches a host when it is missing.
"""

import pytest
import requests


def test_execute_command_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    """Without host_name, proxy_to_host() short-circuits with 400 and never reaches a host."""
    response = requests.post(
        f"{base_url}/server/desktop/pyautogui/executeCommand",
        json={"action": "click", "x": 10, "y": 10},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert "host_name" in body.get("error", "").lower()


def test_execute_command_unknown_host_returns_400(base_url, api_headers, verify_ssl, request_timeout):
    """A host_name that isn't registered is rejected before any input is simulated."""
    response = requests.post(
        f"{base_url}/server/desktop/pyautogui/executeCommand",
        json={"action": "click", "x": 10, "y": 10, "host_name": "__nonexistent_host_for_tests__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False


@pytest.mark.skip(
    reason="A desktop-capable host IS online right now (sample-app-backend / "
    "host-clone-1 — see GET /server/system/getAllHosts), so this isn't "
    "blocked by missing hardware. It's excluded from the every-push "
    "regression suite because it simulates real mouse/keyboard input on a "
    "real shared host's screen; candidate for a separate, manually- or "
    "schedule-triggered hardware suite instead of a permanent skip — see "
    "tests/docs/testing-strategy.md."
)
def test_execute_command_runs_on_real_device():
    """Happy path: proxies a real PyAutoGUI command to a live desktop host and simulates input."""
    pass
