"""
Library Visibility Routes Tests

Covers backend_server/src/routes/server_library_visibility_routes.py:
  GET  /server/library-visibility/list  — list team-scoped visibility overrides
  POST /server/library-visibility/hide  — hide a library item (script/testcase/campaign)
  POST /server/library-visibility/show  — un-hide a library item

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

VALID_ENTITY_TYPES (shared/src/lib/database/library_visibility_db.py) is
{'script', 'testcase', 'campaign'}; tests below use 'testcase' with a
clearly-namespaced fake entity_key, and always call /show as cleanup after
/hide so no visibility override is left behind.
"""

import pytest
import requests


def _is_auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    try:
        resp = requests.get(
            f"{base_url}/server/users",
            headers={"Content-Type": "application/json"},
            timeout=5,
            verify=verify_ssl,
        )
        return resp.status_code in (401, 403)
    except Exception:
        return False


@pytest.fixture(scope="session")
def auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    return _is_auth_enforced(base_url, verify_ssl)


def jwt_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _skip_if_no_jwt(token: str) -> None:
    if not token:
        pytest.skip("AUTH_TEST_JWT not configured — set AUTH_TEST_JWT env var")


TEST_ENTITY_KEY = "__smoke_test_library_visibility__"


# ---------------------------------------------------------------------------
# GET /server/library-visibility/list
# ---------------------------------------------------------------------------


class TestListLibraryVisibility:
    def test_list_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced, team_id
    ):
        resp = requests.get(
            f"{base_url}/server/library-visibility/list",
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("success") is True
            assert isinstance(data.get("items"), list)

    def test_list_requires_team_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/library-visibility/list",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_list_rejects_invalid_entity_type(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/library-visibility/list",
            params={"team_id": team_id, "entity_type": "not_a_real_entity_type"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_list_with_valid_entity_type(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/library-visibility/list",
            params={"team_id": team_id, "entity_type": "testcase"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        assert isinstance(data.get("items"), list)


# ---------------------------------------------------------------------------
# POST /server/library-visibility/hide + POST /server/library-visibility/show
# ---------------------------------------------------------------------------


class TestHideAndShowLibraryItem:
    def test_hide_requires_team_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/library-visibility/hide",
            json={"entity_type": "testcase", "entity_key": TEST_ENTITY_KEY},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_hide_requires_entity_fields(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/library-visibility/hide",
            params={"team_id": team_id},
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_hide_rejects_invalid_entity_type(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/library-visibility/hide",
            params={"team_id": team_id},
            json={"entity_type": "not_a_real_entity_type", "entity_key": TEST_ENTITY_KEY},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_hide_then_show_round_trip(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        headers = jwt_headers(auth_jwt)

        hide_resp = requests.post(
            f"{base_url}/server/library-visibility/hide",
            params={"team_id": team_id},
            json={"entity_type": "testcase", "entity_key": TEST_ENTITY_KEY, "updated_by": "smoke-test"},
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if hide_resp.status_code != 200:
            pytest.skip(
                f"Could not hide test library item (backend may lack Supabase config): "
                f"{hide_resp.status_code} {hide_resp.text}"
            )
        assert hide_resp.json().get("success") is True

        try:
            list_resp = requests.get(
                f"{base_url}/server/library-visibility/list",
                params={"team_id": team_id, "entity_type": "testcase"},
                headers=headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert list_resp.status_code == 200, list_resp.text
            items = list_resp.json().get("items", [])
            keys = [item.get("entity_key") for item in items]
            assert TEST_ENTITY_KEY in keys, "Hidden item did not appear in visibility list"
        finally:
            # Always attempt cleanup, even if the list assertion above fails.
            show_resp = requests.post(
                f"{base_url}/server/library-visibility/show",
                params={"team_id": team_id},
                json={"entity_type": "testcase", "entity_key": TEST_ENTITY_KEY},
                headers=headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert show_resp.status_code == 200, show_resp.text
            assert show_resp.json().get("success") is True

    def test_show_requires_entity_fields(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/library-visibility/show",
            params={"team_id": team_id},
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False
