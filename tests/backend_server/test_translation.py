"""
Translation Routes Tests

Covers backend_server/src/routes/server_translation_routes.py:
  POST /server/translate/text           — translate a single string, proxied to a host
  POST /server/translate/batch          — translate multiple segments
  POST /server/translate/restart-batch  — translate "restart" content blocks, proxied to a host
  POST /server/translate/detect         — detect language of text, proxied to a host

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

Notes / deliberate scope limits:
  - /text, /restart-batch and /detect all proxy the actual translation work
    to a registered host device (call_host / proxy_to_host_with_params).
    There is no guarantee a host is registered/reachable in CI, so only the
    pre-proxy validation branches are exercised.
  - /batch calls a module-level `batch_translate_segments()` helper that is
    not imported anywhere in server_translation_routes.py — providing
    `segments` would hit a NameError, caught by @handle_route_exceptions and
    turned into a 500. That looks like a real latent bug in the route, but
    since this backfill's brief is coverage traceable to what the routes
    already do (not fixing behavior), only the pre-that-bug validation
    branch ("no segments provided" -> 400) is asserted.
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
# POST /server/translate/text
# ---------------------------------------------------------------------------


class TestTranslateText:
    def test_translate_text_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.post(
            f"{base_url}/server/translate/text",
            json={},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 400, resp.text

    def test_translate_text_rejects_empty_body(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/text",
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_translate_text_requires_host(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/text",
            json={"text": "hello", "target_language": "fr"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body.get("success") is False
        # Every route resolves the host through the one shared helper
        # (route_utils.get_host_from_request), so the contract is "the 400 names the
        # missing parameter", not a route-specific sentence. These two tests each
        # asserted a different older wording ("Host information required" /
        # "host_name is required") that no longer exists anywhere in the codebase.
        assert "host_name" in body.get("error", "")


# ---------------------------------------------------------------------------
# POST /server/translate/batch
# ---------------------------------------------------------------------------


class TestTranslateBatch:
    def test_translate_batch_requires_segments(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/batch",
            json={"source_language": "en", "target_language": "fr"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False


# ---------------------------------------------------------------------------
# POST /server/translate/restart-batch
# ---------------------------------------------------------------------------


class TestTranslateRestartBatch:
    def test_restart_batch_requires_content_blocks(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/restart-batch",
            json={"target_language": "fr"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_restart_batch_requires_host_info(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/restart-batch",
            json={"content_blocks": {"intro": "hello"}, "target_language": "fr"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False


# ---------------------------------------------------------------------------
# POST /server/translate/detect
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_detect_rejects_empty_body(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/detect",
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_detect_requires_host_name(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/translate/detect",
            json={"text": "bonjour"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body.get("success") is False
        # Every route resolves the host through the one shared helper
        # (route_utils.get_host_from_request), so the contract is "the 400 names the
        # missing parameter", not a route-specific sentence. These two tests each
        # asserted a different older wording ("Host information required" /
        # "host_name is required") that no longer exists anywhere in the codebase.
        assert "host_name" in body.get("error", "")
