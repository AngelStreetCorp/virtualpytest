"""
Tests for backend_server/src/routes/server_verification_routes.py

Covers the server-logic verification endpoints (reference proxy routes were
moved to auto_proxy.py and are out of scope here). All endpoints are pure
DB/config reads or input-validation paths — no device/host hardware is
involved, so every test here runs live.
"""

import requests


def test_health_check(get, api_headers):
    response = get("/server/verification/health", headers=api_headers)
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True


def test_get_verifications_returns_list(get, api_headers, team_id):
    response = get(
        "/server/verification/getVerifications",
        headers=api_headers,
        params={"device_model": "android_mobile", "team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("verifications"), list)


def test_get_all_references_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/verification/getAllReferences",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False


def test_get_all_references_returns_list(base_url, api_headers, team_id, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/verification/getAllReferences",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("references"), list)


def test_get_reference_versions_requires_reference_id(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """team_id and reference_id are both required — omitting reference_id must 400
    before any DB lookup runs."""
    response = requests.post(
        f"{base_url}/server/verification/getReferenceVersions",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False


def test_get_reference_versions_requires_team_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/verification/getReferenceVersions",
        json={"reference_id": "00000000-0000-0000-0000-000000000000"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False


def test_restore_reference_version_requires_fields(base_url, api_headers, team_id, verify_ssl, request_timeout):
    """restoreReferenceVersion mutates data (snapshots + restores a reference), so
    only the validation-failure path is exercised here — a real reference_id/
    version_id pair is required for the success path and none is safe to invent."""
    response = requests.post(
        f"{base_url}/server/verification/restoreReferenceVersion",
        params={"team_id": team_id},
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400

    body = response.json()
    assert body.get("success") is False
