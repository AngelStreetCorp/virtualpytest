"""
Postman Routes Tests

Covers backend_server/src/routes/server_postman_routes.py:
  GET  /server/postman/workspaces                            — list configured workspaces (sanitized)
  GET  /server/postman/environments                          — list environments for a workspace (local config)
  GET  /server/postman/workspaces/<workspace_id>/collections  — list collections (calls real Postman API)
  GET  /server/postman/workspaces/<workspace_id>/environments — list environments (calls real Postman API)
  GET  /server/postman/environments/<environment_id>          — environment variables (calls real Postman API)
  GET  /server/postman/collections/<collection_id>/requests   — collection requests (calls real Postman API)
  GET  /server/postman/requests/<request_id>/definition        — request definition (calls real Postman API)
  POST /server/postman/test                                    — run selected endpoints as API tests

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.

Notes / deliberate scope limits:
  - Every endpoint that talks to the real Postman API (collections,
    workspace-environments, environment details, collection requests,
    request definition) looks up the workspace by id via
    get_workspace_by_id() and returns 404 *before* calling
    https://api.getpostman.com if the workspace isn't found in the local
    config file. Tests below use a random, never-configured workspace_id to
    exercise exactly that 404 branch without ever reaching the real Postman
    API.
  - POST /server/postman/test resolves the workspace the same way before
    executing any of the requested endpoint checks, so the same
    "workspace not found" 404 branch is used there too.
"""

import uuid

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


def _fake_id() -> str:
    return f"__smoke_test_does_not_exist_{uuid.uuid4().hex[:8]}__"


# ---------------------------------------------------------------------------
# Local-config-only reads
# ---------------------------------------------------------------------------


class TestWorkspacesAndEnvironmentsConfig:
    def test_get_workspaces_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.get(
            f"{base_url}/server/postman/workspaces",
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("success") is True
            assert isinstance(data.get("workspaces"), list)

    def test_get_workspaces_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/workspaces",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        for ws in data.get("workspaces", []):
            # Sanitized: the Postman API key must never be returned.
            assert "postmanApiKey" not in ws

    def test_get_environments_requires_workspace_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/environments",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_get_environments_for_unknown_workspace_is_empty(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        """get_environments_by_workspace() only filters the local config
        file, so an unconfigured workspaceId just yields an empty list
        rather than a 404 — no external call is made either way."""
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/environments",
            params={"workspaceId": _fake_id()},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        assert data.get("environments") == []


# ---------------------------------------------------------------------------
# Real-Postman-API-backed routes — only the pre-call "workspace not found"
# branch is exercised, never the real Postman API.
# ---------------------------------------------------------------------------


class TestUnknownWorkspaceNotFound:
    def test_get_collections_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/workspaces/{_fake_id()}/collections",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_get_workspace_environments_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/workspaces/{_fake_id()}/environments",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_get_environment_details_requires_workspace_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/environments/{_fake_id()}",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_get_environment_details_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/environments/{_fake_id()}",
            params={"workspace_id": _fake_id()},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_get_collection_requests_requires_workspace_id(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/collections/{_fake_id()}/requests",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_get_collection_requests_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/collections/{_fake_id()}/requests",
            params={"workspace_id": _fake_id()},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_get_request_definition_requires_params(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/requests/{_fake_id()}/definition",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_get_request_definition_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/postman/requests/{_fake_id()}/definition",
            params={"workspace_id": _fake_id(), "collection_id": _fake_id()},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False


class TestRunApiTest:
    def test_run_api_test_requires_endpoints(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/postman/test",
            json={"workspaceId": _fake_id(), "endpoints": []},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_run_api_test_unknown_workspace(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/postman/test",
            json={
                "workspaceId": _fake_id(),
                "endpoints": [{"method": "GET", "name": "health", "path": "/server/health"}],
            },
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False


# Every collections/environments/request-definition endpoint that finds a real configured
# workspace calls out to the real Postman API (https://api.getpostman.com) using that
# workspace's API key — no safe way to exercise the success path without a live third-party
# Postman account.
@pytest.mark.manual
class TestPostmanLiveApiCalls:
    def test_collections_and_environments(self):
        ...
