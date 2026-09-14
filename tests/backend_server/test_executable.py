"""
Server Executable Route Tests

server_executable_routes.py (blueprint url_prefix /server/executable) exposes
a single read-only endpoint that unifies scripts (filesystem) and testcases
(database) into one folder-organized listing, with a short-TTL response
cache keyed by team_id + filters.

  GET /server/executable/list -> {success, folders: [...], all_tags: [...], all_folders: [...]}

This is a pure read (no execution, no mutation) and safe to call live.
"""


def test_list_executables_requires_team_id(get, api_headers):
    response = get("/server/executable/list", headers=api_headers)
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "team_id is required"


def test_list_executables_returns_structure(get, api_headers, team_id):
    response = get(
        "/server/executable/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("folders"), list)
    assert isinstance(body.get("all_tags"), list)
    assert isinstance(body.get("all_folders"), list)

    for folder in body["folders"]:
        assert "name" in folder
        assert isinstance(folder.get("items"), list)
        for item in folder["items"]:
            assert item.get("type") in ("script", "testcase")
            assert "id" in item
            assert "name" in item
            assert isinstance(item.get("tags"), list)


def test_list_executables_filters_by_folder(get, api_headers, team_id):
    """Filtering by a folder that can't exist returns an empty (but well-formed) folder list."""
    response = get(
        "/server/executable/list",
        headers=api_headers,
        params={"team_id": team_id, "folder": "__nonexistent_folder_for_tests__"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    assert body.get("folders") == []
