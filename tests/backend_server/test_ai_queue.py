"""
Server AI Queue Routes Tests

Covers backend_server/src/routes/server_ai_queue_routes.py (blueprint:
/server/ai-queue).
"""

import requests


def test_ai_queue_status(base_url, request_timeout, verify_ssl, api_headers):
    """GET /status is read-only (queue length introspection via Redis + a 24h
    Supabase summary query) - safe to call for real regardless of whether
    Redis is reachable from the deployed server."""
    response = requests.get(
        f"{base_url}/server/ai-queue/status",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (200, 500)

    body = response.json()
    assert "status" in body

    if response.status_code == 200:
        assert body.get("status") == "healthy"
        assert isinstance(body.get("queues"), dict)
        assert "incidents" in body["queues"]
        assert "scripts" in body["queues"]
        for queue in body["queues"].values():
            assert isinstance(queue.get("length"), int)
    else:
        assert body.get("status") == "error"


def test_ai_queue_status_with_items(base_url, request_timeout, verify_ssl, api_headers):
    """include_items=true additionally peeks (non-destructively) at queue
    contents - still read-only."""
    response = requests.get(
        f"{base_url}/server/ai-queue/status",
        params={"include_items": "true"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code in (200, 500)
    body = response.json()
    assert "status" in body
    if response.status_code == 200:
        assert isinstance(body["queues"]["incidents"].get("items"), list)
        assert isinstance(body["queues"]["scripts"].get("items"), list)

