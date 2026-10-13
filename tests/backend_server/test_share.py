"""Run share snapshots + exports (TASK-42 §4.3 Sharing, §9 Share/export)."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_run_share_routes import server_run_share_bp  # noqa: E402
from backend_server.src.services.sharing import csv_export, rate_limit, snapshot  # noqa: E402
from shared.src.lib.database import run_share_db  # noqa: E402

pytestmark = pytest.mark.unit

SHARE = ['reports.share:create']
SENSITIVE = [
    '203.0.113.12', 'https://minio.internal/bucket/report.html', 'ops@example.com',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc', 'sk-live_abcdefghijklmnop',
    'secret-host-7', 'device-serial-XYZ', 'Traceback (most recent call last)', 'logs_r2_url',
]


@pytest.fixture
def env(monkeypatch):
    rate_limit.reset()
    fake = common.install(monkeypatch, hosts={'secret-host-7': ['device1']})
    leak = common.script_result(
        host='secret-host-7', device='device1', success=False,
        name='zap 203.0.113.12 https://minio.internal/bucket/report.html ops@example.com',
        error_msg='Traceback (most recent call last) sk-live_abcdefghijklmnop',
        html_report_r2_url='https://minio.internal/bucket/report.html',
        logs_r2_url='https://minio.internal/bucket/logs.txt',
        metadata={'serial': 'device-serial-XYZ',
                  'token': 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc'},
    )
    fake.tables['script_results'] = [leak]
    label_id = common.new_id()
    fake.tables['run_label_definitions'] = [{'id': label_id, 'team_id': common.TEAM_A, 'name': 'nightly'}]
    fake.tables['script_result_labels'] = [{'team_id': common.TEAM_A, 'script_result_id': leak['id'],
                                            'run_label_id': label_id}]
    client = common.make_app(server_run_share_bp, permissions=SHARE).test_client()
    return fake, client, leak


def _create(client, run_id, kind='script', **extra):
    return client.post('/server/run-share-snapshots',
                       json={'team_id': common.TEAM_A, 'run_kind': kind, 'run_id': run_id, **extra})


def test_create_returns_token_once_and_stores_only_its_hash(env):
    fake, client, leak = env
    resp = _create(client, leak['id'])
    assert resp.status_code == 201
    body = resp.get_json()
    token = body['token']
    stored = fake.tables['run_share_snapshots'][0]
    assert stored['token_hash'] == run_share_db.hash_share_token(token)
    assert token not in str(stored)
    assert 'token_hash' not in str(body['snapshot'])
    created = datetime.fromisoformat(stored['created_at'])
    assert datetime.fromisoformat(stored['expires_at']) - created == timedelta(days=7)
    listing = client.get('/server/run-share-snapshots', query_string={
        'team_id': common.TEAM_A, 'run_kind': 'script', 'run_id': leak['id']}).get_json()['items']
    assert token not in str(listing) and stored['token_hash'] not in str(listing)


@pytest.mark.parametrize('ttl', [0, 91, 'x'])
def test_ttl_bounds(env, ttl):
    _, client, leak = env
    assert _create(client, leak['id'], ttl_days=ttl).status_code == 400


def test_payload_is_allowlisted_and_scrubbed(env):
    fake, client, leak = env
    _create(client, leak['id'])
    payload = fake.tables['run_share_snapshots'][0]['sanitized_payload']
    text = str(payload)
    for needle in SENSITIVE:
        assert needle not in text, needle
    assert set(payload) <= {'schema_version', 'kind', 'title', 'status', 'counts', 'durations', 'safe_labels',
                            'rows', 'rows_truncated', 'generated_at'}
    assert payload['status'] == 'failed'
    assert payload['safe_labels'] == ['nightly']
    assert set(payload['rows'][0]) == {'name', 'status', 'execution_time_ms', 'started_at', 'environment'}
    assert '[redacted]' in payload['title']


def test_run_outside_scope_cannot_be_shared(env):
    fake, client, _ = env
    foreign = common.script_result(team_id=common.TEAM_B, host='secret-host-7')
    elsewhere = common.script_result(host='host-of-another-server')
    fake.tables['script_results'] += [foreign, elsewhere]
    assert _create(client, foreign['id']).status_code == 404
    assert _create(client, elsewhere['id']).status_code == 404
    assert 'run_share_snapshots' not in fake.tables


def _public(client, snapshot_id, token=None, **kw):
    headers = {'X-Share-Token': token} if token else {}
    return client.get(f'/server/share/run/{snapshot_id}', headers=headers, **kw)


def test_public_read_needs_matching_id_and_token(env):
    fake, client, leak = env
    first = _create(client, leak['id']).get_json()
    second = _create(client, leak['id']).get_json()
    ok = _public(client, first['snapshot']['id'], first['token'])
    assert ok.status_code == 200
    assert ok.get_json()['snapshot']['payload']['status'] == 'failed'
    assert 'team_id' not in str(ok.get_json()) and 'run_id' not in ok.get_json()['snapshot']
    assert ok.headers['Cache-Control'].startswith('no-store')
    assert ok.headers['Referrer-Policy'] == 'no-referrer'
    assert ok.headers['X-Robots-Tag'].startswith('noindex')
    # a valid token cannot select another snapshot
    assert _public(client, second['snapshot']['id'], first['token']).status_code == 404
    assert _public(client, first['snapshot']['id']).status_code == 404
    assert _public(client, first['snapshot']['id'], 'guess').status_code == 404
    assert _public(client, 'not-a-uuid', first['token']).status_code == 404
    # never from the query string
    assert client.get(f"/server/share/run/{first['snapshot']['id']}?token={first['token']}").status_code == 404


def test_revocation_and_expiry_deny_access(env):
    fake, client, leak = env
    created = _create(client, leak['id']).get_json()
    sid, token = created['snapshot']['id'], created['token']
    resp = client.delete(f'/server/run-share-snapshots/{sid}', query_string={'team_id': common.TEAM_A})
    assert resp.status_code == 200
    assert _public(client, sid, token).status_code == 404
    assert client.delete(f'/server/run-share-snapshots/{sid}', query_string={'team_id': common.TEAM_A}).status_code == 404

    expiring = _create(client, leak['id']).get_json()
    row = next(r for r in fake.tables['run_share_snapshots'] if r['id'] == expiring['snapshot']['id'])
    row['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert _public(client, expiring['snapshot']['id'], expiring['token']).status_code == 404


def test_other_team_cannot_revoke(env):
    _, client, leak = env
    sid = _create(client, leak['id']).get_json()['snapshot']['id']
    assert client.delete(f'/server/run-share-snapshots/{sid}', query_string={'team_id': common.TEAM_B}).status_code == 404


def test_public_csv_escapes_formulas(env):
    fake, client, _ = env
    formula = common.script_result(host='secret-host-7', name='=cmd|/c calc')
    fake.tables['script_results'].append(formula)
    created = _create(client, formula['id']).get_json()
    resp = _public(client, created['snapshot']['id'], created['token'], query_string={'format': 'csv'})
    assert resp.status_code == 200
    assert "'=cmd|/c calc" in resp.get_data(as_text=True)
    assert resp.headers['Cache-Control'].startswith('no-store')


def test_rate_limit(env):
    _, client, leak = env
    created = _create(client, leak['id']).get_json()
    codes = [_public(client, created['snapshot']['id'], created['token']).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


@pytest.mark.parametrize('value,expected', [
    ('=1+1', "'=1+1"), ('+1', "'+1"), ('-1', "'-1"), ('@x', "'@x"), ('\tx', "'\tx"), ('\rx', "'\rx"),
    ('plain', 'plain'), (-5, '-5'), (None, ''), (True, 'true'),
])
def test_escape_cell(value, expected):
    assert csv_export.escape_cell(value) == expected


def test_campaign_counts_keep_missing_children_unknown(monkeypatch):
    fake = common.install(monkeypatch)
    passed = common.script_result(success=True)
    failed = common.script_result(success=False)
    fake.tables['script_results'] = [passed, failed]
    execution_id = common.new_id()
    fake.tables['campaign_executions'] = [{
        'id': execution_id, 'team_id': common.TEAM_A, 'campaign_name': 'Nightly', 'host_name': 'host-1',
        'status': 'completed', 'success': False, 'script_configurations': [{}, {}, {}, {}],
        'script_result_ids': [passed['id'], failed['id']],
    }]
    from backend_server.src.services.analytics.scope import build_scope
    payload = snapshot.build_campaign_payload(build_scope(common.TEAM_A, ['host-1'], None, None), execution_id)
    assert payload['counts']['total'] == 4
    assert payload['counts']['passed'] == 1 and payload['counts']['failed'] == 1 and payload['counts']['unknown'] == 2
    assert payload['counts']['skipped'] == 0
    assert payload['status'] == 'failed'


def test_scrub_keeps_ordinary_names():
    assert snapshot.scrub_text('goto_live_tv_and_check_audio_quality_v2') == 'goto_live_tv_and_check_audio_quality_v2'
    assert snapshot.scrub_text('login 192.168.1.10:8080') == 'login [redacted]'


def test_revoke_and_export_require_the_run_in_scope(env):
    fake, client, leak = env
    sid = _create(client, leak['id']).get_json()['snapshot']['id']
    url = f'/server/run-share-snapshots/{sid}'
    # same team, but the run's host is filtered out of the workspace
    narrowed = {'team_id': common.TEAM_A, 'host_filter': '["other-host"]'}
    assert client.get(f'{url}/export', query_string=narrowed).status_code == 404
    assert client.delete(url, query_string=narrowed).status_code == 404
    # a device filter that excludes the run's device
    other_device = {'team_id': common.TEAM_A, 'device_filter': '["secret-host-7:device9"]'}
    assert client.delete(url, query_string=other_device).status_code == 404
    assert fake.tables['run_share_snapshots'][0].get('revoked_at') is None
    # the run's host is no longer registered on this server
    fake.registry._hosts.pop('secret-host-7')
    assert client.get(f'{url}/export', query_string={'team_id': common.TEAM_A}).status_code == 404
    assert client.delete(url, query_string={'team_id': common.TEAM_A}).status_code == 404
    assert fake.tables['run_share_snapshots'][0].get('revoked_at') is None


def test_export_in_scope_returns_the_stored_payload(env):
    _, client, leak = env
    sid = _create(client, leak['id']).get_json()['snapshot']['id']
    resp = client.get(f'/server/run-share-snapshots/{sid}/export', query_string={'team_id': common.TEAM_A})
    assert resp.status_code == 200 and resp.mimetype == 'text/csv'


def test_rate_limit_ignores_forwarded_for_and_invalid_ids(env):
    _, client, leak = env
    created = _create(client, leak['id']).get_json()
    sid, token = created['snapshot']['id'], created['token']
    codes = [client.get(f'/server/share/run/{sid}', headers={'X-Share-Token': token,
                                                              'X-Forwarded-For': f'198.51.100.{i}'}).status_code
             for i in range(31)]
    # a spoofed X-Forwarded-For per request does not open a fresh bucket
    assert codes[:30] == [200] * 30 and codes[30] == 429
    rate_limit.reset()
    for i in range(50):
        assert _public(client, f'not-a-uuid-{i}', token).status_code == 404
    assert rate_limit.size() == 0


def test_rate_limiter_memory_is_capped(monkeypatch):
    rate_limit.reset()
    monkeypatch.setattr(rate_limit, 'MAX_KEYS', 10)
    for i in range(50):
        assert rate_limit.allow(f'10.0.0.{i}', common.new_id(), now=1000.0 + i)
    assert rate_limit.size() <= 10
    # the most recent client is still tracked; the oldest were evicted first
    assert any(k.startswith('ip:10.0.0.49') for k in rate_limit._buckets)
    assert not any(k.startswith('ip:10.0.0.0:') or k == 'ip:10.0.0.0' for k in rate_limit._buckets)
    rate_limit.reset()


def test_running_attempt_is_not_shared_as_failed(env):
    fake, client, _ = env
    running = common.script_result(host='secret-host-7', success=False, duration=None)
    fake.tables['script_results'].append(running)
    _create(client, running['id'])
    payload = fake.tables['run_share_snapshots'][-1]['sanitized_payload']
    assert payload['status'] == 'unknown' and payload['counts']['failed'] == 0
