"""
Permission System Tests

Covers the permission model described in docs/agent/platform/USER_PERMISSION.md.

Environment variables needed (on top of the base conftest ones):
  ADMIN_TEST_JWT    — Supabase-issued JWT for an admin user
  TESTER_TEST_JWT   — Supabase-issued JWT for a tester user
  VIEWER_TEST_JWT   — Supabase-issued JWT for a viewer user
  RUNNER_TEST_JWT   — JWT for a viewer/runner with team execution permissions

When a JWT variable is empty the corresponding tests are skipped automatically.
"""

import os
import pytest
import requests

# ---------------------------------------------------------------------------
# Session-level helpers
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


def _get_host_name(base_url: str, api_key: str, verify_ssl: bool) -> str:
    """Return the first registered host_name from /server/system/getAllHosts.

    This used to read /server/server-manager/hosts, which is not a route: it falls into the
    auto_proxy catch-all and answers 400, so the helper always returned "" and every
    host-dependent permission test skipped itself with "No host_name available" — on a server
    with five hosts registered.
    """
    try:
        resp = requests.get(
            f"{base_url}/server/system/getAllHosts",
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            timeout=5,
            verify=verify_ssl,
        )
        if resp.status_code == 200:
            data = resp.json()
            hosts = data if isinstance(data, list) else data.get("hosts", [])
            names = [h.get("host_name") or h.get("name", "") for h in hosts]
            names = [n for n in names if n]
            # Prefer VirtualPyTest's own device host: the labox-* fleet belongs to the labox
            # product and is not VPT CI's to drive (tests/docs/testing-strategy.md).
            preferred = os.environ.get("DEVICE_HOST", "host-clone-1")
            if preferred in names:
                return preferred
            non_labox = [n for n in names if not n.startswith("labox-")]
            if non_labox or names:
                return (non_labox or names)[0]
    except Exception:
        pass
    return os.environ.get("HOST_NAME", "")


# ---------------------------------------------------------------------------
# Additional fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def admin_jwt() -> str:
    return os.environ.get("ADMIN_TEST_JWT", "")


@pytest.fixture(scope="session")
def tester_jwt() -> str:
    return os.environ.get("TESTER_TEST_JWT", "")


@pytest.fixture(scope="session")
def viewer_jwt() -> str:
    return os.environ.get("VIEWER_TEST_JWT", "")


@pytest.fixture(scope="session")
def runner_jwt() -> str:
    """Viewer-role user who is a member of a team that grants execution permissions."""
    return os.environ.get("RUNNER_TEST_JWT", "")


def jwt_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture(scope="session")
def auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    """True when the server has ENFORCE_FRONTEND_JWT=true."""
    return _is_auth_enforced(base_url, verify_ssl)


@pytest.fixture(scope="session")
def host_name(base_url: str, api_key: str, verify_ssl: bool) -> str:
    """First available host_name on the connected server."""
    return _get_host_name(base_url, api_key, verify_ssl)


def _skip_if_no_jwt(token: str, label: str) -> None:
    if not token:
        pytest.skip(f"{label} JWT not configured — set {label.upper()}_TEST_JWT env var")


def _skip_if_open_mode(enforced: bool) -> None:
    if not enforced:
        pytest.skip("Server is in open mode (ENFORCE_FRONTEND_JWT not set) — auth tests skipped")


# ---------------------------------------------------------------------------
# 8.1  Role baseline tests
# ---------------------------------------------------------------------------


class TestRoleBaselines:

    def test_admin_can_access_users_endpoint(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_tester_cannot_access_users_endpoint(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_access_users_endpoint(
        self, viewer_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_admin_can_update_user_role(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Resolve the CI-owned mutation target from the list (never a real account).
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        non_admin = next((u for u in users if u.get("id") == ci_user_id), None)
        if non_admin is None:
            pytest.skip("CI mutation target not in users list")

        original_role = non_admin["role"]
        new_role = "tester" if original_role == "viewer" else "viewer"

        resp = requests.put(
            f"{base_url}/server/users/{non_admin['id']}",
            json={"role": new_role},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text

        # Restore original role
        requests.put(
            f"{base_url}/server/users/{non_admin['id']}",
            json={"role": original_role},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_tester_cannot_update_user_role(
        self, ci_user_id, tester_jwt, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        users = users_resp.json()
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("CI mutation target not in users list")

        resp = requests.put(
            f"{base_url}/server/users/{target['id']}",
            json={"role": "viewer"},
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_can_access_health(
        self, viewer_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        resp = requests.get(
            f"{base_url}/server/health",
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 8.2  UC1 — Runner can execute tests/campaigns, blocked from builder
# ---------------------------------------------------------------------------


class TestUC1RunnerCannotBuild:

    def test_runner_can_view_testcases(
        self, runner_jwt, base_url, team_id, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(runner_jwt, "runner")
        # /server/testcase/* is a server-side blueprint keyed on team_id — no host
        # involved, so this no longer skips when the runner has no device host.
        resp = requests.get(
            f"{base_url}/server/testcase/list",
            headers=jwt_headers(runner_jwt),
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text

    def test_runner_can_view_campaigns(
        self, runner_jwt, base_url, team_id, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(runner_jwt, "runner")
        resp = requests.get(
            f"{base_url}/server/campaigns/getAllCampaigns",
            headers=jwt_headers(runner_jwt),
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text

    def test_runner_can_view_reports(
        self, runner_jwt, base_url, team_id, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(runner_jwt, "runner")
        # /server/script-results (bare) is not a route — it falls into the auto_proxy
        # catch-all and answers 400/404. The listing is a plain DB read, no host involved.
        resp = requests.get(
            f"{base_url}/server/script-results/getAllScriptResults",
            headers=jwt_headers(runner_jwt),
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code in (200, 204), resp.text

    def test_runner_cannot_create_testcase(
        self, runner_jwt, base_url, team_id, verify_ssl, request_timeout, auth_enforced
    ):
        """Runner with denied testcases:create cannot create a test case."""
        _skip_if_no_jwt(runner_jwt, "runner")
        _skip_if_open_mode(auth_enforced)
        # /server/testcase/* is a server-side blueprint keyed on team_id — no host
        # involved, so this no longer skips when the runner has no device host.
        resp = requests.post(
            f"{base_url}/server/testcase/save",
            json={
                "team_id": team_id,
                "name": "__runner_create_test__",
                "description": "should be blocked",
            },
            headers=jwt_headers(runner_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_runner_cannot_create_campaign(
        self, runner_jwt, base_url, team_id, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(runner_jwt, "runner")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/campaigns/createCampaign",
            json={"team_id": team_id, "name": "__runner_campaign_test__"},
            headers=jwt_headers(runner_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 8.3  UC2 — Viewer can see test cases but cannot hide/edit/delete
# ---------------------------------------------------------------------------


class TestUC2ViewerCannotHide:

    def test_viewer_can_list_testcases(
        self, viewer_jwt, base_url, team_id, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        # /server/testcase/* is a server-side blueprint keyed on team_id — no host
        # involved, so this no longer skips when the runner has no device host.
        resp = requests.get(
            f"{base_url}/server/testcase/list",
            headers=jwt_headers(viewer_jwt),
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text

    def test_viewer_cannot_create_testcase(
        self, viewer_jwt, base_url, team_id, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        # /server/testcase/* is a server-side blueprint keyed on team_id — no host
        # involved, so this no longer skips when the runner has no device host.
        resp = requests.post(
            f"{base_url}/server/testcase/save",
            json={"team_id": team_id, "name": "__viewer_create__", "description": ""},
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_delete_testcase(
        self, viewer_jwt, base_url, team_id, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.delete(
            f"{base_url}/server/testcase/00000000-0000-0000-0000-000000000001",
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_viewer_cannot_run_test(
        self, viewer_jwt, base_url, team_id, host_name, device_id, verify_ssl, request_timeout,
        auth_enforced,
    ):
        """A viewer must be refused before anything is launched on a device.

        The payload is deliberately complete (host_name, device_id, script_name): with a field
        missing the route answers 400 for the wrong reason and the test passes nothing. It must
        be the permission check that answers.
        """
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/script/execute",
            json={
                "team_id": team_id,
                "host_name": host_name,
                "device_id": device_id,
                "script_name": "validation.py",
            },
            headers=jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 8.4  Team permission inheritance
# ---------------------------------------------------------------------------


class TestTeamPermissions:

    def test_admin_can_set_team_permissions(
        self, admin_jwt, team_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.put(
            f"{base_url}/server/teams/{team_id}",
            json={"permissions": ["execution.run:run_test", "execution.monitor:view"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "execution.run:run_test" in data.get("permissions", [])

        # Restore empty permissions
        requests.put(
            f"{base_url}/server/teams/{team_id}",
            json={"permissions": []},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_assign_user_to_multiple_teams(
        self, ci_user_id, admin_jwt, base_url, ci_team_id, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Resolve the CI-owned mutation target from the list (never a real account).
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        target = next((u for u in users if u.get("id") == ci_user_id), None)
        if not target:
            pytest.skip("CI mutation target not in users list")

        # Add user to the team (may already be there — OK)
        resp = requests.post(
            f"{base_url}/server/teams/{ci_team_id}/members",
            json={"user_id": target["id"], "role": "member"},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        # 201 = added, 500 = already exists (acceptable)
        assert resp.status_code in (201, 500), resp.text


# ---------------------------------------------------------------------------
# 8.5  Denied permissions override
# ---------------------------------------------------------------------------


class TestDeniedPermissions:

    def test_admin_can_set_denied_permissions(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Resolve the CI-owned mutation target from the list (never a real account).
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        tester_user = next((u for u in users if u.get("id") == ci_user_id), None)
        if not tester_user:
            pytest.skip("CI mutation target not in users list")

        original_denied = tester_user.get("denied_permissions", [])

        resp = requests.put(
            f"{base_url}/server/users/{tester_user['id']}",
            json={"denied_permissions": ["campaigns:create"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "campaigns:create" in data.get("denied_permissions", [])

        # Restore original
        requests.put(
            f"{base_url}/server/users/{tester_user['id']}",
            json={"denied_permissions": original_denied},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_effective_permissions_exclude_denied(
        self, ci_user_id, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        tester_user = next((u for u in users if u.get("id") == ci_user_id), None)
        if not tester_user:
            pytest.skip("CI mutation target not in users list")

        # Set a denial
        requests.put(
            f"{base_url}/server/users/{tester_user['id']}",
            json={"denied_permissions": ["testcases:delete"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

        # Check effective permissions
        perms_resp = requests.get(
            f"{base_url}/server/users/{tester_user['id']}/permissions",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert perms_resp.status_code == 200, perms_resp.text
        data = perms_resp.json()
        assert "testcases:delete" not in data.get("effective", [])
        assert "testcases:delete" in data.get("denied_permissions", [])

        # Restore. This test set a denial and never cleared it, so the denial stuck on
        # whichever user it had picked and leaked into later runs.
        requests.put(
            f"{base_url}/server/users/{tester_user['id']}",
            json={"denied_permissions": tester_user.get("denied_permissions", [])},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

        # Restore
        requests.put(
            f"{base_url}/server/users/{tester_user['id']}",
            json={"denied_permissions": []},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )


# ---------------------------------------------------------------------------
# 8.6  Permission matrix API
# ---------------------------------------------------------------------------


class TestPermissionMatrixAPI:

    def test_get_user_effective_permissions(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        if not users:
            pytest.skip("No users in DB")

        user_id = users[0]["id"]
        resp = requests.get(
            f"{base_url}/server/users/{user_id}/permissions",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        for field in ("role", "role_permissions", "team_permissions",
                      "individual_grants", "denied_permissions", "effective"):
            assert field in data, f"Missing field: {field}"

    def test_get_permission_matrix(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/permissions/matrix",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        assert "permissions" in data
        assert "users" in data
        assert isinstance(data["permissions"], list)
        assert isinstance(data["users"], list)

    def test_non_admin_cannot_get_matrix(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/permissions/matrix",
            headers=jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 403, resp.text

    def test_effective_permissions_reflect_role(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        users_resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert users_resp.status_code == 200
        users = users_resp.json()
        viewer_user = next((u for u in users if u.get("role") == "viewer"), None)
        if not viewer_user:
            pytest.skip("No viewer user available")

        resp = requests.get(
            f"{base_url}/server/users/{viewer_user['id']}/permissions",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Viewer should have dashboard:view but NOT testcases:create
        assert "dashboard:view" in data.get("effective", [])
        assert "testcases:create" not in data.get("effective", [])


# ---------------------------------------------------------------------------
# 8.7  Organisation management
# ---------------------------------------------------------------------------


class TestOrgManagement:

    def test_admin_can_list_all_users(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/users",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)

    def test_admin_can_remove_user_from_team(
        self, ci_user_id, admin_jwt, ci_team_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Get members of the team
        members_resp = requests.get(
            f"{base_url}/server/teams/{ci_team_id}/members",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert members_resp.status_code == 200
        members = members_resp.json()
        # Need a non-admin member to remove
        target = next(
            (m for m in members if m.get("role") != "admin"),
            None
        )
        if not target:
            pytest.skip("No non-admin team member available for remove test")

        user_id = target["user_id"]
        resp = requests.delete(
            f"{base_url}/server/teams/{ci_team_id}/members/{user_id}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text

        # Re-add so we don't leave the test in a broken state
        requests.post(
            f"{base_url}/server/teams/{ci_team_id}/members",
            json={"user_id": user_id, "role": target.get("team_role", "member")},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_create_and_delete_team(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        create_resp = requests.post(
            f"{base_url}/server/teams",
            json={"name": "__test_permissions_team__", "permissions": ["dashboard:view"]},
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_resp.status_code == 201, create_resp.text
        team = create_resp.json()
        assert "dashboard:view" in team.get("permissions", [])

        # Delete the created team
        del_resp = requests.delete(
            f"{base_url}/server/teams/{team['id']}",
            headers=jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert del_resp.status_code == 200, del_resp.text
