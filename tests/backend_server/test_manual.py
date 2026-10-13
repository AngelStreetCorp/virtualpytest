"""Manual run sessions (TASK-42 §4.2, §9 Manual).

The transactional parts (idempotent create, optimistic concurrency, exactly
one script_results row on concurrent finalize) live in SQL functions and are
exercised for real in ``test_run_services_pg.py``. Here the RPCs are emulated
with the same semantics to pin the route contract.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_manual_routes import server_manual_bp  # noqa: E402
from backend_server.src.services.manual import sessions as manual  # noqa: E402
from shared.src.lib.database.run_rpc import RunDbError  # noqa: E402

pytestmark = pytest.mark.unit

PERMS = ['reports.manual:execute']
TESTCASE_ID = '11111111-1111-1111-1111-111111111111'


class ManualModel:
    def __init__(self, fake):
        self.fake = fake
        self.results = []
        fake.tables.setdefault('manual_sessions', [])
        fake.tables.setdefault('manual_session_steps', [])
        fake.rpc_handlers.update({
            'rm_create_manual_session': self.create,
            'rm_update_manual_session': self.update,
            'rm_finalize_manual_session': self.finalize,
        })

    def _session(self, p):
        for s in self.fake.tables['manual_sessions']:
            if s['team_id'] == p['p_team_id'] and s['id'] == p['p_session_id']:
                return s
        raise Exception("{'code': 'P0001', 'message': 'rm:not_found'}")

    def create(self, p):
        for s in self.fake.tables['manual_sessions']:
            if s['team_id'] == p['p_team_id'] and s['idempotency_key'] == p['p_idempotency_key']:
                return {'id': s['id'], 'created': False, 'actor_id': s['actor_id']}
        sid = common.new_id()
        self.fake.tables['manual_sessions'].append({
            'id': sid, 'team_id': p['p_team_id'], 'actor_id': p['p_actor_id'],
            'idempotency_key': p['p_idempotency_key'], 'testcase_id': p['p_testcase_id'],
            'testcase_version': p['p_testcase_version'], 'testcase_name': p['p_testcase_name'],
            'testcase_snapshot': p['p_testcase_snapshot'], 'host_name': p['p_host_name'],
            'device_name': p['p_device_name'], 'environment': p['p_environment'], 'status': 'in_progress',
            'optimistic_version': 1, 'script_result_id': None,
        })
        for i, step in enumerate(p['p_steps']):
            self.fake.tables['manual_session_steps'].append({
                'team_id': p['p_team_id'], 'session_id': sid, 'ordinal': i, 'label': step['label'],
                'expected': step.get('expected'), 'required': step['required'], 'outcome': None,
                'note': None, 'evidence_url': None})
        return {'id': sid, 'created': True, 'actor_id': p['p_actor_id']}

    def update(self, p):
        s = self._session(p)
        if s['status'] != 'in_progress':
            raise Exception("{'message': 'rm:not_in_progress'}")
        if s['optimistic_version'] != p['p_expected_version']:
            raise Exception("{'message': 'rm:version_conflict'}")
        for change in p['p_steps']:
            step = next(st for st in self.fake.tables['manual_session_steps']
                        if st['session_id'] == s['id'] and st['ordinal'] == change['ordinal'])
            step.update({k: v for k, v in change.items() if k != 'ordinal'})
        s['optimistic_version'] += 1
        return s['optimistic_version']

    def finalize(self, p):
        s = self._session(p)
        if s['status'] == 'finalized':
            return {'script_result_id': s['script_result_id'], 'already_finalized': True}
        if p['p_expected_version'] is not None and s['optimistic_version'] != p['p_expected_version']:
            raise Exception("{'message': 'rm:version_conflict'}")
        steps = [st for st in self.fake.tables['manual_session_steps'] if st['session_id'] == s['id']]
        missing = sum(1 for st in steps if st['required'] and st['outcome'] is None)
        if missing:
            raise Exception(f"{{'message': 'rm:incomplete {missing} required step(s) have no outcome'}}")
        rid = common.new_id()
        self.results.append({'id': rid, 'actor': p['p_actor_id'],
                             'success': all(st['outcome'] == 'passed' for st in steps if st['required'])
                             and not any(st['outcome'] == 'failed' for st in steps)})
        s.update(status='finalized', script_result_id=rid, optimistic_version=s['optimistic_version'] + 1)
        return {'script_result_id': rid, 'already_finalized': False}


@pytest.fixture
def env(monkeypatch):
    fake = common.install(monkeypatch)
    model = ManualModel(fake)
    import shared.src.lib.database.testcase_db as testcase_db
    monkeypatch.setattr(testcase_db, 'get_testcase', lambda tid, team: {
        'testcase_id': tid, 'environment': 'test'} if tid == TESTCASE_ID and team == common.TEAM_A else None)
    monkeypatch.setattr(testcase_db, 'get_testcase_versions', lambda tid, team, limit=10: [{
        'testcase_id': tid, 'version_number': 4, 'testcase_name': 'Login smoke', 'userinterface_name': 'ui_a',
        'graph_json': {'nodes': [{'type': 'start'}, {'type': 'action', 'data': {'label': 'Press OK'}},
                                 {'type': 'verification', 'data': {'label': 'Home visible', 'expected': 'home menu'}},
                                 {'type': 'success'}]}}])
    client = common.make_app(server_manual_bp, permissions=PERMS).test_client()
    return fake, model, client


def _create(client, **extra):
    body = {'team_id': common.TEAM_A, 'idempotency_key': 'k-1', 'testcase_id': TESTCASE_ID,
            'host_name': 'host-1', 'device_name': 'device1', **extra}
    return client.post('/server/manual-sessions', json=body)


def test_create_snapshots_testcase_and_is_idempotent(env):
    fake, _, client = env
    first = _create(client)
    assert first.status_code == 201
    session = first.get_json()
    assert session['testcase_version'] == 4 and session['testcase_name'] == 'Login smoke'
    assert session['testcase_snapshot']['graph_json']['nodes'][1]['data']['label'] == 'Press OK'
    assert [s['label'] for s in session['steps']] == ['Press OK', 'Home visible']
    assert session['steps'][1]['expected'] == 'home menu'
    assert session['optimistic_version'] == 1 and session['environment'] == 'test'
    again = _create(client)
    assert again.status_code == 200 and again.get_json()['id'] == session['id']
    assert len(fake.tables['manual_sessions']) == 1


def test_create_takes_the_device_display_name(env, monkeypatch):
    # script_results.device_name is the display name; the manual result must match it.
    from backend_server.src.services.analytics import scope as scope_mod
    registry = common.FakeHosts({'host-1': [('device1', 'Living room TV')]})
    monkeypatch.setattr(scope_mod, 'get_host_manager', lambda: registry)
    _, _, client = env
    assert _create(client, device_name='Living room TV',
                   device_filter='["host-1:device1"]').status_code == 201
    assert _create(client, idempotency_key='k-2', device_name='Bedroom').status_code == 404


def test_create_requires_host_device_in_scope(env):
    _, _, client = env
    assert _create(client, host_name='host-of-another-server').status_code == 404
    assert _create(client, device_name='device9').status_code == 404  # not registered on host-1
    assert _create(client, host_name='host-2', device_name='device2').status_code == 404
    # registered, but outside the workspace device filter
    assert _create(client, device_name='device2', device_filter='["host-1:device1"]').status_code == 404
    assert _create(client, host_name=None).status_code == 400
    assert _create(client, testcase_id=common.new_id()).status_code == 404


def test_conflicting_edit_is_409_with_current_state(env):
    _, _, client = env
    sid = _create(client).get_json()['id']
    url = f'/server/manual-sessions/{sid}'
    ok = client.patch(url, json={'team_id': common.TEAM_A, 'expected_version': 1,
                                 'steps': [{'ordinal': 0, 'outcome': 'passed'}]})
    assert ok.status_code == 200 and ok.get_json()['optimistic_version'] == 2
    stale = client.patch(url, json={'team_id': common.TEAM_A, 'expected_version': 1,
                                    'steps': [{'ordinal': 0, 'outcome': 'failed'}]})
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'version_conflict'
    assert stale.get_json()['current']['steps'][0]['outcome'] == 'passed'


@pytest.mark.parametrize('step', [
    {'ordinal': 0, 'outcome': 'great'}, {'ordinal': -1}, {'outcome': 'passed'},
    {'ordinal': 0, 'evidence_url': 'javascript:alert(1)'}, {'ordinal': 0, 'note': 'x' * 2001},
])
def test_step_validation(env, step):
    _, _, client = env
    sid = _create(client).get_json()['id']
    resp = client.patch(f'/server/manual-sessions/{sid}', json={'team_id': common.TEAM_A, 'expected_version': 1,
                                                                'steps': [step]})
    assert resp.status_code == 400


def test_finalize_blocks_on_missing_outcomes_then_is_idempotent(env):
    _, model, client = env
    sid = _create(client).get_json()['id']
    url = f'/server/manual-sessions/{sid}'
    incomplete = client.post(f'{url}/finalize', json={'team_id': common.TEAM_A})
    assert incomplete.status_code == 422
    client.patch(url, json={'team_id': common.TEAM_A, 'expected_version': 1, 'steps': [
        {'ordinal': 0, 'outcome': 'passed'}, {'ordinal': 1, 'outcome': 'passed'}]})
    first = client.post(f'{url}/finalize', json={'team_id': common.TEAM_A, 'expected_version': 2})
    assert first.status_code == 201
    second = client.post(f'{url}/finalize', json={'team_id': common.TEAM_A, 'expected_version': 2})
    assert second.status_code == 200
    assert second.get_json()['idempotent'] is True
    assert first.get_json()['script_result_id'] == second.get_json()['script_result_id']
    assert len(model.results) == 1 and model.results[0]['actor'] == common.USER_A
    assert model.results[0]['success'] is True
    session = first.get_json()['session']
    assert session['summary']['steps_without_evidence'] == 2
    assert all(step['evidence_missing'] for step in session['steps'])


def test_only_the_actor_may_change_or_finalize(env, monkeypatch):
    fake, _, owner = env
    sid = _create(owner).get_json()['id']
    other = common.make_app(server_manual_bp, user_id=common.USER_B, permissions=PERMS).test_client()
    assert other.get(f'/server/manual-sessions/{sid}', query_string={'team_id': common.TEAM_A}).status_code == 200
    assert other.patch(f'/server/manual-sessions/{sid}', json={'team_id': common.TEAM_A, 'expected_version': 1,
                                                               'steps': []}).status_code == 403
    assert other.post(f'/server/manual-sessions/{sid}/finalize', json={'team_id': common.TEAM_A}).status_code == 403


def test_cross_team_session_is_not_found(env):
    _, _, client = env
    sid = _create(client).get_json()['id']
    assert client.get(f'/server/manual-sessions/{sid}', query_string={'team_id': common.TEAM_B}).status_code == 404


def test_idempotency_key_reused_by_someone_else_is_refused(env):
    _, _, owner = env
    _create(owner)
    other = common.make_app(server_manual_bp, user_id=common.USER_B, permissions=PERMS).test_client()
    assert _create(other).status_code == 409


def test_graph_steps_skip_structural_nodes():
    steps = manual.steps_from_graph({'nodes': [{'type': 'start'}, {'type': 'failure'},
                                               {'type': 'action', 'data': {'command': 'press_key'}}]})
    assert steps == [{'label': 'press_key', 'required': True, 'expected': None}]


def test_db_error_parsing():
    from shared.src.lib.database import run_rpc

    class Boom:
        def rpc(self, name, params):
            class _E:
                def execute(self):
                    raise Exception("{'code': 'P0001', 'message': 'rm:incomplete 2 required step(s) have no outcome'}")
            return _E()

    with pytest.raises(RunDbError) as exc:
        run_rpc.call_rpc('x', {}, client=Boom())
    assert exc.value.code == 'incomplete' and exc.value.detail.startswith('2 required')
