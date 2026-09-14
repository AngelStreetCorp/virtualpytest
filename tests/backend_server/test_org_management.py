"""
Organisation Management Smoke Tests

Covers team member management, user permission updates, and org-level
route access control for roles that previously had no dedicated test coverage.

Environment variables needed (on top of the base conftest ones):
  ADMIN_TEST_JWT    — Supabase-issued JWT for an admin user
  TESTER_TEST_JWT   — Supabase-issued JWT for a tester user
  VIEWER_TEST_JWT   — Supabase-issued JWT for a viewer user

When a JWT variable is empty the corresponding tests are skipped automatically.
"""

import os
import pytest
import requests


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _is_auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    """Return True when the server rejects requests without a JWT (auth is enabled)."""
    try:
        resp = requests.get(
            f"{base_url}/server/users",
            headers={"Content-Type": "application/json"},
            timeout=5,
            verify=verify_ssl,
        )
        # 401/403 = auth enforced; 200 = open mode
        return resp.status_code in (401, 403)
    except Exception:
        return False


@pytest.fixture(scope="session")
def admin_jwt() -> str:
    return os.environ.get("ADMIN_TEST_JWT", "")


@pytest.fixture(scope="session")
def tester_jwt() -> str:
    return os.environ.get("TESTER_TEST_JWT", "")


@pytest.fixture(scope="session")
def viewer_jwt() -> str:
    return os.environ.get("VIEWER_TEST_JWT", "")


def jwt_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture(scope="session")
def auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    """True when the server has ENFORCE_FRONTEND_JWT=true."""
    return _is_auth_enforced(base_url, verify_ssl)


def _skip_if_no_jwt(token: str, label: str) -> None:
    if not token:
        pytest.skip(f"{label} JWT not configured — set {label.upper()}_TEST_JWT env var")


def _skip_if_open_mode(enforced: bool) -> None:
    if not enforced:
        pytest.skip("Server is in open mode (ENFORCE_FRONTEND_JWT not set) — auth tests skipped")


# ---------------------------------------------------------------------------
# TestTeamMemberManagement
# ---------------------------------------------------------------------------


class TestTeamMemberManagement:
    """Admin can manage team membership; non-admins are blocked."""

    def test_admin_can_get_team_members(
        self, admin_jwt, team_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/teams/{team_id}/members",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_admin_can_add_and_remove_member(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        """Create a team, add a user, verify presence, remove user, verify gone, delete team."""
        _skip_if_no_jwt(admin_jwt, "admin")

        # Create a dedicated team for this test
        create_resp = requests.post(
            f"{base_url}/server/teams",
            json={"name": "__smoke_member_test_team__"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_resp.status_code == 201, create_resp.text
        test_team_id = create_resp.json()["id"]

        try:
            # The CI-owned mutation target — never a real account.
            users_resp = requests.get(
                f"{base_url}/server/users",
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert users_resp.status_code == 200, users_resp.text
            users = users_resp.json()
            if not users:
                pytest.skip("No users available for team member add/remove test")
            user_id = ci_user_id

            # Add user to team
            add_resp = requests.post(
                f"{base_url}/server/teams/{test_team_id}/members",
                json={"user_id": user_id, "role": "member"},
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )
            # 201 = added, 500 = already exists (acceptable)
            assert add_resp.status_code in (201, 500), add_resp.text

            # Verify user appears in members list
            members_resp = requests.get(
                f"{base_url}/server/teams/{test_team_id}/members",
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert members_resp.status_code == 200, members_resp.text
            members = members_resp.json()
            member_user_ids = [m.get("user_id") for m in members]
            assert user_id in member_user_ids, f"User {user_id} not found in team members after add"

            # Remove user from team
            del_resp = requests.delete(
                f"{base_url}/server/teams/{test_team_id}/members/{user_id}",
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert del_resp.status_code == 200, del_resp.text

            # Verify user no longer appears in members list
            members_after_resp = requests.get(
                f"{base_url}/server/teams/{test_team_id}/members",
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert members_after_resp.status_code == 200, members_after_resp.text
            members_after = members_after_resp.json()
            member_user_ids_after = [m.get("user_id") for m in members_after]
            assert user_id not in member_user_ids_after, f"User {user_id} still in team members after remove"

        finally:
            # Always clean up the test team
            requests.delete(
                f"{base_url}/server/teams/{test_team_id}",
                headers=jwt_headers(admin_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )

    def test_tester_cannot_manage_team_members(
        self, ci_user_id, tester_jwt, admin_jwt, ci_team_id, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        """Tester cannot add members to a team."""
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_no_jwt(admin_jwt, "admin")
        _skip_if_open_mode(auth_enforced)

        # The CI-owned mutation target — never a real account.
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        if not users:
            pytest.skip("No users available for tester member management test")
        user_id = ci_user_id

        resp = requests.post(
            f"{base_url}/server/teams/{ci_team_id}/members",
            json={"user_id": user_id, "role": "member"},
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_manage_team_members(
        self, ci_user_id, viewer_jwt, admin_jwt, ci_team_id, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        """Viewer cannot add members to a team."""
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_no_jwt(admin_jwt, "admin")
        _skip_if_open_mode(auth_enforced)

        # The CI-owned mutation target — never a real account.
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        if not users:
            pytest.skip("No users available for viewer member management test")
        user_id = ci_user_id

        resp = requests.post(
            f"{base_url}/server/teams/{ci_team_id}/members",
            json={"user_id": user_id, "role": "member"},
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# TestUserPermissions
# ---------------------------------------------------------------------------


class TestUserPermissions:
    """Admin can update individual user permissions and denied_permissions."""

    def test_admin_can_update_user_permissions(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("No non-admin user available for permission update test")

        original_permissions = target.get("permissions", [])

        resp = requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"permissions": ["testcases:view"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "testcases:view" in data.get("permissions", [])

        # Restore original permissions
        requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"permissions": original_permissions},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_set_denied_permissions(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("No non-admin user available for denied permissions test")

        original_denied = target.get("denied_permissions", [])

        resp = requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"denied_permissions": ["campaigns:view"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "campaigns:view" in data.get("denied_permissions", [])

        # Restore original denied permissions
        requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"denied_permissions": original_denied},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_clear_permissions(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("No non-admin user available for clear permissions test")

        original_permissions = target.get("permissions", [])
        original_denied = target.get("denied_permissions", [])

        resp = requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"permissions": [], "denied_permissions": []},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("permissions") == [] or data.get("permissions") is None
        assert data.get("denied_permissions") == [] or data.get("denied_permissions") is None

        # Restore original permissions
        requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"permissions": original_permissions, "denied_permissions": original_denied},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_tester_cannot_update_other_user(
        self, ci_user_id, tester_jwt, admin_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        """A tester cannot update another user's profile via PUT /server/users/<id>."""
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_no_jwt(admin_jwt, "admin")
        _skip_if_open_mode(auth_enforced)

        # Find a user that is not the tester themselves to target
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        # Target any user — the tester should be blocked regardless
        if not users:
            pytest.skip("No users available for tester update test")
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("No admin user available to attempt cross-update")

        resp = requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"permissions": ["admin:view"]},
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# TestOrgRouteAccessControl
# ---------------------------------------------------------------------------


class TestOrgRouteAccessControl:
    """Verify that org-level team management routes enforce admin-only access."""

    def test_admin_can_create_team(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/teams",
            json={"name": "__smoke_org_access_team__"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 201, resp.text
        created_id = resp.json()["id"]

        # Cleanup
        requests.delete(
            f"{base_url}/server/teams/{created_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_tester_cannot_create_team(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/teams",
            json={"name": "__tester_create_team__"},
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_tester_cannot_delete_team(
        self, tester_jwt, team_id, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.delete(
            f"{base_url}/server/teams/{team_id}",
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_create_team(
        self, viewer_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/teams",
            json={"name": "__viewer_create_team__"},
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text
