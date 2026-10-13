"""Dashboard parity: Atlas semantic queries versus the maintained Grafana panels.

Offline tests check the committed capture (``fixtures/atlas_parity.json``) and guard
against drift on either side.  ``test_live_parity`` re-runs every case read-only when
``ATLAS_PARITY_DSN`` and ``ATLAS_PARITY_TEAM`` are set.  Re-capture after an intended
change with ``python3 -m tests.backend_server.atlas_parity_support --capture``.
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import ANALYTICS_SOURCES, AnalyticsContext, AnalyticsService  # noqa: E402
from tests.backend_server import atlas_parity_support as parity  # noqa: E402

FIXTURE = json.loads(parity.FIXTURE.read_text(encoding="utf-8"))
ADMIN = AnalyticsContext(team_id="00000000-0000-0000-0000-000000000123", user_role="admin")


def test_parity_covers_every_metric_family():
    families = {source.family for source in ANALYTICS_SOURCES.values() if not source.live}
    captured = {case["family"] for case in FIXTURE["cases"].values()}
    assert families <= captured
    assert {case["id"] for case in parity.CASES} == set(FIXTURE["cases"])


def test_captured_cases_are_at_parity():
    for case_id, case in FIXTURE["cases"].items():
        assert case["mismatches"] == [], case_id
        compared = [row for row in case["rows"] if row.get("dashboard") is not None and row.get("atlas") is not None]
        assert compared, f"{case_id} compared no rows"
        for tolerated in case.get("tolerated", []):
            assert case.get("known_divergence"), f"{case_id} tolerates a difference without explaining it"
            assert tolerated.endswith("only in atlas")


def test_fixture_is_pseudonymised():
    for case in FIXTURE["cases"].values():
        for row in case["rows"]:
            assert row["key"].startswith("k") and row["key"][1:].isdigit()


def test_maintained_panels_still_exist():
    for case in parity.CASES:
        dashboard = json.loads((parity.DASHBOARDS / case["dashboard"]).read_text(encoding="utf-8"))
        panel = parity.find_panel(dashboard, case["panel"])
        assert panel["targets"][0]["rawSql"].strip(), case["id"]


def test_atlas_sql_unchanged_since_capture():
    service = AnalyticsService(dsn="unused")
    for case in parity.CASES:
        digest = parity.atlas_sql_digest(service, ADMIN, case)
        assert digest == FIXTURE["cases"][case["id"]]["atlas_sql_sha256"], (
            f"{case['id']}: Atlas SQL changed; re-run the parity capture against the database")


class _Cursor:
    def __init__(self, rows):
        self.rows, self.executed, self.description = rows, [], None

    def execute(self, sql):
        self.executed.append(sql)
        self.description = [type("C", (), {"name": "__value"})()]

    def fetchall(self):
        return [(value,) for value in self.rows]


def test_grafana_interpolation_matches_grafana_formats():
    dashboard = {"templating": {"list": [
        {"name": "host", "type": "query", "query": "SELECT DISTINCT host_name FROM t", "includeAll": True, "multi": True},
        {"name": "flag", "type": "query", "query": "SELECT 1", "includeAll": True, "allValue": "__ALL__"},
        {"name": "success", "type": "custom", "query": "PASS : true,FAIL : false", "includeAll": True},
        {"name": "workspace", "type": "query", "query": "SELECT 'none'", "current": {"value": "none"}},
    ]}}
    cursor = _Cursor(["a", "o'b"])
    grafana = parity.GrafanaInterpolator(cursor, dashboard, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    sql = grafana.interpolate(
        "SELECT 1 WHERE $__timeFilter(t.started_at) AND h IN ($host) AND h = ANY(string_to_array('${host:csv}', ',')) "
        "AND '${flag}' = '__ALL__' AND s::text IN ($success) AND g(${__user.email:sqlstring}, ${__user.login:sqlstring}) "
        "AND x > $__timeFrom() AND w = ${host:sqlstring}")
    assert "t.started_at BETWEEN '2026-01-01T00:00:00Z' AND '2026-01-02T00:00:00Z'" in sql
    assert "h IN ('a','o''b')" in sql and "string_to_array('a,o'b', ',')" in sql
    assert "'__ALL__' = '__ALL__'" in sql and "s::text IN ('true','false')" in sql
    assert "g('', 'admin')" in sql and "x > '2026-01-01T00:00:00Z'" in sql


@pytest.mark.skipif(not (os.environ.get("ATLAS_PARITY_DSN") and os.environ.get("ATLAS_PARITY_TEAM")),
                    reason="live parity needs ATLAS_PARITY_DSN and ATLAS_PARITY_TEAM (read-only)")
def test_live_parity():
    results = parity.run(os.environ["ATLAS_PARITY_DSN"], os.environ["ATLAS_PARITY_TEAM"])
    assert {case_id: r["mismatches"] for case_id, r in results.items() if r["mismatches"]} == {}
