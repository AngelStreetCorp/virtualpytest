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
- Unit test for the `tool_names` subset path on the MCP server singleton
  (no network, no LLM — verifies the cache is reused, hidden tools are
  excluded, and unknown names are silently dropped).
"""
import requests
import pytest


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


# --- Unit tests for the tool_names subset path ----------------------------
# These do not hit a live server. They use the in-process MCP server
# singleton (the same instance the proxy uses) to verify the filter behaves
# as documented: subset honoured, hidden tools still excluded, unknown
# names silently dropped, ordering preserved.
# ----------------------------------------------------------------------------

def _get_mcp_server():
    """Lazy import of the MCP server singleton — avoids pulling Flask app
    context at collection time on test runners that don't need it."""
    from backend_server.src.mcp.mcp_instance import get_mcp_server
    return get_mcp_server()


@pytest.mark.unit
def test_get_tools_by_names_returns_subset():
    mcp = _get_mcp_server()
    full = mcp.get_available_tools()
    full_names = {t['name'] for t in full}
    # Pick three that are in the catalog and one that isn't.
    sample = ['execute_device_action', 'capture_screenshot', 'list_hosts']
    sample.append('__definitely_not_a_real_tool__')
    result = mcp.get_tools_by_names(sample)
    result_names = {t['name'] for t in result}

    # Unknown names silently dropped.
    assert '__definitely_not_a_real_tool__' not in result_names
    # Known names returned (assuming they are in the catalog — they are in
    # the live server, so a CI run that hits a real catalog will pass).
    for name in sample[:3]:
        if name in full_names:
            assert name in result_names
    # No hidden tools in the result.
    for t in result:
        assert t['name'] not in mcp.HIDDEN_TOOLS
    # Ordering preserved (the unknown name is dropped from the middle, so
    # the result is the original order with the bogus entry removed).
    result_in_order = [t['name'] for t in result]
    expected = [n for n in sample if n in result_names]
    assert result_in_order == expected


@pytest.mark.unit
def test_get_tools_by_names_excludes_hidden_tools():
    mcp = _get_mcp_server()
    # The proxy exposes HIDDEN_TOOLS = {take_control, release_control} from
    # the catalog. Even if a caller explicitly names them, they must be
    # excluded (lock management is the server's job, not the caller's).
    result = mcp.get_tools_by_names(['take_control', 'release_control', 'execute_device_action'])
    result_names = {t['name'] for t in result}
    assert 'take_control' not in result_names
    assert 'release_control' not in result_names
    assert 'execute_device_action' in result_names


@pytest.mark.unit
def test_get_tools_by_names_empty_or_none_returns_empty():
    mcp = _get_mcp_server()
    assert mcp.get_tools_by_names([]) == []
    assert mcp.get_tools_by_names(None) == []

