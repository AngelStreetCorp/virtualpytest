"""
Tests for server_storage_routes.py (/server/storage/*)

- GET  /server/storage/health          — public, no auth
- POST /server/storage/signed-url      — requires Supabase user auth (@require_user_auth)
- POST /server/storage/signed-urls-batch — requires Supabase user auth (@require_user_auth)

The signed-url(s) endpoints need a valid Supabase JWT (AUTH_TEST_JWT) to
reach their body-validation logic; without one we can still assert the auth
guard rejects anonymous requests (mirrors test_auth.py's tolerant status set,
since require_user_auth can also return 500 when SUPABASE_JWT_SECRET isn't
configured on the server).
"""
import pytest
import requests


def test_storage_health(get):
    response = get("/server/storage/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "healthy"
    assert body.get("service") == "storage"
    assert isinstance(body.get("r2_configured"), bool)


def test_signed_url_rejects_without_jwt(base_url, verify_ssl, request_timeout):
    # /signed-url is POST-only; auth is enforced by @require_user_auth
    # inside the view, so a POST without a bearer token exercises it.
    response = requests.post(
        f"{base_url}/server/storage/signed-url",
        json={"path": "captures/device1/test.jpg"},
        headers={"Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (401, 403, 500)


def test_signed_url_requires_path(base_url, verify_ssl, request_timeout, auth_jwt):
    if not auth_jwt:
        pytest.skip("Set AUTH_TEST_JWT to run authenticated storage tests")
    response = requests.post(
        f"{base_url}/server/storage/signed-url",
        json={},
        headers={"Authorization": f"Bearer {auth_jwt}", "Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_signed_url_rejects_invalid_expires_in(base_url, verify_ssl, request_timeout, auth_jwt):
    if not auth_jwt:
        pytest.skip("Set AUTH_TEST_JWT to run authenticated storage tests")
    response = requests.post(
        f"{base_url}/server/storage/signed-url",
        json={"path": "captures/device1/test.jpg", "expires_in": 30},
        headers={"Authorization": f"Bearer {auth_jwt}", "Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "expires_in" in body.get("error", "")


def test_signed_urls_batch_rejects_without_jwt(base_url, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/storage/signed-urls-batch",
        json={"paths": ["captures/device1/test.jpg"]},
        headers={"Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (401, 403, 500)


def test_signed_urls_batch_requires_paths(base_url, verify_ssl, request_timeout, auth_jwt):
    if not auth_jwt:
        pytest.skip("Set AUTH_TEST_JWT to run authenticated storage tests")
    response = requests.post(
        f"{base_url}/server/storage/signed-urls-batch",
        json={},
        headers={"Authorization": f"Bearer {auth_jwt}", "Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False


def test_signed_urls_batch_rejects_oversized_batch(base_url, verify_ssl, request_timeout, auth_jwt):
    if not auth_jwt:
        pytest.skip("Set AUTH_TEST_JWT to run authenticated storage tests")
    response = requests.post(
        f"{base_url}/server/storage/signed-urls-batch",
        json={"paths": [f"file_{i}.jpg" for i in range(101)]},
        headers={"Authorization": f"Bearer {auth_jwt}", "Content-Type": "application/json"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "maximum" in body.get("error", "").lower()
