"""
Server Frontend Routes Tests

server_frontend_routes.py's blueprint (`server_frontend_bp = Blueprint(
'server_frontend', __name__)`) is created and registered with NO url_prefix
(confirmed in backend_server/src/app.py, `app.register_blueprint(blueprint)`
with no extra `url_prefix` argument), so its two routes live at the server
root, not under /server/*: they are unaffected by the global frontend JWT
auth guard, which only gates paths starting with '/server/'.

  POST /navigate -> pure computation: validates `page` against a fixed
                     allow-list and returns a redirect_url string. It never
                     performs any real navigation server-side, so the happy
                     path is safe to call directly.
  GET  /health    -> static health payload for this blueprint

Note: `data = request.get_json()` with no fallback means an empty JSON object
{} is falsy, so a body of `{}` (not just a missing body) is what triggers the
"No JSON data provided" branch — the tests below use `json={}` to hit it
deterministically without relying on a bodiless POST hitting Flask's own
content-type parsing.

UNREACHABLE from the public deployment tested here, for two different nginx
reasons (infra/proxy/nginx/config/production-https.conf), confirmed
2026-09-07 backfilling non-regression tests:
- POST /navigate has no location block at all, so it falls through to the
  `location /` catch-all, which serves the frontend SPA's index.html (200,
  HTML) regardless of path — it never reaches backend_server.
- GET /health IS matched, but by nginx's OWN `location /health` block
  (`return 200 "healthy\n"`) — a plain-text self-check nginx answers
  directly, never proxied to this blueprint's actual `{"service":
  "frontend_routes"}` handler.
All 5 tests below are skipped for that reason; the route logic itself is
presumably fine, matching how backend_host is excluded from this suite's
scope for the same "not exposed" reason (see tests/docs/testing-strategy.md).
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="server_frontend_routes.py's bare-root paths aren't reachable on the "
    "public deployment: /navigate has no nginx location block (falls through to "
    "the frontend SPA) and /health is intercepted by nginx's own healthcheck "
    "block before ever reaching backend_server"
)


def test_navigate_rejects_empty_json_body(base_url, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/navigate",
        json={},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "No JSON data provided"


def test_navigate_requires_page_field(base_url, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/navigate",
        json={"not_page": "x"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "Page parameter is required"


def test_navigate_rejects_invalid_page(base_url, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/navigate",
        json={"page": "not_a_real_page"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert "Invalid page" in body.get("error", "")


def test_navigate_to_valid_page(base_url, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/navigate",
        json={"page": "dashboard"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    assert body.get("page") == "dashboard"
    assert body.get("redirect_url") == "/dashboard"


def test_frontend_health_check(get):
    response = get("/health")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    assert body.get("service") == "frontend_routes"
