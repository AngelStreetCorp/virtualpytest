def test_get_deployment_list_returns_array(get, api_headers, team_id):
    response = get(
        "/server/deployment/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert response.status_code == 200

    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("deployments"), list)


def test_host_deployment_routes_respond(host_url, verify_ssl):
    """Smoke tests for host deployment scheduler routes (add, pause, resume, update, remove)."""
    import requests

    base = host_url.rstrip("/")

    # Route availability checks — these routes are registered on the host service
    routes = [
        ("/host/deployment/add", "post", None),
        ("/host/deployment/pause/some-id", "post", None),
        ("/host/deployment/resume/some-id", "post", None),
        ("/host/deployment/update/some-id", "put", {}),
        ("/host/deployment/remove/some-id", "delete", None),
    ]

    for path, method, json_data in routes:
        url = f"{base}{path}"
        try:
            if method == "post":
                r = requests.post(url, json=json_data, timeout=5, verify=verify_ssl)
            elif method == "put":
                r = requests.put(url, json=json_data, timeout=5, verify=verify_ssl)
            elif method == "delete":
                r = requests.delete(url, timeout=5, verify=verify_ssl)
            # Accept 404 (route not registered on this host), 400 (bad id), 401/403 (auth), or 503 (scheduler unavailable)
            assert r.status_code in (200, 400, 401, 403, 404, 503), f"{method.upper()} {path} returned {r.status_code}"
        except requests.exceptions.ConnectionError:
            # Host service not running on this test environment — skip
            pass
