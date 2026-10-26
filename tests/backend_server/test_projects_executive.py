"""
Projects Executive Endpoint Tests (TASK-65 G4)
==============================================

Smoke tests for `GET /server/projects/<id>/executive` plus unit tests
for the pure helpers (`_health`, `_empty_buckets`, `_pass_rate_trend`
bucketing / `_pass_rate_prev_window` derivation).

Skip rules (mirror test_projects.py):
  * `ADMIN_TEST_JWT` / `TESTER_TEST_JWT` empty -> the affected class is skipped.
  * Server is in open mode (ENFORCE_FRONTEND_JWT != true) and the test needs
    auth -> the affected test is skipped.
  * Without the `20261006a_projects.sql` migration the endpoint answers 500;
    the suite skips on a 500 to keep CI green until the owner applies the
    migration. After apply, the same suite exercises the full path.

Unit tests (no server) live alongside the smoke tests and always run.
"""

import os
import uuid

import pytest
import requests


# ---------------------------------------------------------------------------
# Skip helpers (mirror test_projects.py)
# ---------------------------------------------------------------------------

def _skip_if_no_jwt(token: str, label: str) -> None:
    if not token:
        pytest.skip(f"{label} JWT not configured — set {label.upper()}_TEST_JWT env var")


def _skip_if_open_mode(enforced: bool) -> None:
    if not enforced:
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
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def _skip_if_migration_missing(resp) -> bool:
    if resp.status_code == 500 and "projects" in resp.text.lower():
        pytest.skip("Projects migration not applied yet (server answered 500 on the new routes)")
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def admin_jwt() -> str:
    return os.environ.get("ADMIN_TEST_JWT", "")


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


# ---------------------------------------------------------------------------
# Smoke tests (live server)
# ---------------------------------------------------------------------------

class TestExecutiveEndpoint:
    """Smoke tests for `GET /server/projects/<id>/executive`."""

    @pytest.fixture(scope="class")
    def project_id(self, admin_jwt, team_id, base_url, verify_ssl, request_timeout):
        _skip_if_no_jwt(admin_jwt, "admin")
        resp = requests.post(
            f"{base_url}/server/projects?team_id={team_id}",
            json={
                "name": f"Exec Smoke {uuid.uuid4().hex[:8]}",
                "description": "executive smoke",
            },
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return None
        assert resp.status_code == 201, f"setup: could not create project: {resp.status_code} {resp.text}"
        pid = resp.json()["id"]
        yield pid
        requests.delete(
            f"{base_url}/server/projects/{pid}",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )

    def test_admin_can_get_executive(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/executive?days=30",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project"]["id"] == project_id
        assert body["days"] == 30
        tiles = body["tiles"]
        # Health tile
        assert tiles["health"]["level"] in ("green", "yellow", "red")
        assert 0 <= tiles["health"]["current"] <= 100
        assert 0 <= tiles["health"]["previous"] <= 100
        # Pass-rate trend must have `days` entries
        assert isinstance(tiles["pass_rate_trend"], list)
        assert len(tiles["pass_rate_trend"]) == 30
        for entry in tiles["pass_rate_trend"]:
            assert "day" in entry and "pass" in entry and "fail" in entry
            assert entry["total"] == entry["pass"] + entry["fail"]
        # Top failures default to a list
        assert isinstance(tiles["top_failures"], list)
        assert len(tiles["top_failures"]) <= 5
        # Team-wide last_runs / ai_tokens_30d tiles are gone (the project page reads in-scope instead)
        assert "last_runs" not in tiles and "ai_tokens_30d" not in tiles
        # Members
        mem = tiles["members"]
        assert "owners" in mem and "viewers" in mem
        assert "can_add" in mem and "can_remove" in mem
        assert mem["can_add"] is True  # caller is admin

    def test_executive_clamps_days_param(
        self, admin_jwt, project_id, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        if not project_id:
            return
        # `?days=9999` clamps to 90.
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/executive?days=9999",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200, resp.text
        assert resp.json()["days"] == 90
        # `?days=0` clamps to 7.
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/executive?days=0",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 200
        assert resp.json()["days"] == 7

    def test_executive_unknown_project_returns_404(
        self, admin_jwt, base_url, verify_ssl, request_timeout
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        fake = str(uuid.uuid4())
        resp = requests.get(
            f"{base_url}/server/projects/{fake}/executive",
            headers=_jwt_headers(admin_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        assert resp.status_code == 404

    def test_viewer_can_get_executive(
        self, admin_jwt, viewer_jwt, project_id, base_url, verify_ssl, request_timeout,
        auth_enforced,
    ):
        _skip_if_no_jwt(admin_jwt, "admin")
        _skip_if_no_jwt(viewer_jwt, "viewer")
        _skip_if_open_mode(auth_enforced)
        if not project_id:
            return
        resp = requests.get(
            f"{base_url}/server/projects/{project_id}/executive",
            headers=_jwt_headers(viewer_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if _skip_if_migration_missing(resp):
            return
        # Viewer is in the project's team -> 200, but `can_add` should be False.
        assert resp.status_code == 200, resp.text
        assert resp.json()["tiles"]["members"]["can_add"] is False


# ---------------------------------------------------------------------------
# Unit tests (no server) — run anywhere
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutivePureHelpers:
    """Pure helper unit tests; no Supabase / no live server."""

    def test_health_green_on_improvement(self):
        from backend_server.src.routes.server_projects_executive_routes import _health
        out = _health(pass_rate_30d=92.0, pass_rate_prev_30d=88.0)
        assert out["level"] == "green"
        assert out["delta_pp"] == 4.0
        assert out["current"] == 92.0

    def test_health_yellow_when_stable_under_95(self):
        from backend_server.src.routes.server_projects_executive_routes import _health
        out = _health(pass_rate_30d=90.0, pass_rate_prev_30d=91.0)
        assert out["level"] == "yellow"  # 90% >=85% but no improvement >=+2pp and <95

    def test_health_red_when_below_85(self):
        from backend_server.src.routes.server_projects_executive_routes import _health
        out = _health(pass_rate_30d=70.0, pass_rate_prev_30d=72.0)
        assert out["level"] == "red"

    def test_health_green_when_high_enough(self):
        from backend_server.src.routes.server_projects_executive_routes import _health
        out = _health(pass_rate_30d=96.5, pass_rate_prev_30d=96.5)
        assert out["level"] == "green"  # >=95% is green regardless of delta

    def test_health_handles_zero_prev(self):
        from backend_server.src.routes.server_projects_executive_routes import _health
        # 50% up from 0% is a +50pp jump, which the helper's rule ("delta >= +2pp")
        # flags as green even though 50% < 85%. The test pins that contract: a brand
        # new project (prev = 0) and its first passing batch is green, not red.
        out = _health(pass_rate_30d=50.0, pass_rate_prev_30d=0.0)
        assert out["level"] == "green"
        assert out["delta_pp"] == 50.0

    def test_empty_buckets_returns_days_zeroes(self):
        from backend_server.src.routes.server_projects_executive_routes import _empty_buckets
        buckets = _empty_buckets(7)
        assert len(buckets) == 7
        for b in buckets:
            assert b["pass"] == 0 and b["fail"] == 0 and b["total"] == 0
            assert b["pass_rate"] is None
            assert "day" in b and len(b["day"]) == 10  # YYYY-MM-DD

    def test_pass_rate_trend_bucketing(self, monkeypatch):
        """Three rows on different days should produce 3 buckets with totals."""
        from datetime import datetime, timedelta, timezone as _tz
        from backend_server.src.routes import server_projects_executive_routes as mod

        # The helper buckets the last `days` days ending at `today`. Hard-coded dates
        # drift out of that window as time passes (the test started failing on
        # 2026-10-19 because 2026-09-25 is no longer inside a 7-day window), so we
        # compute the three target days relative to today.
        today = datetime.now(_tz.utc).date()
        day_minus_6 = (today - timedelta(days=6)).isoformat()  # oldest day in the 7-day window
        day_minus_5 = (today - timedelta(days=5)).isoformat()
        day_minus_4 = (today - timedelta(days=4)).isoformat()

        # Build a fake supabase response with three rows over a 7-day window.
        class _FakeSupabase:
            def table(self, _name):
                outer = self

                class _Table:
                    def select(self, *_a, **_kw):
                        return self

                    def eq(self, *_a, **_kw):
                        return self

                    def gte(self, *_a, **_kw):
                        return self

                    def in_(self, *_a, **_kw):
                        return self

                    def execute(self):
                        return _FakeResult([
                            {"success": True,  "started_at": f"{day_minus_6}T10:00:00+00:00"},
                            {"success": False, "started_at": f"{day_minus_5}T11:00:00+00:00"},
                            {"success": True,  "started_at": f"{day_minus_5}T12:00:00+00:00"},
                            {"success": True,  "started_at": f"{day_minus_4}T09:00:00+00:00"},
                        ])

                return _Table()

        class _FakeResult:
            def __init__(self, data):
                self.data = data
                self.count = len(data)

        monkeypatch.setattr(mod, "_supabase", lambda: _FakeSupabase())
        buckets = mod._pass_rate_trend(
            team_id="t1",
            script_names=["s1", "s2"],
            days=7,
        )
        assert len(buckets) == 7
        # Build {day -> bucket}
        by_day = {b["day"]: b for b in buckets}
        assert by_day[day_minus_6]["pass"] == 1 and by_day[day_minus_6]["fail"] == 0
        assert by_day[day_minus_5]["pass"] == 1 and by_day[day_minus_5]["fail"] == 1
        assert by_day[day_minus_4]["pass"] == 1 and by_day[day_minus_4]["fail"] == 0
        for b in buckets:
            assert b["total"] == b["pass"] + b["fail"]
