"""TASK-147 F5: /server/ai/benchmarks carries the feature (category) of every run and case, and ?category= filters."""
import os
import sys

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend_server", "src"))

from backend_server.src.routes import server_ai_routing_routes as routes  # noqa: E402
from shared.src.lib.ai import usages  # noqa: E402
from shared.src.lib.database import ai_benchmarks_db  # noqa: E402


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _case(run, key, ok=True):
    return {"usage_key": f"eval:{key}", "ref_id": run, "ref_kind": "c1", "ref_type": "benchmark", "profile": "p1",
            "model": "m", "endpoint": "e", "parse_ok": ok, "ok": True, "ts": "2026-10-20T10:00:00+00:00", "cost": 0.01}


def _get(monkeypatch, query):
    rows = [_case("r1", "vision.banner"), _case("r2", "text.decision.zap", False)]
    monkeypatch.setattr(ai_benchmarks_db, "get_supabase", lambda: _FakeDb(rows))
    monkeypatch.setattr(routes, "_is_admin", lambda: False)
    with Flask("t").test_request_context("/x?" + query):
        return _unwrap(routes.get_benchmarks)().get_json()


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _):
        return self

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        class R:
            data = self.rows
        return R()


def test_runs_and_cases_carry_the_category(monkeypatch):
    out = _get(monkeypatch, "")
    cats = {r["usage_key"]: r["category"] for r in out["runs"]}
    assert cats == {k: usages.page_category(k) for k in cats} and len(cats) == 2
    assert all(c["category"] == usages.page_category(c["usage_key"]) for c in out["cases"])


def test_category_filter_keeps_only_that_feature(monkeypatch):
    want = usages.page_category("vision.banner")
    out = _get(monkeypatch, f"category={want}")
    assert [r["usage_key"] for r in out["runs"]] == ["vision.banner"]
    assert {c["usage_key"] for c in out["cases"]} == {"vision.banner"}
    assert out["usage_keys"] == ["vision.banner"]
