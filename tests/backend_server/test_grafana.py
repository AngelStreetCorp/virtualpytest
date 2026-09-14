"""
Tests for server_grafana_routes.py (/server/integrations/grafana/*)

The only /integrations route in the design — a thin HTTP wrapper over
shared.src.lib.utils.grafana_admin for Grafana user provisioning.

None of these endpoints require auth (no @require_user_auth /
@require_api_key decorator on the blueprint), so every test here exercises
the routes anonymously, matching the actual route source.

We only exercise validation failure paths that return before any real
Grafana admin API call is made, to avoid creating/mutating real Grafana
accounts against a live server. The delete test uses a placeholder email
that should never correspond to a real account, so a live no-op delete
attempt is harmless either way.
"""
import requests

PLACEHOLDER_EMAIL = "virtualpytest-ci-placeholder@example.invalid"


def test_upsert_user_requires_email(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/integrations/grafana/users",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("status") == "error"
    assert body.get("error") == "invalid_payload"


def test_upsert_user_requires_non_blank_email(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/integrations/grafana/users",
        json={"email": "   "},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("status") == "error"
    assert body.get("error") == "invalid_payload"


def test_set_org_role_requires_org_role(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.patch(
        f"{base_url}/server/integrations/grafana/users/{PLACEHOLDER_EMAIL}/org-role",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("status") == "error"
    assert body.get("error") == "invalid_payload"


def test_delete_user_route_responds(base_url, verify_ssl, request_timeout, api_headers):
    """Deleting a placeholder/nonexistent user exercises the route without
    touching real Grafana accounts. The route either treats the delete as a
    graceful no-op (200) or reports the Grafana admin API as unavailable
    (502) — both are valid outcomes traceable to the route's try/except."""
    response = requests.delete(
        f"{base_url}/server/integrations/grafana/users/{PLACEHOLDER_EMAIL}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (200, 502)
    body = response.json()
    assert body.get("status") in ("ok", "error")
