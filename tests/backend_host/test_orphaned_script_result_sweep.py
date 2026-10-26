"""BUG-0901 — the script_result orphan sweep must close a row once, not every cycle.

Drives the real DeploymentScheduler (compiled from source, no __init__) against a fake
Supabase that applies eq/is_/lt filters and returns the rows an update changed, as PostgREST
does. Values and types are pinned: a stub that only counts calls let the defect live for days.
"""
from __future__ import annotations

import ast
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_PATH = REPO_ROOT / "backend_host" / "src" / "services" / "deployment_scheduler.py"
MESSAGE = (
    "The run never reported a verdict: it stopped before it could write its result "
    "(host restart, killed process, or a run that outlived its slot). Closed by the host "
    "as an orphan, not a test failure."
)
OLD = datetime.now(timezone.utc) - timedelta(hours=5)


def _class_source(path: Path, class_name: str) -> str:
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{path} has no class {class_name}")


class _Query:
    def __init__(self, db):
        self.db, self.filters, self.patch = db, [], None

    def select(self, *a, **k):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def eq(self, key, value):
        self.filters.append(lambda r: r.get(key) == value)
        return self

    def is_(self, key, value):
        self.filters.append(lambda r: r.get(key) is None)
        return self

    def lt(self, key, value):
        self.filters.append(lambda r: datetime.fromisoformat(r[key]) < datetime.fromisoformat(value))
        return self

    def execute(self):
        if self.patch is not None and self.db.before_update:
            self.db.before_update()
            self.db.before_update = None
        rows = [r for r in self.db.rows if all(f(r) for f in self.filters)]
        if self.patch is not None:
            for r in rows:
                r.update(self.patch)
        return SimpleNamespace(data=[dict(r) for r in rows])


class _FakeSupabase:
    def __init__(self):
        self.rows: List[dict] = []
        self.before_update = None

    def table(self, name):
        assert name == "script_results"
        return _Query(self)


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _scheduler():
    ns = {"deployment_logger": _Logger(), "logging": logging, "datetime": datetime,
          "timezone": timezone, "timedelta": timedelta, "Any": Any, "Dict": Dict, "List": List,
          "Optional": Any, "ORPHANED_SCRIPT_RESULT_GRACE_SECONDS": 7200}
    exec(compile(_class_source(SCHEDULER_PATH, "DeploymentScheduler"), str(SCHEDULER_PATH), "exec"), ns)
    s = object.__new__(ns["DeploymentScheduler"])
    s.supabase = _FakeSupabase()
    s.db_lock = threading.Lock()
    s.host_name = "host-a"
    return s


def _row(rid="r1", host="host-a", started=OLD, gap_us=40, exec_ms=None, error=None, completed=None):
    return {"id": rid, "host_name": host, "script_name": "x", "started_at": started.isoformat(),
            "completed_at": (completed or started + timedelta(microseconds=gap_us)).isoformat(),
            "success": False, "execution_time_ms": exec_ms, "error_msg": error}


def test_placeholder_is_closed_with_typed_values():
    s = _scheduler()
    s.supabase.rows = [_row()]
    n = s._sweep_orphaned_script_results()
    assert n == 1 and isinstance(n, int)
    r = s.supabase.rows[0]
    assert r["success"] is False
    assert r["error_msg"] == MESSAGE
    assert datetime.fromisoformat(r["completed_at"]).tzinfo is not None
    assert datetime.fromisoformat(r["completed_at"]) > OLD + timedelta(hours=1)


def test_second_cycle_does_not_touch_the_row():
    s = _scheduler()
    s.supabase.rows = [_row()]
    assert s._sweep_orphaned_script_results() == 1
    before = dict(s.supabase.rows[0])
    assert s._sweep_orphaned_script_results() == 0
    assert s.supabase.rows[0] == before


def test_row_already_closed_by_the_sweep_is_not_written():
    s = _scheduler()
    s.supabase.rows = [_row(error=MESSAGE, completed=OLD + timedelta(hours=3))]
    before = dict(s.supabase.rows[0])
    assert s._sweep_orphaned_script_results() == 0
    assert s.supabase.rows[0] == before


def test_row_closed_by_a_successful_run_is_not_touched():
    s = _scheduler()
    s.supabase.rows = [_row(exec_ms=1234, completed=OLD + timedelta(minutes=2))]
    before = dict(s.supabase.rows[0])
    assert s._sweep_orphaned_script_results() == 0
    assert s.supabase.rows[0] == before


def test_young_row_is_not_closed():
    s = _scheduler()
    s.supabase.rows = [_row(started=datetime.now(timezone.utc) - timedelta(minutes=30))]
    before = dict(s.supabase.rows[0])
    assert s._sweep_orphaned_script_results() == 0
    assert s.supabase.rows[0] == before


def test_other_hosts_rows_are_not_touched():
    s = _scheduler()
    s.supabase.rows = [_row(host="host-b")]
    before = dict(s.supabase.rows[0])
    assert s._sweep_orphaned_script_results() == 0
    assert s.supabase.rows[0] == before


def test_count_is_rows_closed_not_candidates():
    s = _scheduler()
    s.supabase.rows = [_row("r1"), _row("r2"), _row("r3", error=MESSAGE, completed=OLD + timedelta(hours=3))]
    n = s._sweep_orphaned_script_results()
    assert n == 2 and isinstance(n, int)


def test_row_closed_between_select_and_update_is_not_overwritten():
    s = _scheduler()
    s.supabase.rows = [_row()]
    theirs = (OLD + timedelta(minutes=10)).isoformat()

    def run_finishes():
        s.supabase.rows[0].update({"completed_at": theirs, "execution_time_ms": 600000, "success": True})

    s.supabase.before_update = run_finishes
    n = s._sweep_orphaned_script_results()
    r = s.supabase.rows[0]
    assert n == 0
    assert r["completed_at"] == theirs and r["success"] is True and r["error_msg"] is None
