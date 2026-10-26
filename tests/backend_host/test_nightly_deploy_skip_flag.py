"""BUG-0898 — the skip marker is a flag, and the status is one the live table accepts.

The live ``campaign_executions`` table has a CHECK constraint that accepts exactly
pending, running, completed, failed, cancelled and aborted: a skip written as a
status is rejected by the database and the record is lost. The skip therefore
travels in a **flag**, and the status column keeps its own meaning.

The test cannot read the live database, so it states the accepted set as a constant
and asserts that the status the writer uses is inside it — the check that was
missing. It also proves that the readers key off the flag and not off the status
word, and that the record survives a database that has not run the migration yet.
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
from typing import Any, Dict, List
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_PATH = REPO_ROOT / "backend_host" / "src" / "services" / "deployment_scheduler.py"
POLL_PATH = REPO_ROOT / "scripts" / "nightly_campaigns" / "poll_results.py"
SUMMARY_PATH = REPO_ROOT / "backend_server" / "src" / "services" / "governance" / "summary.py"

# The values the live campaign_executions.status CHECK constraint accepts.
LIVE_CAMPAIGN_EXECUTION_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "aborted",
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
    def __init__(self, rows, missing_columns=()):
        self._rows = rows
        self._missing_columns = missing_columns

    def insert(self, row):
        for column in self._missing_columns:
            if column in row:
                # What the database says when the column has not been added yet.
                raise RuntimeError(f'column "{column}" does not exist')
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
    def __init__(self, missing_columns=()):
        self.rows: Dict[str, List[dict]] = {}
        self._missing_columns = missing_columns

    def table(self, name):
        return _FakeTable(self.rows.setdefault(name, []), self._missing_columns)


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


def _make_scheduler(missing_columns=()):
    """The real DeploymentScheduler class, compiled from source, without its __init__."""
    namespace = {
        "get_campaign_by_name": lambda name, team_id: {
            "campaign_id": "c-1",
            "campaign_name": "nightly_tc_web",
            "script_configurations": [{"script_name": "nightly/tc"}],
        },
        "deployment_logger": logging.getLogger("test_nightly_deploy_skip_flag"),
        "logging": logging,
        "uuid4": uuid4,
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "threading": threading,
        "time": time,
        "json": json,
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Any,
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
    scheduler.supabase = _FakeSupabase(missing_columns=missing_columns)
    scheduler.db_lock = threading.Lock()
    scheduler.busy_retry_state = {}
    scheduler.busy_retry_lock = threading.Lock()
    scheduler.host_name = "host-a"
    scheduler.queued_executions = {}
    return scheduler


def _poll_module():
    spec = importlib.util.spec_from_file_location("nightly_poll_results_flag", POLL_PATH)
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
    """A campaign that never ran: the status the live table accepts, plus the flag."""
    return {
        "campaign_name": "nightly_tc_web",
        "status": "cancelled",
        "skipped": True,
        "success": False,
        "started_at": "2026-10-24T00:30:00+00:00",
        "error_message": "Device dev-1 busy",
        "script_results": [],
    }


def _cancelled_row() -> Dict[str, Any]:
    """A campaign that was cancelled by hand: same status, no skip flag."""
    return {
        "campaign_name": "nightly_tc_web",
        "status": "cancelled",
        "skipped": False,
        "success": False,
        "started_at": "2026-10-24T00:30:00+00:00",
        "error_message": "Cancelled by the operator",
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


def _campaign_status(row):
    """The real campaign_status() applied to one row."""
    namespace = {"Dict": Dict, "Any": Any}
    exec(compile(_function_source(SUMMARY_PATH, "campaign_status"), str(SUMMARY_PATH), "exec"), namespace)
    return namespace["campaign_status"](row)


def test_the_status_written_for_a_skip_is_one_the_live_table_accepts():
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
    assert row["status"] in LIVE_CAMPAIGN_EXECUTION_STATUSES, (
        f"the skip is written with the status {row['status']!r}, which the live "
        "campaign_executions CHECK constraint rejects"
    )
    assert row["skipped"] is True, (
        "the skip is not marked by a flag, so nothing can tell it from a cancellation"
    )
    assert row["metadata"]["skip_reason"] == "Device dev-1 busy"
    assert row["metadata"]["skipped"] is True


def test_the_readers_key_off_the_flag_and_not_off_the_status_word(monkeypatch, capsys, tmp_path):
    out = _run_report(monkeypatch, capsys, tmp_path, [_skipped_row(), _completed_row()])
    assert "[skip" in out, (
        "a night that never ran does not read as skipped in the nightly report"
    )
    assert "✗" not in out, "a night that never ran is shown as a failure"
    assert "done=2" in out, "a night that never ran is not counted as a finished night"
    assert "reason=Device dev-1 busy" in out, "the report does not say why the night did not run"

    # The status word alone does not make a skip: a cancelled campaign without the flag
    # keeps its own reading.
    out = _run_report(monkeypatch, capsys, tmp_path, [_cancelled_row(), _completed_row()])
    assert "[skip" not in out, (
        "a cancelled campaign reads as skipped without the skip flag"
    )

    # The platform's own health agrees with the report.
    assert _campaign_status({"status": "cancelled", "skipped": True}) == "skipped", (
        "a night that never ran reads as cancelled in the platform health"
    )
    assert _campaign_status({"status": "cancelled"}) == "cancelled", (
        "a cancelled campaign reads as skipped in the platform health without the flag"
    )
    assert _campaign_status({"status": "completed", "success": True}) == "passed"


def test_the_skip_record_is_stored_even_when_the_flag_column_is_missing():
    scheduler = _make_scheduler(missing_columns=("skipped",))
    assert hasattr(scheduler, "_record_skipped_campaign_execution"), (
        "the scheduler leaves no campaign-level record for a deployment that never started"
    )
    row = scheduler._record_skipped_campaign_execution(
        _deployment(), "dep-1", _START, "Device dev-1 busy"
    )
    assert row is not None, (
        "the skip record was lost because the skip-flag column has not been added yet"
    )
    written = scheduler.supabase.rows["campaign_executions"]
    assert len(written) == 1, (
        f"the skip record was written {len(written)} times instead of once"
    )
    assert "skipped" not in written[0], "the missing column was written anyway"
    assert written[0]["metadata"]["skipped"] is True, (
        "the skip was lost with the column that does not exist yet"
    )
    assert written[0]["status"] in LIVE_CAMPAIGN_EXECUTION_STATUSES


def test_the_uuid_columns_of_the_skip_row_hold_a_uuid_or_null():
    """campaign_executions.executed_by (and id, campaign_execution_id) are uuid columns.

    A label such as 'deployment_scheduler' is rejected by the database with 22P02 and the
    whole skip record is lost, which is what happened on the first live night. The tests
    stub the database, so the row's types are asserted here against the live column types.
    """
    from uuid import UUID

    scheduler = _make_scheduler()
    row = scheduler._record_skipped_campaign_execution(
        _deployment(), "dep-1", _START, "Device dev-1 busy"
    )
    assert row is not None
    for column in ("id", "campaign_execution_id", "executed_by"):
        value = row.get(column)
        if value is None:
            assert column == "executed_by", f"{column} must not be null"
            continue
        UUID(str(value))  # raises when the value is a label, not a uuid
