"""
TASK-42 — run-management routes through a production-like guard.

The app from ``make_task42_app`` runs the real viewer write floor, team-scope
check and permission resolution against the fresh-install role catalog
(053 + 060). Data lives in MemorySupabase, which really filters, so these tests
prove: role/permission outcomes, cross-team refusal, registered-host and
workspace scope on opaque ids, counts over all children before pagination,
latest-merge reporting, failures-only rerun selection (manual and discarded
excluded) and idempotent dispatch.

The RPC handlers below emulate the SQL functions' contract (scope / team /
cap checks) so the route wiring can be exercised; the SQL itself is verified
against Postgres in test_run_management_pg.py.
"""
import json
import os
import sys
from urllib.parse import quote

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from tests.backend_server._task42_common import (  # noqa: E402
    TEAM_A,
    TEAM_B,
    MemorySupabase,
    make_task42_app,
)
from backend_server.src.routes import server_run_management_routes as routes  # noqa: E402
from shared.src.lib.database import run_management_db as rmdb  # noqa: E402

pytestmark = pytest.mark.unit

U = '00000000-0000-0000-0000-0000000001{:02x}'.format
HOSTS = ['host-a', 'host-b']
BLUEPRINTS = (routes.server_run_management_bp, routes.server_run_groups_bp,
              routes.server_milestones_bp, routes.server_run_labels_bp)


def _result(i, **over):
    row = {
        'id': U(i), 'team_id': TEAM_A, 'script_name': 'zap.py', 'script_type': 'script',
        'userinterface_name': 'ui', 'environment': 'prod', 'host_name': 'host-a',
        'device_name': 'dev1', 'success': True, 'discard': False, 'checked': False,
        'started_at': f'2026-10-01T10:{i:02d}:00+00:00', 'completed_at': f'2026-10-01T10:{i:02d}:30+00:00',
        'execution_time_ms': 30000, 'milestone_id': None, 'run_group_id': None,
        'html_report_r2_url': None, 'logs_r2_url': None, 'error_msg': None, 'metadata': None,
    }
    row.update(over)
    return row


def _install_rpcs(db):
    def in_scope(params, sid):
        keys = params.get('p_device_keys')
        return any(str(r['id']) == str(sid) and str(r['team_id']) == str(params['p_team_id'])
                   and (params['p_host_names'] is None or r['host_name'] in params['p_host_names'])
                   and (keys is None or f"{r['host_name']}:{r['device_name']}" in keys)
                   for r in db.rows('script_results'))

    def replace_labels(params):
        labels = sorted(set(params['p_label_ids'] or []))
        if len(labels) > 10:
            raise Exception('run_mgmt:label_limit: at most 10 labels per entity')
        if params['p_entity_kind'] == 'script_result' and not in_scope(params, params['p_entity_id']):
            raise Exception('run_mgmt:not_found: script_result not found in this scope')
        team_labels = {str(d['id']) for d in db.rows('run_label_definitions')
                       if str(d['team_id']) == str(params['p_team_id'])}
        if not set(labels) <= team_labels:
            raise Exception('run_mgmt:foreign_label: label id(s) are not in this team')
        table, column = (('script_result_labels', 'script_result_id') if params['p_entity_kind'] == 'script_result'
                         else ('testcase_labels', 'testcase_id'))
        db.data[table] = [r for r in db.rows(table) if str(r[column]) != str(params['p_entity_id'])]
        for label in labels:
            db.rows(table).append({'team_id': params['p_team_id'], column: params['p_entity_id'], 'run_label_id': label})
        return {'label_ids': labels}

    def assign(params):
        ids = params['p_script_result_ids']
        if not all(in_scope(params, sid) for sid in ids):
            raise Exception('run_mgmt:not_found: some script results are not in this scope')
        for field, flag, table in (('milestone_id', 'p_set_milestone', 'run_milestones'),
                                   ('run_group_id', 'p_set_run_group', 'run_groups')):
            target = params['p_' + field]
            if params[flag] and target is not None and not any(
                    str(o['id']) == target and str(o['team_id']) == str(params['p_team_id']) and not o.get('archived')
                    for o in db.rows(table)):
                raise Exception(f'run_mgmt:not_found: {field} not found or archived')
        for row in db.rows('script_results'):
            if str(row['id']) in ids:
                if params['p_set_milestone']:
                    row['milestone_id'] = params['p_milestone_id']
                if params['p_set_run_group']:
                    row['run_group_id'] = params['p_run_group_id']
        if params['p_set_labels']:
            for sid in ids:
                replace_labels({**params, 'p_entity_kind': 'script_result', 'p_entity_id': sid})
        return {'updated': len(ids), 'script_result_ids': ids}

    db.rpc_handlers['run_mgmt_replace_labels'] = replace_labels
    db.rpc_handlers['run_mgmt_assign_script_results'] = assign


@pytest.fixture
def env(monkeypatch):
    def build(role='admin', team_ids=(TEAM_A,), hosts=HOSTS, **kwargs):
        db = kwargs.pop('db', None) or MemorySupabase()
        _install_rpcs(db)
        app, _, state = make_task42_app(
            monkeypatch, blueprints=BLUEPRINTS, data_layer=rmdb, supabase_client=db, role=role,
            team_ids=team_ids, registered_hosts=hosts, host_manager_modules=(routes,), **kwargs)
        return app.test_client(), db
    return build


# ---------------------------------------------------------------------------
# Paths, permissions, team scope
# ---------------------------------------------------------------------------


def test_every_route_lives_under_server_prefix():
    import flask
    app = flask.Flask('paths')
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
    rules = [r.rule for r in app.url_map.iter_rules() if r.endpoint != 'static']
    assert rules and all(rule.startswith('/server/') for rule in rules)


def test_tester_can_create_label_with_shipped_role_defaults(env):
    client, db = env(role='tester')
    res = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': ' Nightly '})
    assert res.status_code == 201, res.get_json()
    assert res.get_json()['name'] == 'Nightly'


def test_viewer_reads_but_cannot_write(env):
    client, db = env(role='viewer')
    assert client.get(f'/server/run-groups?team_id={TEAM_A}').status_code == 200
    res = client.post('/server/run-groups', json={'team_id': TEAM_A, 'name': 'x'})
    assert res.status_code == 403
    assert db.rows('run_groups') == []


def test_role_without_edit_permission_is_refused(env):
    client, db = env(role='tester', role_defaults={'tester': ['reports.tests:view']})
    res = client.post('/server/milestones', json={'team_id': TEAM_A, 'name': 'M1'})
    assert res.status_code == 403
    assert 'reports.runs:edit' in res.get_json()['message']


def test_explicit_denial_beats_role_default(env):
    client, _ = env(role='developer', denied_permissions=['reports.runs:edit'])
    assert client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'x'}).status_code == 403


def test_member_of_team_a_cannot_name_team_b(env):
    client, db = env(role='tester', team_ids=(TEAM_A,))
    db.seed('run_groups', {'id': U(90), 'team_id': TEAM_B, 'name': 'theirs', 'archived': False, 'pinned': False})
    assert client.get(f'/server/run-groups?team_id={TEAM_B}').status_code == 403
    res = client.patch(f'/server/run-groups/{U(90)}', json={'team_id': TEAM_B, 'name': 'pwned'})
    assert res.status_code == 403
    assert db.rows('run_groups')[0]['name'] == 'theirs'


def test_foreign_team_object_id_is_not_found_from_own_team(env):
    client, db = env(role='tester')
    db.seed('run_groups', {'id': U(90), 'team_id': TEAM_B, 'name': 'theirs', 'archived': False, 'pinned': False})
    res = client.patch(f'/server/run-groups/{U(90)}', json={'team_id': TEAM_A, 'name': 'pwned'})
    assert res.status_code == 404
    assert db.rows('run_groups')[0]['name'] == 'theirs'


def test_team_id_is_required(env):
    client, _ = env()
    assert client.get('/server/run-labels').status_code == 400


# ---------------------------------------------------------------------------
# Governance validation
# ---------------------------------------------------------------------------


def test_label_rules(env):
    client, _ = env()
    assert client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'x' * 21}).status_code == 400
    assert client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'Smoke'}).status_code == 201
    dup = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'SMOKE '})
    assert dup.status_code == 409
    assert client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'c', 'color': 'red'}).status_code == 400


def test_group_archive_restore_keeps_member_links(env):
    client, db = env()
    gid = client.post('/server/run-groups', json={'team_id': TEAM_A, 'name': 'R1'}).get_json()['id']
    db.seed('script_results', _result(1, run_group_id=gid))
    assert client.patch(f'/server/run-groups/{gid}', json={'team_id': TEAM_A, 'archived': True}).get_json()['archived'] is True
    assert db.rows('script_results')[0]['run_group_id'] == gid
    listed = client.get(f'/server/run-groups?team_id={TEAM_A}').get_json()
    assert listed['total'] == 0
    assert client.post(f'/server/run-groups/{gid}/restore?team_id={TEAM_A}').get_json()['archived'] is False
    assert client.patch(f'/server/run-groups/{gid}', json={'team_id': TEAM_A, 'owner': 'me'}).status_code == 400


def test_label_delete_removes_assignments_only(env):
    client, db = env()
    lid = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'flaky'}).get_json()['id']
    db.seed('script_results', _result(1))
    assert client.put(f'/server/script-results/{U(1)}/labels', json={'team_id': TEAM_A, 'label_ids': [lid]}).status_code == 200
    out = client.delete(f'/server/run-labels/{lid}?team_id={TEAM_A}').get_json()
    assert out['removed_script_result_assignments'] == 1
    assert db.rows('script_result_labels') == [] and len(db.rows('script_results')) == 1


# ---------------------------------------------------------------------------
# Assignments and scope on opaque ids
# ---------------------------------------------------------------------------


def test_assigning_a_result_on_another_servers_host_is_404(env):
    client, db = env()
    db.seed('script_results', _result(1, host_name='host-on-other-server'))
    lid = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'l'}).get_json()['id']
    res = client.put(f'/server/script-results/{U(1)}/labels', json={'team_id': TEAM_A, 'label_ids': [lid]})
    assert res.status_code == 404
    assert db.rows('script_result_labels') == []


def test_workspace_host_filter_narrows_scope(env):
    client, db = env()
    db.seed('script_results', _result(1, host_name='host-b'))
    url = f'/server/run-management/summary/script/{U(1)}?team_id={TEAM_A}'
    assert client.get(url).status_code == 200
    assert client.get(url + '&host_filter=' + quote(json.dumps(['host-a']))).status_code == 404


def test_foreign_label_is_rejected(env):
    client, db = env()
    db.seed('script_results', _result(1))
    db.seed('run_label_definitions', {'id': U(80), 'team_id': TEAM_B, 'name': 'theirs'})
    res = client.put(f'/server/script-results/{U(1)}/labels', json={'team_id': TEAM_A, 'label_ids': [U(80)]})
    assert res.status_code == 400
    assert db.rows('script_result_labels') == []


def test_eleven_labels_is_a_4xx_before_any_write(env):
    client, db = env()
    db.seed('script_results', _result(1))
    res = client.put(f'/server/script-results/{U(1)}/labels',
                     json={'team_id': TEAM_A, 'label_ids': [U(60 + i) for i in range(11)]})
    assert res.status_code == 422
    assert db.rpc_calls == []


def test_batch_assignment_is_all_or_nothing_and_replaces_labels(env):
    client, db = env()
    db.seed('script_results', _result(1), _result(2), _result(3, host_name='elsewhere'))
    gid = client.post('/server/run-groups', json={'team_id': TEAM_A, 'name': 'G'}).get_json()['id']
    bad = client.put('/server/script-results/batch/assignments',
                     json={'team_id': TEAM_A, 'script_result_ids': [U(1), U(3)], 'run_group_id': gid})
    assert bad.status_code == 404
    assert all(r['run_group_id'] is None for r in db.rows('script_results'))
    ok = client.put('/server/script-results/batch/assignments',
                    json={'team_id': TEAM_A, 'script_result_ids': [U(1), U(2)], 'run_group_id': gid, 'label_ids': []})
    assert ok.status_code == 200 and ok.get_json()['updated'] == 2
    assert [r['run_group_id'] for r in db.rows('script_results')] == [gid, gid, None]
    unknown = client.put('/server/script-results/batch/assignments',
                         json={'team_id': TEAM_A, 'script_result_ids': [U(1)], 'owner': 'x'})
    assert unknown.status_code == 400


def test_archived_group_cannot_receive_new_members_but_clearing_works(env):
    client, db = env()
    db.seed('script_results', _result(1))
    db.seed('run_groups', {'id': U(70), 'team_id': TEAM_A, 'name': 'old', 'archived': True, 'pinned': False})
    assert client.put(f'/server/script-results/{U(1)}/run-group',
                      json={'team_id': TEAM_A, 'run_group_id': U(70)}).status_code == 404
    assert client.put(f'/server/script-results/{U(1)}/run-group',
                      json={'team_id': TEAM_A, 'run_group_id': None}).status_code == 200


def test_results_listing_filters_then_pages(env):
    client, db = env()
    db.seed('script_results', *[_result(i, milestone_id=U(50) if i % 2 else None) for i in range(1, 8)])
    db.seed('script_results', _result(20, milestone_id=U(50), host_name='elsewhere'))
    res = client.get(f'/server/run-management/results?team_id={TEAM_A}&milestone_id={U(50)}&limit=2').get_json()
    assert res['total'] == 4
    assert [r['id'] for r in res['items']] == [U(7), U(5)]
    assert all('labels' in r for r in res['items'])


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_script_summary_is_one_verdict_with_separate_evidence(env):
    client, db = env()
    db.seed('script_results', _result(1, success=False, html_report_r2_url='https://r/1.html'))
    body = client.get(f'/server/run-management/summary/script/{U(1)}?team_id={TEAM_A}').get_json()
    assert body['identity'] == {'kind': 'script', 'id': U(1)}
    assert body['status'] == 'failed'
    assert body['counts']['total'] == 1 and body['counts']['failed'] == 1
    assert body['children']['total'] == 1
    assert body['evidence']['report_url'] == 'https://r/1.html'
    assert body['evidence']['steps'] is None
    assert body['trend']['window_days'] == 30 and len(body['trend']['points']) == 30


def test_script_summary_does_not_treat_same_name_history_as_children(env):
    client, db = env()
    db.seed('script_results', *[_result(i) for i in range(1, 6)])
    body = client.get(f'/server/run-management/summary/script/{U(5)}?team_id={TEAM_A}').get_json()
    assert body['children']['total'] == 1


def test_campaign_summary_takes_execution_id_and_counts_before_paging(env):
    client, db = env()
    outcomes, ids = [], []
    for order in range(1, 34):
        if order <= 12:
            outcomes.append({'execution_order': order, 'script_name': f's{order}', 'skipped': True})
            continue
        sid = U(order)
        ids.append(sid)
        db.seed('script_results', _result(order, id=sid, success=order > 16))  # 13..16 failed
        outcomes.append({'execution_order': order, 'script_name': f's{order}', 'script_result_id': sid})
    db.seed('campaign_executions', {
        'id': U(99), 'team_id': TEAM_A, 'campaign_name': 'nightly', 'host_name': 'host-a',
        'device_name': 'dev1', 'userinterface_name': 'ui', 'status': 'completed', 'success': False,
        'started_at': '2026-10-01T09:00:00+00:00', 'script_configurations': [{}] * 33,
        'script_result_ids': ids, 'metadata': {'script_outcomes': outcomes}})
    body = client.get(f'/server/run-management/summary/campaign/{U(99)}?team_id={TEAM_A}&limit=5&offset=10').get_json()
    c = body['counts']
    assert (c['total'], c['passed'], c['failed'], c['skipped']) == (33, 17, 4, 12)
    assert body['children']['total'] == 33 and len(body['children']['items']) == 5
    failed_only = client.get(f'/server/run-management/summary/campaign/{U(99)}?team_id={TEAM_A}&status=failed').get_json()
    assert failed_only['counts']['total'] == 33 and failed_only['children']['total'] == 4


def test_campaign_on_unregistered_host_is_404(env):
    client, db = env()
    db.seed('campaign_executions', {'id': U(98), 'team_id': TEAM_A, 'campaign_name': 'c', 'host_name': 'nope',
                                    'status': 'completed', 'script_configurations': [], 'script_result_ids': []})
    assert client.get(f'/server/run-management/summary/campaign/{U(98)}?team_id={TEAM_A}').status_code == 404


def test_group_summary_merges_latest_and_pages_after_aggregation(env):
    client, db = env()
    gid = U(70)
    db.seed('run_groups', {'id': gid, 'team_id': TEAM_A, 'name': 'G', 'archived': False, 'pinned': False})
    for i in range(1, 8):  # 7 identities (one per device)
        db.seed('script_results', _result(i, device_name=f'd{i}', run_group_id=gid, success=i != 3))
    db.seed('script_results', _result(8, device_name='d3', run_group_id=gid, success=True,
                                      started_at='2026-10-02T00:00:00+00:00'))  # d3 recovered
    body = client.get(f'/server/run-management/summary/group/{gid}?team_id={TEAM_A}&limit=2').get_json()
    assert body['counts']['total'] == 7 and body['counts']['passed'] == 7
    assert body['attempts']['total'] == 8 and body['attempts']['failed'] == 1
    assert len(body['children']['items']) == 2
    report = client.get(f'/server/run-groups/{gid}/report?team_id={TEAM_A}').get_json()
    assert report['attempts_total'] == 8 and len(report['rows']) == 7
    assert {r['device_name']: r['attempts'] for r in report['rows']}['d3'] == 2


def test_invalid_kind_is_400(env):
    client, _ = env()
    assert client.get(f'/server/run-management/summary/widget/{U(1)}?team_id={TEAM_A}').status_code == 400


# ---------------------------------------------------------------------------
# Group rerun
# ---------------------------------------------------------------------------


def _rerun_fixture(db):
    gid = U(70)
    db.seed('run_groups', {'id': gid, 'team_id': TEAM_A, 'name': 'G', 'archived': False, 'pinned': False})
    meta = {'parameters': '--x 1', 'device_id': 'device1'}
    db.seed('script_results',
            _result(1, script_name='a.py', success=False, run_group_id=gid, metadata=meta),
            _result(2, script_name='b.py', success=True, run_group_id=gid, metadata=meta),
            _result(3, script_name='m', script_type='manual', success=False, run_group_id=gid, metadata=meta),
            _result(4, script_name='d.py', success=False, discard=True, run_group_id=gid, metadata=meta))
    return gid


def test_failures_rerun_dispatches_once_and_replays_on_retry(env, monkeypatch):
    client, db = env(role='tester')
    gid = _rerun_fixture(db)
    created = []
    monkeypatch.setattr(routes, '_create_deployment',
                        lambda team_id, data: created.append((team_id, data)) or {'id': f'dep-{len(created)}'})
    body = {'team_id': TEAM_A, 'mode': 'failures', 'idempotency_key': 'click-1'}
    first = client.post(f'/server/run-groups/{gid}/rerun', json=body)
    assert first.status_code == 202, first.get_json()
    out = first.get_json()
    assert [d['script_result_id'] for d in out['dispatched']] == [U(1)]
    assert out['skipped_manual'] == [U(3)]
    assert created[0][1]['script_name'] == 'a.py' and created[0][1]['parameters'] == '--x 1'
    second = client.post(f'/server/run-groups/{gid}/rerun', json=body)
    assert second.status_code == 200 and second.get_json()['idempotent_replay'] is True
    assert len(created) == 1
    attempt = next(r for r in db.rows('script_results') if r['id'] == U(1))
    assert attempt['success'] is False and attempt['run_group_id'] == gid  # history untouched


def test_reusing_a_key_for_a_different_mode_is_409(env, monkeypatch):
    client, db = env()
    gid = _rerun_fixture(db)
    monkeypatch.setattr(routes, '_create_deployment', lambda team_id, data: {'id': 'dep'})
    client.post(f'/server/run-groups/{gid}/rerun', json={'team_id': TEAM_A, 'mode': 'all', 'idempotency_key': 'k'})
    res = client.post(f'/server/run-groups/{gid}/rerun', json={'team_id': TEAM_A, 'mode': 'failures', 'idempotency_key': 'k'})
    assert res.status_code == 409


def test_rerun_requires_run_permission(env, monkeypatch):
    client, db = env(role='viewer')
    gid = _rerun_fixture(db)
    res = client.post(f'/server/run-groups/{gid}/rerun', json={'team_id': TEAM_A, 'mode': 'all', 'idempotency_key': 'k'})
    assert res.status_code == 403
    assert db.rows('run_group_rerun_requests') == []


def test_rerun_validates_mode_and_key(env):
    client, db = env()
    gid = _rerun_fixture(db)
    assert client.post(f'/server/run-groups/{gid}/rerun', json={'team_id': TEAM_A, 'mode': 'some', 'idempotency_key': 'k'}).status_code == 400
    assert client.post(f'/server/run-groups/{gid}/rerun', json={'team_id': TEAM_A, 'mode': 'all'}).status_code == 400


def test_testcase_labels_are_team_scoped(env):
    client, db = env()
    db.seed('testcase_definitions', {'testcase_id': U(40), 'team_id': TEAM_B, 'testcase_name': 'theirs'})
    assert client.get(f'/server/testcase/{U(40)}/labels?team_id={TEAM_A}').status_code == 404
    db.seed('testcase_definitions', {'testcase_id': U(41), 'team_id': TEAM_A, 'testcase_name': 'mine'})
    lid = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'tc'}).get_json()['id']
    res = client.put(f'/server/testcase/{U(41)}/labels', json={'team_id': TEAM_A, 'label_ids': [lid]})
    assert res.status_code == 200 and [entry['name'] for entry in res.get_json()['labels']] == ['tc']


# ---------------------------------------------------------------------------
# Workspace device filter and evidence-based status
# ---------------------------------------------------------------------------

DEVICE_HOSTS = {'host-a': [('device1', 'dev1'), ('device2', 'dev2')], 'host-b': [('device1', 'tv-b')]}


def _two_device_group(db):
    gid = U(70)
    db.seed('run_groups', {'id': gid, 'team_id': TEAM_A, 'name': 'G', 'archived': False, 'pinned': False})
    meta = {'parameters': '', 'device_id': 'device1'}
    db.seed('script_results',
            _result(1, device_name='dev1', success=False, run_group_id=gid, metadata=meta),
            _result(2, device_name='dev2', success=False, run_group_id=gid, metadata=meta),
            _result(3, device_name='dev2', success=True, run_group_id=None))
    return gid


def test_device_filter_scopes_summary_report_and_rerun(env, monkeypatch):
    client, db = env(hosts=DEVICE_HOSTS)
    gid = _two_device_group(db)
    ws = '&device_filter=' + quote(json.dumps(['host-a:device1']))
    summary = client.get(f'/server/run-management/summary/group/{gid}?team_id={TEAM_A}{ws}').get_json()
    assert summary['counts']['total'] == 1 and summary['attempts']['total'] == 1
    assert summary['children']['items'][0]['device_name'] == 'dev1'
    assert summary['scope']['device_filter_applied'] is True
    report = client.get(f'/server/run-groups/{gid}/report?team_id={TEAM_A}{ws}').get_json()
    assert [r['device_name'] for r in report['rows']] == ['dev1'] and report['attempts_total'] == 1
    assert client.get(f'/server/run-management/summary/script/{U(2)}?team_id={TEAM_A}{ws}').status_code == 404
    assert client.get(f'/server/run-management/summary/script/{U(1)}?team_id={TEAM_A}{ws}').status_code == 200
    listing = client.get(f'/server/run-management/results?team_id={TEAM_A}{ws}').get_json()
    assert [r['id'] for r in listing['items']] == [U(1)]

    created = []
    monkeypatch.setattr(routes, '_create_deployment',
                        lambda team_id, data: created.append(data) or {'id': f'dep-{len(created)}'})
    out = client.post(f'/server/run-groups/{gid}/rerun', json={
        'team_id': TEAM_A, 'mode': 'failures', 'idempotency_key': 'ws-1',
        'device_filter': ['host-a:device1']}).get_json()
    assert [d['script_result_id'] for d in out['dispatched']] == [U(1)] and len(created) == 1


def test_device_filter_scopes_assignments(env):
    client, db = env(hosts=DEVICE_HOSTS)
    gid = _two_device_group(db)
    lid = client.post('/server/run-labels', json={'team_id': TEAM_A, 'name': 'ws'}).get_json()['id']
    ws = ['host-a:device1']
    out_of_ws = client.put(f'/server/script-results/{U(3)}/labels',
                           json={'team_id': TEAM_A, 'label_ids': [lid], 'device_filter': ws})
    assert out_of_ws.status_code == 404 and db.rows('script_result_labels') == []
    assert client.put(f'/server/script-results/{U(3)}/run-group',
                      json={'team_id': TEAM_A, 'run_group_id': gid, 'device_filter': ws}).status_code == 404
    batch = client.put('/server/script-results/batch/assignments', json={
        'team_id': TEAM_A, 'script_result_ids': [U(1), U(3)], 'milestone_id': None, 'device_filter': ws})
    assert batch.status_code == 404
    assert client.get(f'/server/script-results/{U(3)}/labels?team_id={TEAM_A}&device_filter='
                      + quote(json.dumps(ws))).status_code == 404
    ok = client.put(f'/server/script-results/{U(1)}/labels',
                    json={'team_id': TEAM_A, 'label_ids': [lid], 'device_filter': ws})
    assert ok.status_code == 200
    rpc = [p for name, p in db.rpc_calls if name == 'run_mgmt_replace_labels'][-1]
    assert rpc['p_device_keys'] == ['host-a:dev1'] and rpc['p_host_names'] == ['host-a']


def test_malformed_device_filter_is_400(env):
    client, db = env(hosts=DEVICE_HOSTS)
    _two_device_group(db)
    bad = client.get(f'/server/run-management/summary/script/{U(1)}?team_id={TEAM_A}&device_filter='
                     + quote(json.dumps(['no-colon'])))
    assert bad.status_code == 400


def test_running_member_is_unknown_not_failed(env, monkeypatch):
    client, db = env()
    gid = U(70)
    db.seed('run_groups', {'id': gid, 'team_id': TEAM_A, 'name': 'G', 'archived': False, 'pinned': False})
    meta = {'parameters': '', 'device_id': 'device1'}
    db.seed('script_results',
            _result(1, device_name='d1', run_group_id=gid, success=True, metadata=meta),
            # inserted at start: success=false, no duration yet
            _result(2, device_name='d2', run_group_id=gid, success=False, execution_time_ms=None, metadata=meta))
    body = client.get(f'/server/run-management/summary/group/{gid}?team_id={TEAM_A}').get_json()
    assert body['status'] == 'unknown'
    assert body['counts']['failed'] == 0 and body['counts']['unknown'] == 1
    assert body['attempts']['failed'] == 0 and body['attempts']['unknown'] == 1
    report = client.get(f'/server/run-groups/{gid}/report?team_id={TEAM_A}').get_json()
    assert report['counts']['failed'] == 0 and report['rerun_preview']['failures']['targets'] == 0
    script = client.get(f'/server/run-management/summary/script/{U(2)}?team_id={TEAM_A}').get_json()
    assert script['status'] == 'unknown'
    created = []
    monkeypatch.setattr(routes, '_create_deployment', lambda team_id, data: created.append(data) or {'id': 'x'})
    out = client.post(f'/server/run-groups/{gid}/rerun',
                      json={'team_id': TEAM_A, 'mode': 'failures', 'idempotency_key': 'run-1'}).get_json()
    assert out['dispatched'] == [] and created == []


def test_device_filter_on_campaign_matches_recorded_device_id_or_name(env):
    # campaign_executions.device_name holds the configured device (usually its id).
    client, db = env(hosts=DEVICE_HOSTS)
    db.seed('campaign_executions', {
        'id': U(97), 'team_id': TEAM_A, 'campaign_name': 'c', 'host_name': 'host-a', 'device_name': 'device1',
        'status': 'completed', 'success': True, 'started_at': '2026-10-01T09:00:00+00:00',
        'script_configurations': [], 'script_result_ids': []})
    url = f'/server/run-management/summary/campaign/{U(97)}?team_id={TEAM_A}&device_filter='
    assert client.get(url + quote(json.dumps(['host-a:device1']))).status_code == 200
    assert client.get(url + quote(json.dumps(['host-a:device2']))).status_code == 404
