"""
Server Desktop Bash Route Tests

server_desktop_bash_routes.py exposes a single proxy endpoint that forwards
bash command execution to a real connected desktop host
(POST /server/desktop/bash/executeCommand -> /host/desktop/bash/executeCommand).

Because this endpoint executes real shell commands on a real desktop device,
the happy path is skipped in this sandbox (no live server/device reachable).
Only the safe, pre-proxy validation path is exercised: proxy_to_host()
(backend_server/src/lib/utils/route_utils.py::get_host_from_request) requires
a host_name in the JSON body or query params and returns 400 *before* any
request reaches a host when it is missing.
"""

import requests


def test_execute_command_requires_host_name(base_url, api_headers, verify_ssl, request_timeout):
    """Without host_name, proxy_to_host() short-circuits with 400 and never reaches a host."""
    response = requests.post(
        f"{base_url}/server/desktop/bash/executeCommand",
        json={"command": "echo hello"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert "host_name" in body.get("error", "").lower()


def test_execute_command_unknown_host_returns_400(base_url, api_headers, verify_ssl, request_timeout):
    """A host_name that isn't registered is rejected before any command executes."""
    response = requests.post(
        f"{base_url}/server/desktop/bash/executeCommand",
        json={"command": "echo hello", "host_name": "__nonexistent_host_for_tests__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False

