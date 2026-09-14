"""
Server Web Routes Tests

server_web_routes.py (blueprint url_prefix /server/web) proxies web-automation
commands to a selected host controller. Every endpoint except /taskComplete
resolves a `host_name` via get_host_from_request() before doing anything, so
calling them without a real, registered host consistently fails validation
with 400 before any host is ever contacted — safe to exercise live.

  POST /server/web/executeCommand -> proxy to host /host/web/executeCommand (or
                                      starts a background browser_use_task)
  POST /server/web/taskComplete   -> callback receiver (host -> server);
                                      explicitly listed as an unauthenticated
                                      route in app.py's global auth guard
  POST /server/web/navigateToUrl  -> proxy to host /host/web/navigateToUrl
  POST /server/web/getPageInfo    -> proxy to host /host/web/getPageInfo
  POST /server/web/openBrowser    -> proxy to host /host/web/openBrowser
  POST /server/web/closeBrowser   -> proxy to host /host/web/closeBrowser
  POST /server/web/getStatus      -> proxy to host /host/web/getStatus

Every proxy endpoint here is only exercised for its `host_name` validation
path — actually reaching a host would run a real browser action on that
host's machine, which is a side effect this suite avoids.
"""

import requests


def test_execute_command_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/executeCommand",
        json={"command": "navigate"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_navigate_to_url_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/navigateToUrl",
        json={"url": "https://example.com"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_get_page_info_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/getPageInfo",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_open_browser_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/openBrowser",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_close_browser_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/closeBrowser",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_get_status_requires_host(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/getStatus",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error")


def test_task_complete_requires_task_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/web/taskComplete",
        json={"result": {}},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "task_id required"


def test_task_complete_accepts_unknown_task_id(base_url, api_headers, verify_ssl, request_timeout):
    """Completing a task_id the server never created is a safe no-op — the
    in-memory task_manager just skips updating an id it doesn't know about —
    so this exercises the happy path without depending on a real in-flight
    browser-use task."""
    response = requests.post(
        f"{base_url}/server/web/taskComplete",
        json={"task_id": "non-existent-task-id-for-tests", "result": {"ok": True}},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
