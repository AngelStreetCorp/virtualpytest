"""
Coverage for server_navigation_execution_routes.py (`/server/navigation/*`
execute / status / preview / batch-execute).

Every success path here proxies to a real backend_host device and needs an
actively controlled hardware session, so this module sticks to the
request-validation edge of each endpoint (safe, repeatable, no host needed).

One test (`test_batch_execute_navigation_hits_missing_import_bug`) documents a
real bug found while writing this coverage: `batch_execute_navigation()` calls
`populate_navigation_cache_for_control(...)` (server_navigation_execution_routes.py,
around line 368) without importing it in that function's scope — it's only
imported locally inside `execute_navigation()` and
`get_navigation_preview_with_executor()`. Any batch request with at least one
`tree_id` therefore raises `NameError`, which `handle_route_exceptions` turns
into a 500. The test asserts the documented contract (a 400 "failed to
populate cache" response for an unknown tree) so it starts passing once the
missing import is added.
"""

import uuid

import requests


def test_execute_navigation_requires_target_node(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/navigation/execute/{tree_id}",
        params={"team_id": team_id},
        json={"host_name": "fake_host", "userinterface_name": "fake_ui"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_execute_navigation_rejects_both_target_params(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/navigation/execute/{tree_id}",
        params={"team_id": team_id},
        json={
            "host_name": "fake_host",
            "userinterface_name": "fake_ui",
            "target_node_id": "a",
            "target_node_label": "b",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_execute_navigation_requires_host_name(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/navigation/execute/{tree_id}",
        params={"team_id": team_id},
        json={"target_node_label": "home", "userinterface_name": "fake_ui"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_navigation_execution_status_requires_host_name(
    base_url, api_headers, request_timeout, verify_ssl
):
    execution_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/navigation/execution/{execution_id}/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_get_navigation_preview_requires_host_name(
    base_url, api_headers, request_timeout, verify_ssl
):
    tree_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/navigation/preview/{tree_id}/{node_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_batch_execute_navigation_requires_host_name(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/batch-execute",
        params={"team_id": team_id},
        json={"navigations": [{"tree_id": "t1", "target_node_id": "n1"}]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_batch_execute_navigation_requires_navigations(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigation/batch-execute",
        params={"team_id": team_id},
        json={"host_name": "fake_host"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False


def test_batch_execute_navigation_hits_missing_import_bug(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """Regression test for the missing-import bug described in the module
    docstring. Currently returns 500 (NameError: populate_navigation_cache_for_control);
    should return 400 once the local import is added to batch_execute_navigation()."""
    resp = requests.post(
        f"{base_url}/server/navigation/batch-execute",
        params={"team_id": team_id},
        json={
            "host_name": "fake_host",
            "navigations": [{"tree_id": str(uuid.uuid4()), "target_node_id": "n1"}],
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("success") is False
