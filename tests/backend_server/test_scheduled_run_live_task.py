"""Scheduled deployment runs get a server task the live endpoints can follow (TASK-127)."""

import os
import sys
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from flask import Flask  # noqa: E402

from backend_server.src.lib.utils import task_manager as tm  # noqa: E402
from backend_server.src.routes import server_deployment_routes as routes  # noqa: E402

pytestmark = pytest.mark.unit


def test_create_task_with_chosen_id_is_idempotent():
    m = tm.TaskManager()
    assert m.create_task('script_execute', {'a': 1}, task_id='dep-x') == 'dep-x'
    m.record_progress('dep-x', {'step': {'label': 's'}, 'step_number': 1})
    assert m.create_task('script_execute', {'a': 2}, task_id='dep-x') == 'dep-x'
    task = m.get_task('dep-x')
    assert task['params'] == {'a': 1} and len(task['progress_steps']) == 1


@pytest.fixture
def client(monkeypatch):
    manager = tm.TaskManager()
    monkeypatch.setattr(tm, 'task_manager', manager)
    monkeypatch.setattr(routes, 'get_supabase_client', lambda: MagicMock())
    monkeypatch.setattr(routes, 'release_device_lock', lambda **k: {'success': True})
    monkeypatch.setattr(routes, 'emit_system_update', lambda *a, **k: None)
    monkeypatch.setattr(routes, 'notify_completion', lambda *a, **k: {})
    app = Flask(__name__)
    app.register_blueprint(routes.server_deployment_bp)
    return app.test_client(), manager


def _post(c, status, **extra):
    body = {'deployment_id': 'd1', 'execution_id': 'e1', 'host_name': 'h', 'device_id': 'device1',
            'script_name': 'goto_live', 'team_id': 't1', 'status': status}
    body.update(extra)
    return c.post('/server/deployment/executionComplete', json=body)


def test_running_opens_task_and_completion_closes_it(client):
    c, manager = client
    _post(c, 'running')
    task = manager.get_task('dep-e1')
    assert task['status'] == 'started' and task['command'] == 'script_execute'
    assert task['params']['host_name'] == 'h' and task['params']['team_id'] == 't1'
    assert task['params']['script_name'] == 'goto_live' and task['params']['execution_id'] == 'e1'
    assert [t['id'] for t in manager.running_tasks('script_execute', 't1')] == ['dep-e1']
    _post(c, 'failed', success=False, error='boom')
    assert manager.get_task('dep-e1')['status'] == 'failed'
    _post(c, 'running', execution_id='e2')
    _post(c, 'completed', execution_id='e2', success=True)
    assert manager.get_task('dep-e2')['status'] == 'completed'


def test_scheduler_passes_the_task_id_the_server_derives():
    """The host scheduler hands the script the same id the server opens (dep-<execution id>)."""
    src = open(os.path.join(_REPO_ROOT, 'backend_host/src/services/deployment_scheduler.py')).read()
    assert "task_id=f'dep-{exec_id}'" in src
    assert tm.deployment_task_id('E') == 'dep-E'
