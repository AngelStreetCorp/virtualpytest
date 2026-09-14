def test_get_requirements_list_returns_array(get, api_headers, team_id):
    response = get(
        "/server/requirements/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("requirements"), list)


def test_get_requirements_coverage_summary(get, api_headers, team_id):
    response = get(
        "/server/requirements/coverage/summary",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
