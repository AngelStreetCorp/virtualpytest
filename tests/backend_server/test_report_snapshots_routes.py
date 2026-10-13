"""Unit tests for the authenticated report-snapshot routes (TASK-49). Offline: db and builder mocked."""

import pytest

from tests.backend_server.snapshot_test_support import ensure_snapshots_db_importable, make_app

ensure_snapshots_db_importable()

from backend_server.src.lib import auth_middleware as am  # noqa: E402
from backend_server.src.routes import server_report_snapshots_routes as routes  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = 'team-a'
RESULT = {'id': 'res-1', 'team_id': TEAM, 'script_name': 'zap_test', 'started_at': '2026-10-01T10:00:00+00:00',
          'html_report_r2_path': 'script-reports/m/f/report.html'}


@pytest.fixture
def ctx(monkeypatch):
    state = {'created': [], 'purged': [], 'revoked': [], 'built': [], 'live_bytes': 0}
    monkeypatch.setenv('REPORT_SHARING_ENABLED', 'true')
    monkeypatch.setenv('SERVER_NAME', 'srv-1')
    monkeypatch.setattr(am, 'role_default_permissions',
                        lambda role: {'reports.tests:share', 'reports.tests:view'} if role in ('tester', 'manager') else set())
    monkeypatch.setattr(routes, 'get_script_by_id', lambda rid: RESULT if rid == 'res-1' else None)

    def fake_build(path, snapshot_id, include_video, banner, platform_hosts=None, quota_left_bytes=None):
        state['built'].append({'path': path, 'id': snapshot_id, 'video': include_video, 'banner': banner,
                               'quota_left': quota_left_bytes})
        return state.get('build_result') or {'success': True, 'storage_prefix': f'shared-snapshots/{snapshot_id}/',
                                             'size_bytes': 1234, 'assets': []}

    monkeypatch.setattr(routes.report_snapshot_builder, 'build_snapshot', fake_build)
    monkeypatch.setattr(routes.report_snapshot_builder, 'purge_snapshot',
                        lambda prefix: state['purged'].append(prefix) or True)
    db = routes.report_snapshots_db
    monkeypatch.setattr(db, 'team_live_bytes', lambda team_id: state['live_bytes'])
    monkeypatch.setattr(db, 'create_snapshot', lambda **kw: state['created'].append(kw) or kw)
    monkeypatch.setattr(db, 'get_snapshot', lambda team_id, sid: (
        {'id': sid, 'team_id': team_id, 'created_by': '11111111-1111-4111-8111-111111111111',
         'server_name': state.get('row_server', 'srv-1'), 'storage_prefix': f'shared-snapshots/{sid}/'}
        if team_id == TEAM and sid == 'snap-1' else None))
    state['marked'] = []
    monkeypatch.setattr(db, 'mark_purged', lambda sid: state['marked'].append(sid) or True)
    monkeypatch.setattr(db, 'revoke_snapshot', lambda team_id, sid: state['revoked'].append((team_id, sid)) or True)
    monkeypatch.setattr(db, 'list_snapshots', lambda team_id, rid, active_only=True: [
        {'id': 'snap-1', 'key_hash': 'x', 'delete_key_hash': 'y', 'password_hash': 'z', 'size_bytes': 1}])
    state['client'] = make_app(routes.server_report_snapshots_bp).test_client()
    return state


def _post(ctx, body=None, headers=None):
    payload = {'script_result_id': 'res-1', 'team_id': TEAM, 'expires_in': 86400, 'include_video': True}
    payload.update(body or {})
    return ctx['client'].post('/server/report-snapshots', json=payload, headers=headers or {})


def test_config(ctx):
    data = ctx['client'].get('/server/report-snapshots/config').get_json()
    assert data == {'enabled': True, 'can_share': True, 'expiry_choices': [3600, 86400, 604800, 2592000],
                    'default_expires_in': 604800}
    viewer = ctx['client'].get('/server/report-snapshots/config', headers={'X-Test-Role': 'viewer'}).get_json()
    assert viewer['enabled'] is True and viewer['can_share'] is False


def test_config_disabled(ctx, monkeypatch):
    monkeypatch.setenv('REPORT_SHARING_ENABLED', 'false')
    data = ctx['client'].get('/server/report-snapshots/config').get_json()
    assert data['enabled'] is False and data['can_share'] is False


def test_create_disabled_is_403(ctx, monkeypatch):
    monkeypatch.delenv('REPORT_SHARING_ENABLED')
    assert _post(ctx).status_code == 403
    assert ctx['built'] == []


def test_create_without_permission_is_403(ctx):
    assert _post(ctx, headers={'X-Test-Role': 'viewer'}).status_code == 403


def test_create_ok(ctx):
    resp = _post(ctx, {'password': 'hunter2hunter2'})
    assert resp.status_code == 201
    body = resp.get_json()
    key = body['path'].removeprefix('/server/share/').rstrip('/')
    delete_key = body['delete_path'].removeprefix('/server/share/delete/')
    assert body['path'].startswith('/server/share/') and body['path'].endswith('/')
    assert len(key) >= 20 and key != delete_key
    assert body['size_bytes'] == 1234 and body['id'] and body['expires_at']

    row = ctx['created'][0]
    import hashlib
    assert row['key_hash'] == hashlib.sha256(key.encode()).hexdigest()
    assert row['delete_key_hash'] == hashlib.sha256(delete_key.encode()).hexdigest()
    assert row['password_hash'] and row['password_hash'] != 'hunter2hunter2'
    assert row['team_id'] == TEAM and row['server_name'] == 'srv-1' and row['created_by'] == '11111111-1111-4111-8111-111111111111'
    assert key not in str(row) and delete_key not in str(row)
    assert 'zap_test' in ctx['built'][0]['banner'] and '2026-10-01' in ctx['built'][0]['banner']


def test_create_without_password_stores_none(ctx):
    assert _post(ctx).status_code == 201
    assert ctx['created'][0]['password_hash'] is None


@pytest.mark.parametrize('expires_in', [0, 60, 999999, '86400', None, True])
def test_create_invalid_expiry_is_400(ctx, expires_in):
    assert _post(ctx, {'expires_in': expires_in}).status_code == 400


def test_create_other_team_report_is_404(ctx):
    # The row belongs to team-a; asking as team-b must look like "not found".
    assert _post(ctx, {'team_id': 'team-b'}).status_code == 404
    assert _post(ctx, {'script_result_id': 'nope'}).status_code == 404
    assert ctx['built'] == []


def test_create_query_team_wins_like_the_middleware(ctx):
    # enforce_team_scope checks the query string first; the route must act on the same team.
    resp = ctx['client'].post('/server/report-snapshots?team_id=team-b',
                              json={'script_result_id': 'res-1', 'team_id': TEAM, 'expires_in': 3600})
    assert resp.status_code == 404


@pytest.mark.parametrize('code,status', [('report_gone', 410), ('too_large', 413), ('storage_error', 502)])
def test_builder_errors_map_to_status(ctx, code, status):
    ctx['build_result'] = {'success': False, 'error': 'x', 'error_code': code}
    assert _post(ctx).status_code == status


def test_remaining_quota_is_passed_to_the_builder(ctx):
    ctx['live_bytes'] = 5 * 1024 ** 3 - 1000
    assert _post(ctx).status_code == 201
    assert ctx['built'][0]['quota_left'] == 1000


def test_quota_refused_by_builder_is_413(ctx):
    ctx['build_result'] = {'success': False, 'error_code': 'quota', 'error': 'quota left'}
    resp = _post(ctx)
    assert resp.status_code == 413
    assert ctx['created'] == []


def test_list_strips_hashes(ctx):
    resp = ctx['client'].get(f'/server/report-snapshots?script_result_id=res-1&team_id={TEAM}')
    assert resp.status_code == 200
    row = resp.get_json()['snapshots'][0]
    assert not {'key_hash', 'delete_key_hash', 'password_hash'} & set(row)
    assert row['has_password'] is True


def test_list_requires_view_permission(ctx):
    resp = ctx['client'].get(f'/server/report-snapshots?script_result_id=res-1&team_id={TEAM}',
                             headers={'X-Test-Role': 'viewer'})
    assert resp.status_code == 403


def test_revoke_by_creator(ctx):
    resp = ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}')
    assert resp.status_code == 200 and ctx['revoked'] == [(TEAM, 'snap-1')]


def test_revoke_by_manager_and_admin(ctx):
    for role in ('manager', 'admin'):
        resp = ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}',
                                    headers={'X-Test-Role': role, 'X-Test-User': 'someone-else'})
        assert resp.status_code == 200


def test_revoke_by_other_tester_is_403(ctx):
    resp = ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}',
                                headers={'X-Test-User': 'someone-else'})
    assert resp.status_code == 403 and ctx['revoked'] == []


def test_revoke_other_team_is_404(ctx):
    resp = ctx['client'].delete('/server/report-snapshots/snap-1?team_id=team-b', headers={'X-Test-Role': 'admin'})
    assert resp.status_code == 404 and ctx['revoked'] == []


def test_sweep_once_purges_then_marks(ctx, monkeypatch):
    marked = []
    db = routes.report_snapshots_db
    monkeypatch.setattr(db, 'list_purgeable', lambda server, limit=100: [
        {'id': 'a', 'storage_prefix': 'shared-snapshots/a/'}, {'id': 'b', 'storage_prefix': 'shared-snapshots/b/'}])
    monkeypatch.setattr(db, 'mark_purged', lambda sid: marked.append(sid) or True)
    calls = []

    def purge(prefix):
        calls.append(prefix)
        if prefix.endswith('a/'):
            raise RuntimeError('boom')  # one failure must not stop the sweep
        return True

    monkeypatch.setattr(routes.report_snapshot_builder, 'purge_snapshot', purge)
    assert routes.sweep_once() == 1
    assert calls == ['shared-snapshots/a/', 'shared-snapshots/b/'] and marked == ['b']


def test_sweeper_only_starts_when_enabled(monkeypatch):
    monkeypatch.setattr(routes, '_sweeper_started', False)
    monkeypatch.setenv('SERVER_NAME', 'srv-1')
    monkeypatch.setenv('REPORT_SHARING_ENABLED', 'false')
    assert routes.start_snapshot_sweeper() is False



def test_create_passes_expires_at_as_a_datetime(ctx, monkeypatch):
    """report_snapshots_db.create_snapshot calls expires_at.isoformat(). A string passed every
    stubbed test and failed on the first live create (2026-10-04)."""
    from datetime import datetime
    seen = {}
    monkeypatch.setattr(routes.report_snapshots_db, 'create_snapshot',
                        lambda **kw: seen.update(kw) or {'id': kw['snapshot_id']})
    assert _post(ctx).status_code == 201
    assert isinstance(seen['expires_at'], datetime) and seen['expires_at'].tzinfo is not None



@pytest.mark.parametrize('user_id,expected', [
    ('auto_signed', None),  # the auto-sign principal: not a profile UUID
    ('6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b', '6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b'),
])
def test_created_by_is_a_uuid_or_none(ctx, monkeypatch, user_id, expected):
    seen = {}
    monkeypatch.setattr(routes.report_snapshots_db, 'create_snapshot',
                        lambda **kw: seen.update(kw) or {'id': kw['snapshot_id']})
    resp = ctx['client'].post('/server/report-snapshots', json={
        'script_result_id': 'res-1', 'team_id': TEAM, 'expires_in': 3600, 'include_video': True,
    }, headers={'X-Test-User': user_id, 'X-Test-Role': 'tester'})
    assert resp.status_code == 201, resp.get_json()
    assert seen['created_by'] == expected


def test_password_shorter_than_8_is_400(ctx):
    assert _post(ctx, {'password': '1234567'}).status_code == 400
    assert ctx['built'] == [] and ctx['created'] == []
    assert _post(ctx, {'password': '12345678'}).status_code == 201


def test_list_ignores_team_id_in_a_get_body(ctx):
    resp = ctx['client'].open('/server/report-snapshots?script_result_id=res-1', method='GET',
                              json={'team_id': TEAM})
    assert resp.status_code == 400


def test_sweep_once_drains_the_backlog_in_batches(ctx, monkeypatch):
    db = routes.report_snapshots_db
    monkeypatch.setattr(routes, 'SWEEP_BATCH_SIZE', 3)
    pending = [{'id': f'r{i}', 'storage_prefix': f'shared-snapshots/r{i}/'} for i in range(7)]
    limits = []

    def list_purgeable(server, limit=100):
        limits.append(limit)
        return pending[:limit]

    def mark(sid):
        pending[:] = [r for r in pending if r['id'] != sid]
        return True

    monkeypatch.setattr(db, 'list_purgeable', list_purgeable)
    monkeypatch.setattr(db, 'mark_purged', mark)
    assert routes.sweep_once() == 7
    assert limits == [3, 3, 3] and pending == []


def test_sweep_once_caps_batches_when_nothing_gets_purged(ctx, monkeypatch):
    db = routes.report_snapshots_db
    monkeypatch.setattr(routes, 'SWEEP_BATCH_SIZE', 2)
    calls = []
    monkeypatch.setattr(db, 'list_purgeable', lambda server, limit=100: calls.append(1) or [
        {'id': 'a', 'storage_prefix': 'shared-snapshots/a/'}, {'id': 'b', 'storage_prefix': 'shared-snapshots/b/'}])
    monkeypatch.setattr(routes.report_snapshot_builder, 'purge_snapshot', lambda p: False)
    assert routes.sweep_once() == 0
    assert len(calls) == routes.SWEEP_MAX_BATCHES


# ----------------------------------------------------------- revoke deletes now


def test_revoke_purges_and_marks_for_this_server(ctx):
    assert ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}').status_code == 200
    assert ctx['purged'] == ['shared-snapshots/snap-1/'] and ctx['marked'] == ['snap-1']


def test_revoke_leaves_other_servers_rows_to_their_sweeper(ctx):
    ctx['row_server'] = 'srv-2'
    assert ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}').status_code == 200
    assert ctx['revoked'] == [(TEAM, 'snap-1')] and ctx['purged'] == [] and ctx['marked'] == []


def test_revoke_purge_failure_is_still_200(ctx, monkeypatch):
    def boom(prefix):
        raise RuntimeError('storage down')
    monkeypatch.setattr(routes.report_snapshot_builder, 'purge_snapshot', boom)
    assert ctx['client'].delete(f'/server/report-snapshots/snap-1?team_id={TEAM}').status_code == 200
    assert ctx['marked'] == []


# ------------------------------------------------------------ team list (Shared links)

ME = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


@pytest.fixture
def team_ctx(ctx, monkeypatch):
    db = routes.report_snapshots_db
    ctx['list_calls'] = []
    ctx['summary_calls'] = []
    ctx['name_calls'] = []
    rows = [
        {'id': 's1', 'script_result_id': 'r1', 'created_by': ME, 'revoked_at': None, 'has_password': True},
        {'id': 's2', 'script_result_id': 'r1', 'created_by': OTHER, 'revoked_at': None, 'has_password': False},
        {'id': 's3', 'script_result_id': 'r2', 'created_by': None, 'revoked_at': None, 'has_password': False},
        {'id': 's4', 'script_result_id': 'r2', 'created_by': ME, 'revoked_at': '2026-10-01T00:00:00+00:00',
         'has_password': False, 'password_hash': 'leak', 'key_hash': 'leak'},
    ]
    monkeypatch.setattr(db, 'list_team_snapshots', lambda team_id, status='active', limit=200:
                        ctx['list_calls'].append((team_id, status)) or rows)
    monkeypatch.setattr(db, 'get_script_summaries', lambda team_id, ids: ctx['summary_calls'].append((team_id, list(ids))) or {
        'r1': {'script_name': 'zap', 'device_name': 'stb1', 'host_name': 'h1', 'started_at': 'T1', 'report_url': 'u1'}})
    monkeypatch.setattr(db, 'get_profile_names', lambda ids: ctx['name_calls'].append(list(ids)) or {ME: 'Me Myself'})
    monkeypatch.setattr(db, 'team_live_bytes', lambda team_id: 4242)
    return ctx


def _team_get(ctx, query='', headers=None):
    return ctx['client'].get(f'/server/report-snapshots/team?team_id={TEAM}{query}', headers=headers or {})


def test_team_list_scope_enrichment_and_quota(team_ctx):
    resp = _team_get(team_ctx, '&status=all')
    assert resp.status_code == 200
    data = resp.get_json()
    assert team_ctx['list_calls'] == [(TEAM, 'all')]
    assert len(team_ctx['summary_calls']) == 1 and team_ctx['summary_calls'][0][0] == TEAM
    assert len(team_ctx['name_calls']) == 1
    assert data['quota'] == {'used_bytes': 4242, 'limit_bytes': routes.TEAM_QUOTA_BYTES}
    by_id = {s['id']: s for s in data['snapshots']}
    assert by_id['s1']['script_name'] == 'zap' and by_id['s1']['device_name'] == 'stb1'
    assert by_id['s1']['host_name'] == 'h1' and by_id['s1']['script_started_at'] == 'T1'
    assert by_id['s1']['created_by_name'] == 'Me Myself'
    assert by_id['s3']['created_by_name'] is None and by_id['s3']['script_name'] is None
    assert 'key_hash' not in by_id['s4'] and 'password_hash' not in by_id['s4']


def test_team_list_can_revoke_rules(team_ctx):
    def flags(headers=None):
        return {s['id']: s['can_revoke'] for s in _team_get(team_ctx, headers=headers).get_json()['snapshots']}
    assert flags() == {'s1': True, 's2': False, 's3': False, 's4': False}
    assert flags({'X-Test-Role': 'manager'}) == {'s1': True, 's2': True, 's3': True, 's4': False}


def test_team_list_team_from_args_only(team_ctx):
    resp = team_ctx['client'].get('/server/report-snapshots/team?status=all', json={'team_id': TEAM})
    assert resp.status_code == 400 and team_ctx['list_calls'] == []


def test_team_list_defaults_and_rejects_bad_status(team_ctx):
    assert _team_get(team_ctx).status_code == 200 and team_ctx['list_calls'] == [(TEAM, 'active')]
    assert _team_get(team_ctx, '&status=bogus').status_code == 400


def test_team_list_needs_view_permission(team_ctx):
    assert _team_get(team_ctx, headers={'X-Test-Role': 'viewer'}).status_code == 403
