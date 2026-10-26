"""Editing a deployment (cron, parameters, dates, max_executions) must only reschedule future runs.

Only DeploymentScheduler.start() -> _sync_from_db() may close 'running' executions as
"Execution aborted - scheduler restarted" (a real process start). 2026-10-19: an update of
b1238a96 coincided with a host redeploy and looked like the edit aborted the run; this pins that
update_deployment itself never touches executions. update_deployment is loaded alone (ast), like
test_deployment_scheduler_params.py does, because the module needs host-only dependencies."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

_PATH = Path(__file__).resolve().parents[2] / 'backend_host/src/services/deployment_scheduler.py'


def _update_deployment():
    tree = ast.parse(_PATH.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeploymentScheduler')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'update_deployment')
    namespace = {'deployment_logger': MagicMock()}
    exec(compile(ast.Module([node], []), str(_PATH), 'exec'), namespace)
    return namespace['update_deployment']


def _scheduler():
    sched = MagicMock()
    sched.supabase = MagicMock()
    sched._is_future_one_shot.return_value = False
    return sched


def test_update_reschedules_with_new_cron_and_leaves_running_executions_alone():
    sched = _scheduler()
    dep = {'id': 'b1238a96', 'name': 'CoC LLM hourly', 'status': 'active', 'cron_expression': '0 * * * *'}

    _update_deployment()(sched, dep)

    sched.scheduler.remove_job.assert_called_once_with('b1238a96')
    sched._add_job.assert_called_once_with(dep, log_details=True)
    sched._sync_from_db.assert_not_called()
    sched._mark_stale_execution_failed.assert_not_called()
    sched.start.assert_not_called()
    sched.scheduler.shutdown.assert_not_called()
    sched.supabase.table.assert_not_called()


def test_update_of_paused_deployment_only_removes_the_job():
    sched = _scheduler()
    _update_deployment()(sched, {'id': 'x', 'status': 'paused'})

    sched._add_job.assert_not_called()
    sched._mark_stale_execution_failed.assert_not_called()
    sched.supabase.table.assert_not_called()


def test_only_sync_from_db_writes_the_restart_abort_message():
    src = _PATH.read_text()
    assert src.count("'Execution aborted - scheduler restarted'") == 1
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeploymentScheduler')
    holders = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)
               and 'Execution aborted - scheduler restarted' in ast.get_source_segment(src, n)]
    assert holders == ['_sync_from_db']
