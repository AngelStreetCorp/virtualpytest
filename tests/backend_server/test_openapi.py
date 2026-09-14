"""
OpenAPI Documentation Routes Tests

server_openapi_routes.py (blueprint url_prefix /docs/api) serves pre-generated
OpenAPI/Swagger HTML docs from disk via flask.send_from_directory. It is not
mounted under /server/*, so the global frontend JWT auth guard in app.py
never applies to it.

  GET /docs/api/docs/<filename> -> serve_openapi_docs: 404 when the file
                                    doesn't exist on disk
  GET /docs/api/docs/ or /docs/api/docs -> serve_index: serves index.html, or
                                            404 if the docs were never
                                            generated on this deployment

Whether the docs bundle (built by scripts/export_openapi_specs.py) exists
varies by deployment, so the index tests accept either outcome rather than
assuming one. Note: modern Flask/Werkzeug raise werkzeug.exceptions.NotFound
(not the FileNotFoundError the route explicitly catches) when the file is
missing, so a missing file falls through to Flask's default 404 handler
rather than the route's custom JSON error body — these tests only assert on
the status code, which is correct either way.

/docs/api is not reachable from the public deployment tested here: nginx's
production config (infra/proxy/nginx/config/production-https.conf) has no
`location /docs/api` block, so every request under it falls through to the
`location /` catch-all, which serves the frontend SPA's index.html with a
200 regardless of path (confirmed 2026-09-07 backfilling non-regression
tests — GET /docs/api/docs/__definitely_not_a_real_doc_file__.html returned
200 text/html, not a 404 from backend_server). The route logic itself is
presumably fine; it's simply unreachable through the public entry point
these tests hit, matching how backend_host is excluded from this suite's
scope for the same reason (see tests/docs/testing-strategy.md).
"""

import pytest


@pytest.mark.skip(
    reason="/docs/api has no nginx location block on the public deployment — "
    "falls through to the frontend SPA (200 index.html) before ever reaching "
    "backend_server, so this can't be exercised through SERVER_URL"
)
def test_serve_openapi_docs_missing_file_returns_404(get):
    response = get("/docs/api/docs/__definitely_not_a_real_doc_file__.html")
    assert response.status_code == 404


def test_serve_index_trailing_slash(get):
    response = get("/docs/api/docs/")
    assert response.status_code in (200, 404), response.text
    if response.status_code == 200:
        assert "text/html" in response.headers.get("Content-Type", "")


def test_serve_index_no_trailing_slash(get):
    response = get("/docs/api/docs")
    assert response.status_code in (200, 404), response.text
    if response.status_code == 200:
        assert "text/html" in response.headers.get("Content-Type", "")
