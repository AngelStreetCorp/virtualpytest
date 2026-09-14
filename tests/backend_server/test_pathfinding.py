"""
Coverage for server_pathfinding_routes.py (`/server/pathfinding/*`):
graph stats, cache management, take-control session bookkeeping, and
alternative-paths lookup.

`cache/clear` and `cache/refresh` are only exercised with an explicit
`tree_id` so the test suite never trips the process-wide `clear_all_cache()`
branch (omitting `tree_id`), which would evict every team's cached navigation
graph on a shared live server.

`test_get_alternative_paths_hits_missing_helper_bug` documents a real bug
found while writing this coverage: `get_alternative_paths()` calls
`get_navigation_preview_internal(...)` (server_pathfinding_routes.py, ~line
296), a name that is never defined or imported anywhere in this module.
Every call to `/server/pathfinding/alternatives/<tree_id>/<node_id>`
currently raises `NameError`, converted to a 500 by `handle_route_exceptions`.
The test asserts the documented 200/alternatives-list contract, so it starts
passing once the missing helper is implemented or imported.
"""

import uuid

import requests


def test_get_navigation_stats_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/pathfinding/stats/{tree_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_navigation_stats_missing_graph_returns_404(
    get, api_headers, team_id
):
    tree_id = str(uuid.uuid4())
    resp = get(
        f"/server/pathfinding/stats/{tree_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_clear_navigation_cache_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/pathfinding/cache/clear",
        json={"tree_id": str(uuid.uuid4())},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_clear_navigation_cache_scoped_to_tree_id(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """Scoped clear (tree_id given) only touches one (likely nonexistent)
    tree's cache entry — safe to repeat, unlike the no-tree_id 'clear
    everything' branch."""
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/pathfinding/cache/clear",
        params={"team_id": team_id},
        json={"tree_id": tree_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True


def test_refresh_navigation_cache_requires_tree_id(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/pathfinding/cache/refresh",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_refresh_navigation_cache_scoped_to_tree_id(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/pathfinding/cache/refresh",
        params={"team_id": team_id},
        json={"tree_id": tree_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True


def test_get_cache_stats_returns_dict(get, api_headers):
    resp = get("/server/pathfinding/cache/stats", headers=api_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("cache_stats"), dict)


def test_take_control_toggle_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/pathfinding/takeControl/{tree_id}",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_take_control_activate_and_deactivate(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """Take-control sessions are purely in-memory (take_control_sessions dict
    on the server process) — activating/deactivating a made-up tree_id has no
    external side effects and is safe to repeat."""
    tree_id = str(uuid.uuid4())

    activate_resp = requests.post(
        f"{base_url}/server/pathfinding/takeControl/{tree_id}",
        params={"team_id": team_id},
        json={"enable": True},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert activate_resp.status_code == 200, activate_resp.text
    assert activate_resp.json().get("success") is True

    deactivate_resp = requests.post(
        f"{base_url}/server/pathfinding/takeControl/{tree_id}",
        params={"team_id": team_id},
        json={"enable": False},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert deactivate_resp.status_code == 200, deactivate_resp.text
    assert deactivate_resp.json().get("success") is True


def test_get_take_control_status_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/pathfinding/takeControl/{tree_id}/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_take_control_status_returns_active(get, api_headers, team_id):
    """is_take_control_active() is currently hardcoded to always return True
    (see server_pathfinding_routes.py comment: 'For demo purposes, assume
    take control is always active')."""
    tree_id = str(uuid.uuid4())
    resp = get(
        f"/server/pathfinding/takeControl/{tree_id}/status",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("is_active") is True


def test_get_alternative_paths_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/pathfinding/alternatives/{tree_id}/{node_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_alternative_paths_hits_missing_helper_bug(get, api_headers, team_id):
    """Regression test for the missing-helper bug described in the module
    docstring. Currently returns 500 (NameError: get_navigation_preview_internal);
    should return 200 with an (empty) alternatives list once fixed."""
    tree_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    resp = get(
        f"/server/pathfinding/alternatives/{tree_id}/{node_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("alternatives"), list)
