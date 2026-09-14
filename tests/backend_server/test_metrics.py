"""
Tests for server_metrics_routes.py (/server/metrics/*)

All endpoints are read-only aggregations over navigation_metrics_db /
navigation_trees_db, so they are safe to exercise fully. To keep these
tests self-contained (no dependency on a specific tree/device having run
executions), most use fabricated tree/node/edge ids:

- get_tree_metrics()/get_edge_direction_metrics() return an empty/None
  result (not an error) for ids with no matching rows, per
  shared/src/lib/database/navigation_metrics_db.py.
- get_action_execution_history()/get_verification_execution_history() return
  {success: True, ...: [], count: 0} when the filtered query matches nothing.
- get_complete_tree_hierarchy() (used by the /tree/<tree_id> endpoint) raises
  when the tree isn't found in the materialized view, which the route
  surfaces as a 400 — this is the one endpoint where a fabricated id
  produces an error response rather than an empty success response.
"""
FAKE_TREE_ID = "00000000-0000-0000-0000-000000000fff"
FAKE_NODE_ID = "00000000-0000-0000-0000-00000000f001"
FAKE_EDGE_ID = "00000000-0000-0000-0000-00000000f002"
FAKE_ACTION_SET_ID = "00000000-0000-0000-0000-00000000f003"


def test_tree_metrics_unknown_tree_returns_400(get, api_headers, team_id):
    response = get(
        f"/server/metrics/tree/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "error" in body


def test_node_metrics_unknown_node(get, api_headers, team_id):
    response = get(
        f"/server/metrics/node/{FAKE_NODE_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert "node_metric" in body


def test_edge_metrics_unknown_edge(get, api_headers, team_id):
    response = get(
        f"/server/metrics/edge/{FAKE_EDGE_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("edge_metrics"), dict)


def test_edge_direction_metrics_unknown(get, api_headers, team_id):
    response = get(
        f"/server/metrics/edge/{FAKE_EDGE_ID}/{FAKE_ACTION_SET_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert "metrics" in body


def test_action_history_unknown_edge_returns_empty(get, api_headers, team_id):
    response = get(
        f"/server/metrics/history/actions/{FAKE_EDGE_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("action_executions"), list)
    assert body.get("count") == len(body.get("action_executions"))


def test_verification_history_unknown_node_returns_empty(get, api_headers, team_id):
    response = get(
        f"/server/metrics/history/verifications/{FAKE_NODE_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("verification_executions"), list)
    assert body.get("count") == len(body.get("verification_executions"))


def test_action_history_respects_limit_param(get, api_headers, team_id):
    response = get(
        f"/server/metrics/history/actions/{FAKE_EDGE_ID}/{FAKE_TREE_ID}",
        headers=api_headers,
        params={"team_id": team_id, "limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body.get("action_executions", [])) <= 1
