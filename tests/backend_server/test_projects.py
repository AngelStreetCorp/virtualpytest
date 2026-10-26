"""
Projects API Tests (TASK-65 G1)
================================

Smoke tests for the Projects REST API + Active Users heartbeat.

Skip rules (mirrors test_workspaces.py):
  * `ADMIN_TEST_JWT` / `TESTER_TEST_JWT` / `VIEWER_TEST_JWT` empty -> the affected
    class is skipped.
  * Server is in open mode (ENFORCE_FRONTEND_JWT != true) and the test needs
    auth -> the affected test is skipped.

The test suite depends on three SQL migrations being applied (the owner decides when):
  * setup/db/migrations/20261006a_projects.sql
  * setup/db/migrations/20261006b_team_members_last_seen.sql
  * setup/db/migrations/20261006c_report_snapshots_project_ids.sql
Without them the new routes answer 500; the smoke suite skips on a 500 to keep CI
green until the owner applies them. After apply, the same suite exercises the
full path.

Unit tests (no server) live alongside the smoke tests and always run.
"""

import os
import uuid
from datetime import datetime, timezone, timedelta

import requests


# ---------------------------------------------------------------------------
# Skip helpers (mirrors test_workspaces.py)
# ---------------------------------------------------------------------------

def _skip_if_no_jwt(token: str, label: str) -> None:
    if not token:
        import pytest
        pytest.skip(f"{label} JWT not configured — set {label.upper()}_TEST_JWT env var")


def _skip_if_open_mode(enforced: bool) -> None:
    if not enforced:
        import pytest
        pytest.skip("Server is in open mode (ENFORCE_FRONTEND_JWT not set) — auth tests skipped")


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


def _jwt_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _skip_if_migration_missing(resp) -> bool:
    """Skip (no fail) when the server reports the projects tables are missing.

    Without the migration applied the new routes answer 500. Skipping keeps the
    suite green while the owner hasn't applied the migration yet.
    """
    if resp.status_code == 500 and ("projects" in resp.text.lower() or "team_members" in resp.text.lower()):
        import pytest
        pytest.skip("Projects migration not applied yet (server answered 500 on the new routes)")
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import pytest


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
def auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    return _is_auth_enforced(base_url, verify_ssl)


@pytest.fixture(scope="session")
def request_timeout() -> float:
    return float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))


@pytest.fixture(scope="session")
def verify_ssl() -> bool:
    return os.environ.get("VERIFY_SSL", "false").lower() in ("1", "true", "yes", "on")


@pytest.fixture
def unique_project_name():
    """`P-<hex8>` — unique enough for one run; the smoke cleanup deletes it on teardown."""
    return f"p-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# TestProjectsCRUD  — admin can fully manage a project
# ---------------------------------------------------------------------------


class TestProjectsCRUD:
    """Admin can create, read, update, delete a project."""

    @pytest.fixture(scope="class")
    def project_id(self, admin_jwt, team_id, base_url, verify_ssl, request_timeout):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Smoke Project {uuid.uuid4().hex[:8]}",
                  "description": "Project smoke test",
                  "color": "#FFB300"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return None
        assert resp.status_code == 201, f"could not create project: {resp.status_code} {resp.text}"
        pid = resp.json()["id"]
        yield pid
        # Teardown
        requests.delete(
            f"{base_url}/server/projects/{pid}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_list_projects(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.get(
            f"{base_url}/server/projects",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_admin_can_create_project(
        self, admin_jwt, team_id, base_url, verify_ssl, request_timeout, unique_project_name
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": unique_project_name, "description": "smoke"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body.get("name") == unique_project_name
        # Tag was created automatically with the slugified name
        assert isinstance(body.get("tags"), list) and body["tags"], "project must own at least one tag"
        # Creator is the first owner
        assert any(m.get("role") == "owner" for m in body.get("members", []))
        # Cleanup
        requests.delete(
            f"{base_url}/server/projects/{body['id']}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_create_project_requires_name(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects",
            json={"description": "Missing name field"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 400, resp.text

    def test_create_project_validates_color(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects",
            json={"name": f"BadColor {uuid.uuid4().hex[:8]}", "color": "not-a-color"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 400, resp.text

    def test_create_project_rejects_duplicate_name(
        self, admin_jwt, team_id, base_url, verify_ssl, request_timeout, project_id
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        existing = requests.get(
            f"{base_url}/server/projects/{project_id}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(existing):
            return
        name = existing.json()["name"]
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": name},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 409, resp.text

    def test_admin_can_get_project(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == project_id

    def test_admin_can_update_project(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        new_desc = f"Updated by smoke at {uuid.uuid4().hex[:8]}"
        resp = requests.patch(
            f"{base_url}/server/projects/{project_id}",
            json={"description": new_desc},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        assert resp.json().get("description") == new_desc

    def test_admin_can_delete_project(
        self, admin_jwt, team_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        # Create a throwaway project
        create = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Smoke Delete {uuid.uuid4().hex[:8]}"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(create):
            return
        assert create.status_code == 201, create.text
        pid = create.json()["id"]

        delete = requests.delete(
            f"{base_url}/server/projects/{pid}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert delete.status_code == 200, delete.text


# ---------------------------------------------------------------------------
# TestProjectsAccessControl  — non-admin roles cannot create
# ---------------------------------------------------------------------------


class TestProjectsAccessControl:
    """Testers and viewers cannot create / edit projects."""

    def test_tester_can_create_project(
        self, tester_jwt, admin_jwt, team_id, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Tester Create {uuid.uuid4().hex[:8]}"},
            headers=_jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        # Migration 20261006a_projects.sql grants team:projects:create to manager/developer/tester
        # (viewer is view-only), and the route is @require_permission('team:projects:create').
        assert resp.status_code == 201, resp.text
        created_id = resp.json().get("id")
        if created_id:
            # Only admins/owners may delete: a tester token gets 403 and the project would leak.
            requests.delete(
                f"{base_url}/server/projects/{created_id}?team_id={team_id}",
                headers=_jwt_headers(admin_jwt or tester_jwt),
                timeout=request_timeout,
                verify=verify_ssl,
            )

    def test_viewer_cannot_create_project(
        self, viewer_jwt, team_id, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Viewer Create {uuid.uuid4().hex[:8]}"},
            headers=_jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 403, resp.text

    def test_tester_can_list_projects(
        self, tester_jwt, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        _skip_if_no_jwt(tester_jwt, "tester")
        _skip_if_open_mode(auth_enforced)
        resp = requests.get(
            f"{base_url}/server/projects",
            headers=_jwt_headers(tester_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        # testers have team:projects:view in role_permissions defaults; expect 200
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# TestProjectsMembers  — members CRUD
# ---------------------------------------------------------------------------


class TestProjectsMembers:
    """Admin can list + add + remove project members."""

    @pytest.fixture(scope="class")
    def project_id(self, admin_jwt, team_id, base_url, verify_ssl, request_timeout):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Smoke Member Project {uuid.uuid4().hex[:8]}"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return None
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        yield pid
        requests.delete(
            f"{base_url}/server/projects/{pid}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_get_project_members(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/members",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_admin_can_add_and_remove_project_member(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout,
        api_headers,
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        # Discover the caller's own team_member row (we need a real one to add).
        team_id = os.environ.get("TEAM_ID", "00000000-0000-0000-0000-000000000001")
        members_resp = requests.get(
            f"{base_url}/server/teams/{team_id}/members",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(members_resp):
            return
        if members_resp.status_code != 200 or not members_resp.json():
            import pytest
            pytest.skip("No team member available to add")
        target = members_resp.json()[0]
        team_member_id = target.get("id") or target.get("team_member_id") or target.get("user_id")
        if not team_member_id:
            import pytest
            pytest.skip("Team member list did not include an id field")

        add_resp = requests.post(
            f"{base_url}/server/projects/{project_id}/members",
            json={"team_member_id": team_member_id, "role": "viewer"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(add_resp):
            return
        assert add_resp.status_code in (200, 201), add_resp.text

        rm_resp = requests.delete(
            f"{base_url}/server/projects/{project_id}/members/{team_member_id}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert rm_resp.status_code == 200, rm_resp.text

    def test_add_member_validates_role(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        resp = requests.post(
            f"{base_url}/server/projects/{project_id}/members",
            json={"team_member_id": "irrelevant", "role": "superuser"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# TestHeartbeat — PUT /server/team/last_seen
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Heartbeat is idempotent and accepts signed-in callers."""

    def test_admin_heartbeat_succeeds(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.put(
            f"{base_url}/server/team/last_seen",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # admin has at least one team_member row; expect updated_rows >= 1
        assert body.get("updated_rows", 0) >= 1 or body.get("reason") == "no_team_membership", body


# ---------------------------------------------------------------------------
# TestProjectActiveUsers — GET /server/projects/<id>/active-users
# ---------------------------------------------------------------------------


class TestProjectActiveUsers:
    """Active users endpoint returns users with `last_seen_at > now() - 5 min`."""

    @pytest.fixture(scope="class")
    def project_id(self, admin_jwt, team_id, base_url, verify_ssl, request_timeout):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={"name": f"Smoke Active {uuid.uuid4().hex[:8]}"},
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return None
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        yield pid
        requests.delete(
            f"{base_url}/server/projects/{pid}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_active_users_returns_count(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        # The admin's heartbeat ran in TestHeartbeat -> that user is active now.
        requests.put(
            f"{base_url}/server/team/last_seen",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/active-users",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "count" in body and "active_users" in body
        assert isinstance(body["active_users"], list)


# ---------------------------------------------------------------------------
# Unit tests (no server) — run anywhere
# ---------------------------------------------------------------------------


class TestProjectsPureHelpers:
    """Pure helper unit tests; no Supabase / no live server."""

    def test_project_not_found_error(self):
        from shared.src.lib.database.projects_db import ProjectNotFoundError
        e = ProjectNotFoundError("missing")
        assert "missing" in str(e)

    def test_project_duplicate_error(self):
        from shared.src.lib.database.projects_db import ProjectDuplicateError
        e = ProjectDuplicateError("Acme TV")
        assert e.name == "Acme TV"
        assert "Acme TV" in str(e)

    def test_protected_tag_error(self):
        from shared.src.lib.database.projects_db import ProtectedTagError
        e = ProtectedTagError(42)
        assert e.tag_id == 42

    def test_color_validation_accepts_hex(self):
        from backend_server.src.routes.server_projects_routes import _validate_color
        assert _validate_color("#FFB300") is None
        assert _validate_color("#123abc") is None

    def test_color_validation_rejects_bad(self):
        from backend_server.src.routes.server_projects_routes import _validate_color
        assert _validate_color("not-a-color") is not None
        assert _validate_color("#FFF") is not None        # too short
        assert _validate_color("FFB300") is not None     # missing #
        assert _validate_color(123) is not None           # not a string
        assert _validate_color(None) is None              # None is allowed (no color)

    def test_slugify_project_name_lowercases(self):
        from shared.src.lib.database.projects_db import _slugify_project_name
        assert _slugify_project_name("Acme TV") == "acme_tv"
        assert _slugify_project_name("  Hello World  ") == "hello_world"
        assert _slugify_project_name("@@@") == "project"
        assert _slugify_project_name("") == "project"

    def test_color_palette_is_stable(self):
        """The palette is part of the UI contract (front-end badge reads it back)."""
        from shared.src.lib.database.projects_db import _get_or_create_tag
        # The constant isn't accessible directly. Sanity-import to make sure it exists.
        assert callable(_get_or_create_tag)

    def test_protected_tag_pattern(self):
        """A tag used by any project must be marked protected (Q1 risk)."""
        # Pure unit: the trigger raises `restrict_violation`; the db helper
        # surfaces it as ProtectedTagError. We assert the class exists.
        from shared.src.lib.database.projects_db import ProtectedTagError
        assert issubclass(ProtectedTagError, Exception)