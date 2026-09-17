"""
Server Frontend Routes Tests

server_frontend_routes.py's blueprint is mounted at /server/frontend (app.py), so both
routes are proxied to the backend and covered by the global JWT auth guard, which gates
every path starting with '/server/'.

  POST /server/frontend/navigate -> pure computation: validates `page` against a fixed
                     allow-list and returns a redirect_url string. It never performs any
                     real navigation server-side, so the happy path is safe to call
                     directly. AUTHENTICATED: it drives the UI, so it stays behind the
                     guard and the tests below present api_headers.
  GET  /server/frontend/health   -> static health payload for this blueprint.
                     UNAUTHENTICATED by design: app.py exempts the exact path
                     '/server/frontend/health', alongside /server/health,
                     /server/action/health and /server/storage/health. The exact path and
                     not the '/server/frontend' prefix — the guard matches
                     `path == prefix or path.startswith(prefix + '/')`, so a prefix
                     exemption would open /navigate too. test_frontend_health_check
                     deliberately sends no headers, which is what keeps that exemption
                     honest: if the path ever falls back under the guard, it goes red.

Note: `data = request.get_json()` with no fallback means an empty JSON object
{} is falsy, so a body of `{}` (not just a missing body) is what triggers the
"No JSON data provided" branch — the tests below use `json={}` to hit it
deterministically without relying on a bodiless POST hitting Flask's own
content-type parsing.

These ran nowhere until 2026-09-16, for two separate nginx reasons
(infra/proxy/nginx/config/production-https.conf). The blueprint was registered with no
url_prefix, so its routes sat at the server root:
- POST /navigate had no location block at all, so it fell through to the
  `location /` catch-all and got the frontend SPA's index.html (200, HTML).
- GET /health WAS matched — by nginx's OWN `location /health` block
  (`return 200 "healthy\n"`), a plain-text self-check nginx answers itself and
  never proxies, so this blueprint's `{"service": "frontend_routes"}` handler
  was unreachable even in principle.
Mounting the blueprint at /server/frontend fixes both: /server/* is proxied to
the backend and collides with no nginx block.
"""


def test_navigate_rejects_empty_json_body(base_url, api_headers, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/server/frontend/navigate",
        headers=api_headers,
        json={},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "No JSON data provided"


def test_navigate_requires_page_field(base_url, api_headers, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/server/frontend/navigate",
        headers=api_headers,
        json={"not_page": "x"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "Page parameter is required"


def test_navigate_rejects_invalid_page(base_url, api_headers, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/server/frontend/navigate",
        headers=api_headers,
        json={"page": "not_a_real_page"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("success") is False
    assert "Invalid page" in body.get("error", "")


def test_navigate_to_valid_page(base_url, api_headers, verify_ssl, request_timeout):
    import requests

    response = requests.post(
        f"{base_url}/server/frontend/navigate",
        headers=api_headers,
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
    # No headers on purpose. /server/frontend/health is in app.py's unauthenticated_prefixes,
    # the same as every other liveness probe, so a monitor can reach it without a JWT. Sending
    # api_headers here would still pass and would stop proving the exemption exists.
    response = get("/server/frontend/health")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    assert body.get("service") == "frontend_routes"
