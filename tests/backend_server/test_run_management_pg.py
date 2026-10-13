"""
TASK-42 — run governance schema acceptance against a real Postgres.

Skipped unless TASK42_PG_DSN points at a DISPOSABLE database with the full
schema applied (fresh install or base + migrations) and the Supabase roles
anon / authenticated / service_role. Never point it at a shared database.

Verifies by real SQL: composite (team_id, id) foreign keys reject cross-team
links even for the superuser and service_role; label name trim/length/
case-insensitive uniqueness; the 10-label cap under two racing transactions;
the atomic replace/batch RPCs (success, all-or-nothing on a foreign or
out-of-scope id); RLS/grants (anon and authenticated hold nothing on the new
tables or RPCs); archive/restore keeps links and an in-use group cannot be
deleted; rerun idempotency key uniqueness; label delete removes assignments only.

Every test seeds its own tenant/teams with random ids and deletes them after.
"""
import json
import os
import threading
import uuid

import pytest

pytestmark = pytest.mark.unit

DSN = os.environ.get('TASK42_PG_DSN')
if not DSN:
    pytest.skip('TASK42_PG_DSN is not set (disposable Postgres for TASK-42 schema tests)', allow_module_level=True)

try:
    import psycopg as _pg  # psycopg 3

    def _connect():
        return _pg.connect(DSN, autocommit=True)
except ImportError:  # pragma: no cover - depends on the gate image
    import psycopg2 as _pg

    def _connect():
        conn = _pg.connect(DSN)
        conn.autocommit = True
        return conn


def _sqlstate(exc):
    return getattr(exc, 'sqlstate', None) or getattr(exc, 'pgcode', None)


FK_VIOLATION = '23503'
UNIQUE_VIOLATION = '23505'
CHECK_VIOLATION = '23514'
INSUFFICIENT_PRIVILEGE = '42501'
NO_DATA_FOUND = 'P0002'
INVALID_PARAMETER = '22023'


def _expect(conn, sql, params, state):
    """Run ``sql`` in its own transaction and assert it fails with ``state``."""
    with pytest.raises(Exception) as info:
        with conn.cursor() as cur:
            cur.execute('BEGIN')
            try:
                cur.execute(sql, params)
            finally:
                cur.execute('ROLLBACK')
    assert _sqlstate(info.value) == state, f'{info.value!r}'
    return info.value


def _one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _exec(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)


@pytest.fixture
def conn():
    connection = _connect()
    yield connection
    connection.close()


@pytest.fixture
def world(conn):
    """Two teams in one tenant, each with results on host-a, plus testcases."""
    tenant = str(uuid.uuid4())
    team_a, team_b = str(uuid.uuid4()), str(uuid.uuid4())
    _exec(conn, 'INSERT INTO public.tenants (id, name, slug) VALUES (%s, %s, %s)',
          (tenant, 'task42 test', 't42-' + tenant[:8]))
    for team in (team_a, team_b):
        _exec(conn, 'INSERT INTO public.teams (id, name, tenant_id) VALUES (%s, %s, %s)',
              (team, 'task42-' + team[:8], tenant))

    def result(team, host='host-a', success=True):
        rid = str(uuid.uuid4())
        _exec(conn, """INSERT INTO public.script_results
                       (id, team_id, script_name, script_type, host_name, device_name, success, started_at, completed_at)
                       VALUES (%s, %s, 'zap.py', 'script', %s, 'dev1', %s, now(), now())""",
              (rid, team, host, success))
        return rid

    def testcase(team):
        tid = str(uuid.uuid4())
        _exec(conn, """INSERT INTO public.testcase_definitions (testcase_id, team_id, testcase_name, graph_json)
                       VALUES (%s, %s, %s, '{}'::jsonb)""", (tid, team, 'tc-' + tid[:8]))
        return tid

    def label(team, name):
        return str(_one(conn, 'INSERT INTO public.run_label_definitions (team_id, name) VALUES (%s, %s) RETURNING id',
                        (team, name))[0])

    def group(team, name, archived=False):
        return str(_one(conn, 'INSERT INTO public.run_groups (team_id, name, archived) VALUES (%s, %s, %s) RETURNING id',
                        (team, name, archived))[0])

    def milestone(team, name):
        return str(_one(conn, 'INSERT INTO public.run_milestones (team_id, name) VALUES (%s, %s) RETURNING id',
                        (team, name))[0])

    w = {'a': team_a, 'b': team_b, 'result': result, 'testcase': testcase, 'label': label,
         'group': group, 'milestone': milestone}
    yield w
    _exec(conn, 'RESET ROLE')
    _exec(conn, 'DELETE FROM public.teams WHERE id IN (%s, %s)', (team_a, team_b))
    _exec(conn, 'DELETE FROM public.tenants WHERE id = %s', (tenant,))


# ---------------------------------------------------------------------------
# Composite foreign keys
# ---------------------------------------------------------------------------


def test_cross_team_label_assignment_is_rejected_for_superuser(conn, world):
    rid = world['result'](world['a'])
    foreign_label = world['label'](world['b'], 'theirs')
    _expect(conn, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
            (world['a'], rid, foreign_label), FK_VIOLATION)
    _expect(conn, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
            (world['b'], rid, foreign_label), FK_VIOLATION)
    tc = world['testcase'](world['a'])
    _expect(conn, 'INSERT INTO public.testcase_labels (team_id, testcase_id, run_label_id) VALUES (%s, %s, %s)',
            (world['a'], tc, foreign_label), FK_VIOLATION)


def test_cross_team_label_assignment_is_rejected_for_service_role(conn, world):
    rid = world['result'](world['a'])
    foreign_label = world['label'](world['b'], 'theirs')
    _exec(conn, 'SET ROLE service_role')
    try:
        _expect(conn, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
                (world['a'], rid, foreign_label), FK_VIOLATION)
    finally:
        _exec(conn, 'RESET ROLE')


def test_cross_team_milestone_and_group_links_are_rejected(conn, world):
    rid = world['result'](world['a'])
    _expect(conn, 'UPDATE public.script_results SET milestone_id = %s WHERE id = %s',
            (world['milestone'](world['b'], 'M'), rid), FK_VIOLATION)
    _expect(conn, 'UPDATE public.script_results SET run_group_id = %s WHERE id = %s',
            (world['group'](world['b'], 'G'), rid), FK_VIOLATION)
    own_group = world['group'](world['a'], 'G')
    _exec(conn, 'UPDATE public.script_results SET run_group_id = %s WHERE id = %s', (own_group, rid))


def test_rerun_request_must_reference_own_team_group(conn, world):
    _expect(conn, """INSERT INTO public.run_group_rerun_requests (team_id, run_group_id, idempotency_key, mode)
                     VALUES (%s, %s, 'k', 'all')""", (world['a'], world['group'](world['b'], 'G')), FK_VIOLATION)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_label_names_trimmed_bounded_and_case_insensitive_unique(conn, world):
    world['label'](world['a'], 'Smoke')
    _expect(conn, 'INSERT INTO public.run_label_definitions (team_id, name) VALUES (%s, %s)',
            (world['a'], 'SMOKE'), UNIQUE_VIOLATION)
    for bad in ('', ' padded', 'x' * 21):
        _expect(conn, 'INSERT INTO public.run_label_definitions (team_id, name) VALUES (%s, %s)',
                (world['a'], bad), CHECK_VIOLATION)
    world['label'](world['a'], 'x' * 20)
    world['label'](world['b'], 'smoke')  # other team: allowed


def test_group_and_milestone_names_case_insensitive_unique(conn, world):
    world['group'](world['a'], 'Release')
    _expect(conn, 'INSERT INTO public.run_groups (team_id, name) VALUES (%s, %s)', (world['a'], 'release'), UNIQUE_VIOLATION)
    world['milestone'](world['a'], 'Q4')
    _expect(conn, 'INSERT INTO public.run_milestones (team_id, name) VALUES (%s, %s)', (world['a'], 'q4'), UNIQUE_VIOLATION)


# ---------------------------------------------------------------------------
# 10-label cap under concurrency
# ---------------------------------------------------------------------------


def test_label_cap_holds_under_racing_transactions(world):
    setup = _connect()
    rid = world['result'](world['a'])
    labels = [world['label'](world['a'], f'l{i}') for i in range(11)]
    for lid in labels[:9]:
        _exec(setup, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
              (world['a'], rid, lid))
    first, second = _connect(), _connect()
    errors = []
    try:
        _exec(first, 'BEGIN')
        _exec(first, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
              (world['a'], rid, labels[9]))

        def racer():
            try:
                _exec(second, 'BEGIN')
                _exec(second, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
                      (world['a'], rid, labels[10]))
                _exec(second, 'COMMIT')
            except Exception as e:  # expected: the 11th label
                errors.append(e)
                _exec(second, 'ROLLBACK')

        thread = threading.Thread(target=racer)
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), 'the second writer must wait for the first (advisory lock)'
        _exec(first, 'COMMIT')
        thread.join(timeout=30)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()
    assert len(errors) == 1 and _sqlstate(errors[0]) == CHECK_VIOLATION
    count = _one(setup, 'SELECT count(*) FROM public.script_result_labels WHERE team_id = %s AND script_result_id = %s',
                 (world['a'], rid))[0]
    setup.close()
    assert count == 10


# ---------------------------------------------------------------------------
# RPCs
# ---------------------------------------------------------------------------


def _labels_of(conn, team, rid):
    with conn.cursor() as cur:
        cur.execute('SELECT run_label_id::text FROM public.script_result_labels WHERE team_id = %s AND script_result_id = %s '
                    'ORDER BY 1', (team, rid))
        return [r[0] for r in cur.fetchall()]


REPLACE = 'SELECT public.run_mgmt_replace_labels(%s, %s, %s, %s::uuid[], %s::text[], %s)'
ASSIGN = ('SELECT public.run_mgmt_assign_script_results(%s, %s::uuid[], %s::text[], %s, %s, %s, %s, %s, %s::uuid[], %s)')


def test_replace_labels_is_atomic(conn, world):
    rid = world['result'](world['a'])
    l1, l2 = world['label'](world['a'], 'one'), world['label'](world['a'], 'two')
    foreign = world['label'](world['b'], 'theirs')
    out = _one(conn, REPLACE, (world['a'], 'script_result', rid, [l1, l2], ['host-a'], 'u1'))[0]
    out = out if isinstance(out, dict) else json.loads(out)
    assert sorted(out['label_ids']) == sorted([l1, l2])
    assert _labels_of(conn, world['a'], rid) == sorted([l1, l2])
    _expect(conn, REPLACE, (world['a'], 'script_result', rid, [l1, foreign], ['host-a'], 'u1'), INVALID_PARAMETER)
    assert _labels_of(conn, world['a'], rid) == sorted([l1, l2])
    _expect(conn, REPLACE, (world['a'], 'script_result', rid, [l1], ['other-host'], 'u1'), NO_DATA_FOUND)
    _expect(conn, REPLACE, (world['b'], 'script_result', rid, [], None, 'u1'), NO_DATA_FOUND)
    many = [world['label'](world['a'], f'm{i}') for i in range(11)]
    _expect(conn, REPLACE, (world['a'], 'script_result', rid, many, None, 'u1'), CHECK_VIOLATION)
    _one(conn, REPLACE, (world['a'], 'script_result', rid, [], None, 'u1'))
    assert _labels_of(conn, world['a'], rid) == []


def test_replace_labels_on_testcase_checks_team(conn, world):
    tc = world['testcase'](world['b'])
    _expect(conn, REPLACE, (world['a'], 'testcase', tc, [], None, 'u1'), NO_DATA_FOUND)


def test_batch_assignment_is_all_or_nothing(conn, world):
    r1, r2 = world['result'](world['a']), world['result'](world['a'])
    foreign = world['result'](world['b'])
    gid = world['group'](world['a'], 'G')
    lid = world['label'](world['a'], 'L')
    _expect(conn, ASSIGN, (world['a'], [r1, foreign], None, False, None, True, gid, True, [lid], 'u1'), NO_DATA_FOUND)
    _expect(conn, ASSIGN, (world['a'], [r1, r2], ['other-host'], False, None, True, gid, False, None, 'u1'), NO_DATA_FOUND)
    assert _one(conn, 'SELECT count(*) FROM public.script_results WHERE run_group_id = %s', (gid,))[0] == 0
    _one(conn, ASSIGN, (world['a'], [r1, r2], ['host-a'], False, None, True, gid, True, [lid], 'u1'))
    assert _one(conn, 'SELECT count(*) FROM public.script_results WHERE run_group_id = %s', (gid,))[0] == 2
    assert _labels_of(conn, world['a'], r2) == [lid]
    archived = world['group'](world['a'], 'old', archived=True)
    _expect(conn, ASSIGN, (world['a'], [r1], None, False, None, True, archived, False, None, 'u1'), NO_DATA_FOUND)
    _one(conn, ASSIGN, (world['a'], [r1], None, False, None, True, None, False, None, 'u1'))
    assert _one(conn, 'SELECT run_group_id FROM public.script_results WHERE id = %s', (r1,))[0] is None


REPLACE_WS = 'SELECT public.run_mgmt_replace_labels(%s, %s, %s, %s::uuid[], %s::text[], %s, %s::text[])'
ASSIGN_WS = ('SELECT public.run_mgmt_assign_script_results('
             '%s, %s::uuid[], %s::text[], %s, %s, %s, %s, %s, %s::uuid[], %s, %s::text[])')


def test_assignment_rpcs_honour_the_workspace_device_filter(conn, world):
    rid = world['result'](world['a'])  # host-a / dev1
    gid = world['group'](world['a'], 'WS')
    lid = world['label'](world['a'], 'ws')
    _expect(conn, REPLACE_WS, (world['a'], 'script_result', rid, [lid], ['host-a'], 'u1', ['host-a:dev2']),
            NO_DATA_FOUND)
    _expect(conn, ASSIGN_WS, (world['a'], [rid], ['host-a'], False, None, True, gid, False, None, 'u1',
                              ['host-a:dev2']), NO_DATA_FOUND)
    assert _labels_of(conn, world['a'], rid) == []
    _one(conn, ASSIGN_WS, (world['a'], [rid], ['host-a'], False, None, True, gid, True, [lid], 'u1',
                           ['host-a:dev1']))
    assert _labels_of(conn, world['a'], rid) == [lid]
    assert _one(conn, 'SELECT run_group_id::text FROM public.script_results WHERE id = %s', (rid,))[0] == gid


# ---------------------------------------------------------------------------
# RLS and grants
# ---------------------------------------------------------------------------


NEW_TABLES = ('run_groups', 'run_milestones', 'run_label_definitions', 'script_result_labels',
              'testcase_labels', 'run_group_rerun_requests')


def test_rls_enabled_on_every_new_table(conn, world):
    for table in NEW_TABLES:
        assert _one(conn, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f'public.{table}',))[0] is True


def test_anon_holds_nothing(conn, world):
    world['group'](world['a'], 'G')
    _exec(conn, 'SET ROLE anon')
    try:
        for table in NEW_TABLES:
            _expect(conn, f'SELECT 1 FROM public.{table} LIMIT 1', (), INSUFFICIENT_PRIVILEGE)
        _expect(conn, 'INSERT INTO public.run_groups (team_id, name) VALUES (%s, %s)', (world['a'], 'x'),
                INSUFFICIENT_PRIVILEGE)
        _expect(conn, REPLACE, (world['a'], 'script_result', str(uuid.uuid4()), [], None, None), INSUFFICIENT_PRIVILEGE)
    finally:
        _exec(conn, 'RESET ROLE')


def test_authenticated_member_of_team_a_cannot_read_or_write_team_b(conn, world):
    world['group'](world['b'], 'theirs')
    _exec(conn, 'SET ROLE authenticated')
    try:
        claims = json.dumps({'sub': str(uuid.uuid4()), 'role': 'authenticated',
                             'app_metadata': {'team_ids': [world['a']]}})
        _one(conn, "SELECT set_config('request.jwt.claims', %s, false)", (claims,))
        for table in NEW_TABLES:
            _expect(conn, f'SELECT * FROM public.{table} LIMIT 1', (), INSUFFICIENT_PRIVILEGE)
        _expect(conn, 'UPDATE public.run_groups SET name = %s WHERE team_id = %s', ('pwned', world['b']),
                INSUFFICIENT_PRIVILEGE)
        _expect(conn, ASSIGN, (world['b'], [str(uuid.uuid4())], None, False, None, True, None, False, None, None),
                INSUFFICIENT_PRIVILEGE)
    finally:
        _one(conn, "SELECT set_config('request.jwt.claims', '', false)")
        _exec(conn, 'RESET ROLE')
    assert _one(conn, 'SELECT name FROM public.run_groups WHERE team_id = %s', (world['b'],))[0] == 'theirs'


# ---------------------------------------------------------------------------
# Archive, delete, idempotency
# ---------------------------------------------------------------------------


def test_archive_restore_keeps_links_and_in_use_group_cannot_be_deleted(conn, world):
    rid = world['result'](world['a'])
    gid = world['group'](world['a'], 'G')
    mid = world['milestone'](world['a'], 'M')
    _exec(conn, 'UPDATE public.script_results SET run_group_id = %s, milestone_id = %s WHERE id = %s', (gid, mid, rid))
    _exec(conn, 'UPDATE public.run_groups SET archived = true WHERE id = %s', (gid,))
    _exec(conn, 'UPDATE public.run_milestones SET archived = true WHERE id = %s', (mid,))
    assert _one(conn, 'SELECT run_group_id::text, milestone_id::text FROM public.script_results WHERE id = %s',
                (rid,)) == (gid, mid)
    _exec(conn, 'UPDATE public.run_groups SET archived = false WHERE id = %s', (gid,))
    _expect(conn, 'DELETE FROM public.run_groups WHERE id = %s', (gid,), FK_VIOLATION)
    _expect(conn, 'DELETE FROM public.run_milestones WHERE id = %s', (mid,), FK_VIOLATION)
    updated = _one(conn, 'SELECT updated_at > created_at FROM public.run_groups WHERE id = %s', (gid,))[0]
    assert updated is True


def test_rerun_idempotency_key_is_unique_per_team(conn, world):
    ga, gb = world['group'](world['a'], 'G'), world['group'](world['b'], 'G')
    sql = ("INSERT INTO public.run_group_rerun_requests (team_id, run_group_id, idempotency_key, mode) "
           "VALUES (%s, %s, %s, 'failures')")
    _exec(conn, sql, (world['a'], ga, 'click-1'))
    _expect(conn, sql, (world['a'], ga, 'click-1'), UNIQUE_VIOLATION)
    _exec(conn, sql, (world['b'], gb, 'click-1'))


def test_label_delete_removes_assignments_only(conn, world):
    rid = world['result'](world['a'])
    tc = world['testcase'](world['a'])
    lid = world['label'](world['a'], 'gone')
    _exec(conn, 'INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id) VALUES (%s, %s, %s)',
          (world['a'], rid, lid))
    _exec(conn, 'INSERT INTO public.testcase_labels (team_id, testcase_id, run_label_id) VALUES (%s, %s, %s)',
          (world['a'], tc, lid))
    _exec(conn, 'DELETE FROM public.run_label_definitions WHERE id = %s', (lid,))
    assert _one(conn, 'SELECT count(*) FROM public.script_result_labels WHERE run_label_id = %s', (lid,))[0] == 0
    assert _one(conn, 'SELECT count(*) FROM public.testcase_labels WHERE run_label_id = %s', (lid,))[0] == 0
    assert _one(conn, 'SELECT count(*) FROM public.script_results WHERE id = %s', (rid,))[0] == 1
    assert _one(conn, 'SELECT count(*) FROM public.testcase_definitions WHERE testcase_id = %s', (tc,))[0] == 1
