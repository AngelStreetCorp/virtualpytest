"""
Settings Routes Tests

Covers backend_server/src/routes/server_settings_routes.py:
  GET  /server/settings/config  — read whitelisted (non-secret) server/frontend/host/device config
  POST /server/settings/config  — update whitelisted config, writes .env files
  POST /server/settings/backup  — snapshot all .env files to timestamped backup files

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

Notes / deliberate scope limits:
  - POST /server/settings/config writes directly into the live server's own
    .env files (SERVER_URL, SERVER_PORT, AI provider keys, etc.) with no
    delete/rollback endpoint beyond the timestamped backup copy it makes.
    Mutating this on a real, shared deployment risks breaking the server for
    every other suite running against it, so only the pre-write "no data"
    validation branch is exercised.
  - POST /server/settings/backup does not modify any live config value, but
    it also has no corresponding delete endpoint — every CI run against a
    real server would leave a new `<file>.backup.<timestamp>` file behind
    forever, so it is skipped for the same reason as server_settings write
    endpoints: no safe/repeatable cleanup path.
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


# ---------------------------------------------------------------------------
# GET /server/settings/config
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_get_config_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.get(
            f"{base_url}/server/settings/config",
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            for section in ("server", "frontend", "host", "devices"):
                assert section in data, f"Missing section: {section}"

    def test_get_config_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/settings/config",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data.get("server"), dict)
        assert isinstance(data.get("frontend"), dict)
        assert isinstance(data.get("host"), dict)
        assert isinstance(data.get("devices"), dict)
        # Secrets must never be exposed even though SAFE_FIELDS whitelists
        # the *names* of some API key fields for editing — the sample values
        # returned here are still whatever is genuinely configured, so we
        # only assert that clearly-non-whitelisted keys are absent.
        assert "SUPABASE_JWT_SECRET" not in data.get("server", {})
        assert "FLASK_SECRET_KEY" not in data.get("server", {})


# ---------------------------------------------------------------------------
# POST /server/settings/config — validation only, no live-config mutation
# ---------------------------------------------------------------------------


class TestUpdateConfigValidation:
    def test_update_config_rejects_empty_body(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/settings/config",
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "No data provided"

    @pytest.mark.skip(
        reason=(
            "Writes directly into the live server's own .env files with no "
            "safe rollback beyond a timestamped backup copy — mutating real "
            "server/frontend/host config on a shared deployment is out of "
            "scope for a repeatable CI smoke test."
        )
    )
    def test_update_config_happy_path(self):
        ...


# ---------------------------------------------------------------------------
# POST /server/settings/backup
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Creates a new <file>.backup.<timestamp> file on the server's disk "
        "for every .env file present, with no corresponding delete endpoint "
        "— every CI run would leave permanent artifacts behind on a real "
        "deployment."
    )
)
class TestBackupConfig:
    def test_backup_config(self):
        ...
