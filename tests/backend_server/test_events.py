"""
Event System REST API Routes Tests

event_routes.py (blueprint url_prefix /api/events) provides manual event
publishing plus read-only event type/stat listings. The blueprint prefix is
/api/events, not /server/*, so the global frontend JWT auth guard in app.py
never applies to it.

  POST /api/events/publish               -> validate then publish an arbitrary
                                             event
  GET  /api/events/types                 -> list distinct event types seen
                                             (Supabase read via events_db)
  GET  /api/events/stats                 -> event routing stats for the last
                                             24h (Supabase read via events_db)
  POST /api/events/alerts/blackscreen    -> validate then publish a
                                             blackscreen alert event
  POST /api/events/alerts/device-offline -> validate then publish a
                                             device-offline alert event
  POST /api/events/builds/deployed       -> validate then publish a
                                             build-deployed event

Every POST handler validates its required fields *before* constructing and
routing an Event, so the validation-failure paths below were designed to be
exercised with real requests with no event ever published as a result.
Actually publishing an event dispatches it through the live event bus/router
(Redis pub/sub + Supabase event_log), which other running services may act
on — e.g. a real 'alert.blackscreen' event could reach whatever alerting is
wired to it — so that side effect is skipped rather than exercised here.

UNREACHABLE from the public deployment tested here: nginx's production
config (infra/proxy/nginx/config/production-https.conf) has no
`location /api/events` (or any `/api/` block at all), so every request under
this prefix falls through to the `location /` catch-all, which serves the
frontend SPA's index.html with a 200/HTML body regardless of path or method
— it never reaches backend_server (confirmed 2026-09-07 backfilling
non-regression tests: POST /api/events/publish returned HTML, not JSON).
All tests below are skipped for that reason; the route logic itself is
presumably fine, matching how backend_host is excluded from this suite's
scope for the same "not exposed" reason (see tests/docs/testing-strategy.md).
"""

import requests
import pytest

pytestmark = pytest.mark.skip(
    reason="/api/events has no nginx location block on the public deployment — "
    "falls through to the frontend SPA (200 HTML) before ever reaching "
    "backend_server, so this can't be exercised through SERVER_URL"
)


def test_publish_event_requires_type_and_payload(base_url, api_headers, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/api/events/publish",
        json={"type": "test.event"},  # payload missing
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "type and payload required"


def test_list_event_types(get, api_headers):
    response = get("/api/events/types", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    event_types = body.get("event_types")
    assert isinstance(event_types, list)
    assert body.get("count") == len(event_types)


def test_get_event_stats(get, api_headers):
    response = get("/api/events/stats", headers=api_headers)
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
        f"{base_url}/api/events/alerts/blackscreen",
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
        f"{base_url}/api/events/alerts/device-offline",
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
        f"{base_url}/api/events/builds/deployed",
        json={"version": "1.0.0"},  # userinterface missing
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("error") == "version and userinterface required"


@pytest.mark.skip(
    reason="Successfully publishing an event (POST /api/events/publish or the "
    "alerts/builds shortcuts) dispatches it through the live event bus/router, "
    "which other running services may act on (e.g. real alerting) — not safe "
    "to exercise from this non-regression suite."
)
def test_publish_event_success_not_exercised():
    pass
