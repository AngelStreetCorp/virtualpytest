"""
Workspace System Smoke Tests

Covers CRUD operations and access control for the workspace management system.

Environment variables needed (on top of the base conftest ones):
  ADMIN_TEST_JWT    — Supabase-issued JWT for an admin user
  TESTER_TEST_JWT   — Supabase-issued JWT for a tester user
  VIEWER_TEST_JWT   — Supabase-issued JWT for a viewer user

When a JWT variable is empty the corresponding tests are skipped automatically.
"""

import os
import uuid

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
# TestWorkspaceCRUD
# ---------------------------------------------------------------------------


class TestWorkspaceCRUD:
    """Admin can fully manage workspaces (create, read, update, delete)."""

    @pytest.fixture(scope="class")
    def workspace_id(self, admin_jwt, base_url, verify_ssl, request_timeout):
        """Create a workspace for the class tests, delete it on teardown.

        Unique name per run: the slug is derived from it and is unique in the table, so a
        fixed name turns any run whose teardown did not fire into a permanent collision.
        """
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": f"Test Workspace Smoke {uuid.uuid4().hex[:8]}",
                  "description": "Smoke test workspace"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        # Fail, never skip: creating a workspace as admin is a thing this platform must do.
        assert resp.status_code == 201, f"could not create workspace: {resp.status_code} {resp.text}"
        wid = resp.json()["id"]
        yield wid
        # teardown
        requests.delete(
            f"{base_url}/server/workspaces/{wid}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_list_workspaces(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/workspaces",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_admin_can_create_workspace(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": f"Smoke Create Test {uuid.uuid4().hex[:8]}",
                  "description": "Created by smoke test"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data, "Response must include an id field"
        created_id = data["id"]

        # Cleanup the workspace created in this test
        requests.delete(
            f"{base_url}/server/workspaces/{created_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_get_workspace(
        self, admin_jwt, workspace_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/workspaces/{workspace_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == workspace_id

    def test_admin_can_update_workspace(
        self, admin_jwt, workspace_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.put(
            f"{base_url}/server/workspaces/{workspace_id}",
            json={"name": "Test Workspace Smoke Updated", "description": "Updated by smoke test"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("name") == "Test Workspace Smoke Updated"

    def test_admin_can_delete_workspace(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        """Create a dedicated workspace and delete it; does not rely on the class fixture."""
        _skip_if_no_jwt(admin_jwt, "admin")
        create_resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": f"Smoke Delete Target {uuid.uuid4().hex[:8]}",
                  "description": "To be deleted"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_resp.status_code == 201, (
            f"could not create workspace for delete test: {create_resp.status_code} {create_resp.text}")
        wid = create_resp.json()["id"]

        del_resp = requests.delete(
            f"{base_url}/server/workspaces/{wid}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert del_resp.status_code == 200, del_resp.text

    def test_create_workspace_requires_name(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"description": "Missing name field"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# TestWorkspaceAccessControl
# ---------------------------------------------------------------------------


class TestWorkspaceAccessControl:
    """Non-admin roles cannot manage workspaces."""

    def test_tester_cannot_list_workspaces(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/workspaces",
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_list_workspaces(
        self, viewer_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/workspaces",
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_tester_cannot_create_workspace(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": "__tester_create_workspace__"},
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_create_workspace(
        self, viewer_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": "__viewer_create_workspace__"},
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# TestWorkspaceMembers
# ---------------------------------------------------------------------------


class TestWorkspaceMembers:
    """Admin can manage workspace membership (users and teams)."""

    @pytest.fixture(scope="class")
    def workspace_id(self, admin_jwt, base_url, verify_ssl, request_timeout):
        """Create a workspace for member tests, delete it on teardown.

        The name is unique per run. It used to be the fixed "Smoke Member Test Workspace",
        whose derived slug is unique in the table — so the first run whose teardown did not
        fire (an interrupt, a failed delete) left a row that made every later run collide.
        That surfaced as a 500 and the fixture skipped on it, so three tests stopped asking
        their question permanently and nothing said so.
        """
        _skip_if_no_jwt(admin_jwt, "admin")
        unique = uuid.uuid4().hex[:8]
        resp = requests.post(
            f"{base_url}/server/workspaces",
            json={"name": f"Smoke Member Test Workspace {unique}",
                  "description": "Workspace for member tests"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        # Fail, never skip: creating a workspace as admin is a thing this platform must do.
        assert resp.status_code == 201, f"could not create workspace: {resp.status_code} {resp.text}"
        wid = resp.json()["id"]
        yield wid
        requests.delete(
            f"{base_url}/server/workspaces/{wid}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_get_workspace_members(
        self, admin_jwt, workspace_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/workspaces/{workspace_id}/members",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_admin_can_add_and_remove_user_from_workspace(
        self, ci_user_id, admin_jwt, workspace_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Discover a user to add
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        if not users:
            pytest.skip("No users available for member test")
        user_id = ci_user_id

        # Add user to workspace
        add_resp = requests.post(
            f"{base_url}/server/workspaces/{workspace_id}/members/user",
            json={"user_id": user_id, "role": "member"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert add_resp.status_code in (200, 201), add_resp.text

        # Verify member appears in list
        members_resp = requests.get(
            f"{base_url}/server/workspaces/{workspace_id}/members",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert members_resp.status_code == 200, members_resp.text
        members = members_resp.json()
        member_ids = [m.get("user_id") or m.get("id") for m in members]
        assert user_id in member_ids, f"User {user_id} not found in workspace members after add"

        # Remove user from workspace — find the member record id
        member_record = next(
            (m for m in members if (m.get("user_id") or m.get("id")) == user_id),
            None,
        )
        member_record_id = member_record.get("member_id") or member_record.get("id") if member_record else user_id

        del_resp = requests.delete(
            f"{base_url}/server/workspaces/{workspace_id}/members/{member_record_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert del_resp.status_code == 200, del_resp.text

    def test_admin_can_add_and_remove_team_from_workspace(
        self, admin_jwt, workspace_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Discover a team to add
        teams_resp = requests.get(
            f"{base_url}/server/teams",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert teams_resp.status_code == 200, teams_resp.text
        teams = teams_resp.json()
        if not teams:
            pytest.skip("No teams available for workspace team member test")
        team_id = teams[0]["id"]

        # Add team to workspace
        add_resp = requests.post(
            f"{base_url}/server/workspaces/{workspace_id}/members/team",
            json={"team_id": team_id, "role": "member"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert add_resp.status_code in (200, 201), add_resp.text

        # Verify team appears in members list
        members_resp = requests.get(
            f"{base_url}/server/workspaces/{workspace_id}/members",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert members_resp.status_code == 200, members_resp.text
        members = members_resp.json()
        team_member_ids = [m.get("team_id") for m in members if m.get("team_id")]
        assert team_id in team_member_ids, f"Team {team_id} not found in workspace members after add"

        # Remove team from workspace — find the member record id
        team_record = next(
            (m for m in members if m.get("team_id") == team_id),
            None,
        )
        member_record_id = team_record.get("member_id") or team_record.get("id") if team_record else team_id

        del_resp = requests.delete(
            f"{base_url}/server/workspaces/{workspace_id}/members/{member_record_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert del_resp.status_code == 200, del_resp.text


# ---------------------------------------------------------------------------
# TestUserWorkspaces
# ---------------------------------------------------------------------------


class TestUserWorkspaces:
    """The per-user workspace listing endpoint works correctly."""

    def test_get_user_workspaces(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Discover a user id
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200, users_resp.text
        users = users_resp.json()
        if not users:
            pytest.skip("No users available for user workspaces test")
        user_id = users[0]["id"]

        resp = requests.get(
            f"{base_url}/server/workspaces/user/{user_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)
