"""
Event System REST API Routes Tests

event_routes.py (blueprint url_prefix /server/events) provides manual event
publishing plus read-only event type/stat listings. It sits under /server/*
like every other backend blueprint, so nginx proxies it and app.py's frontend
JWT auth guard applies to it.

  POST /server/events/publish               -> validate then publish an
                                                arbitrary event
  GET  /server/events/types                 -> list distinct event types seen
                                                (Supabase read via events_db)
  GET  /server/events/stats                 -> event routing stats for the last
                                                24h (Supabase read via events_db)
  POST /server/events/alerts/blackscreen    -> validate then publish a
                                                blackscreen alert event
  POST /server/events/alerts/device-offline -> validate then publish a
                                                device-offline alert event
  POST /server/events/builds/deployed       -> validate then publish a
                                                build-deployed event

Every POST handler validates its required fields *before* constructing and
routing an Event, so the validation-failure paths below were designed to be
exercised with real requests with no event ever published as a result.
Actually publishing an event dispatches it through the live event bus/router
(Redis pub/sub + Supabase event_log), which other running services may act
on — e.g. a real 'alert.blackscreen' event could reach whatever alerting is
wired to it — so that side effect is skipped rather than exercised here.

These ran nowhere until 2026-09-16. The blueprint used to be mounted at
/api/events, and nginx (infra/proxy/nginx/config/production-https.conf) has no
`/api/` location block at all, so every request under it fell through to the
`location /` catch-all and got the frontend SPA's index.html — 200, HTML,
whatever the path or method. The whole events API was dead on the public
deployment and an alert POST read that 200 as success. Rather than keep the
tests deselected, the routes moved under /server/*, where they are both
proxied and auth-guarded.
"""

import requests


def test_publish_event_requires_type_and_payload(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/events/publish",
        json={"type": "test.event"},  # payload missing
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "type and payload required"


def test_list_event_types(get, api_headers):
    response = get("/server/events/types", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    event_types = body.get("event_types")
    assert isinstance(event_types, list)
    assert body.get("count") == len(event_types)


def test_get_event_stats(get, api_headers):
    response = get("/server/events/stats", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    for key in (
        "total_events",
        "processed_events",
        "unprocessed_events",
        "unique_event_types",
        "avg_processing_time_seconds",
    ):
        assert key in body, f"missing '{key}' in {body}"


def test_emit_blackscreen_alert_requires_device_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/events/alerts/blackscreen",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "device_id required"


def test_emit_device_offline_alert_requires_device_id(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/events/alerts/device-offline",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "device_id required"


def test_emit_build_deployed_requires_version_and_userinterface(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/events/builds/deployed",
        json={"version": "1.0.0"},  # userinterface missing
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "version and userinterface required"

