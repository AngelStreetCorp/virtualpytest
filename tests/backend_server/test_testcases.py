def test_get_testcase_list_returns_array(get, api_headers, team_id):
    response = get(
        "/server/testcase/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("testcases"), list)
