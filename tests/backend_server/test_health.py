import pytest
import requests


def test_server_health(get):
    response = get("/server/health")
    assert response.status_code == 200

    body = response.json()
    assert body.get("status") in {"ok", "healthy"}


def test_system_health(get, api_headers, system_health_reachable):
    """Test system health endpoint.

    This test may be skipped if the remote host (e.g. <origin-ip>) is unreachable,
    as the endpoint makes internal calls that may time out.
    """
    if not system_health_reachable:
        pytest.skip("System health endpoint not reachable (remote host unavailable)")

    try:
        response = get("/server/system/health", headers=api_headers)
    except requests.exceptions.ReadTimeout:
        pytest.skip("System health endpoint timed out (remote host slow/unreachable)")

    assert response.status_code == 200

    body = response.json()
    assert body.get("status") == "healthy"


def test_system_hosts_with_stats(get, api_headers, team_id, system_health_reachable):
    """Test getAllHosts endpoint with system stats.

    This test may be skipped if the remote host (e.g. <origin-ip>) is unreachable,
    as the endpoint makes internal calls that may time out.
    """
    if not system_health_reachable:
        pytest.skip("System health endpoint not reachable (remote host unavailable)")

    try:
        response = get(
            "/server/system/getAllHosts",
            headers=api_headers,
            params={"team_id": team_id, "include_system_stats": "true"},
        )
    except requests.exceptions.ReadTimeout:
        pytest.skip("System health endpoint timed out (remote host slow/unreachable)")

    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("hosts"), list)
    assert isinstance(body.get("server_info"), dict)
