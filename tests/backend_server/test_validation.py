"""
Coverage for server_validation_routes.py (`/server/validation/*`).

The only endpoint here (`GET /preview/<tree_id>`) proxies to a real
backend_host to compute an optimal depth-first edge-validation sequence, which
needs a live, cache-populated host — not reachable from this suite. Coverage
is limited to the parameter validation that runs before any host contact.
"""

import uuid

import requests


def test_get_validation_preview_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/validation/preview/{tree_id}",
        params={"host_name": "fake_host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_validation_preview_requires_host_name(
    get, api_headers, team_id
):
    tree_id = str(uuid.uuid4())
    resp = get(
        f"/server/validation/preview/{tree_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_validation_preview_unknown_host_returns_error(
    get, api_headers, team_id
):
    """host_name validation passes, but populate_navigation_cache_for_control /
    the host lookup fails for a host that was never registered — exercises the
    error path without needing a real host."""
    tree_id = str(uuid.uuid4())
    resp = get(
        f"/server/validation/preview/{tree_id}",
        headers=api_headers,
        params={"team_id": team_id, "host_name": f"__nonexistent_host_{uuid.uuid4().hex[:8]}__"},
    )
    assert resp.status_code in (400, 404), resp.text
    body = resp.json()
    assert body.get("success") is False
