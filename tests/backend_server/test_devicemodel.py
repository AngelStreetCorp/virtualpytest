"""
Device Model Route Tests

server_devicemodel_routes.py (blueprint url_prefix /server/devicemodel)
manages device model CRUD, with a 24h in-memory cache on the list endpoint.

Endpoints:
  GET    /server/devicemodel/getAllModels             -> bare JSON list
  GET    /server/devicemodel/getDeviceModel/<id>       -> model dict or 404
  POST   /server/devicemodel/createDeviceModel         -> requires name + types
  PUT    /server/devicemodel/updateDeviceModel/<id>    -> requires name + types
  DELETE /server/devicemodel/deleteDeviceModel/<id>    -> 200 or 404 (403 if default model)

getAllModels and getDeviceModel are pure reads and safe to call live
(get_device_model() swallows Supabase "no rows" errors internally and
returns None, so a bogus id cleanly yields 404 rather than a 500). The
create/update/delete endpoints are only exercised for their pre-database
validation and not-found paths, so no real device model is created,
modified, or removed.
"""

import requests

_FAKE_ID = "00000000-0000-0000-0000-000000000000"


def test_get_all_models_returns_list(get, api_headers, team_id):
    response = get(
        "/server/devicemodel/getAllModels",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_get_device_model_not_found(get, api_headers, team_id):
    response = get(
        f"/server/devicemodel/getDeviceModel/{_FAKE_ID}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("error") == "Device model not found"


def test_create_device_model_requires_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/devicemodel/createDeviceModel",
        params={"team_id": team_id},
        json={"types": ["mobile"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "Name is required"


def test_create_device_model_requires_types(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/devicemodel/createDeviceModel",
        params={"team_id": team_id},
        json={"name": "__smoke_test_model__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "At least one type must be selected"


def test_update_device_model_requires_name(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.put(
        f"{base_url}/server/devicemodel/updateDeviceModel/{_FAKE_ID}",
        params={"team_id": team_id},
        json={"types": ["mobile"]},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "Name is required"


def test_delete_device_model_not_found(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.delete(
        f"{base_url}/server/devicemodel/deleteDeviceModel/{_FAKE_ID}",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("error") == "Device model not found or failed to delete"
