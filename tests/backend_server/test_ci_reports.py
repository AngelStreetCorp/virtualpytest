"""
Tests for the CI/CD feature's backend routes (features/cicd/backend_server/__init__.py,
blueprint url_prefix /server/cicd).

This entirely replaced the old core `server_ci_reports_routes.py` blueprint
(`/server/ci-reports/*`) — that module no longer exists on this branch. The
new API is project-scoped (not run-number-scoped) and backed by its own
`cicd` Postgres schema (features/cicd/db/001_cicd_schema.sql), separate from
the main VPT database; report HTML is still served off disk from
/opt/ci-reports (rewritten 2026-09-07 after the original file, written
against an older core blueprint, failed against this branch's real API).

Every read endpoint here checks `cicd_db.schema_error()` first and returns
a 200 with `{'success': False, 'configured': False, 'error': ...}` if the
schema isn't set up — never a 4xx/5xx — so these tests accept either the
"configured" or "not configured" response shape rather than assuming the
`cicd` schema exists on every deployment this suite runs against.

Mutating/destructive endpoints (dispatch, ingest, project registry writes,
runner restart) are skipped: they need auth this suite doesn't have, fire a
real GitHub Actions workflow, write real database rows, or SSH into a real
runner VM.
"""

import os

import pytest
import requests


def test_health_returns_capability_flags(get, api_headers):
    response = get("/server/cicd/health", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    for key in ("configured", "github_token", "reports_dir", "reports_dir_present", "ingest_token"):
        assert key in body, f"missing '{key}' in {body}"


def test_list_projects_returns_array_or_not_configured(get, api_headers):
    response = get("/server/cicd/projects", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    if body.get("configured"):
        assert isinstance(body.get("projects"), list)
    else:
        assert body.get("success") is False
        assert "error" in body


def test_list_runs_returns_array_or_not_configured(get, api_headers):
    response = get("/server/cicd/runs", headers=api_headers, params={"limit": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    if body.get("configured"):
        assert body.get("success") is True
        assert isinstance(body.get("runs"), list)
    else:
        assert body.get("success") is False


def test_get_run_unknown_returns_404_or_not_configured(get, api_headers):
    response = get(
        "/server/cicd/runs/__definitely_not_a_real_project__/__definitely_not_a_real_run__",
        headers=api_headers,
    )
    body = response.json()
    if body.get("configured") is False:
        # schema_error short-circuits before the "not found" check, still 200
        assert response.status_code == 200
        assert body.get("success") is False
    else:
        assert response.status_code == 404, response.text
        assert body.get("success") is False


def test_list_runners_returns_array_or_not_configured(get, api_headers):
    response = get("/server/cicd/runners", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    if body.get("configured"):
        assert isinstance(body.get("runners"), list)
        assert isinstance(body.get("errors"), dict)
    else:
        assert body.get("success") is False


def test_branches_unknown_project_returns_400_or_not_configured(get, api_headers):
    response = get(
        "/server/cicd/branches",
        headers=api_headers,
        params={"project": "__definitely_not_a_real_project__"},
    )
    body = response.json()
    if body.get("configured") is False:
        assert response.status_code == 200
        assert body.get("success") is False
    else:
        assert response.status_code == 400, response.text
        assert body.get("success") is False
        assert body.get("error") == "unknown project"


def test_live_returns_running_and_dispatches_or_not_configured(get, api_headers):
    response = get("/server/cicd/live", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    if body.get("configured"):
        assert isinstance(body.get("running"), list)
        assert isinstance(body.get("dispatches"), list)
    else:
        assert body.get("success") is False


def test_serve_report_unknown_run_returns_404(get, api_headers):
    # /server/cicd/report/* is behind the closed-by-default guard (BUG-0057): authenticate.
    response = get("/server/cicd/report/__definitely_not_a_real_run_dir__/", headers=api_headers)
    assert response.status_code == 404, response.text
    body = response.json()
    assert "not found" in body.get("error", "").lower()


@pytest.mark.skip(reason="fires a real GitHub Actions workflow_dispatch and writes a ci_dispatches row")
def test_dispatch_not_exercised():
    pass


def test_ingest_rejects_missing_and_wrong_token(base_url, verify_ssl, request_timeout):
    """/cicd/ingest is bearer-auth'd with CICD_INGEST_TOKEN, not the suite's API key."""
    for headers in ({"Content-Type": "application/json"},
                    {"Authorization": "Bearer __definitely_not_the_ingest_token__"}):
        resp = requests.post(
            f"{base_url}/server/cicd/ingest", json={}, headers=headers,
            timeout=request_timeout, verify=verify_ssl,
        )
        # 503 when the server has no token configured at all — still not a successful write.
        assert resp.status_code in (401, 503), resp.text
        assert resp.json().get("success") is False


def test_ingest_validates_payload_without_writing(base_url, verify_ssl, request_timeout):
    """With a valid token but an incomplete run, ingest 400s before touching the schema.

    Deliberately stops at validation: this endpoint writes to the real cicd schema that
    the Reports page reads, so the test proves the auth and validation paths and leaves
    the row-writing path to actual CI jobs.
    """
    token = os.environ.get("CICD_INGEST_TOKEN", "").strip()
    if not token:
        pytest.skip("CICD_INGEST_TOKEN not set")
    resp = requests.post(
        f"{base_url}/server/cicd/ingest",
        json={"run": {"project": "virtualpytest"}},   # missing "run" key -> 400
        headers={"Authorization": f"Bearer {token}"},
        timeout=request_timeout, verify=verify_ssl,
    )
    if resp.status_code == 503:
        pytest.skip("cicd schema not configured on this server")
    assert resp.status_code == 400, resp.text
    assert "project and run" in resp.json().get("error", "")


def test_update_project_requires_admin(base_url, verify_ssl, request_timeout, admin_jwt, tester_jwt):
    """PUT /cicd/projects/<p> is @require_user_auth + @require_role('admin').

    Checks the gate from both sides without mutating the registry: unauthenticated and
    tester-role callers are refused. The success path is left alone on purpose — there is
    no delete_project route, so a real upsert would leave a row behind permanently.
    """
    url = f"{base_url}/server/cicd/projects/__never_a_real_project__"
    anon = requests.put(url, json={}, timeout=request_timeout, verify=verify_ssl)
    assert anon.status_code in (401, 403), anon.text

    if not tester_jwt:
        pytest.skip("TESTER_TEST_JWT not set")
    tester = requests.put(
        url, json={}, headers={"Authorization": f"Bearer {tester_jwt}"},
        timeout=request_timeout, verify=verify_ssl,
    )
    assert tester.status_code == 403, tester.text


@pytest.mark.skip(reason="SSHes into a real runner VM and restarts its systemd service — destructive, not safe to run every CI cycle")
def test_restart_runner_not_exercised():
    pass
