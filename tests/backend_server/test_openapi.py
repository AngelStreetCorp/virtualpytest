"""
OpenAPI Documentation Routes Tests

server_openapi_routes.py is mounted at /server/docs/api (app.py) and serves pre-generated
OpenAPI/Swagger HTML from disk via flask.send_from_directory. Being under /server/* it is
covered by the global JWT auth guard, so these tests present api_headers.

  GET /server/docs/api/docs/<filename> -> serve_openapi_docs: 404 when the file
                                    doesn't exist on disk
  GET /server/docs/api/docs/ or /server/docs/api/docs -> serve_index: serves index.html,
                                            or 404 if the docs were never generated on
                                            this deployment

Authenticated rather than exempt, deliberately: this blueprint has no browser consumer.
The Swagger UI the app links to is the FRONTEND's own static build —
frontend/src/pages/ApiDocumentation.tsx builds a relative `/docs/api/interactive.html`,
served from frontend/public/docs by the frontend VM, which never reaches backend_server.
Exempting this blueprint would open a surface nothing calls. "A missing doc file is a
404" is just as true for an authenticated caller, and that is the assertion worth keeping.

Whether the docs bundle (built by scripts/export_openapi_specs.py) exists
varies by deployment, so the index tests accept either outcome rather than
assuming one. Note: modern Flask/Werkzeug raise werkzeug.exceptions.NotFound
(not the FileNotFoundError the route explicitly catches) when the file is
missing, so a missing file falls through to Flask's default 404 handler
rather than the route's custom JSON error body — these tests only assert on
the status code, which is correct either way.

This ran nowhere until 2026-09-16. The blueprint used to be mounted at
/docs/api, which nginx does not proxy — so requests fell through to the
`location /` catch-all and got the SPA's index.html (200) instead of a 404
from backend_server. Worse, /docs/api is the *frontend's* own published docs
site (frontend/public/docs/api, Swagger UI at /docs/api/interactive.html), so
the backend blueprint was shadowed by a real page rather than merely unrouted.
Mounting it at /server/docs/api removes the collision and puts it behind the
same proxy and guard as every other backend route.
"""

def test_serve_openapi_docs_missing_file_returns_404(get, api_headers):
    response = get("/server/docs/api/docs/__definitely_not_a_real_doc_file__.html", headers=api_headers)
    assert response.status_code == 404


def test_serve_index_trailing_slash(get, api_headers):
    response = get("/server/docs/api/docs/", headers=api_headers)
    assert response.status_code in (200, 404), response.text
    if response.status_code == 200:
        assert "text/html" in response.headers.get("Content-Type", "")


def test_serve_index_no_trailing_slash(get, api_headers):
    response = get("/server/docs/api/docs", headers=api_headers)
    assert response.status_code in (200, 404), response.text
    if response.status_code == 200:
        assert "text/html" in response.headers.get("Content-Type", "")
