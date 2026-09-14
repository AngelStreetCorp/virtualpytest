import pytest


def test_protected_profile_rejects_without_jwt(get):
    response = get("/server/auth/profile")
    assert response.status_code in (401, 403, 500)

    if response.status_code == 500:
        body = response.json()
        assert body.get("error") == "Server configuration error"


def test_protected_profile_accepts_valid_jwt(get, auth_jwt):
    if not auth_jwt:
        pytest.skip("Set AUTH_TEST_JWT to run authenticated profile test when JWT auth is enabled")

    response = get(
        "/server/auth/profile",
        headers={
            "Authorization": f"Bearer {auth_jwt}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("user"), dict)


def test_auth_check_is_public(get):
    response = get("/server/auth/check")
    assert response.status_code == 200

    body = response.json()
    assert "authenticated" in body
