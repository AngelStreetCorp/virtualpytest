"""
Coverage for server_navigation_trees_routes.py (`/server/navigationTrees/*`
and `/server/userinterface/domReport`): tree metadata, node/edge CRUD, nested
(sub-)trees, KPI/node picker caches, locking placeholders, and tree history.

This is the highest-priority / highest-risk cluster in the whole backend
(navigation is the product's core value proposition), so coverage here is
deliberately broad: every route gets at least a parameter-validation test,
and most get a real request against a random (guaranteed-nonexistent)
tree/node/edge id. That's safe to run repeatedly because the underlying
Supabase delete/upsert-existence-check calls are idempotent no-ops for ids
that were never written (verified by reading
shared/src/lib/database/navigation_trees_db.py — e.g. delete_tree,
delete_node, and delete_edge all `return {'success': True}` unconditionally;
save_node/save_edge fail on missing required keys *before* any DB write).

Two tests document real bugs found while writing this coverage:

- `test_create_tree_regression_currently_500s_due_to_bug`: `create_tree_api()`
  (~line 601) reads `tree_request.args.get('team_id')` — `tree_request` is
  never defined anywhere in the module (the parameter is called `request`
  everywhere else). Every POST to `/server/navigationTrees` currently 500s
  with a NameError, regardless of whether team_id/body are valid.
"""

import uuid

import pytest
import requests


def _fake_id() -> str:
    return str(uuid.uuid4())


# ============================================================================
# TREE METADATA
# ============================================================================


def test_get_all_navigation_trees_requires_team_id(get, api_headers):
    resp = get("/server/navigationTrees", headers=api_headers)
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_get_all_navigation_trees_returns_list(get, api_headers, team_id):
    resp = get("/server/navigationTrees", headers=api_headers, params={"team_id": team_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("trees"), list)


def test_get_tree_metadata_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_metadata_unknown_id_returns_404(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_create_tree_requires_body(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/navigationTrees",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
        # no json= at all -> request.get_json() is None -> 400 before the
        # buggy `tree_request` line is ever reached.
    )
    assert resp.status_code == 400, resp.text


def test_create_tree_regression_currently_500s_due_to_bug(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """See module docstring: create_tree_api() references an undefined
    `tree_request` name and currently 500s on every well-formed request. This
    test asserts the intended contract (successful creation) and cleans up
    after itself via DELETE if the bug is ever fixed and creation succeeds."""
    name = f"__smoke_test_tree_{uuid.uuid4().hex[:8]}__"
    resp = requests.post(
        f"{base_url}/server/navigationTrees",
        params={"team_id": team_id},
        json={"name": name, "description": "pytest smoke test"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    created_id = None
    try:
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("success") is True
        created_id = body.get("tree", {}).get("id")
    finally:
        if created_id:
            requests.delete(
                f"{base_url}/server/navigationTrees/{created_id}",
                params={"team_id": team_id},
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )


def test_update_tree_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}",
        json={"name": "x"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_update_tree_requires_body(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_tree_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_tree_unknown_id_is_idempotent(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """delete_tree() unconditionally returns {'success': True} regardless of
    whether a row matched — safe to call on a made-up id."""
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True


# ============================================================================
# NODE ENDPOINTS
# ============================================================================


def test_get_tree_nodes_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/nodes", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_nodes_unknown_tree_returns_empty(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/nodes",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("nodes") == []


def test_get_node_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_node_unknown_returns_404(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_create_node_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes",
        json={"node_id": "n1"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_node_requires_body(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_node_requires_node_id_field(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """save_node() does `node_data['node_id']` unconditionally; a body without
    it fails with a KeyError *before* touching the DB (caught, surfaced as a
    400) — this exercises that shape-validation path safely."""
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes",
        params={"team_id": team_id},
        json={"label": "Home"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_update_node_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_update_node_rejects_variant_overrides(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        params={"team_id": team_id},
        json={"variant_overrides": {}},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert "variant_overrides" in resp.json().get("message", "")


def test_update_node_rejects_non_bool_hidden_in_base(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        params={"team_id": team_id},
        json={"hidden_in_base": "yes"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_node_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_node_unknown_is_idempotent(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True


# ============================================================================
# EDGE ENDPOINTS
# ============================================================================


def test_get_tree_edges_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/edges", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_edges_unknown_tree_returns_empty(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/edges",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("edges") == []


def test_get_edge_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_edge_unknown_returns_404(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_validate_edge_actions_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/validate",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_validate_edge_actions_empty_action_sets_is_noop_success(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/validate",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("errors") == []
    assert body.get("warnings") == []


def test_create_edge_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_edge_requires_body(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_edge_requires_action_sets_field(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    """save_edge() raises ValueError('action_sets is required') before any DB
    write when the field is absent — safe shape-validation coverage."""
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges",
        params={"team_id": team_id},
        json={"source_node_id": "a", "target_node_id": "b"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_update_edge_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_update_edge_rejects_variant_overrides(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        params={"team_id": team_id},
        json={"variant_overrides": {}},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert "variant_overrides" in resp.json().get("message", "")


def test_update_edge_rejects_non_bool_hidden_in_base(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        params={"team_id": team_id},
        json={"hidden_in_base": "yes"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_edge_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_edge_unknown_is_idempotent(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/edges/{_fake_id()}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True


# ============================================================================
# KPI ACTION-SET / NAVIGATION-NODE PICKER CACHES
# ============================================================================


def test_get_kpi_action_sets_requires_params(get, api_headers, team_id):
    resp = get("/server/navigationTrees/kpi-action-sets", headers=api_headers, params={"team_id": team_id})
    assert resp.status_code == 400, resp.text


def test_get_kpi_action_sets_unknown_interface_returns_404(get, api_headers, team_id):
    resp = get(
        "/server/navigationTrees/kpi-action-sets",
        headers=api_headers,
        params={"team_id": team_id, "userinterface_name": f"__nonexistent_{uuid.uuid4().hex[:8]}__"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_get_navigation_nodes_requires_params(get, api_headers, team_id):
    resp = get("/server/navigationTrees/nodes", headers=api_headers, params={"team_id": team_id})
    assert resp.status_code == 400, resp.text


def test_get_navigation_nodes_unknown_interface_returns_404(get, api_headers, team_id):
    resp = get(
        "/server/navigationTrees/nodes",
        headers=api_headers,
        params={"team_id": team_id, "userinterface_name": f"__nonexistent_{uuid.uuid4().hex[:8]}__"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


# ============================================================================
# NESTED TREE ENDPOINTS
# ============================================================================


def test_get_node_sub_trees_requires_team_id(get, api_headers):
    resp = get(
        f"/server/navigationTrees/getNodeSubTrees/{_fake_id()}/{_fake_id()}",
        headers=api_headers,
    )
    assert resp.status_code == 400, resp.text


def test_get_node_sub_trees_unknown_returns_empty(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/getNodeSubTrees/{_fake_id()}/{_fake_id()}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("sub_trees") == []


def test_create_sub_tree_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}/subtrees",
        json={"name": "sub"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_sub_tree_unknown_parent_returns_400(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/nodes/{_fake_id()}/subtrees",
        params={"team_id": team_id},
        json={"name": "sub"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_get_tree_hierarchy_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/hierarchy", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_hierarchy_unknown_tree(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/hierarchy",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True


def test_get_tree_breadcrumb_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/breadcrumb", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_breadcrumb_unknown_tree(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/breadcrumb",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True


def test_delete_tree_cascade_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/cascade",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_delete_tree_cascade_unknown_tree_deletes_zero(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.delete(
        f"{base_url}/server/navigationTrees/{_fake_id()}/cascade",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("deleted_count") == 0


def test_move_subtree_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/move",
        json={"new_parent_tree_id": _fake_id(), "new_parent_node_id": _fake_id()},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_move_subtree_requires_body_fields(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/move",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_move_subtree_unknown_parent_returns_400(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.put(
        f"{base_url}/server/navigationTrees/{_fake_id()}/move",
        params={"team_id": team_id},
        json={"new_parent_tree_id": _fake_id(), "new_parent_node_id": _fake_id()},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


# ============================================================================
# BATCH OPERATIONS
# ============================================================================


def test_get_full_tree_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/full", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_full_tree_unknown_returns_404(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/full",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_save_tree_data_batch_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/batch",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_save_tree_data_batch_requires_body(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/batch",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


# ============================================================================
# INTERFACE OPERATIONS
# ============================================================================


def test_get_tree_by_userinterface_id_requires_team_id(get, api_headers):
    resp = get(
        f"/server/navigationTrees/getTreeByUserInterfaceId/{_fake_id()}",
        headers=api_headers,
    )
    assert resp.status_code == 400, resp.text


def test_get_tree_by_userinterface_id_unknown_returns_success_false(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/getTreeByUserInterfaceId/{_fake_id()}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is False


# ============================================================================
# LOCKING (placeholder — always succeeds, no real locking implemented yet)
# ============================================================================


def test_check_lock_status_requires_userinterface_id(get, api_headers):
    resp = get("/server/navigationTrees/lockStatus", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_check_lock_status_returns_unlocked(get, api_headers):
    resp = get(
        "/server/navigationTrees/lockStatus",
        headers=api_headers,
        params={"userinterface_id": _fake_id()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("lock") is None


def test_acquire_lock_requires_fields(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/lockAcquire",
        json={"userinterface_id": _fake_id()},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_acquire_and_release_lock_placeholder(
    base_url, api_headers, request_timeout, verify_ssl
):
    userinterface_id = _fake_id()
    session_id = _fake_id()
    acquire_resp = requests.post(
        f"{base_url}/server/navigationTrees/lockAcquire",
        json={"userinterface_id": userinterface_id, "session_id": session_id, "user_id": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert acquire_resp.status_code == 200, acquire_resp.text
    assert acquire_resp.json().get("success") is True

    release_resp = requests.post(
        f"{base_url}/server/navigationTrees/lockRelease",
        json={"userinterface_id": userinterface_id, "session_id": session_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert release_resp.status_code == 200, release_resp.text
    assert release_resp.json().get("success") is True


def test_release_lock_requires_fields(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/lockRelease",
        json={"userinterface_id": _fake_id()},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


# ============================================================================
# TREE HISTORY & VERSIONING
# ============================================================================


def test_get_tree_history_requires_team_id(get, api_headers):
    resp = get(f"/server/navigationTrees/{_fake_id()}/history", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_get_tree_history_unknown_tree_returns_empty(get, api_headers, team_id):
    resp = get(
        f"/server/navigationTrees/{_fake_id()}/history",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("versions") == []


def test_restore_tree_from_history_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/restore/1",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_restore_tree_from_history_unknown_version_returns_400(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/navigationTrees/{_fake_id()}/restore/1",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


# ============================================================================
# DOM REPORT
# ============================================================================


def test_dom_report_requires_params(get, api_headers):
    resp = get("/server/userinterface/domReport", headers=api_headers)
    assert resp.status_code == 400, resp.text


def test_dom_report_unknown_interface_returns_not_found_html(get, api_headers, team_id):
    name = f"__nonexistent_ui_{uuid.uuid4().hex[:8]}__"
    resp = get(
        "/server/userinterface/domReport",
        headers=api_headers,
        params={"userinterface": name, "team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert "not found" in resp.text.lower()
