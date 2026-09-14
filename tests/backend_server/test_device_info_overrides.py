"""
Device Info Overrides Route Tests

server_device_info_overrides_routes.py (blueprint url_prefix
/server/device-info-overrides) lets an operator correct OCR-extracted device
info per device/key, non-destructively (raw OCR is never mutated).

Endpoints:
  GET    /server/device-info-overrides/keys   -> per-key correction status (list)
  PUT    /server/device-info-overrides        -> upsert an override (requires
         device_name, host_name, info_key, corrected_value)
  DELETE /server/device-info-overrides        -> remove an override (requires
         device_name, host_name, info_key)

All three endpoints are wrapped in require_user_auth_if_enabled, which is a
pass-through in open mode (no SUPABASE_JWT_SECRET) and JWT-gated otherwise;
tests here use api_headers as-is, matching the other read-only route tests
in this suite, and don't assert a specific auth behavior.

The GET /keys endpoint is a pure read and safe to call live. PUT/DELETE are
only exercised for their pre-database validation (missing required fields),
so no real device's override data is touched.
"""

import requests


def test_get_keys_returns_list(get, api_headers, team_id):
    response = get(
        "/server/device-info-overrides/keys",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_upsert_override_requires_fields(base_url, api_headers, verify_ssl, request_timeout):
    """Missing required fields (device_name, host_name, info_key, corrected_value) -> 400."""
    response = requests.put(
        f"{base_url}/server/device-info-overrides",
        json={"device_name": "some_device"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "Missing required fields" in body.get("error", "")


def test_delete_override_requires_fields(base_url, api_headers, verify_ssl, request_timeout):
    """Missing required fields (device_name, host_name, info_key) -> 400."""
    response = requests.delete(
        f"{base_url}/server/device-info-overrides",
        json={"device_name": "some_device"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "Missing required fields" in body.get("error", "")


def test_delete_override_not_found(base_url, api_headers, verify_ssl, request_timeout):
    """A well-formed delete for an override that doesn't exist returns 404."""
    response = requests.delete(
        f"{base_url}/server/device-info-overrides",
        json={
            "device_name": "__nonexistent_device_for_tests__",
            "host_name": "__nonexistent_host_for_tests__",
            "info_key": "__nonexistent_key_for_tests__",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("error") == "Override not found"
