"""
Tests for backend_server/src/routes/server_execution_results_routes.py

Single read-only endpoint backed directly by Supabase — no host/device
hardware involved.
"""


def test_get_all_execution_results_returns_list(get, api_headers, team_id):
    response = get(
        "/server/execution-results/getAllExecutionResults",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    # Route returns get_execution_results()['execution_results'] unwrapped
    # (jsonify(result['execution_results'])), i.e. a bare list, not an
    # envelope with a "success" key.
    body = response.json()
    assert isinstance(body, list)
