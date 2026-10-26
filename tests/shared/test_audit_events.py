"""TASK-154 audit trail: writer, drop-list, synthetic principals, grants."""
import pathlib
import queue

import pytest

from backend_server.src.lib import audit_emitter
from shared.src.lib.database import audit_events_db as db

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('principal', ['auto_signed', 'service_api_key', 'open_mode', 'public_key'])
def test_synthetic_principals_are_never_users(principal):
    assert db.actor_for(principal) in ('system', 'service')


def test_real_user_and_missing_principal():
    assert db.actor_for('3f2c1a9e-0000-4000-8000-000000000000') == 'user'
    assert db.actor_for(None) == 'system'


@pytest.mark.parametrize('method,path,status,expected', [
    ('POST', '/server/script/execute', 200, True),
    ('DELETE', '/server/campaigns/1', 200, True),
    ('GET', '/server/devices', 200, False),
    ('GET', '/server/devices', 403, True),
    ('GET', '/server/reports/export', 200, True),
    ('OPTIONS', '/server/script/execute', 204, False),
    ('POST', '/server/system/health', 200, False),
    ('GET', '/server/script/status/abc', 200, False),
    ('POST', '/host/stream/restart', 200, False),
    ('POST', '/server/system/register', 200, False),
])
def test_drop_list(method, path, status, expected):
    assert audit_emitter.should_audit(method, path, status) is expected


def test_raw_ip_only_under_flag(monkeypatch):
    monkeypatch.delenv('VPT_AUDIT_STORE_RAW_IP', raising=False)
    net = db.network_info('203.0.113.9', 'ua')
    assert 'ip' not in net and net['ip_hash']
    monkeypatch.setenv('VPT_AUDIT_STORE_RAW_IP', '1')
    assert db.network_info('203.0.113.9', 'ua')['ip'] == '203.0.113.9'


def test_meta_is_redacted_and_capped():
    row = db.build_row(category='api', action='x', meta={
        'token': 'abc', 'Authorization': 'Bearer x', 'prompt': 'secret text', 'ok': 'y' * 1000})
    assert set(row['meta']) == {'ok'}
    assert len(row['meta']['ok']) <= db.STRING_CAP + 1


def test_invalid_enums_fall_back():
    row = db.build_row(category='bogus', action='x', actor_kind='alien', outcome='weird')
    assert (row['category'], row['actor_kind'], row['outcome']) == ('system', 'system', 'ok')


def test_full_queue_drops_without_raising(monkeypatch):
    full = queue.Queue(maxsize=1)
    full.put('x')
    monkeypatch.setattr(db, '_events', full)
    monkeypatch.setattr(db, '_worker_started', True)
    assert db.record(category='api', action='x') is False


def test_migration_revokes_anon_and_authenticated():
    sql = (ROOT / 'setup/db/migrations/20261022a_audit_events.sql').read_text()
    assert 'REVOKE ALL ON public.audit_events FROM anon, authenticated' in sql
    assert 'GRANT' not in sql.replace('GRANT ALL ON public.audit_events TO service_role', '') \
        .replace('GRANT USAGE, SELECT ON SEQUENCE public.audit_events_id_seq TO service_role', '')
    assert (ROOT / 'setup/db/schema/079_audit_events.sql').read_text() == sql


def test_call_meta_names_host_device_command_and_key_only():
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context('/server/remote/executeCommand', method='POST', json={
            'host_name': 'h1', 'device_id': 'd1', 'command': 'press_key',
            'params': {'key': 'HOME', 'text': 'hunter2'}}):
        meta = audit_emitter._call_meta()
    assert meta['host_name'] == 'h1' and meta['device_id'] == 'd1'
    assert meta['command'] == 'press_key' and meta['key'] == 'HOME'
    assert 'hunter2' not in str(meta)


def test_activity_actor_shows_kind_and_role():
    from shared.src.lib.database.activity_db import _audit_actor
    assert _audit_actor({'actor_email': 'a@b.c', 'actor_kind': 'user', 'actor_role': 'admin'}) == 'a@b.c (user, admin)'
    assert _audit_actor({'actor_id': 'eval', 'actor_kind': 'agent'}) == 'eval (agent)'


def _reset_stats():
    for key in db._stats:
        db._stats[key] = 0


def test_full_queue_counts_dropped_full(monkeypatch):
    _reset_stats()
    full = queue.Queue(maxsize=1)
    full.put('x')
    monkeypatch.setattr(db, '_events', full)
    monkeypatch.setattr(db, '_worker_started', True)
    assert db.record(category='api', action='x') is False
    assert db.stats()['dropped_full'] == 1 and db.stats()['queued'] == 1


def test_failed_batch_is_retried_then_counted_dropped(monkeypatch):
    _reset_stats()
    calls, sleeps = [], []

    def boom(rows):
        calls.append(len(rows))
        raise RuntimeError('db down')

    monkeypatch.setattr(db, 'insert_batch', boom)
    assert db.insert_with_retry([{}, {}, {}], sleep=sleeps.append) is False
    assert len(calls) == db.INSERT_ATTEMPTS and len(sleeps) == db.INSERT_ATTEMPTS - 1
    assert db.stats()['dropped_failed'] == 3


def test_batch_succeeds_on_retry_without_drop(monkeypatch):
    _reset_stats()
    results = iter([RuntimeError('blip'), True])

    def flaky(rows):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(db, 'insert_batch', flaky)
    assert db.insert_with_retry([{}], sleep=lambda s: None) is True
    assert db.stats()['dropped_failed'] == 0


@pytest.mark.parametrize('raw,expected', [
    ('30', 30), ('90', 90), ('-5', db.RETENTION_DAYS_MIN), ('0', db.RETENTION_DAYS_MIN),
    ('3', db.RETENTION_DAYS_MIN), ('99999', db.RETENTION_DAYS_MAX),
    ('abc', db.RETENTION_DAYS_DEFAULT), ('1e3', db.RETENTION_DAYS_DEFAULT), ('', db.RETENTION_DAYS_DEFAULT),
])
def test_retention_setting_is_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv('VPT_AUDIT_RETENTION_DAYS', raw)
    assert db.retention_days() == expected


def test_retention_default_when_unset(monkeypatch):
    monkeypatch.delenv('VPT_AUDIT_RETENTION_DAYS', raising=False)
    assert db.retention_days() == 90


def test_delete_older_than_cannot_wipe_the_table(monkeypatch):
    import datetime as dt
    from shared.src.lib.utils import supabase_utils
    seen = {}

    class Q:
        def delete(self): return self
        def lt(self, col, cutoff): seen['cutoff'] = cutoff; return self
        def execute(self): return type('R', (), {'data': []})()

    class C:
        def table(self, name): return Q()

    monkeypatch.setattr(supabase_utils, 'get_supabase_client', lambda: C())
    db.delete_older_than(-1)
    cutoff = dt.datetime.fromisoformat(seen['cutoff'])
    age = dt.datetime.now(dt.timezone.utc) - cutoff
    assert age >= dt.timedelta(days=db.RETENTION_DAYS_MIN) - dt.timedelta(minutes=1)


TEAM_A = '11111111-1111-4111-8111-111111111111'
TEAM_B = '22222222-2222-4222-8222-222222222222'


def test_writer_nulls_a_non_uuid_team_and_counts_it():
    _reset_stats()
    assert db.build_row(category='api', action='x', team_id='not-a-uuid')['team_id'] is None
    assert db.build_row(category='api', action='x', team_id=TEAM_A.upper())['team_id'] == TEAM_A
    assert db.build_row(category='api', action='x')['team_id'] is None
    assert db.stats()['team_rejected'] == 1


def _team_for(query='', headers=None, ids=None):
    from flask import Flask, request
    app = Flask(__name__)
    with app.test_request_context('/server/x' + query, headers=headers or {}):
        if ids is not None:
            request._vpt_team_ids = ids
        return audit_emitter._team_id()


def test_emitter_rejects_a_team_the_caller_is_not_in():
    _reset_stats()
    assert _team_for(f'?team_id={TEAM_B}', ids={TEAM_A}) is None
    assert _team_for(headers={'X-Team-ID': TEAM_B}, ids={TEAM_A}) is None
    assert db.stats()['team_rejected'] == 2


def test_emitter_keeps_a_team_the_caller_is_in():
    assert _team_for(f'?team_id={TEAM_A}', ids={TEAM_A, TEAM_B}) == TEAM_A
    assert _team_for(ids={TEAM_A}) == TEAM_A
    assert _team_for(ids={TEAM_A, TEAM_B}) is None
