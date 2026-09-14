"""
Tests for backend_server/src/routes/server_campaign_results_routes.py

Single read-only endpoint. Note it returns the raw list from
get_campaign_results()['data'] via jsonify(result['data']) — a bare JSON
array, not an envelope object.
"""


def test_get_all_campaign_results_returns_list(get, api_headers, team_id):
    response = get(
        "/server/campaign-results/getAllCampaignResults",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    for item in body:
        assert isinstance(item, dict)
