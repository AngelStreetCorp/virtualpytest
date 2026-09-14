"""
Builder Routes Tests

Covers backend_server/src/routes/server_builder_routes.py:
  POST /server/builder/execute                          — proxy standard block execution to host
  GET  /server/builder/execution/<execution_id>/status   — proxy execution status to host

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

Notes / deliberate scope limits:
  - Both endpoints proxy to a `host_name` via proxy_to_host_with_params(), an
    internal call to a registered host device. There is no guarantee a host
    is registered/reachable in the CI environment, so only the pre-proxy
    validation branches (which return before proxy_to_host_with_params is
    ever called) are exercised here.
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
# POST /server/builder/execute
# ---------------------------------------------------------------------------


class TestExecuteStandardBlockValidation:
    def test_execute_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced, team_id
    ):
        resp = requests.post(
            f"{base_url}/server/builder/execute",
            json={"command": "sleep", "host_name": "smoke-host"},
            params={"team_id": team_id},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            # Open mode: falls through to route logic; host_name is set but
            # a nonexistent host will fail inside the proxy call, not here.
            assert resp.status_code in (200, 400, 404, 500, 502, 504), resp.text

    def test_execute_requires_command(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/builder/execute",
            json={"host_name": "smoke-host"},
            params={"team_id": team_id},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "command is required"

    def test_execute_requires_host_name(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/builder/execute",
            json={"command": "sleep"},
            params={"team_id": team_id},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "host_name is required"

    def test_execute_requires_team_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/builder/execute",
            json={"command": "sleep", "host_name": "smoke-host"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "team_id is required"


# ---------------------------------------------------------------------------
# GET /server/builder/execution/<execution_id>/status
# ---------------------------------------------------------------------------


class TestExecutionStatusValidation:
    def test_status_requires_host_name(
        self, base_url, verify_ssl, request_timeout, auth_jwt, team_id
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/builder/execution/fake-execution-id/status",
            params={"team_id": team_id},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "host_name is required"

    def test_status_requires_team_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/builder/execution/fake-execution-id/status",
            params={"host_name": "smoke-host"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("error") == "team_id is required"
