"""
Device Flags Route Tests

server_device_flags_routes.py (blueprint url_prefix /server/device-flags) is a
thin CRUD layer over the `device_flags` Supabase table used for
device clustering/tagging. Endpoints:

  GET  /server/device-flags/                -> {success, data: [device_flags rows]}
  GET  /server/device-flags/batch           -> {success, data: {device_flags: [...], unique_flags: [...]}}
  GET  /server/device-flags/flags           -> {success, data: [unique flag strings]}
  PUT  /server/device-flags/<host>/<device> -> {success, data: updated row} or 404/400

All three GET endpoints are pure reads and safe to call live. The PUT
endpoint is exercised only for its validation/not-found paths so the test
never mutates a real device's flags.
"""


def test_get_all_device_flags(get, api_headers):
    response = get("/server/device-flags/", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("data"), list)


def test_get_batch_device_flags(get, api_headers):
    response = get("/server/device-flags/batch", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    data = body.get("data")
    assert isinstance(data, dict)
    assert isinstance(data.get("device_flags"), list)
    assert isinstance(data.get("unique_flags"), list)


def test_get_unique_flags(get, api_headers):
    response = get("/server/device-flags/flags", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("data"), list)


def test_update_device_flags_rejects_non_array_flags(base_url, api_headers, verify_ssl, request_timeout):
    """Route validates `flags` is a list before touching the database."""
    import requests

    response = requests.put(
        f"{base_url}/server/device-flags/__nonexistent_host__/__nonexistent_device__",
        json={"flags": "not-a-list"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "flags must be an array" in body.get("error", "")


def test_update_device_flags_not_found(base_url, api_headers, verify_ssl, request_timeout):
    """Updating flags for a host/device pair that doesn't exist returns 404."""
    import requests

    response = requests.put(
        f"{base_url}/server/device-flags/__nonexistent_host_for_tests__/__nonexistent_device_for_tests__",
        json={"flags": ["smoke_test_flag"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("error") == "Device not found"
