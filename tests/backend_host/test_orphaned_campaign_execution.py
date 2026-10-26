"""BUG-0900 — a campaign aborted by a scheduler restart must not stay `running`.

Drives the real DeploymentScheduler (compiled from source, no __init__) against a fake
Supabase that applies eq/in_ filters, so the test can see which rows the repair really
reaches. Values and types are pinned: a stub that only counts calls missed BUG-0898.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import ast

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_PATH = REPO_ROOT / "backend_host" / "src" / "services" / "deployment_scheduler.py"

LIVE_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "aborted"}
WRITTEN_COLUMNS = {"status", "success", "completed_at", "updated_at", "error_message"}
REASON = "Execution aborted - scheduler restarted"


def _class_source(path: Path, class_name: str) -> str:
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{path} has no class {class_name}")


def _get(row, key):
    if "->>" in key:
        col, sub = key.split("->>")
        return (row.get(col) or {}).get(sub)
    return row.get(key)


class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.patch = db, name, [], None

    def select(self, *a, **k):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def eq(self, key, value):
        self.filters.append(lambda r: _get(r, key) == value)
        return self

    def is_(self, *a):
        return self

    def in_(self, key, values):
        self.filters.append(lambda r: _get(r, key) in values)
        return self

    def execute(self):
        if self.db.fail_on == (self.name, self.patch is not None):
            raise RuntimeError("boom")
        rows = [r for r in self.db.rows.setdefault(self.name, []) if all(f(r) for f in self.filters)]
        if self.patch is not None:
            self.db.writes.append((self.name, dict(self.patch)))
            for r in rows:
                r.update(self.patch)
        return SimpleNamespace(data=[dict(r) for r in rows])


class _FakeSupabase:
    def __init__(self):
        self.rows: Dict[str, List[dict]] = {}
        self.writes: List[Any] = []
        self.fail_on = None

    def table(self, name):
        return _Query(self, name)


class _Logger:
    def __init__(self):
        self.errors: List[str] = []

    def error(self, msg, *a, **k):
        self.errors.append(str(msg))

    def __getattr__(self, name):
        return lambda *a, **k: None


def _scheduler():
    logger = _Logger()
    ns = {"deployment_logger": logger, "logging": logging, "datetime": datetime,
          "timezone": timezone, "timedelta": timedelta, "Any": Any, "Dict": Dict, "List": List,
          "Optional": Any}
    exec(compile(_class_source(SCHEDULER_PATH, "DeploymentScheduler"), str(SCHEDULER_PATH), "exec"), ns)
    s = object.__new__(ns["DeploymentScheduler"])
    s.supabase = _FakeSupabase()
    s.db_lock = threading.Lock()
    s.host_name = "host-a"
    s.logger = logger
    return s


def _campaign(exec_id="exec-1", status="running", team="team-1", host="host-a", link=True):
    meta = {"campaign_identity": {"campaign_ref": "x"}}
    if link:
        meta["deployment_execution_id"] = exec_id
    return {"id": f"camp-{exec_id}-{team}-{status}", "team_id": team, "host_name": host,
            "status": status, "success": False, "skipped": False, "executed_by": None,
            "completed_at": None, "error_message": None, "metadata": meta}


def _stale(exec_id="exec-1", team="team-1"):
    return {"id": exec_id, "deployment_id": "dep-1", "script_result_id": None,
            "started_at": "2026-10-25T00:40:00+00:00", "deployments": {"host_name": "host-a", "team_id": team}}


def _sweep(s):
    assert hasattr(s, "_sweep_orphaned_campaign_executions"), "no campaign sweep on the scheduler"
    return s._sweep_orphaned_campaign_executions()


def _repair(s, stale=None):
    s.supabase.rows.setdefault("deployment_executions", []).append(
        {"id": "exec-1", "status": "running", "deployments": {"host_name": "host-a", "team_id": "team-1"}})
    s._find_orphaned_script_result = lambda e: None
    s._mark_stale_execution_failed(stale or _stale(), REASON)


def test_repair_closes_linked_running_campaign():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign()]
    _repair(s)
    row = s.supabase.rows["campaign_executions"][0]
    assert row["status"] == "aborted" and row["status"] in LIVE_STATUSES
    assert row["success"] is False
    assert row["error_message"] == REASON
    assert row["executed_by"] is None and row["skipped"] is False
    dep = s.supabase.rows["deployment_executions"][0]
    assert dep["status"] == "failed"
    (_, patch), = [w for w in s.supabase.writes if w[0] == "campaign_executions"]
    assert set(patch) == WRITTEN_COLUMNS
    assert isinstance(patch["success"], bool)
    for col in ("completed_at", "updated_at"):
        assert datetime.fromisoformat(patch[col]).tzinfo is not None
    assert patch["completed_at"] == patch["updated_at"] == dep["completed_at"]


def test_repair_without_linked_campaign_does_nothing():
    s = _scheduler()
    _repair(s)  # must not raise
    assert s.supabase.rows.get("campaign_executions", []) == []
    assert s.supabase.rows["deployment_executions"][0]["status"] == "failed"
    assert hasattr(s, "_close_campaign_execution")


def test_closed_campaign_is_not_modified():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign(status="completed")]
    before = dict(s.supabase.rows["campaign_executions"][0])
    _repair(s)
    assert s.supabase.rows["campaign_executions"][0] == before


def test_sweep_leaves_campaign_of_running_execution():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign()]
    s.supabase.rows["deployment_executions"] = [
        {"id": "exec-1", "status": "running", "deployments": {"host_name": "host-a", "team_id": "team-1"}}]
    assert _sweep(s) == 0
    assert s.supabase.rows["campaign_executions"][0]["status"] == "running"


def test_sweep_closes_running_campaign_of_closed_execution():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign()]
    s.supabase.rows["deployment_executions"] = [
        {"id": "exec-1", "status": "failed", "completed_at": "2026-10-25T00:40:37.723757+00:00",
         "error_message": REASON, "deployments": {"host_name": "host-a", "team_id": "team-1"}}]
    assert _sweep(s) == 1
    row = s.supabase.rows["campaign_executions"][0]
    assert row["status"] == "aborted" and row["success"] is False
    assert row["completed_at"] == "2026-10-25T00:40:37.723757+00:00"
    assert row["error_message"] == REASON


def test_other_team_campaign_not_touched():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign(team="team-2")]
    _repair(s)
    assert s.supabase.rows["campaign_executions"][0]["status"] == "running"
    s.supabase.rows["deployment_executions"] = [
        {"id": "exec-1", "status": "failed", "completed_at": "2026-10-25T00:40:37+00:00",
         "error_message": REASON, "deployments": {"host_name": "host-a", "team_id": "team-1"}}]
    assert _sweep(s) == 0
    assert s.supabase.rows["campaign_executions"][0]["status"] == "running"


def test_campaign_without_link_not_touched():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign(link=False)]
    _repair(s)
    assert _sweep(s) == 0
    assert s.supabase.rows["campaign_executions"][0]["status"] == "running"


def test_campaign_write_failure_is_logged_and_swallowed():
    s = _scheduler()
    s.supabase.rows["campaign_executions"] = [_campaign()]
    s.supabase.fail_on = ("campaign_executions", True)
    _repair(s)  # must not raise
    assert s.supabase.rows["deployment_executions"][0]["status"] == "failed"
    assert s.supabase.rows["campaign_executions"][0]["status"] == "running"
    assert any("exec-1" in e for e in s.logger.errors)
    s.supabase.fail_on = ("campaign_executions", False)
    assert _sweep(s) == 0  # query failure: no raise
