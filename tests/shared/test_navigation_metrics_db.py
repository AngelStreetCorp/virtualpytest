"""Navigation metrics readers against the post-rename schema.

Guards the column names the readers select from node_metrics / edge_metrics /
execution_results (20260507_clarify_metrics_naming.sql renamed
avg_execution_time_ms to avg_verification_time_ms / avg_action_time_ms) and the
per-edge KPI fields the Edge Selection panel expects.

The fake Supabase client rejects any selected column that is not in the table's
real column list, the same way PostgREST does (42703), so a stale column name
fails here instead of on prod.

Run: pytest tests/shared/test_navigation_metrics_db.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.database import navigation_metrics_db as nav_db  # noqa: E402
from shared.src.lib.database import execution_results_db as er_db  # noqa: E402
from backend_server.src.lib.utils import tree_metrics_payload as payload  # noqa: E402

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
TREE = "178f2a7a-deeb-48af-acd0-5f281a989c0b"
EDGE = "edge-home-to-search_results"
ACTION_SET = "home_to_search_results"
REPORT_NEW = "https://r2.example/kpi/new.html"
REPORT_OLD = "https://r2.example/kpi/old.html"

# Real prod columns (confirmed via PostgREST on 2026-09-28).
SCHEMA = {
    "node_metrics": {
        "id", "node_id", "tree_id", "team_id", "created_at", "total_executions",
        "successful_executions", "success_rate", "avg_verification_time_ms", "variant",
    },
    "edge_metrics": {
        "id", "edge_id", "tree_id", "team_id", "created_at", "total_executions",
        "successful_executions", "success_rate", "avg_action_time_ms", "action_set_id",
        "total_kpi_measurements", "successful_kpi_measurements", "avg_kpi_ms", "min_kpi_ms",
        "max_kpi_ms", "kpi_success_rate", "variant",
    },
    "execution_results": {
        "id", "team_id", "tree_id", "edge_id", "node_id", "action_set_id", "variant", "success",
        "execution_time_ms", "executed_at", "kpi_measurement_ms", "kpi_measurement_success",
        "kpi_report_url",
    },
}


class _Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table, rows):
        self.table = table
        self.rows = rows
        self.columns = None
        self.filters = []
        self.ordering = None
        self._negate = False

    def select(self, columns, **_kwargs):
        wanted = [c.strip() for c in columns.split(",")] if columns != "*" else sorted(SCHEMA[self.table])
        for col in wanted:
            if col not in SCHEMA[self.table]:
                raise Exception({"message": f"column {self.table}.{col} does not exist", "code": "42703"})
        self.columns = wanted
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, predicate):
        if self._negate:
            self.filters.append(lambda r: not predicate(r))
            self._negate = False
        else:
            self.filters.append(predicate)
        return self

    def eq(self, col, value):
        return self._add(lambda r: r.get(col) == value)

    def in_(self, col, values):
        values = list(values)
        return self._add(lambda r: r.get(col) in values)

    def is_(self, col, value):
        assert value == "null", "fake only models IS NULL"
        return self._add(lambda r: r.get(col) is None)

    def order(self, col, desc=False):
        self.ordering = (col, desc)
        return self

    def range(self, start, end):
        self.window = (start, end + 1)
        return self

    def execute(self):
        assert self.columns is not None, "select() must be called"
        out = [r for r in self.rows if all(f(r) for f in self.filters)]
        if self.ordering:
            col, desc = self.ordering
            out.sort(key=lambda r: r[col], reverse=desc)
        if getattr(self, "window", None):
            out = out[self.window[0]:self.window[1]]
        return _Result([{c: r.get(c) for c in self.columns} for r in out])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, name):
        q = FakeQuery(name, self.tables.get(name, []))
        self.queries.append(q)
        return q


def _tables():
    return {
        "node_metrics": [
            {"node_id": "home", "tree_id": TREE, "team_id": TEAM, "variant": None,
             "total_executions": 4, "successful_executions": 4, "success_rate": 1,
             "avg_verification_time_ms": 800, "created_at": "2026-09-27T10:00:00Z"},
            {"node_id": "home", "tree_id": TREE, "team_id": TEAM, "variant": "dark",
             "total_executions": 1, "successful_executions": 0, "success_rate": 0,
             "avg_verification_time_ms": 50, "created_at": "2026-09-27T10:00:00Z"},
        ],
        "edge_metrics": [
            {"edge_id": EDGE, "tree_id": TREE, "team_id": TEAM, "action_set_id": ACTION_SET, "variant": None,
             "total_executions": 1, "successful_executions": 1, "success_rate": 1,
             "avg_action_time_ms": 2300, "total_kpi_measurements": 1, "successful_kpi_measurements": 1,
             "avg_kpi_ms": 1505, "min_kpi_ms": 1505, "max_kpi_ms": 1505, "kpi_success_rate": 1,
             "created_at": "2026-09-27T10:00:00Z"},
            {"edge_id": EDGE, "tree_id": TREE, "team_id": TEAM, "action_set_id": ACTION_SET, "variant": "dark",
             "total_executions": 3, "successful_executions": 1, "success_rate": 0.3333,
             "avg_action_time_ms": 900, "total_kpi_measurements": 0, "successful_kpi_measurements": 0,
             "avg_kpi_ms": 0, "min_kpi_ms": None, "max_kpi_ms": None, "kpi_success_rate": 0,
             "created_at": "2026-09-27T10:00:00Z"},
            {"edge_id": "edge-search_results-to-home", "tree_id": TREE, "team_id": TEAM,
             "action_set_id": "search_results_to_home", "variant": None,
             "total_executions": 2, "successful_executions": 2, "success_rate": 1,
             "avg_action_time_ms": 400, "total_kpi_measurements": 0, "successful_kpi_measurements": 0,
             "avg_kpi_ms": 0, "min_kpi_ms": None, "max_kpi_ms": None, "kpi_success_rate": 0,
             "created_at": "2026-09-27T10:00:00Z"},
        ],
        "execution_results": [
            {"id": "r1", "team_id": TEAM, "tree_id": TREE, "edge_id": EDGE, "action_set_id": ACTION_SET,
             "variant": None, "executed_at": "2026-09-26T09:00:00Z", "kpi_measurement_ms": 1400,
             "kpi_report_url": REPORT_OLD},
            {"id": "r2", "team_id": TEAM, "tree_id": TREE, "edge_id": EDGE, "action_set_id": ACTION_SET,
             "variant": None, "executed_at": "2026-09-27T09:00:00Z", "kpi_measurement_ms": 1505,
             "kpi_report_url": REPORT_NEW},
            {"id": "r3", "team_id": TEAM, "tree_id": TREE, "edge_id": EDGE, "action_set_id": ACTION_SET,
             "variant": None, "executed_at": "2026-09-28T09:00:00Z", "kpi_measurement_ms": None,
             "kpi_report_url": None},
            {"id": "r4", "team_id": TEAM, "tree_id": TREE, "edge_id": EDGE, "action_set_id": ACTION_SET,
             "variant": "dark", "executed_at": "2026-09-28T10:00:00Z", "kpi_measurement_ms": 999,
             "kpi_report_url": "https://r2.example/kpi/dark.html"},
        ],
    }


@pytest.fixture
def fake(monkeypatch):
    client = FakeSupabase(_tables())
    monkeypatch.setattr(nav_db, "get_supabase", lambda: client)
    monkeypatch.setattr(er_db, "get_supabase", lambda: client)
    return client


def test_tree_metrics_base_scope_uses_real_columns_and_kpi_fields(fake):
    out = nav_db.get_tree_metrics(TEAM, ["home", "search_results"], [EDGE, "edge-search_results-to-home"])

    assert out["nodes"]["home"] == {"volume": 4, "success_rate": 1.0, "avg_verification_time": 800}
    # untested node still present with defaults
    assert out["nodes"]["search_results"] == {"volume": 0, "success_rate": 0.0, "avg_verification_time": 0}

    key = f"{EDGE}#{ACTION_SET}"
    assert out["edges"][key] == {
        "volume": 1,
        "success_rate": 1.0,
        "avg_action_time": 2300,
        "avg_kpi_ms": 1505,
        "kpi_volume": 1,
        "kpi_report_url": REPORT_NEW,  # newest executed_at with a non-null url, not r3
        "action_set_id": ACTION_SET,
        "variant": None,
    }
    other = out["edges"]["edge-search_results-to-home#search_results_to_home"]
    assert other["kpi_volume"] == 0 and other["kpi_report_url"] is None

    # No stale column anywhere in the selects
    for q in fake.queries:
        assert "avg_execution_time_ms" not in q.columns


def test_tree_metrics_variant_scope_matches_trigger_keys(fake):
    out = nav_db.get_tree_metrics(TEAM, ["home"], [EDGE], variant="dark")

    assert out["nodes"]["home"]["avg_verification_time"] == 50
    edge = out["edges"][f"{EDGE}#{ACTION_SET}"]
    assert edge["volume"] == 3 and edge["avg_action_time"] == 900 and edge["variant"] == "dark"
    # dark scope has no KPI samples yet, so no report url is looked up for it
    assert edge["kpi_volume"] == 0 and edge["kpi_report_url"] is None
    assert not any(q.table == "execution_results" for q in fake.queries)


def test_tree_metrics_returns_defaults_when_a_column_is_missing(fake, monkeypatch):
    # Simulate a DB that still has the pre-rename column: the select must fail
    # loudly in the fake, and the reader must degrade to defaults (not crash).
    monkeypatch.setitem(SCHEMA, "node_metrics", SCHEMA["node_metrics"] - {"avg_verification_time_ms"})
    out = nav_db.get_tree_metrics(TEAM, ["home"], [EDGE])
    assert out == {"nodes": {"home": {"volume": 0, "success_rate": 0.0, "avg_verification_time": 0}}, "edges": {}}


def test_edge_direction_metrics(fake):
    out = nav_db.get_edge_direction_metrics(TEAM, EDGE, ACTION_SET)
    assert out == {"volume": 1, "success_rate": 1.0, "avg_action_time": 2300,
                   "avg_kpi_ms": 1505, "kpi_volume": 1, "confidence": 1.0}

    missing = nav_db.get_edge_direction_metrics(TEAM, EDGE, "no_such_direction")
    assert missing == {"volume": 0, "success_rate": 0.0, "avg_action_time": 0,
                       "avg_kpi_ms": 0, "kpi_volume": 0, "confidence": 0.0}


def test_execution_results_db_readers(fake):
    # get_tree_metrics here is the same reader (single implementation)
    same = er_db.get_tree_metrics(TEAM, ["home"], [EDGE])
    assert same["edges"][f"{EDGE}#{ACTION_SET}"]["avg_kpi_ms"] == 1505

    raw = er_db.get_raw_tree_metrics(TEAM, TREE, ["home"], [EDGE])
    assert raw["success"] is True
    assert raw["node_metrics"][0]["avg_verification_time_ms"] == 800
    assert raw["node_metrics"][0]["updated_at"] == raw["node_metrics"][0]["created_at"]
    edge_row = raw["edge_metrics"][0]
    assert edge_row["avg_action_time_ms"] == 2300 and edge_row["avg_kpi_ms"] == 1505
    assert edge_row["action_set_id"] == ACTION_SET and edge_row["variant"] is None


def test_payload_shape_matches_frontend(fake):
    out = payload.build_tree_metrics_payload(
        TEAM, ["home", "search_results"], [EDGE, "edge-search_results-to-home", "edge-never-run"], variant=None)

    assert set(out) == {"nodes", "edges", "variant", "global_confidence", "confidence_distribution"}
    assert set(out["nodes"]["home"]) == {"volume", "success_rate", "avg_verification_time", "confidence",
                                       "verified_frame_url", "verified_at"}
    edge = out["edges"][f"{EDGE}#{ACTION_SET}"]
    assert set(edge) == {"volume", "success_rate", "avg_action_time", "avg_kpi_ms", "kpi_volume",
                         "kpi_report_url", "confidence"}
    assert edge["kpi_report_url"] == REPORT_NEW
    # volume 1 -> 0.025 + 0.75
    assert edge["confidence"] == pytest.approx(0.775)
    # search_results has no executions + edge-never-run has no executed direction;
    # counted per edge_id, never per direction key, so it cannot go negative.
    assert out["confidence_distribution"]["untested"] == 2
    assert out["confidence_distribution"]["high"] + out["confidence_distribution"]["medium"] \
        + out["confidence_distribution"]["low"] == 3  # home + 2 executed edge directions
    assert 0 < out["global_confidence"] <= 1
