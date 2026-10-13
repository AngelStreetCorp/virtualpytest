"""TASK-42 run-services SQL against a disposable PostgreSQL (schema + migration applied).

Skipped unless ``TASK42_PG_DSN`` points at a throwaway database prepared by the
gate harness (full schema, Supabase-like roles anon/authenticated/service_role).
NEVER point it at a shared database: the tests create and delete teams.

Covers: exactly-once manual finalize under concurrent calls, optimistic
concurrency, defect evidence composite FKs across teams, share snapshot lookup
needing id + hash, the quality RPCs on deterministic sequences, the report
query function, the Jira push claim state machine, and the role lockdown.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

DSN = os.environ.get('TASK42_PG_DSN')

try:  # psycopg 3 preferred
    import psycopg as _pg

    def _connect():
        return _pg.connect(DSN, autocommit=True)

    _errors = _pg.errors
except ImportError:  # pragma: no cover - fallback
    try:
        import psycopg2 as _pg
        import psycopg2.errors as _errors

        def _connect():
            conn = _pg.connect(DSN)
            conn.autocommit = True
            return conn
    except ImportError:
        _pg = None

if not DSN or _pg is None:
    pytest.skip('TASK42_PG_DSN not set (or no psycopg): PG-backed run-services tests skipped',
                allow_module_level=True)

DEFAULT_TENANT = '00000000-0000-0000-0000-000000000000'
T0 = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        try:
            return cur.fetchall()
        except Exception:
            return []


def one(conn, sql, params=None):
    rows = q(conn, sql, params)
    return rows[0][0] if rows else None


@pytest.fixture
def conn():
    connection = _connect()
    yield connection
    connection.close()


def _make_team(conn):
    team_id = str(uuid.uuid4())
    q(conn, 'INSERT INTO public.teams (id, name, tenant_id) VALUES (%s, %s, %s)',
      (team_id, f't42-{team_id[:8]}', DEFAULT_TENANT))
    return team_id


def _drop_team(conn, team_id):
    q(conn, 'DELETE FROM public.manual_sessions WHERE team_id = %s', (team_id,))
    q(conn, 'DELETE FROM public.teams WHERE id = %s', (team_id,))


@pytest.fixture
def team(conn):
    team_id = _make_team(conn)
    yield team_id
    _drop_team(conn, team_id)


@pytest.fixture
def other_team(conn):
    team_id = _make_team(conn)
    yield team_id
    _drop_team(conn, team_id)


def add_result(conn, team_id, *, name='goto_live', success=True, duration=1000, started=T0,
               host='host-1', device='device1', env='prod', ui='ui_a', discard=False, script_type=None):
    rid = str(uuid.uuid4())
    q(conn, '''INSERT INTO public.script_results
               (id, team_id, script_name, script_type, userinterface_name, host_name, device_name,
                success, execution_time_ms, started_at, completed_at, environment, discard)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
      (rid, team_id, name, script_type or name, ui, host, device, success, duration, started,
       started + timedelta(minutes=1), env, discard))
    return rid


def sequence(conn, team_id, outcomes, **kwargs):
    return [add_result(conn, team_id, success=(o == 'P'), started=T0 + timedelta(hours=i), **kwargs)
            for i, o in enumerate(outcomes)]


SCOPE = (['host-1', 'host-2'], None, T0 - timedelta(days=1), T0 + timedelta(days=5))


def flaky_rows(conn, team_id, host_names=SCOPE[0], device_keys=None):
    rows = q(conn, '''SELECT script_name, environment, device_name, attempts, transitions, flaky_score, is_flaky
                      FROM public.rm_quality_flaky(%s, %s, %s, %s, %s, 5)''',
             (team_id, host_names, device_keys, SCOPE[2], SCOPE[3]))
    return {(r[0], r[1], r[2]): r[3:] for r in rows}


# ---------------------------------------------------------------- quality


def test_flaky_score_on_deterministic_sequences(conn, team):
    sequence(conn, team, 'PFPFP', name='alternating')
    sequence(conn, team, 'PPPPF', name='late_failure')
    sequence(conn, team, 'PPPP', name='too_few')
    rows = flaky_rows(conn, team)
    assert rows[('alternating', 'prod', 'device1')] == (5, 4, pytest.approx(1.0), True)
    assert rows[('late_failure', 'prod', 'device1')] == (5, 1, pytest.approx(0.25), True)
    assert ('too_few', 'prod', 'device1') not in rows


def test_devices_and_environments_never_mix(conn, team):
    sequence(conn, team, 'PPPPP', name='split', device='device1')
    sequence(conn, team, 'FFFFF', name='split', device='device2')
    sequence(conn, team, 'FFFFF', name='split', env='test')
    rows = flaky_rows(conn, team)
    assert rows[('split', 'prod', 'device1')][3] is False
    assert rows[('split', 'prod', 'device2')][3] is False
    assert rows[('split', 'test', 'device1')][3] is False


def test_discarded_nonterminal_and_out_of_scope_rows_are_excluded(conn, team, other_team):
    sequence(conn, team, 'PFPFP', name='noisy')
    add_result(conn, team, name='noisy', success=False, started=T0 + timedelta(hours=10), discard=True)
    add_result(conn, team, name='noisy', success=False, duration=None, started=T0 + timedelta(hours=11))
    add_result(conn, team, name='noisy', success=False, started=T0 + timedelta(hours=12), host='foreign-host')
    sequence(conn, other_team, 'FFFFF', name='noisy')
    assert flaky_rows(conn, team)[('noisy', 'prod', 'device1')][:2] == (5, 4)
    assert flaky_rows(conn, team, host_names=['host-2']) == {}
    assert flaky_rows(conn, team, device_keys=['host-1:device9']) == {}


def test_slow_percentiles_nearest_rank(conn, team):
    for i in range(1, 21):
        add_result(conn, team, name='timed', duration=i * 100, started=T0 + timedelta(minutes=i))
    add_result(conn, team, name='timed', success=False, duration=99999, started=T0 + timedelta(hours=3))
    rows = q(conn, '''SELECT samples, p50_ms, p95_ms FROM public.rm_quality_slow(%s, %s, NULL, %s, %s, 5)
                      WHERE script_name = 'timed' ''', (team, SCOPE[0], SCOPE[2], SCOPE[3]))
    assert rows == [(20, 1000, 1900)]


def test_executed_script_names(conn, team):
    add_result(conn, team, name='ran')
    names = q(conn, 'SELECT script_name FROM public.rm_executed_script_names(%s, %s, NULL, %s, %s)',
              (team, SCOPE[0], SCOPE[2], SCOPE[3]))
    assert names == [('ran',)]


def run_query(conn, team_id, **overrides):
    params = dict(p_team_id=team_id, p_host_names=SCOPE[0], p_device_keys=None, p_since=SCOPE[2],
                  p_until=SCOPE[3], p_scripts=None, p_hosts=None, p_devices=None, p_uis=None, p_envs=None,
                  p_statuses=None, p_milestone_ids=None, p_label_ids=None, p_flaky_only=False,
                  p_include_discarded=False, p_sort='started_at', p_desc=True, p_limit=2, p_offset=0,
                  p_chart='status_by_day')
    params.update(overrides)
    names = list(params)
    sql = 'SELECT public.rm_run_query(' + ', '.join(f'{n} => %s' for n in names) + ')'
    value = one(conn, sql, [params[n] for n in names])
    return value if isinstance(value, dict) else json.loads(value)


def test_run_query_counts_before_pagination_and_zero_filled_days(conn, team):
    sequence(conn, team, 'PFPFP', name='alpha')
    add_result(conn, team, name='beta', success=False, duration=None, started=T0)
    result = run_query(conn, team)
    assert result['total'] == 6 and len(result['rows']) == 2
    assert result['counts'] == {'passed': 3, 'failed': 2, 'unknown': 1}
    days = result['series']
    assert len(days) == 7 and days[0]['x'] == '2026-09-19' and days[0]['passed'] == 0
    assert sum(d['passed'] + d['failed'] + d['other'] for d in days) == 6
    failed_alpha = run_query(conn, team, p_statuses=['failed'], p_scripts=['alp*'])
    assert failed_alpha['total'] == 2
    assert run_query(conn, team, p_hosts=['host-1', 'host-2'])['total'] == 0  # repeated key = AND
    assert run_query(conn, team, p_flaky_only=True)['total'] == 5


# ---------------------------------------------------------------- manual


def create_session(conn, team_id, key='k1', actor='actor-1'):
    steps = json.dumps([{'label': 'Press OK'}, {'label': 'Check home', 'required': True},
                        {'label': 'Optional look', 'required': False}])
    created = one(conn, '''SELECT public.rm_create_manual_session(%s, %s, %s, NULL, NULL, 'Login smoke',
                           '{"testcase_name": "Login smoke"}'::jsonb, 'ui_a', 'prod', 'host-1', 'device1', %s::jsonb)''',
                  (team_id, actor, key, steps))
    return created if isinstance(created, dict) else json.loads(created)


def update(conn, team_id, sid, version, steps):
    return one(conn, 'SELECT public.rm_update_manual_session(%s, %s, %s, %s, %s::jsonb, NULL, false, false)',
               (team_id, sid, version, 'actor-1', json.dumps(steps)))


def test_manual_create_is_idempotent(conn, team):
    first = create_session(conn, team)
    second = create_session(conn, team)
    assert first['created'] is True and second['created'] is False and first['id'] == second['id']
    assert one(conn, 'SELECT count(*) FROM public.manual_session_steps WHERE session_id = %s', (first['id'],)) == 3


def test_manual_optimistic_concurrency_and_incomplete_finalize(conn, team):
    sid = create_session(conn, team)['id']
    assert update(conn, team, sid, 1, [{'ordinal': 0, 'outcome': 'passed'}]) == 2
    with pytest.raises(Exception) as exc:
        update(conn, team, sid, 1, [{'ordinal': 0, 'outcome': 'failed'}])
    assert 'rm:version_conflict' in str(exc.value)
    with pytest.raises(Exception) as exc:
        one(conn, 'SELECT public.rm_finalize_manual_session(%s, %s, %s, NULL)', (team, sid, 'actor-1'))
    assert 'rm:incomplete' in str(exc.value)


def test_manual_finalize_exactly_once_under_concurrency(conn, team):
    sid = create_session(conn, team)['id']
    update(conn, team, sid, 1, [{'ordinal': 0, 'outcome': 'passed'}, {'ordinal': 1, 'outcome': 'passed'}])
    results, errors = [], []
    barrier = threading.Barrier(8)

    def finalize():
        c = _connect()
        try:
            barrier.wait()
            value = one(c, 'SELECT public.rm_finalize_manual_session(%s, %s, %s, NULL)', (team, sid, 'actor-1'))
            results.append(value if isinstance(value, dict) else json.loads(value))
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)
        finally:
            c.close()

    threads = [threading.Thread(target=finalize) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    ids = {r['script_result_id'] for r in results}
    assert len(ids) == 1
    assert sum(1 for r in results if not r['already_finalized']) == 1
    rows = q(conn, '''SELECT id::text, script_type, success, metadata->'trigger'->>'caller_user',
                             (metadata->'manual'->>'steps_without_evidence')::int
                      FROM public.script_results WHERE team_id = %s AND metadata->>'manual_session_id' = %s''',
             (team, sid))
    assert len(rows) == 1
    assert rows[0][0] in ids and rows[0][1] == 'manual' and rows[0][2] is True
    assert rows[0][3] == 'actor-1' and rows[0][4] == 2
    assert one(conn, 'SELECT script_result_id::text FROM public.manual_sessions WHERE id = %s', (sid,)) in ids


def test_manual_failed_step_fails_the_result(conn, team):
    sid = create_session(conn, team, key='k-fail')['id']
    update(conn, team, sid, 1, [{'ordinal': 0, 'outcome': 'passed'}, {'ordinal': 1, 'outcome': 'failed'}])
    outcome = one(conn, 'SELECT public.rm_finalize_manual_session(%s, %s, %s, 2)', (team, sid, 'actor-1'))
    outcome = outcome if isinstance(outcome, dict) else json.loads(outcome)
    assert outcome['success'] is False


# ---------------------------------------------------------------- defects


def add_defect(conn, team_id):
    return str(one(conn, "INSERT INTO public.defects (team_id, title) VALUES (%s, 'Black screen') RETURNING id",
                   (team_id,)))


def test_defect_evidence_composite_fk_rejects_cross_team(conn, team, other_team):
    defect = add_defect(conn, team)
    own = add_result(conn, team)
    foreign = add_result(conn, other_team)
    q(conn, 'INSERT INTO public.defect_script_results (team_id, defect_id, script_result_id) VALUES (%s,%s,%s)',
      (team, defect, own))
    with pytest.raises(_errors.ForeignKeyViolation):
        q(conn, 'INSERT INTO public.defect_script_results (team_id, defect_id, script_result_id) VALUES (%s,%s,%s)',
          (team, defect, foreign))
    with pytest.raises(_errors.ForeignKeyViolation):
        q(conn, 'INSERT INTO public.defect_script_results (team_id, defect_id, script_result_id) VALUES (%s,%s,%s)',
          (other_team, defect, foreign))


def test_resolving_a_defect_leaves_results_untouched(conn, team):
    defect = add_defect(conn, team)
    rid = add_result(conn, team, success=False)
    q(conn, 'INSERT INTO public.defect_script_results (team_id, defect_id, script_result_id) VALUES (%s,%s,%s)',
      (team, defect, rid))
    before = q(conn, 'SELECT success, discard, execution_time_ms FROM public.script_results WHERE id = %s', (rid,))
    q(conn, "UPDATE public.defects SET status = 'resolved' WHERE id = %s", (defect,))
    assert q(conn, 'SELECT success, discard, execution_time_ms FROM public.script_results WHERE id = %s', (rid,)) == before


def claim(conn, team_id, defect, instance='jira-1', project='QA', lease=120):
    value = one(conn, 'SELECT public.rm_claim_defect_jira_push(%s, %s, %s, %s, %s)',
                (team_id, defect, instance, project, lease))
    return value if isinstance(value, dict) else json.loads(value)


def test_jira_push_claim_state_machine(conn, team, other_team):
    defect = add_defect(conn, team)
    assert claim(conn, other_team, defect)['reason'] == 'not_found'
    first = claim(conn, team, defect)
    assert first['claimed'] is True and first['reconcile'] is False
    assert first['correlation_label'] == f'vpt-defect-{defect}'
    assert claim(conn, team, defect)['reason'] == 'in_flight'
    one(conn, 'SELECT public.rm_fail_defect_jira_push(%s, %s, %s, true)', (team, defect, 'HTTP 400'))
    assert claim(conn, team, defect, project='OPS')['reason'] == 'target_mismatch'
    retry = claim(conn, team, defect)
    assert retry['claimed'] is True and retry['reconcile'] is True and retry['attempt'] == 2
    one(conn, 'SELECT public.rm_complete_defect_jira_push(%s, %s, %s, %s)',
        (team, defect, 'QA-7', 'https://example.atlassian.net/browse/QA-7'))
    done = claim(conn, team, defect)
    assert done['reason'] == 'already_created' and done['external_key'] == 'QA-7'
    assert q(conn, 'SELECT integration, external_key FROM public.defects WHERE id = %s', (defect,)) == [('jira', 'QA-7')]


def test_unknown_outcome_keeps_the_lease(conn, team):
    defect = add_defect(conn, team)
    claim(conn, team, defect)
    one(conn, 'SELECT public.rm_fail_defect_jira_push(%s, %s, %s, false)', (team, defect, 'timeout'))
    assert claim(conn, team, defect)['reason'] == 'in_flight'


# ---------------------------------------------------------------- share


def add_snapshot(conn, team_id, token_hash, *, days=7):
    return str(one(conn, '''INSERT INTO public.run_share_snapshots
                            (team_id, run_kind, run_id, sanitized_payload, token_hash, created_at, expires_at)
                            VALUES (%s, 'script', %s, '{}'::jsonb, %s, now(), now() + make_interval(days => %s))
                            RETURNING id''', (team_id, str(uuid.uuid4()), token_hash, days)))


def test_share_lookup_requires_id_and_hash(conn, team):
    h1, h2 = 'a' * 64, 'b' * 64
    s1 = add_snapshot(conn, team, h1)
    s2 = add_snapshot(conn, team, h2)
    lookup = 'SELECT count(*) FROM public.run_share_snapshots WHERE id = %s AND token_hash = %s'
    assert one(conn, lookup, (s1, h1)) == 1
    assert one(conn, lookup, (s2, h1)) == 0
    with pytest.raises(_errors.CheckViolation):
        add_snapshot(conn, team, 'c' * 64, days=91)
    with pytest.raises(_errors.CheckViolation):
        add_snapshot(conn, team, 'plaintext-token')


# ---------------------------------------------------------------- lockdown


@pytest.mark.parametrize('table', ['defects', 'defect_script_results', 'defect_jira_pushes', 'run_share_snapshots',
                                   'custom_reports', 'manual_sessions', 'manual_session_steps'])
def test_tables_closed_to_anon_and_authenticated(conn, table):
    for role in ('anon', 'authenticated'):
        with pytest.raises(_errors.InsufficientPrivilege):
            q(conn, f'BEGIN; SET LOCAL ROLE {role}; SELECT 1 FROM public.{table} LIMIT 1')
        q(conn, 'ROLLBACK')


@pytest.mark.parametrize('call', [
    "public.rm_quality_flaky('00000000-0000-0000-0000-000000000000'::uuid, ARRAY['h'], NULL, now(), now(), 5)",
    "public.rm_finalize_manual_session('00000000-0000-0000-0000-000000000000'::uuid, gen_random_uuid(), 'x', NULL)",
])
def test_functions_not_executable_by_authenticated(conn, call):
    with pytest.raises(_errors.InsufficientPrivilege):
        q(conn, f'BEGIN; SET LOCAL ROLE authenticated; SELECT {call}')
    q(conn, 'ROLLBACK')
