"""
Coverage for server_userinterface_routes.py (`/server/userinterface/*`):
user interface CRUD, dev->prod publish, .vptree export/import, and the
variant registry.

Most GET/validation paths are safe to run repeatedly. One true CRUD flow
(create -> verify -> delete) is included for `createUserInterface` /
`deleteUserInterface` since it mirrors the existing create-then-cleanup
pattern used elsewhere in this suite (see test_org_management.py) and is the
only way to get real signal on the write path without leaving orphan data
behind. Export/import and publish are exercised only through their validation
and not-found paths, since a real publish creates a permanent second
(`mode='prod'`) row with no corresponding delete route.
"""

import io
import uuid

import requests


# ---------------------------------------------------------------------------
# USER INTERFACES — read paths
# ---------------------------------------------------------------------------


def test_get_compatible_interfaces_requires_device_model(get, api_headers, team_id):
    resp = get(
        "/server/userinterface/getCompatibleInterfaces",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 400, resp.text


def test_get_compatible_interfaces_returns_list(get, api_headers, team_id):
    resp = get(
        "/server/userinterface/getCompatibleInterfaces",
        headers=api_headers,
        params={"team_id": team_id, "device_model": "android_mobile"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("interfaces"), list)
    assert body.get("count") == len(body.get("interfaces"))


def test_get_all_user_interfaces_returns_list(get, api_headers, team_id):
    resp = get(
        "/server/userinterface/getAllUserInterfaces",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_get_user_interface_unknown_id_returns_404(get, api_headers, team_id):
    interface_id = str(uuid.uuid4())
    resp = get(
        f"/server/userinterface/getUserInterface/{interface_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text


def test_get_user_interface_by_name_unknown_returns_404(get, api_headers, team_id):
    name = f"__nonexistent_ui_{uuid.uuid4().hex[:8]}__"
    resp = get(
        f"/server/userinterface/getUserInterfaceByName/{name}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text


def test_get_user_interface_by_name_rejects_bad_mode(get, api_headers, team_id):
    name = f"__nonexistent_ui_{uuid.uuid4().hex[:8]}__"
    resp = get(
        f"/server/userinterface/getUserInterfaceByName/{name}",
        headers=api_headers,
        params={"team_id": team_id, "mode": "bogus"},
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# USER INTERFACES — create / verify / delete round trip
# ---------------------------------------------------------------------------


def test_create_userinterface_requires_name(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/userinterface/createUserInterface",
        params={"team_id": team_id},
        json={"models": ["android_mobile"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_userinterface_requires_models(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/userinterface/createUserInterface",
        params={"team_id": team_id},
        json={"name": f"__smoke_ui_{uuid.uuid4().hex[:8]}__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_create_get_and_delete_userinterface_round_trip(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    name = f"__smoke_test_ui_{uuid.uuid4().hex[:8]}__"
    created_id = None
    try:
        create_resp = requests.post(
            f"{base_url}/server/userinterface/createUserInterface",
            params={"team_id": team_id},
            json={"name": name, "models": ["android_mobile"]},
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert created.get("status") == "success"
        created_id = created["userinterface"]["id"]
        assert created["userinterface"]["name"] == name

        get_resp = requests.get(
            f"{base_url}/server/userinterface/getUserInterface/{created_id}",
            params={"team_id": team_id},
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert get_resp.status_code == 200, get_resp.text
        assert get_resp.json().get("name") == name

        # Duplicate name is rejected
        dup_resp = requests.post(
            f"{base_url}/server/userinterface/createUserInterface",
            params={"team_id": team_id},
            json={"name": name, "models": ["android_mobile"]},
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert dup_resp.status_code == 400, dup_resp.text
    finally:
        if created_id:
            requests.delete(
                f"{base_url}/server/userinterface/deleteUserInterface/{created_id}",
                params={"team_id": team_id},
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )


def test_update_userinterface_unknown_id_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.put(
        f"{base_url}/server/userinterface/updateUserInterface/{interface_id}",
        params={"team_id": team_id},
        json={"name": "whatever", "models": ["android_mobile"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_delete_userinterface_unknown_id_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.delete(
        f"{base_url}/server/userinterface/deleteUserInterface/{interface_id}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_duplicate_userinterface_requires_name(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/userinterface/duplicateUserInterface/{interface_id}",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# DEV -> PROD PUBLISH
# ---------------------------------------------------------------------------


def test_publish_unknown_interface_fails(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/userinterface/publish/{interface_id}",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    # publish_userinterface_route returns the raw result dict with 500 on any
    # failure (including "interface not found") — see
    # server_userinterface_routes.py publish_userinterface_route().
    assert resp.status_code == 500, resp.text
    assert resp.json().get("success") is False


def test_list_publishes_unknown_interface_returns_empty(get, api_headers, team_id):
    interface_id = str(uuid.uuid4())
    resp = get(
        f"/server/userinterface/{interface_id}/publishes",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("publishes") == []


# ---------------------------------------------------------------------------
# EXPORT / IMPORT
# ---------------------------------------------------------------------------


def test_export_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/userinterface/{interface_id}/export",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_import_requires_file(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/userinterface/import",
        params={"team_id": team_id},
        data={"name": "whatever"},
        headers={k: v for k, v in api_headers.items() if k != "Content-Type"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_import_requires_name(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/userinterface/import",
        params={"team_id": team_id},
        files={"file": ("bundle.vptree", io.BytesIO(b"not a real zip"), "application/zip")},
        headers={k: v for k, v in api_headers.items() if k != "Content-Type"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# VARIANT REGISTRY
# ---------------------------------------------------------------------------


def test_list_all_variants_requires_team_id(
    base_url, api_headers, request_timeout, verify_ssl
):
    resp = requests.get(
        f"{base_url}/server/userinterface/variants",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text


def test_list_all_variants_returns_dict(get, api_headers, team_id):
    resp = get(
        "/server/userinterface/variants",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("variants_by_interface"), dict)


def test_list_variants_for_unknown_interface_returns_empty(get, api_headers, team_id):
    interface_id = str(uuid.uuid4())
    resp = get(
        f"/server/userinterface/{interface_id}/variants",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("variants") == []


def test_create_variant_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/userinterface/{interface_id}/variants",
        params={"team_id": team_id},
        json={"name": "myvariant"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_update_variant_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.put(
        f"{base_url}/server/userinterface/{interface_id}/variants/myvariant",
        params={"team_id": team_id},
        json={"description": "x"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_delete_variant_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.delete(
        f"{base_url}/server/userinterface/{interface_id}/variants/myvariant",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_sweep_orphans_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/userinterface/{interface_id}/variants/sweep-orphans",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text


def test_rename_variant_unknown_interface_returns_404(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    interface_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/userinterface/{interface_id}/variants/myvariant/rename",
        params={"team_id": team_id},
        json={"new_name": "othervariant"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 404, resp.text
