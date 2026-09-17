"""
Tests for the external provisioning half of server_users_routes.py
(`/server/users/{email}` — see docs/integrations/user-provisioning.md).

The call that matters to an integrator is the password reset:

    PUT /server/users/{email}?grafana=true   {"password": "..."}   -> 200

and the mistake they make is dropping `-X PUT` from that curl, which turns it into a
GET. The GET address is a real read-only status check, so it used to answer
`200 {"status":"ok","exists":true}` — the reset never ran, but the response reads like
success. It now answers 405 and names the right call.

Lifecycle writes here use a dedicated CI email and delete themselves; no real account is
touched.
"""
import pytest
import requests

CI_EMAIL = "provisioning.ci@vpt.local"
ABSENT_EMAIL = "virtualpytest-ci-placeholder@example.invalid"


def _delete(base_url, api_headers, verify_ssl, request_timeout, email):
    requests.delete(
        f"{base_url}/server/users/{email}?grafana=true",
        headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )


def test_reset_password_returns_200(base_url, api_headers, verify_ssl, request_timeout):
    """The documented call succeeds and reports both halves."""
    try:
        response = requests.put(
            f"{base_url}/server/users/{CI_EMAIL}?grafana=true",
            json={"password": "ci-temp-password-9f2a"},
            headers=api_headers, timeout=request_timeout, verify=verify_ssl,
        )
        if response.status_code == 502:
            pytest.skip("Grafana not configured on this deployment — platform half only")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["action"] in ("created", "updated")
        assert body["email"] == CI_EMAIL
        # The mirror ran: absent here means ?grafana=true was silently dropped.
        assert "grafana" in body
    finally:
        _delete(base_url, api_headers, verify_ssl, request_timeout, CI_EMAIL)


def test_edit_without_a_password_leaves_the_password_alone(base_url, api_headers,
                                                          verify_ssl, request_timeout):
    """PUT is not password-only: with no `password` it edits and nothing else changes."""
    try:
        created = requests.put(
            f"{base_url}/server/users/{CI_EMAIL}",
            json={"password": "ci-temp-password-9f2a", "full_name": "CI Before"},
            headers=api_headers, timeout=request_timeout, verify=verify_ssl,
        )
        assert created.status_code == 200, created.text

        edited = requests.put(
            f"{base_url}/server/users/{CI_EMAIL}",
            json={"full_name": "CI After", "provider_type": "dmacp"},
            headers=api_headers, timeout=request_timeout, verify=verify_ssl,
        )
        assert edited.status_code == 200, edited.text
        platform = edited.json()["platform"]
        assert platform["full_name"] == "CI After"
        assert platform["provider_type"] == "dmacp"
    finally:
        _delete(base_url, api_headers, verify_ssl, request_timeout, CI_EMAIL)


def test_edit_of_an_absent_user_still_needs_a_password(base_url, api_headers,
                                                       verify_ssl, request_timeout):
    """No password is fine for an edit, but a create has nothing to set."""
    response = requests.put(
        f"{base_url}/server/users/{ABSENT_EMAIL}",
        json={"full_name": "Nobody"},
        headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "invalid_payload"
    assert "password" in body["detail"]


def test_edit_with_an_empty_body_is_rejected(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.put(
        f"{base_url}/server/users/{CI_EMAIL}",
        json={}, headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "invalid_payload"


def test_get_with_grafana_flag_is_rejected(base_url, api_headers, verify_ssl, request_timeout):
    """`curl <url>?grafana=true` without -X PUT must not look like a successful reset."""
    response = requests.get(
        f"{base_url}/server/users/{CI_EMAIL}?grafana=true",
        headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )
    assert response.status_code == 405, response.text
    assert "PUT" in (response.headers.get("Allow") or "")
    body = response.json()
    assert body["error"] == "method_not_allowed"
    assert "PUT" in body["detail"]


def test_get_carrying_a_password_is_rejected(base_url, api_headers, verify_ssl, request_timeout):
    """Same mistake, spelled with a body instead of the query flag."""
    response = requests.get(
        f"{base_url}/server/users/{CI_EMAIL}",
        json={"password": "not-applied-by-a-GET"},
        headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )
    assert response.status_code == 405, response.text
    assert response.json()["error"] == "method_not_allowed"


def test_plain_get_still_reads_status(base_url, api_headers, verify_ssl, request_timeout):
    """The read-only status check is unchanged: 200 + exists:false when absent."""
    response = requests.get(
        f"{base_url}/server/users/{ABSENT_EMAIL}",
        headers=api_headers, timeout=request_timeout, verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["exists"] is False
