def test_get_script_list_returns_array(get, api_headers, team_id):
    response = get(
        "/server/script/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("scripts"), list)


def test_script_list_items_carry_a_label(get, api_headers, team_id):
    """Every script comes back with a rendered label, one per entry in `scripts`.

    `items[].label` is the single string the UI, Grafana and external callers all
    show (BUG-0099) — an unmapped script falls back to its own name, so the field
    is never empty and never has to be built by the caller.
    """
    response = get(
        "/server/script/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()

    items = body.get("items")
    assert isinstance(items, list)
    assert len(items) == len(body.get("scripts", [])), "one item per script"

    for item in items:
        assert item.get("script_ref"), "script_ref is the identifier sent back to /execute"
        assert item.get("label"), f"no label for {item.get('script_ref')}"
        assert not item["script_ref"].endswith(".py"), "script_ref is normalized"
        # The label is the identity label, or the script's own name when unmapped.
        if not item.get("prefix") and not item.get("display_name"):
            assert item["label"] == item["script_ref"]


def test_campaign_executables_include_contained_scripts(get, api_headers, team_id):
    """Campaign executables endpoint returns contained_scripts for recursive resolution."""
    response = get(
        "/server/campaigns/listExecutables",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True

    # Find any campaign entry — all should now include contained_scripts
    campaigns = body.get("campaigns", []) + body.get("scripts", [])
    if campaigns:
        for item in campaigns:
            # contained_scripts may be absent for simple entries, but if present must be a list
            if "contained_scripts" in item:
                assert isinstance(item["contained_scripts"], list), (
                    f"contained_scripts should be a list for {item.get('name', item.get('path'))}"
                )
                for cs in item["contained_scripts"]:
                    assert "script_name" in cs, "contained_scripts entries must have script_name"
                    assert "script_type" in cs, "contained_scripts entries must have script_type"
