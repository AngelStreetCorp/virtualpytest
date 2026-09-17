"""
Server API Testing Routes Tests

server_api_testing_routes.py (blueprint url_prefix /server/api-testing) is an
internal API test-runner: it can auto-discover the Flask route table, execute
a battery of HTTP calls against other server endpoints, and render an HTML
report. It sits under /server/*, so the global frontend JWT auth guard in
app.py applies to it when enabled.

  GET  /server/api-testing/config           -> auto-discovers routes + the
                                                static CRITICAL_ROUTES list;
                                                pure read (introspects
                                                current_app.url_map only)
  GET  /server/api-testing/report/<id>/html -> renders a static sample HTML
                                                report with empty results;
                                                pure computation
  GET  /server/api-testing/categories       -> groups TEST_CONFIG endpoints by
                                                category
  POST /server/api-testing/run              -> actually executes selected API
                                                tests against other live
                                                endpoints
  POST /server/api-testing/quick            -> actually executes the
                                                'critical' category endpoints
                                                (navigation, script execution,
                                                etc.) against other live
                                                endpoints

/run and /quick are genuine test-runner endpoints that fire real HTTP requests
at other server routes as a side effect of being called — exactly the kind of
endpoint this suite is told to skip rather than execute against a live
server.

Note: /categories (and /run, /quick) reference a module-level `TEST_CONFIG`
name that is never assigned anywhere in server_api_testing_routes.py (only
`CRITICAL_ROUTES` and `DEFAULT_VALUES` are module-level; `auto_discover_routes`
builds its own local dict and is never stored as `TEST_CONFIG`). Calling
/categories today raises a NameError inside its own try/except and returns a
500 with success=False; the test below documents that observed contract
instead of assuming a future fix.
"""


def test_get_test_config_auto_discovers_routes(get, api_headers):
    response = get("/server/api-testing/config", headers=api_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body.get("success") is True
    config = body.get("config")
    assert isinstance(config, dict)
    assert isinstance(config.get("endpoints"), list)
    assert isinstance(body.get("total_endpoints"), int)
    stats = body.get("stats")
    assert isinstance(stats, dict)
    assert "auto_discovered" in stats
    assert "critical_routes" in stats


def test_get_html_report_renders_sample_report(get, api_headers):
    response = get("/server/api-testing/report/test-report-id/html", headers=api_headers)
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers.get("Content-Type", "")
    assert "API Test Report" in response.text


def test_get_categories_groups_static_routes(get, api_headers):
    """Groups the static TEST_CONFIG routes by category. Until 2026-09-08 TEST_CONFIG
    was never defined, so this route (and /run, /quick) died with NameError -> 500
    (BUG-0066); the old test pinned that 500 as the "current contract"."""
    response = get("/server/api-testing/categories", headers=api_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    categories = body.get("categories")
    assert isinstance(categories, dict) and categories
    assert "critical" in categories
    assert isinstance(body.get("total_endpoints"), int)


