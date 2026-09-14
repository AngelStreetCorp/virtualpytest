"""
Tests for server_heatmap_routes.py (/server/heatmap/*)

Covers the two endpoints on this blueprint:
- GET  /server/heatmap/history       — list recent heatmap reports for a team
- POST /server/heatmap/generateReport — generate + upload an HTML heatmap report

generateReport's happy path uploads a real HTML file to Cloudflare R2 and
writes a row to the database, so only its validation-failure paths (which
return before any upload/DB write) are exercised here.
"""
import requests


def test_history_requires_team_id(get, api_headers):
    response = get("/server/heatmap/history", headers=api_headers)
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "team_id" in body.get("error", "")


def test_history_returns_reports_for_team(get, api_headers, team_id):
    response = get(
        "/server/heatmap/history",
        headers=api_headers,
        params={"team_id": team_id, "limit": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("reports"), list)
    assert body.get("count") == len(body.get("reports"))


def test_generate_report_requires_body(base_url, verify_ssl, request_timeout, api_headers):
    response = requests.post(
        f"{base_url}/server/heatmap/generateReport",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "Request body is required" in body.get("error", "")


def test_generate_report_requires_required_fields(base_url, verify_ssl, request_timeout, api_headers):
    """time_key, mosaic_url and analysis_data are all required together."""
    response = requests.post(
        f"{base_url}/server/heatmap/generateReport",
        json={"time_key": "1407"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "time_key, mosaic_url, and analysis_data are required" in body.get("error", "")
