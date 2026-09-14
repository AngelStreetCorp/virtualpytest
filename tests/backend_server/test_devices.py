def test_get_all_devices_returns_array(get, api_headers, team_id):
    response = get(
        "/server/devices/getAllDevices",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    if isinstance(body, list):
        assert all(isinstance(item, dict) for item in body)
        return

    assert body.get("success") is True
    assert isinstance(body.get("devices"), list)
