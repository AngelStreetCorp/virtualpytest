"""BUG-0417 — PostgREST in.() filters are chunked so the URL never overflows.

`list_testcases` put every test case name in one `in.(...)` filter; with ~200
test cases the request URL passed the proxy limit and PostgREST answered 414
"URI too long", so execution stats silently fell back to 0. The fake client
below raises the same 414 as soon as one in.() carries more than
IN_FILTER_CHUNK values, so these tests fail on the old single-query code.
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from tests.backend_server._task42_common import TEAM_A, MemorySupabase  # noqa: E402
from shared.src.lib.database import testcase_db  # noqa: E402
from shared.src.lib.database.in_filter import IN_FILTER_CHUNK, chunked_in  # noqa: E402

pytestmark = pytest.mark.unit


class UriTooLong(Exception):
    pass


@pytest.fixture
def mem(monkeypatch):
    """MemorySupabase whose in_() fails like PostgREST past IN_FILTER_CHUNK values."""
    db = MemorySupabase()
    db.in_sizes = []
    real_table = db.table

    def table(name):
        query = real_table(name)
        real_in = query.in_

        def in_(col, values):
            values = list(values)
            db.in_sizes.append(len(values))
            if len(values) > IN_FILTER_CHUNK:
                raise UriTooLong({'code': 414, 'details': "b'URI too long\\n'"})
            return real_in(col, values)
        query.in_ = in_
        return query
    db.table = table
    return db


def test_chunked_in_splits_and_concatenates(mem):
    mem.seed('items', *({'id': f'id-{i}', 'n': i} for i in range(130)))
    wanted = [f'id-{i}' for i in range(0, 130)] + ['missing']

    rows = chunked_in(lambda chunk: mem.table('items').select('id, n').in_('id', chunk), wanted)

    assert sorted(r['n'] for r in rows) == list(range(130))
    assert mem.in_sizes == [50, 50, 31]


def test_chunked_in_empty_list_makes_no_query(mem):
    assert chunked_in(lambda chunk: mem.table('items').select('*').in_('id', chunk), []) == []
    assert mem.in_sizes == []


def test_chunked_in_accepts_sets_and_custom_size(mem):
    mem.seed('items', *({'id': str(i)} for i in range(10)))
    rows = chunked_in(lambda chunk: mem.table('items').select('id').in_('id', chunk),
                      {str(i) for i in range(10)}, size=4)
    assert len(rows) == 10 and mem.in_sizes == [4, 4, 2]


def test_list_testcases_stats_survive_200_testcases(mem, monkeypatch):
    monkeypatch.setattr(testcase_db, 'get_supabase', lambda: mem)
    names = [f'TC_NAV_{i:03d}_open_the_settings_menu_and_check_the_title' for i in range(200)]
    for i, name in enumerate(names):
        mem.seed('testcase_definitions', {
            'testcase_id': f'00000000-0000-0000-0000-{i:012x}', 'team_id': TEAM_A,
            'testcase_name': name, 'updated_at': f'2026-10-01T00:{i % 60:02d}:00+00:00'})
    # TC 7 ran three times, last run failed; TC 150 ran once and passed.
    for started, success in (('2026-10-01T10:00:00', True), ('2026-10-02T10:00:00', True),
                             ('2026-10-03T10:00:00', False)):
        mem.seed('script_results', {'team_id': TEAM_A, 'script_type': 'testcase',
                                    'script_name': names[7], 'success': success, 'started_at': started})
    mem.seed('script_results', {'team_id': TEAM_A, 'script_type': 'testcase',
                                'script_name': names[150], 'success': True, 'started_at': '2026-10-04T10:00:00'})
    mem.seed('testcase_definitions_history', {'team_id': TEAM_A, 'testcase_id': '00000000-0000-0000-0000-000000000007',
                                              'version_number': 4})

    by_name = {tc['testcase_name']: tc for tc in testcase_db.list_testcases(TEAM_A)}

    assert len(by_name) == 200
    assert max(mem.in_sizes) <= IN_FILTER_CHUNK
    assert by_name[names[7]]['execution_count'] == 3
    assert by_name[names[7]]['last_execution_success'] is False
    assert by_name[names[7]]['current_version'] == 5
    assert by_name[names[150]]['execution_count'] == 1
    assert by_name[names[150]]['last_execution_success'] is True
    assert by_name[names[0]]['execution_count'] == 0


def test_chunked_in_pages_past_the_postgrest_row_cap(mem, monkeypatch):
    """PostgREST returns at most PGRST_DB_MAX_ROWS (1000) rows per request; a chunk
    with more matching rows must be paged, or execution counts come back short."""
    from shared.src.lib.database import in_filter
    mem.seed('items', *({'id': f'id-{i % 3}', 'n': i} for i in range(2500)))
    cap = in_filter.MAX_ROWS_PER_REQUEST
    table = mem.table

    def capped_table(name):
        query = table(name)
        real_execute = query.execute

        def execute():
            result = real_execute()
            result.data = result.data[:cap]
            return result
        query.execute = execute
        return query
    mem.table = capped_table
    rows = chunked_in(lambda chunk: mem.table('items').select('*').in_('id', chunk).order('n'),
                      ['id-0', 'id-1', 'id-2'])
    assert sorted(r['n'] for r in rows) == list(range(2500))
