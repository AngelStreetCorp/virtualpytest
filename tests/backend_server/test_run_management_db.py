"""
TASK-42 — run governance data layer and summary/rerun services (unit level).

Behaviour, not call shapes: the MemorySupabase client really filters, so these
tests prove scope-before-window, unique-name conflicts, idempotent rerun
claims, latest-merge ordering and the campaign child accounting. The SQL
bodies of the RPCs (atomicity, the concurrent 10-label cap, composite FKs, RLS)
are covered against real Postgres in test_run_management_pg.py.

Defect / share / custom-report / manual helpers of run_management_db are tested
in their own modules' test files.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from tests.backend_server._task42_common import TEAM_A, TEAM_B, FakeSupabaseClient, MemorySupabase  # noqa: E402
from shared.src.lib.database import run_management_db as rmdb  # noqa: E402
from shared.src.lib.database.run_management_db import RunManagementError  # noqa: E402
from backend_server.src.services.governance import rerun_payload as rerun  # noqa: E402
from backend_server.src.services.governance import summary as summ  # noqa: E402

pytestmark = pytest.mark.unit

U = '00000000-0000-0000-0000-0000000000{:02x}'.format


@pytest.fixture
def mem(monkeypatch):
    db = MemorySupabase()
    monkeypatch.setattr(rmdb, 'get_supabase', lambda: db)
    return db


def _result(i, **over):
    row = {
        'id': U(i), 'team_id': TEAM_A, 'script_name': 'zap.py', 'script_type': 'script',
        'userinterface_name': 'ui', 'environment': 'prod', 'host_name': 'host-a',
        'device_name': 'dev1', 'success': True, 'discard': False, 'execution_time_ms': 30000,
        'started_at': f'2026-10-01T10:{i:02d}:00+00:00', 'completed_at': None,
        'milestone_id': None, 'run_group_id': None,
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------


def test_clean_name_trims_and_bounds():
    assert rmdb.clean_name('  smoke  ', 20) == 'smoke'
    with pytest.raises(RunManagementError) as e:
        rmdb.clean_name('   ', 20)
    assert e.value.code == 'invalid'
    with pytest.raises(RunManagementError):
        rmdb.clean_name('x' * 21, 20)
    assert rmdb.clean_name('x' * 20, 20) == 'x' * 20


def test_clean_color_normalizes_and_rejects():
    assert rmdb.clean_color('#AbC') == '#abc'
    assert rmdb.clean_color('') is None
    for bad in ('red', '#12', 'javascript:alert(1)', 123):
        with pytest.raises(RunManagementError):
            rmdb.clean_color(bad)


def test_clean_timestamp_assumes_utc_and_rejects_garbage():
    assert rmdb.clean_timestamp('2026-10-03', 'due_at') == '2026-10-03T00:00:00+00:00'
    assert rmdb.clean_timestamp('2026-10-03T12:00:00+02:00', 'due_at') == '2026-10-03T10:00:00+00:00'
    with pytest.raises(RunManagementError):
        rmdb.clean_timestamp('next friday', 'due_at')


def test_translate_db_error_maps_rpc_tokens_and_unique_violation():
    err = rmdb._translate_db_error(Exception("{'message': 'run_mgmt:label_limit: at most 10 labels per entity'}"))
    assert isinstance(err, RunManagementError) and err.code == 'limit'
    err = rmdb._translate_db_error(Exception('run_mgmt:not_found: script_result not found in this scope'))
    assert err.code == 'not_found'
    err = rmdb._translate_db_error(Exception('run_mgmt:foreign_label: 1 label id(s) are not in this team'))
    assert err.code == 'invalid'
    dup = Exception('duplicate key value violates unique constraint "run_label_definitions_team_lower_name_key"')
    assert rmdb._translate_db_error(dup).code == 'conflict'
    other = RuntimeError('connection reset')
    assert rmdb._translate_db_error(other) is other


# ---------------------------------------------------------------------------
# governance objects
# ---------------------------------------------------------------------------


def test_label_names_are_case_insensitive_unique_per_team(mem):
    rmdb.create_run_label(TEAM_A, name=' Smoke ')
    with pytest.raises(RunManagementError) as e:
        rmdb.create_run_label(TEAM_A, name='SMOKE')
    assert e.value.code == 'conflict'
    # Another team may use the same name.
    assert rmdb.create_run_label(TEAM_B, name='smoke')['team_id'] == TEAM_B
    assert [r['name'] for r in mem.rows('run_label_definitions')] == ['Smoke', 'smoke']


def test_group_create_update_archive_restore_keeps_links(mem):
    group = rmdb.create_run_group(TEAM_A, {'name': 'Release 1', 'color': '#00FF00'}, created_by='u1')
    mem.seed('script_results', _result(1, run_group_id=group['id']))
    archived = rmdb.archive_run_group(TEAM_A, group['id'])
    assert archived['archived'] is True
    assert mem.rows('script_results')[0]['run_group_id'] == group['id']
    assert rmdb.restore_run_group(TEAM_A, group['id'])['archived'] is False
    with pytest.raises(RunManagementError) as e:
        rmdb.update_run_group(TEAM_A, group['id'], {'owner': 'x'})
    assert e.value.code == 'invalid'


def test_update_other_teams_group_is_not_found(mem):
    group = rmdb.create_run_group(TEAM_B, {'name': 'theirs'})
    with pytest.raises(RunManagementError) as e:
        rmdb.update_run_group(TEAM_A, group['id'], {'name': 'mine now'})
    assert e.value.code == 'not_found'
    assert mem.rows('run_groups')[0]['name'] == 'theirs'


def test_list_groups_excludes_archived_and_paginates_after_filter(mem):
    for i in range(5):
        rmdb.create_run_group(TEAM_A, {'name': f'g{i}'})
    rmdb.create_run_group(TEAM_A, {'name': 'old', 'archived': True})
    rmdb.create_run_group(TEAM_B, {'name': 'other'})
    rows, total = rmdb.list_run_groups(TEAM_A, limit=2, offset=0)
    assert total == 5 and [r['name'] for r in rows] == ['g0', 'g1']
    rows, total = rmdb.list_run_groups(TEAM_A, include_archived=True, limit=50)
    assert total == 6


def test_delete_label_removes_assignments_not_results(mem):
    label = rmdb.create_run_label(TEAM_A, name='flaky')
    mem.seed('script_results', _result(1))
    mem.seed('script_result_labels', {'team_id': TEAM_A, 'script_result_id': U(1), 'run_label_id': label['id']})
    out = rmdb.delete_run_label(TEAM_A, label['id'])
    assert out['removed_script_result_assignments'] == 1
    assert mem.rows('script_result_labels') == []
    assert len(mem.rows('script_results')) == 1


def test_rename_is_canonical_because_assignments_hold_the_id(mem):
    label = rmdb.create_run_label(TEAM_A, name='nightly')
    mem.seed('script_result_labels', {'team_id': TEAM_A, 'script_result_id': U(1), 'run_label_id': label['id']})
    rmdb.update_run_label(TEAM_A, label['id'], {'name': 'Nightly-2'})
    labels = rmdb.labels_for_entities(TEAM_A, 'script_result', [U(1)])
    assert [entry['name'] for entry in labels[U(1)]] == ['Nightly-2']


def test_labels_for_120_results_stay_under_the_proxy_url_limit(mem, monkeypatch):
    """BUG-0416: PostgREST echoes the query in Content-Location; >~85 uuids per
    in.() overflows the proxy's 4 KB header buffer -> 502. Chunk at IN_FILTER_CHUNK."""
    from shared.src.lib.database import script_results_db as srdb
    from shared.src.lib.database.in_filter import IN_FILTER_CHUNK
    label = rmdb.create_run_label(TEAM_A, name='nightly')
    ids = ['00000000-0000-0000-0000-{:012x}'.format(i) for i in range(120)]
    for rid in ids:
        mem.seed('script_result_labels', {'team_id': TEAM_A, 'script_result_id': rid, 'run_label_id': label['id']})
    sizes = []
    real_table = mem.table

    def spy_table(name):
        query = real_table(name)
        real_in = query.in_

        def in_(col, values):
            sizes.append(len(list(values)))
            return real_in(col, values)
        query.in_ = in_
        return query
    monkeypatch.setattr(mem, 'table', spy_table)

    labels = rmdb.labels_for_entities(TEAM_A, 'script_result', ids)
    rows = [{'id': rid} for rid in ids]
    srdb._attach_labels(mem, TEAM_A, rows)

    assert all(n <= IN_FILTER_CHUNK <= 50 for n in sizes) and sum(sizes) == 240
    assert all(labels[rid][0]['name'] == 'nightly' for rid in ids)
    assert all(row['labels'][0]['name'] == 'nightly' for row in rows)


# ---------------------------------------------------------------------------
# assignments -> RPC parameters
# ---------------------------------------------------------------------------


def test_replace_labels_rejects_eleven_before_the_database(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(rmdb, 'get_supabase', lambda: client)
    with pytest.raises(RunManagementError) as e:
        rmdb.replace_labels(TEAM_A, 'script_result', U(1), [U(i) for i in range(11)], host_names=['h'])
    assert e.value.code == 'limit'
    assert not client.tables  # no RPC issued


def test_replace_labels_passes_host_scope_and_dedups(mem):
    mem.rpc_handlers['run_mgmt_replace_labels'] = lambda p: {'entity_id': p['p_entity_id'], 'label_ids': p['p_label_ids']}
    rmdb.replace_labels(TEAM_A, 'script_result', U(1), [U(3), U(3), U(2)], host_names=['host-a'], actor='u1')
    name, params = mem.rpc_calls[-1]
    assert name == 'run_mgmt_replace_labels'
    assert params['p_team_id'] == TEAM_A
    assert params['p_host_names'] == ['host-a']
    assert params['p_label_ids'] == [U(2), U(3)]


def test_replace_labels_maps_rpc_errors(mem):
    def boom(_params):
        raise Exception('run_mgmt:foreign_label: 1 label id(s) are not in this team')
    mem.rpc_handlers['run_mgmt_replace_labels'] = boom
    with pytest.raises(RunManagementError) as e:
        rmdb.replace_labels(TEAM_A, 'testcase', U(1), [U(2)], host_names=None)
    assert e.value.code == 'invalid'


def test_assign_only_sets_what_was_given(mem):
    mem.rpc_handlers['run_mgmt_assign_script_results'] = lambda p: {'updated': len(p['p_script_result_ids'])}
    rmdb.assign_script_results(TEAM_A, [U(2), U(1), U(1)], host_names=['host-a'], milestone_id=None)
    _, params = mem.rpc_calls[-1]
    assert params['p_script_result_ids'] == [U(1), U(2)]
    assert params['p_set_milestone'] is True and params['p_milestone_id'] is None
    assert params['p_set_run_group'] is False and params['p_set_labels'] is False


def test_assign_requires_something_and_bounds_batch(mem):
    with pytest.raises(RunManagementError):
        rmdb.assign_script_results(TEAM_A, [U(1)], host_names=[])
    with pytest.raises(RunManagementError) as e:
        rmdb.assign_script_results(TEAM_A, [U(1)] * 501, host_names=[], run_group_id=None)
    assert e.value.code == 'limit'
    with pytest.raises(RunManagementError):
        rmdb.assign_script_results(TEAM_A, ['not-a-uuid'], host_names=[], run_group_id=None)


# ---------------------------------------------------------------------------
# scoped reads
# ---------------------------------------------------------------------------


def test_host_scope_applies_before_the_page_window(mem):
    mem.seed('script_results', *[_result(i, host_name='host-b') for i in range(1, 6)])
    mem.seed('script_results', *[_result(i, host_name='host-a') for i in range(6, 9)])
    mem.seed('script_results', _result(9, team_id=TEAM_B))
    rows, total = rmdb.list_script_results_in_scope(TEAM_A, host_names=['host-a'], limit=2, offset=0)
    assert total == 3
    assert [r['id'] for r in rows] == [U(8), U(7)]
    assert all(r['host_name'] == 'host-a' for r in rows)


def test_label_filter_is_an_inner_join_within_team(mem):
    mem.seed('script_results', _result(1), _result(2), _result(3, team_id=TEAM_B))
    mem.seed('script_result_labels',
             {'team_id': TEAM_A, 'script_result_id': U(2), 'run_label_id': U(50)},
             {'team_id': TEAM_B, 'script_result_id': U(3), 'run_label_id': U(50)})
    rows, total = rmdb.list_script_results_in_scope(TEAM_A, host_names=['host-a'], label_id=U(50))
    assert total == 1 and rows[0]['id'] == U(2)
    assert 'script_result_labels' not in rows[0]


def test_out_of_scope_id_is_invisible(mem):
    mem.seed('script_results', _result(1, host_name='other-server-host'))
    assert rmdb.get_script_result_in_scope(TEAM_A, U(1), host_names=['host-a']) is None
    assert rmdb.get_script_result_in_scope(TEAM_B, U(1), host_names=None) is None
    assert rmdb.get_script_result_in_scope(TEAM_A, 'garbage', host_names=None) is None
    assert rmdb.get_script_result_in_scope(TEAM_A, U(1), host_names=None)['id'] == U(1)


def test_fetch_all_pages_and_refuses_unbounded(mem, monkeypatch):
    mem.seed('script_results', *[_result(i) for i in range(1, 8)])
    monkeypatch.setattr(rmdb, '_PAGE_BATCH', 2)
    assert len(rmdb.fetch_script_results_in_scope(TEAM_A, host_names=['host-a'])) == 7
    with pytest.raises(RunManagementError) as e:
        rmdb._fetch_all(lambda: mem.table('script_results').select('*').eq('team_id', TEAM_A).order('id'), cap=5)
    assert e.value.code == 'limit'


# ---------------------------------------------------------------------------
# latest merge
# ---------------------------------------------------------------------------


def test_latest_merge_orders_by_timestamp_then_id_and_counts_attempts():
    same_time = '2026-10-01T10:00:00+00:00'
    members = [
        _result(1, success=False, started_at='2026-10-01T09:00:00+00:00'),
        _result(2, success=True, started_at=same_time),
        _result(3, success=False, started_at=same_time),       # same time, higher id wins
        _result(4, device_name='dev2', success=True),
    ]
    merged = {e['identity']['device_name']: e for e in rmdb.merge_latest_with_attempts(members)}
    assert merged['dev1']['latest']['id'] == U(3)
    assert merged['dev1']['attempt_count'] == 3
    assert merged['dev1']['attempt_ids'] == [U(3), U(2), U(1)]
    assert merged['dev2']['attempt_count'] == 1


def test_latest_merge_never_mixes_environment_or_device():
    members = [_result(1), _result(2, environment='dev'), _result(3, device_name='dev9'), _result(4, userinterface_name=None)]
    assert len(rmdb.merge_latest_with_attempts(members)) == 4


# ---------------------------------------------------------------------------
# rerun idempotency + selection
# ---------------------------------------------------------------------------


def test_rerun_claim_is_idempotent_per_team_key(mem):
    first, created = rmdb.claim_rerun_request(TEAM_A, U(9), 'key-1', 'failures', 'u1')
    assert created is True and first['status'] == 'dispatching'
    rmdb.finish_rerun_request(TEAM_A, first['id'], status='dispatched', dispatched=[{'deployment_id': 'd1'}], skipped=[])
    again, created = rmdb.claim_rerun_request(TEAM_A, U(9), 'key-1', 'failures', 'u1')
    assert created is False and again['id'] == first['id'] and again['dispatched'] == [{'deployment_id': 'd1'}]
    other_team, created = rmdb.claim_rerun_request(TEAM_B, U(9), 'key-1', 'failures', 'u2')
    assert created is True and other_team['id'] != first['id']


def test_failures_mode_selects_latest_failed_excluding_manual_and_discarded():
    members = [
        _result(1, script_name='a.py', success=False, started_at='2026-10-01T09:00:00+00:00'),
        _result(2, script_name='a.py', success=True, started_at='2026-10-01T10:00:00+00:00'),   # recovered
        _result(3, script_name='b.py', success=False),                                          # eligible
        _result(4, script_name='c.py', success=False, script_type='manual'),                    # manual
        _result(5, script_name='d.py', success=True, started_at='2026-10-01T09:00:00+00:00'),
        _result(6, script_name='d.py', success=False, discard=True),                            # discarded latest
        _result(7, script_name='e.py', success=False, discard=True),                            # only discarded
    ]
    targets, skipped = rerun.select_rerun_targets(members, 'failures')
    assert [t['id'] for t in targets] == [U(3)]
    reasons = {s['script_name']: s['reason'] for s in skipped}
    assert reasons == {'c.py': 'manual_run', 'e.py': 'only_discarded_attempts'}


def test_failures_mode_never_relaunches_a_running_attempt():
    # script_results rows are inserted at start with success=false and no duration.
    members = [
        _result(1, script_name='a.py', success=False, started_at='2026-10-01T09:00:00+00:00'),
        _result(2, script_name='a.py', success=False, execution_time_ms=None,
                started_at='2026-10-01T10:00:00+00:00'),                                       # running now
    ]
    targets, skipped = rerun.select_rerun_targets(members, 'failures')
    assert targets == []
    assert [(s['script_result_id'], s['reason']) for s in skipped] == [(U(2), 'latest_attempt_not_terminal')]


def test_running_rows_are_unknown_everywhere():
    running = _result(1, success=False, execution_time_ms=None)
    finished = _result(2, script_name='b.py', success=False)
    assert summ.result_child(running)['status'] == 'unknown'
    assert summ.result_child(finished)['status'] == 'failed'
    counts = summ.count_statuses(summ.result_child(r)['status'] for r in (running, finished))
    assert (counts['failed'], counts['unknown']) == (1, 1)
    assert summ.rollup_status(['passed', 'unknown']) == 'unknown'


def test_all_mode_takes_latest_per_identity_but_never_manual():
    members = [_result(1, script_name='a.py'), _result(2, script_name='a.py'),
               _result(3, script_name='m', script_type='manual')]
    targets, skipped = rerun.select_rerun_targets(members, 'all')
    assert [t['id'] for t in targets] == [U(2)]
    assert skipped[0]['reason'] == 'manual_run'


def test_rerun_payload_mirrors_testreports_rules():
    row = _result(1, metadata={'parameters': '--max 3', 'device_id': 'device2', 'virtual_script_id': 'v1'})
    assert rerun.rerun_payload_from_result(row) == {
        'type': 'script', 'scriptName': 'zap.py', 'hostName': 'host-a', 'deviceId': 'device2',
        'parameters': '--max 3', 'virtualScriptId': 'v1'}
    assert rerun.rerun_payload_from_result(_result(1, metadata={})) is None
    campaign_payload = {'type': 'campaign', 'campaignName': 'c'}
    assert rerun.rerun_payload_from_result(_result(1, rerun_payload=campaign_payload, metadata=None)) is None
    deployment_payload = {'type': 'script', 'scriptName': 'zap.py', 'hostName': 'host-a', 'deviceId': 'd', 'parameters': ''}
    assert rerun.rerun_payload_from_result(_result(1, rerun_payload=deployment_payload)) == deployment_payload
    tc = _result(1, script_type='testcase', metadata={'testcase_id': 'tc1', 'testcase_version': 4})
    assert rerun.rerun_payload_from_result(tc)['type'] == 'testcase'


def test_dispatch_uses_one_shot_deployment_on_original_target():
    created = []

    def fake_create(team_id, data):
        created.append((team_id, data))
        return {'id': 'dep-1'}

    payload = {'type': 'script', 'scriptName': 'zap.py', 'hostName': 'host-a', 'deviceId': 'device1', 'parameters': '-x'}
    out = rerun.dispatch_rerun(TEAM_A, _result(1), payload, fake_create)
    team_id, data = created[0]
    assert team_id == TEAM_A
    assert data['cron_expression'] == '0 0 1 1 *' and data['max_executions'] == 1
    assert (data['host_name'], data['device_id'], data['parameters']) == ('host-a', 'device1', '-x')
    assert data['rerun_payload'] == payload
    assert out == {'source_script_result_id': U(1), 'script_name': 'zap.py', 'host_name': 'host-a',
                   'device_id': 'device1', 'deployment_id': 'dep-1'}


# ---------------------------------------------------------------------------
# summary aggregation
# ---------------------------------------------------------------------------


def _campaign_with_outcomes(passed, failed, skipped):
    outcomes, results = [], {}
    order = 0
    for status, n in (('passed', passed), ('failed', failed), ('skipped', skipped)):
        for _ in range(n):
            order += 1
            if status == 'skipped':
                outcomes.append({'execution_order': order, 'script_name': f's{order}', 'skipped': True,
                                 'skip_reason': 'os_mismatch'})
            else:
                sid = U(order)
                results[sid] = _result(order, id=sid, success=(status == 'passed'))
                outcomes.append({'execution_order': order, 'script_name': f's{order}', 'script_result_id': sid})
    execution = {
        'script_configurations': [{'script_name': f's{i}'} for i in range(1, order + 1)],
        'script_result_ids': list(results),
        'metadata': {'script_outcomes': outcomes},
        'status': 'completed', 'success': False,
    }
    return execution, results


def test_campaign_33_children_counts_exactly():
    execution, results = _campaign_with_outcomes(passed=17, failed=4, skipped=12)
    children = summ.campaign_children(execution, results)
    counts = summ.count_statuses(c['status'] for c in children)
    assert counts['total'] == 33
    assert (counts['passed'], counts['failed'], counts['skipped'], counts['unknown']) == (17, 4, 12, 0)
    assert [c['position'] for c in children] == list(range(1, 34))


def test_campaign_child_outside_scope_or_unrecorded_stays_unknown():
    execution, results = _campaign_with_outcomes(passed=2, failed=1, skipped=0)
    execution['script_configurations'].append({'script_name': 'never-ran'})
    results.pop(U(1))  # linked but on a host outside this server's scope
    children = summ.campaign_children(execution, results)
    counts = summ.count_statuses(c['status'] for c in children)
    assert (counts['passed'], counts['failed'], counts['unknown'], counts['total']) == (1, 1, 2, 4)


def test_campaign_without_outcomes_never_invents_skips():
    execution = {'script_configurations': [{}] * 5, 'script_result_ids': [U(1), U(2)], 'metadata': {}}
    results = {U(1): _result(1), U(2): _result(2, success=False)}
    counts = summ.count_statuses(c['status'] for c in summ.campaign_children(execution, results))
    assert (counts['passed'], counts['failed'], counts['skipped'], counts['unknown']) == (1, 1, 0, 3)


def test_trend_is_zero_filled_utc_with_explicit_denominator():
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    attempts = [
        {'started_at': '2026-10-03T01:00:00+02:00', 'success': True},    # 2026-10-02 23:00 UTC
        {'started_at': '2026-10-03T08:00:00Z', 'success': False, 'execution_time_ms': 1200},
        {'started_at': '2026-10-03T08:30:00Z', 'success': False, 'execution_time_ms': None},  # still running
        {'started_at': '2026-10-03T09:00:00Z', 'success': True, 'discard': True},
        {'started_at': '2026-09-01T09:00:00Z', 'success': True},        # outside window
    ]
    trend = summ.trend_series(attempts, days=3, now=now)
    assert trend['window_days'] == 3
    assert [p['day'] for p in trend['points']] == ['2026-10-01', '2026-10-02', '2026-10-03']
    assert trend['points'][0] == {'day': '2026-10-01', 'passed': 0, 'failed': 0, 'other': 0, 'total': 0}
    assert trend['points'][1]['passed'] == 1
    assert trend['points'][2] == {'day': '2026-10-03', 'passed': 0, 'failed': 1, 'other': 0, 'total': 1}
    assert trend['excluded']['discarded'] == 1
    assert trend['excluded']['not_terminal'] == 1


def test_campaign_trend_counts_cancelled_as_other_and_skips_running():
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    runs = [
        {'started_at': '2026-10-03T01:00:00Z', 'status': 'completed', 'success': True},
        {'started_at': '2026-10-03T02:00:00Z', 'status': 'aborted', 'success': False},
        {'started_at': '2026-10-03T03:00:00Z', 'status': 'running', 'success': False},
    ]
    point = summ.trend_series(runs, days=1, now=now, status_of=summ.campaign_status)['points'][0]
    assert point == {'day': '2026-10-03', 'passed': 1, 'failed': 0, 'other': 1, 'total': 2}


def test_step_evidence_is_separate_and_null_when_missing():
    assert summ.step_evidence([]) is None
    ev = summ.step_evidence([{'execution_type': 'edge', 'success': True},
                             {'execution_type': 'verification', 'success': False}])
    assert (ev['total'], ev['passed'], ev['failed']) == (2, 1, 1)


def test_rollup_status_is_evidence_based():
    assert summ.rollup_status([]) == 'unknown'
    assert summ.rollup_status(['passed', 'failed']) == 'failed'
    assert summ.rollup_status(['passed', 'passed']) == 'passed'
    assert summ.rollup_status(['passed', 'unknown']) == 'unknown'


def test_paginate_counts_all_before_slicing():
    page = summ.paginate(list(range(7)), limit=2, offset=4)
    assert page == {'items': [4, 5], 'total': 7, 'limit': 2, 'offset': 4}
