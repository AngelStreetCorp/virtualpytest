def test_get_all_campaigns_returns_array(get, api_headers, team_id):
    response = get(
        "/server/campaigns/getAllCampaigns",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("campaigns"), list)


def test_get_all_campaign_results_returns_expected_shape(get, api_headers, team_id):
    response = get(
        "/server/campaigns/results",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("campaign_results"), list)
    assert isinstance(body.get("count"), int)
    assert body["count"] == len(body["campaign_results"])
