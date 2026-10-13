"""Live run status adapter and Stop (TASK-42 §4.3 Live, §9 Live)."""

import os
import sys
import time

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.lib.utils.task_manager import TaskManager  # noqa: E402
from backend_server.src.routes import server_live_routes  # noqa: E402
from backend_server.src.services.live import adapter  # noqa: E402

pytestmark = pytest.mark.unit

VIEW = ['reports.tests:view']
RUN = ['reports.tests:view', 'execution.run:run_test']


@pytest.fixture
def env(monkeypatch):
    fake = common.install(monkeypatch)
    manager = TaskManager()
    monkeypatch.setattr(server_live_routes, 'task_manager', manager)
    monkeypatch.setattr(server_live_routes, 'get_host_manager', lambda: fake.registry)
    calls = []

    def fake_call_host(host_info, path, method='GET', data=None, timeout=None):
        calls.append((host_info['host_name'], path, data))
        return {'success': True, 'aborted': True}, 200

    monkeypatch.setattr(server_live_routes, 'call_host', fake_call_host)
    return fake, manager, calls


def _task(manager, team=common.TEAM_A, host='host-1', device='device1'):
    return manager.create_task('script_execute', {'script_name': 'goto_live', 'host_name': host,
                                                  'device_id': device, 'team_id': team})


def _client(perms=RUN):
    return common.make_app(server_live_routes.server_live_bp, permissions=perms).test_client()


def _get(client, task_id, team=common.TEAM_A):
    return client.get(f'/server/run-management/live/{task_id}', query_string={'team_id': team})


def test_running_task_with_progress(env):
    _, manager, _ = env
    task_id = _task(manager)
    manager.record_progress(task_id, {'step_number': 2, 'total_steps': 5, 'message': 'zapping'})
    body = _get(_client(), task_id).get_json()
    assert body['status'] == 'running' and body['stale'] is False
    assert body['progress']['completed'] == 2 and body['progress']['total'] == 5
    assert body['eta_ms'] is not None and body['can_stop'] is True
    assert body['script_result_id'] is None and body['device_name'] == 'device1'


def test_no_producer_totals_means_null_progress_and_eta(env):
    _, manager, _ = env
    body = _get(_client(), _task(manager)).get_json()
    assert body['progress'] is None and body['eta_ms'] is None


def test_silence_marks_stale_not_complete(env):
    _, manager, _ = env
    task_id = _task(manager)
    manager.get_task(task_id)['created_at'] = time.time() - adapter.STALE_AFTER_SECONDS - 5
    body = _get(_client(), task_id).get_json()
    assert body['status'] == 'running' and body['stale'] is True


def test_missing_task_is_unknown(env):
    resp = _get(_client(), 'does-not-exist')
    assert resp.status_code == 404 and resp.get_json()['status'] == 'unknown'


def test_other_team_or_out_of_scope_host_cannot_see_or_stop(env):
    _, manager, calls = env
    foreign = _task(manager, team=common.TEAM_B)
    elsewhere = _task(manager, host='host-of-another-server')
    client = _client()
    for task_id in (foreign, elsewhere):
        assert _get(client, task_id).status_code == 404
        assert client.post(f'/server/run-management/live/{task_id}/stop',
                           json={'team_id': common.TEAM_A}).status_code == 404
    narrowed = client.get(f'/server/run-management/live/{_task(manager)}',
                          query_string={'team_id': common.TEAM_A, 'host_filter': '["host-2"]'})
    assert narrowed.status_code == 404
    assert calls == []


def test_completion_hands_off_to_durable_result(env):
    fake, manager, _ = env
    result = common.script_result()
    fake.tables['script_results'] = [result]
    task_id = _task(manager)
    manager.complete_task(task_id, {'script_result_id': result['id']}, None, success=True)
    body = _get(_client(), task_id).get_json()
    assert body['status'] == 'passed' and body['script_result_id'] == result['id']
    assert body['can_stop'] is False


def test_completion_pointing_at_another_teams_result_is_not_exposed(env):
    fake, manager, _ = env
    foreign = common.script_result(team_id=common.TEAM_B)
    fake.tables['script_results'] = [foreign]
    task_id = _task(manager)
    manager.complete_task(task_id, {'script_result_id': foreign['id']}, 'boom', success=False)
    body = _get(_client(), task_id).get_json()
    assert body['status'] == 'failed' and body['script_result_id'] is None


def test_stop_calls_host_abort_with_task_id_and_marks_cancellation(env):
    _, manager, calls = env
    task_id = _task(manager)
    resp = _client().post(f'/server/run-management/live/{task_id}/stop', json={'team_id': common.TEAM_A})
    assert resp.status_code == 202 and resp.get_json()['success'] is True
    assert calls == [('host-1', '/host/script/abort', {'device_id': 'device1', 'task_id': task_id})]
    manager.complete_task(task_id, {}, 'killed', success=False)
    assert _get(_client(), task_id).get_json()['status'] == 'cancelled'


def test_stop_refused_when_host_has_no_process_for_this_task(env, monkeypatch):
    _, manager, _ = env
    monkeypatch.setattr(server_live_routes, 'call_host',
                        lambda *a, **k: ({'success': True, 'aborted': False, 'message': 'not this task'}, 200))
    task_id = _task(manager)
    resp = _client().post(f'/server/run-management/live/{task_id}/stop', json={'team_id': common.TEAM_A})
    assert resp.status_code == 409
    manager.complete_task(task_id, {}, 'boom', success=False)
    assert _get(_client(), task_id).get_json()['status'] == 'failed'  # not mislabelled as cancelled


def test_stop_of_finished_task_is_409(env):
    _, manager, calls = env
    task_id = _task(manager)
    manager.complete_task(task_id, {}, None, success=True)
    resp = _client().post(f'/server/run-management/live/{task_id}/stop', json={'team_id': common.TEAM_A})
    assert resp.status_code == 409 and calls == []


def test_stop_requires_run_permission_and_can_stop_reflects_it(env):
    _, manager, _ = env
    task_id = _task(manager)
    viewer_like = _client(perms=VIEW)
    assert _get(viewer_like, task_id).get_json()['can_stop'] is False
    assert viewer_like.post(f'/server/run-management/live/{task_id}/stop',
                            json={'team_id': common.TEAM_A}).status_code == 403


def test_task_scoped_abort_on_host(monkeypatch):
    from shared.src.lib.executors import script_executor

    class Proc:
        pid = 4242

        def poll(self):
            return None

    killed = []
    monkeypatch.setattr(script_executor, '_kill_process_tree', lambda p: killed.append(p))
    proc = Proc()
    script_executor._register_running_process('device7', proc, 'goto_live', task_id='task-new')
    stale = script_executor.abort_running_script('device7', task_id='task-old')
    assert stale['aborted'] is False and killed == []
    current = script_executor.abort_running_script('device7', task_id='task-new')
    assert current['aborted'] is True and killed == [proc]


def test_device_filtered_workspace_sees_and_stops_its_device(env, monkeypatch):
    # Task records carry the device id; the workspace filter is resolved to the
    # display name results use. Both must line up for status and Stop.
    fake, manager, calls = env
    from backend_server.src.services.analytics import scope as scope_mod
    registry = common.FakeHosts({'host-1': [('device1', 'Living room TV'), ('device2', 'Bedroom')]})
    monkeypatch.setattr(scope_mod, 'get_host_manager', lambda: registry)
    monkeypatch.setattr(server_live_routes, 'get_host_manager', lambda: registry)
    client = _client()
    task_id = _task(manager)
    in_ws = {'team_id': common.TEAM_A, 'device_filter': '["host-1:device1"]'}
    body = client.get(f'/server/run-management/live/{task_id}', query_string=in_ws)
    assert body.status_code == 200
    assert body.get_json()['device_name'] == 'Living room TV' and body.get_json()['device_id'] == 'device1'
    stop = client.post(f'/server/run-management/live/{task_id}/stop', json=in_ws)
    assert stop.status_code == 202
    assert calls == [('host-1', '/host/script/abort', {'device_id': 'device1', 'task_id': task_id})]

    other_ws = {'team_id': common.TEAM_A, 'device_filter': '["host-1:device2"]'}
    other = _task(manager)
    assert client.get(f'/server/run-management/live/{other}', query_string=other_ws).status_code == 404
    assert client.post(f'/server/run-management/live/{other}/stop', json=other_ws).status_code == 404
    assert len(calls) == 1
