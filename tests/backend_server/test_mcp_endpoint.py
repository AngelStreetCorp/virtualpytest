import os

import pytest
import requests


def test_mcp_health(base_url, request_timeout, verify_ssl):
    response = requests.get(
        f"{base_url}/server/mcp/health",
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("status") == "healthy"
    assert isinstance(body.get("tools_count"), int)
    assert body.get("tools_count", 0) > 0
    assert isinstance(body.get("mcp_version"), str)


def test_mcp_main_endpoint_requires_auth(base_url, request_timeout, verify_ssl):
    response = requests.get(
        f"{base_url}/server/mcp",
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (401, 403)

    body = response.json()
    assert body.get("error")


def test_mcp_initialize_with_auth_if_token_available(base_url, request_timeout, verify_ssl):
    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not token:
        pytest.skip("Set MCP_AUTH_TOKEN to run authenticated MCP protocol tests")

    response = requests.post(
        f"{base_url}/server/mcp",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        },
        timeout=request_timeout,
        verify=verify_ssl,
    )

    assert response.status_code == 200
    body = response.json()
    assert body.get("jsonrpc") == "2.0"
    assert body.get("id") == 1
    assert isinstance(body.get("result"), dict)
    assert "protocolVersion" in body["result"]
