"""BUG-0898 — a recurring nightly that never ran must leave a visible record.

The scheduler module pulls in the browser stack when it is imported, so its class is
compiled from the source with `ast` and instantiated without running `__init__`; the
nightly report is driven through its real `main()` with the HTTP call stubbed out.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_PATH = REPO_ROOT / "backend_host" / "src" / "services" / "deployment_scheduler.py"
POLL_PATH = REPO_ROOT / "scripts" / "nightly_campaigns" / "poll_results.py"
SUMMARY_PATH = REPO_ROOT / "backend_server" / "src" / "services" / "governance" / "summary.py"

try:  # pragma: no cover - the fallback covers the daily cron the nightlies use
    import croniter as _croniter
except Exception:  # pragma: no cover
    class _FallbackCroniter:
        def __init__(self, expr, start):
            self._expr = expr
            self._start = start

        def get_next(self, kind):
            minute, hour = int(self._expr.split()[0]), int(self._expr.split()[1])
            nxt = self._start.replace(minute=minute, hour=hour, second=0, microsecond=0)
            if nxt <= self._start:
                nxt += timedelta(days=1)
            return nxt

    class _croniter:
        def __init__(self, expr, start):
            self._inner = _FallbackCroniter(expr, start)

        def get_next(self, kind):
            return self._inner.get_next(kind)


CAMPAIGNS = {
    "nightly_tc_web": {
        "campaign_id": "c-1",
        "campaign_name": "nightly_tc_web",
        "script_configurations": [{"script_name": "nightly/tc"}],
    }
}

_START = datetime(2026, 10, 24, 0, 30, tzinfo=timezone.utc)


def _class_source(path: Path, class_name: str) -> str:
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{path} has no class {class_name}")


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{path} has no function {function_name}")


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def insert(self, row):
        self._rows.append(dict(row))
        return self

    def select(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class _FakeSupabase:
    def __init__(self):
        self.rows: Dict[str, List[dict]] = {}

    def table(self, name):
        return _FakeTable(self.rows.setdefault(name, []))


def _deployment(**overrides) -> Dict[str, Any]:
    dep = {
        "id": "dep-1",
        "name": "nightly tc web",
        "script_name": "nightly_tc_web",
        "cron_expression": "30 0 * * *",
        "team_id": "team-1",
        "host_name": "host-a",
        "device_id": "dev-1",
    }
    dep.update(overrides)
    return dep


class _FixedClock:
    """A clock frozen at a fixed instant, so the retry window is deterministic."""

    def __init__(self, instant: datetime):
        self._instant = instant.timestamp()

    def time(self):
        return self._instant

    def __getattr__(self, name):
        return getattr(time, name)


def _make_scheduler(campaigns=None, now: Optional[datetime] = None):
    """The real DeploymentScheduler class, compiled from source, without its __init__."""
    namespace = {
        "get_campaign_by_name": lambda name, team_id: (campaigns or CAMPAIGNS).get(name),
        "deployment_logger": logging.getLogger("test_deployment_scheduler"),
        "uuid4": uuid4,
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "threading": threading,
        "time": _FixedClock(now) if now else time,
        "croniter": _croniter,
        "json": json,
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "ORPHANED_SCRIPT_RESULT_GRACE_SECONDS": 7200,
        "ORPHANED_SCRIPT_RESULT_SWEEP_SECONDS": 300,
        "LEAKED_BROWSER_REAP_SECONDS": 300,
        "BUSY_RETRY_MAX_ATTEMPTS": 3,
        "BUSY_RETRY_INTERVAL_SECONDS": 300,
        "BUSY_RETRY_WINDOW_MARGIN_SECONDS": 600,
    }
    exec(
        compile(_class_source(SCHEDULER_PATH, "DeploymentScheduler"), str(SCHEDULER_PATH), "exec"),
        namespace,
    )
    scheduler = object.__new__(namespace["DeploymentScheduler"])
    scheduler.supabase = _FakeSupabase()
    scheduler.db_lock = threading.Lock()
    scheduler.busy_retry_state = {}
    scheduler.busy_retry_lock = threading.Lock()
    scheduler.host_name = "host-a"
    scheduler.queued_executions = {}
    scheduler.executed = []
    scheduler._execute_deployment = (
        lambda deployment_id, queued_execution_id=None, busy_retry_attempt=0:
        scheduler.executed.append((deployment_id, busy_retry_attempt))
    )
    return scheduler


def _poll_module():
    spec = importlib.util.spec_from_file_location("nightly_poll_results", POLL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_report(monkeypatch, capsys, tmp_path, rows) -> str:
    """Drive the nightly report the way it really runs, with the HTTP call stubbed out."""
    poll = _poll_module()
    monkeypatch.setattr(poll, "http_get", lambda base, path, params, token: (200, list(rows)))
    monkeypatch.setattr(poll.time, "sleep", lambda *args: None)
    monkeypatch.setattr(sys, "argv", [
        "poll_results.py", "--team-id", "team-1", "--auto-signed", "token",
        "--interval", "1", "--deadline", "2", "--out-dir", str(tmp_path),
    ])
    poll.main()
    return capsys.readouterr().out


def _skipped_row() -> Dict[str, Any]:
    return {
        "campaign_name": "nightly_tc_web",
        "status": "cancelled",
        "skipped": True,
        "success": False,
        "started_at": "2026-10-24T00:30:00+00:00",
        "error_message": "Device dev-1 busy",
        "script_results": [],
    }


def _completed_row(name: str = "nightly_vs_web", success: bool = True) -> Dict[str, Any]:
    return {
        "campaign_name": name,
        "status": "completed",
        "success": success,
        "started_at": "2026-10-24T00:31:00+00:00",
        "script_results": [{"success": success}],
    }


def test_a_busy_skip_leaves_a_campaign_level_record_that_reads_as_skipped():
    scheduler = _make_scheduler()
    assert hasattr(scheduler, "_record_skipped_campaign_execution"), (
        "the scheduler leaves no campaign-level record for a deployment that never started"
    )
    row = scheduler._record_skipped_campaign_execution(
        _deployment(), "dep-1", _START, "Device dev-1 busy"
    )
    assert row is not None, (
        "a recurring deployment skipped because the device was busy left no campaign record"
    )
    written = scheduler.supabase.rows["campaign_executions"]
    assert len(written) == 1
    record = written[0]
    assert record["status"] == "cancelled", (
        "the skip is written with a status the live campaign_executions CHECK rejects"
    )
    assert record["skipped"] is True, "the skip is not marked by a flag"
    assert record["success"] is False
    assert record["campaign_name"] == "nightly_tc_web"
    assert record["error_message"] == "Device dev-1 busy"
    assert record["started_at"] == _START.isoformat()
    assert record["metadata"]["skip_reason"] == "Device dev-1 busy"


def test_busy_locked_and_queue_full_leave_the_same_kind_of_record():
    scheduler = _make_scheduler()
    assert hasattr(scheduler, "_record_skipped_campaign_execution"), (
        "the scheduler leaves no campaign-level record for a deployment that never started"
    )
    reasons = ["Device dev-1 busy", "Device locked by human", "Device queue full (dev-1, max 10)"]
    for reason in reasons:
        scheduler._record_skipped_campaign_execution(_deployment(), "dep-1", _START, reason)
    written = scheduler.supabase.rows["campaign_executions"]
    assert len(written) == 3
    assert len({frozenset(r.keys()) for r in written}) == 1, (
        "the three skip reasons leave three different kinds of record"
    )
    assert {r["status"] for r in written} == {"cancelled"}
    assert {r["skipped"] for r in written} == {True}
    assert {r["error_message"] for r in written} == set(reasons)


def test_only_a_recurring_deployment_leaves_a_campaign_level_skip_record():
    scheduler = _make_scheduler()
    assert hasattr(scheduler, "_record_skipped_campaign_execution"), (
        "the scheduler leaves no campaign-level record for a deployment that never started"
    )
    one_off = _deployment(max_executions=1)
    assert scheduler._record_skipped_campaign_execution(
        one_off, "dep-1", _START, "Device dev-1 busy"
    ) is None
    assert scheduler.supabase.rows.get("campaign_executions", []) == []
    assert scheduler._record_skipped_campaign_execution(
        _deployment(), "dep-1", _START, "Device dev-1 busy"
    ) is not None


def test_the_nightly_report_counts_a_skipped_campaign_as_done_and_not_as_a_failure(
    monkeypatch, capsys, tmp_path
):
    out = _run_report(monkeypatch, capsys, tmp_path, [_skipped_row(), _completed_row()])
    assert "done=2" in out, "a skipped campaign is not counted as a finished night"
    assert "All watched campaigns terminal." in out, "the report keeps waiting for a night that never ran"
    assert "[skip" in out, "a skipped campaign does not read as skipped in the report"
    assert "✗" not in out, "a night that never ran is shown as a failure"
    assert "fail=0" in out, "a night that never ran is counted as a failed night"
    assert "reason=Device dev-1 busy" in out, "the report does not say why the night did not run"


def test_a_campaign_that_ran_keeps_its_verdict(monkeypatch, capsys, tmp_path):
    out = _run_report(monkeypatch, capsys, tmp_path, [
        _skipped_row(),
        _completed_row(success=True),
        _completed_row(name="nightly_ds_web", success=False),
    ])
    assert "✓" in out, "a night that ran and succeeded no longer reads as a success"
    assert "✗" in out, "a night that ran and failed no longer reads as a failure"
    assert "done=3" in out, "a skipped campaign is not counted as a finished night"
    assert "[skip" in out, "a skipped campaign does not read as skipped in the report"


def test_the_platform_health_reads_a_skipped_campaign_as_skipped():
    namespace = {"Dict": Dict, "Any": Any}
    exec(compile(_function_source(SUMMARY_PATH, "campaign_status"), str(SUMMARY_PATH), "exec"), namespace)
    campaign_status = namespace["campaign_status"]
    assert campaign_status({"status": "cancelled", "skipped": True}) == "skipped", (
        "a night that never ran reads as unknown in the platform health"
    )
    assert campaign_status({"status": "cancelled"}) == "cancelled"
    assert campaign_status({"status": "completed", "success": True}) == "passed"
    assert campaign_status({"status": "completed", "success": False}) == "failed"


def test_a_busy_skipped_nightly_is_retried_inside_its_own_trigger_window():
    scheduler = _make_scheduler(now=_START)
    assert hasattr(scheduler, "_schedule_busy_retry"), (
        "a recurring deployment skipped because the device was busy is never retried today"
    )
    assert scheduler._schedule_busy_retry(_deployment(), "dep-1", _START, 1) is True
    state = scheduler.busy_retry_state["dep-1"]
    assert state["attempt"] == 1
    assert state["deadline"] > _START.timestamp(), "the retry deadline is already in the past"
    next_trigger = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    assert state["deadline"] <= next_trigger.timestamp(), (
        "the retry deadline falls outside the trigger window"
    )


def test_the_busy_retry_is_bounded_and_never_double_runs():
    scheduler = _make_scheduler(now=_START)
    assert hasattr(scheduler, "_schedule_busy_retry"), (
        "a recurring deployment skipped because the device is busy is never retried today"
    )
    dep = _deployment()
    assert scheduler._schedule_busy_retry(dep, "dep-1", _START, 1) is True
    # A second trigger while the attempt is still running must not start a parallel one.
    assert scheduler._schedule_busy_retry(dep, "dep-1", _START, 1) is False
    # The attempt budget is bounded.
    scheduler.busy_retry_state["dep-1"] = {
        "attempt": 3, "deadline": _START.timestamp() + 3600, "running": False,
    }
    assert scheduler._schedule_busy_retry(dep, "dep-1", _START, 4) is False
    assert "dep-1" not in scheduler.busy_retry_state
