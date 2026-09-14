"""
Tests for server_mcp_proxy_routes.py (/server/mcp-proxy/*)

- POST /server/mcp-proxy/execute-prompt — bridges a natural-language prompt to
  MCP tool execution via a real OpenRouter LLM call, which can then execute a
  real device action (execute_device_action / navigate_to_node / etc.) on a
  live host. Only the pre-flight validation path (missing prompt) is safe to
  exercise against a live server; the actual prompt-execution path is skipped
  since it costs real LLM tokens and can drive a real device.
- GET /server/mcp-proxy/list-tools — pure read of the already-registered MCP
  tool catalog, no external calls, safe to exercise fully.
"""
import pytest
import requests


def test_execute_prompt_requires_prompt(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/mcp-proxy/execute-prompt",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "Prompt required"


@pytest.mark.skip(reason="calls a real OpenRouter LLM and can execute a real device/host action — unsafe to run in every CI cycle")
def test_execute_prompt_runs_a_device_action():
    """POST /server/mcp-proxy/execute-prompt with a real prompt — drives a live device."""


def test_list_tools_returns_catalog(get, api_headers):
    response = get("/server/mcp-proxy/list-tools", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    tools = body.get("tools")
    assert isinstance(tools, list)
    assert body.get("count") == len(tools)
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
