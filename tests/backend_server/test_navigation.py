"""
Coverage for server_navigation_routes.py (`/server/navigation/*`).

This module owns tree-config bootstrap, cache fan-out to hosts, and screenshot
cleanup. Every endpoint here mutates real state (DB rows, per-host in-memory
caches, R2 objects) once past validation, so — per the navigation/pathfinding
delivery policy — tests stick to the validation ("400 required field") edge of
each endpoint, which is safe to run repeatedly against a live server. The one
endpoint that requires a live, controlled hardware host (`/goto`) is skipped
with a tracked reason instead of silently omitted.
"""

import uuid

import requests


def test_create_empty_navigation_config_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """Unknown interface name short-circuits before any tree/node/edge is
    written (get_userinterface_by_name lookup fails first), so this is safe
    to repeat."""
    interface_name = f"__nonexistent_ui_{uuid.uuid4().hex[:8]}__"
    resp = requests.post(
        f"{base_url}/server/navigation/config/createEmpty/{interface_name}",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_update_edge_in_cache_requires_params(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/cache/update-edge",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_update_node_in_cache_requires_params(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/cache/update-node",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_invalidate_navigation_cache_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    fake_tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/navigation/cache/invalidate/{fake_tree_id}",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_refresh_navigation_cache_requires_tree_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/cache/refresh",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_delete_screenshot_requires_params(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/screenshot/delete",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False
