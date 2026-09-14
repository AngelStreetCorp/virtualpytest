"""
Branding Routes Tests

Covers backend_server/src/routes/server_branding_routes.py:
  GET  /server/branding         — load current branding
  POST /server/branding         — save branding + create backup
  POST /server/branding/revert  — restore from backup
  GET  /server/branding/backup  — read the current backup (for preview)
  POST /server/branding/upload  — upload logo/favicon file

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

Notes / deliberate scope limits:
  - POST /server/branding/upload always writes a real file into the
    frontend's public/ (and dist/, if present) directories with no delete
    endpoint to clean up afterwards, so only its pre-write validation errors
    (which return before any file touches disk) are exercised here.
  - The save/revert round trip below relies on _save() backing up whatever
    branding existed *before* our write. If no branding file exists yet on
    the target server, there is nothing to restore from and the round trip
    is skipped rather than asserted, per save_data['backup_available'].
"""

import pytest
import requests


def _is_auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    """Return True when the server rejects requests without a JWT (auth is enabled)."""
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
# GET /server/branding
# ---------------------------------------------------------------------------


class TestLoadBranding:
    def test_load_branding_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.get(
            f"{base_url}/server/branding", timeout=request_timeout, verify=verify_ssl
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("success") is True
            assert "branding" in data

    def test_load_branding_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/branding",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        assert isinstance(data.get("branding"), dict)


# ---------------------------------------------------------------------------
# GET /server/branding/backup
# ---------------------------------------------------------------------------


class TestBackupBranding:
    def test_get_backup_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/branding/backup",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        # Always 200: either the backup contents, or success=True with
        # branding=None and an informational message when no backup exists.
        assert resp.status_code == 200, resp.text
        assert resp.json().get("success") is True


# ---------------------------------------------------------------------------
# POST /server/branding + POST /server/branding/revert
# ---------------------------------------------------------------------------


class TestSaveAndRevertBranding:
    """Saving backs up whatever was there before; reverting restores that
    backup — so saving a throwaway value and then reverting puts the server
    back exactly how this test found it."""

    def test_save_then_revert_restores_original(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        headers = jwt_headers(auth_jwt)

        original_resp = requests.get(
            f"{base_url}/server/branding",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert original_resp.status_code == 200, original_resp.text
        original = original_resp.json().get("branding", {})

        save_resp = requests.post(
            f"{base_url}/server/branding",
            json={"name": "__smoke_test_branding__", "tagline": "temporary"},
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert save_resp.status_code == 200, save_resp.text
        save_data = save_resp.json()
        assert save_data.get("success") is True
        assert save_data.get("saved", {}).get("name") == "__smoke_test_branding__"

        if not save_data.get("backup_available"):
            # No branding file existed before this test wrote one, so there is
            # nothing meaningful for /revert to restore. Put back an empty
            # branding config to avoid leaving our throwaway value live, and
            # stop here rather than asserting an exact revert target.
            requests.post(
                f"{base_url}/server/branding",
                json={},
                headers=headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            pytest.skip("No branding existed before this test — nothing for /revert to restore")

        revert_resp = requests.post(
            f"{base_url}/server/branding/revert",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert revert_resp.status_code == 200, revert_resp.text
        assert revert_resp.json().get("branding") == original

        # Confirm the live branding now matches what it was before the test.
        confirm_resp = requests.get(
            f"{base_url}/server/branding",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        assert confirm_resp.json().get("branding") == original

    def test_save_filters_unknown_keys(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        headers = jwt_headers(auth_jwt)

        original_resp = requests.get(
            f"{base_url}/server/branding",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert original_resp.status_code == 200
        original = original_resp.json().get("branding", {})

        save_resp = requests.post(
            f"{base_url}/server/branding",
            json={"name": "__smoke_filter_test__", "not_a_real_field": "should be dropped"},
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert save_resp.status_code == 200, save_resp.text
        saved = save_resp.json().get("saved", {})
        assert "not_a_real_field" not in saved
        assert saved.get("name") == "__smoke_filter_test__"

        # Restore whatever branding existed before this test ran.
        requests.post(
            f"{base_url}/server/branding",
            json=original,
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )


# ---------------------------------------------------------------------------
# POST /server/branding/upload — validation only, no file write
# ---------------------------------------------------------------------------


class TestUploadValidation:
    """Only exercise validation paths that return before any file is written
    to the frontend's public/dist directories (no cleanup endpoint exists)."""

    def test_upload_rejects_invalid_asset(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/branding/upload",
            data={"asset": "not_a_valid_asset"},
            headers={"Authorization": f"Bearer {auth_jwt}"},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_upload_rejects_missing_file(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/branding/upload",
            data={"asset": "logo"},
            headers={"Authorization": f"Bearer {auth_jwt}"},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False
