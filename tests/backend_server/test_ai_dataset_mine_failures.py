"""ai-dataset feature: mine_failures.py (TASK-27 step 4, task 1) — pure unit tests.

No network, no DB, no real Langfuse: the supabase client and the langfuse
module are both fakes built in this file. The script is loaded directly from
its path (features/ai-dataset/scripts/ is not a package), so these tests exercise the
exact file that ships.

Run: pytest tests/backend_server/test_ai_dataset_mine_failures.py -v
"""
import csv
import importlib.util
import io
import os
import sys

import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
_SCRIPT_PATH = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "mine_failures.py")

_spec = importlib.util.spec_from_file_location("mine_failures", _SCRIPT_PATH)
mine_failures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mine_failures)

# Pure: no live server needed (tests/backend_server/conftest.py skips unmarked tests without one).
pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"
FAMILY = "banner"


# ---------------------------------------------------------------------------
# Fake supabase-style query builder / client
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Mimics the chained, mutating postgrest builder closely enough for the
    script: .eq/.neq/.is_/.order return self, .limit/.execute are terminal."""

    def __init__(self, rows):
        self._all_rows = rows
        self._filters = []
        self._order = []
        self._limit = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, col, val):
        self._filters.append(('eq', col, val))
        return self

    def neq(self, col, val):
        self._filters.append(('neq', col, val))
        return self

    def is_(self, col, val):
        self._filters.append(('is', col, val))
        return self

    def contains(self, col, val):
        self._filters.append(('contains', col, val))
        return self

    def order(self, col, desc=False):
        self._order.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = list(self._all_rows)
        for kind, col, val in self._filters:
            if kind == 'eq':
                rows = [r for r in rows if r.get(col) == val]
            elif kind == 'neq':
                rows = [r for r in rows if r.get(col) != val]
            elif kind == 'is':
                # only 'null' is used by the script
                rows = [r for r in rows if r.get(col) is None]
            elif kind == 'contains':
                rows = [r for r in rows if isinstance(r.get(col), dict)
                        and all(r[col].get(k) == v for k, v in val.items())]
        for col, desc in reversed(self._order):
            rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResult(rows)


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return _FakeQuery(self._rows)


class FakeSupabaseClient:
    def __init__(self, rows):
        self._rows = rows
        self.table_calls = []

    def table(self, name):
        self.table_calls.append(name)
        assert name == mine_failures.TABLE
        return _FakeTable(self._rows)


def _row(id_, is_failure=False, label_conflict=False, split='train',
        label_source='none', eval_version=None, created_at='2026-01-01T00:00:00Z',
        device_model='stb3', node_id=None, family=FAMILY, team_id=TEAM, model_answer=None):
    return {
        'model_answer': model_answer,
        'id': id_, 'team_id': team_id, 'family': family, 'split': split, 'is_failure': is_failure,
        'label_conflict': label_conflict, 'label_source': label_source,
        'device_model': device_model, 'node_id': node_id, 'created_at': created_at,
        'eval_version': eval_version,
    }


# ---------------------------------------------------------------------------
# DB ordering / skip rules
# ---------------------------------------------------------------------------

def test_eval_split_rows_come_before_train_rows_even_if_older():
    rows = [
        _row('train-new', split='train', created_at='2026-02-01T00:00:00Z'),
        _row('eval-old', split='eval', created_at='2026-01-01T00:00:00Z'),
    ]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=10)
    assert [r['id'] for r in out] == ['eval-old', 'train-new']


def test_within_a_split_group_failure_then_conflict_then_recency():
    rows = [
        _row('recent', split='train', created_at='2026-03-01T00:00:00Z'),
        _row('older', split='train', created_at='2026-01-01T00:00:00Z'),
        _row('conflict', split='train', label_conflict=True, created_at='2026-01-15T00:00:00Z'),
        _row('failure', split='train', is_failure=True, created_at='2026-01-10T00:00:00Z'),
    ]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=10)
    assert [r['id'] for r in out] == ['failure', 'conflict', 'recent', 'older']


def test_human_labelled_rows_are_skipped():
    rows = [
        _row('human', label_source='human'),
        _row('kept'),
    ]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=10)
    assert [r['id'] for r in out] == ['kept']


def test_frozen_rows_with_eval_version_are_skipped():
    rows = [
        _row('frozen', eval_version='eval-v1'),
        _row('kept'),
    ]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=10)
    assert [r['id'] for r in out] == ['kept']


def test_other_team_and_other_family_rows_never_appear():
    rows = [
        _row('mine'),
        _row('other-team', team_id='22222222-2222-2222-2222-222222222222'),
        _row('other-family', family='menu'),
    ]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=10)
    assert [r['id'] for r in out] == ['mine']


def test_limit_is_respected_across_the_two_queries():
    rows = [_row(f'eval-{i}', split='eval') for i in range(3)] + \
           [_row(f'train-{i}', split='train') for i in range(3)]
    client = FakeSupabaseClient(rows)
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=4)
    assert len(out) == 4
    assert all(r['split'] == 'eval' for r in out[:3])
    assert out[3]['split'] == 'train'


def test_zero_limit_makes_no_query_and_returns_nothing():
    client = FakeSupabaseClient([_row('x')])
    out = mine_failures.fetch_candidates(client, TEAM, FAMILY, limit=0)
    assert out == []
    assert client.table_calls == []


# ---------------------------------------------------------------------------
# CSV shape
# ---------------------------------------------------------------------------

def test_rows_to_records_reason_and_header_shape():
    rows = [
        _row('a', is_failure=True),
        _row('b', label_conflict=True),
        _row('c'),
    ]
    records = mine_failures.rows_to_records(rows)
    assert [r['reason'] for r in records] == ['failure', 'conflict', 'recent']
    for rec in records:
        assert set(rec.keys()) == set(mine_failures.CSV_HEADER)
    assert records[0]['is_failure'] == 'true'
    assert records[2]['is_failure'] == 'false'


def test_write_csv_header_matches_the_documented_contract(tmp_path):
    records = mine_failures.rows_to_records([_row('a', is_failure=True)])
    out_path = str(tmp_path / "out.csv")
    mine_failures.write_csv(records, out_path)
    with open(out_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        data_row = next(reader)
    assert header == ['sample_id', 'family', 'split', 'is_failure', 'label_conflict',
                       'label_source', 'device_model', 'node_id', 'created_at', 'reason']
    assert data_row[0] == 'a'
    assert data_row[-1] == 'failure'


def test_write_csv_to_stdout_when_no_out_path(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    mine_failures.write_csv(mine_failures.rows_to_records([_row('a')]), None)
    buf.seek(0)
    text = buf.getvalue()
    assert text.startswith('sample_id,')
    assert 'a,' in text


# ---------------------------------------------------------------------------
# Langfuse part
# ---------------------------------------------------------------------------

def test_langfuse_skips_cleanly_with_no_host_set(monkeypatch, capsys):
    monkeypatch.delenv('LANGFUSE_HOST', raising=False)
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert unmapped == []
    assert 'LANGFUSE_HOST not set' in capsys.readouterr().err


def test_langfuse_skips_cleanly_when_package_missing(monkeypatch, capsys):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')
    real_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'langfuse':
            raise ImportError('no module named langfuse')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', fake_import)
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert unmapped == []
    assert 'not installed' in capsys.readouterr().err


def test_langfuse_never_raises_on_api_error(monkeypatch, capsys):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')

    class ExplodingLangfuse:
        def __init__(self, **_kwargs):
            pass

        def fetch_observations(self, **_kwargs):
            raise RuntimeError('connection refused')

    fake_module = type(sys)('langfuse')
    fake_module.Langfuse = ExplodingLangfuse
    monkeypatch.setitem(sys.modules, 'langfuse', fake_module)

    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert unmapped == []
    assert 'lookup failed' in capsys.readouterr().err


class _Obs:
    def __init__(self, model, output, metadata):
        self.model = model
        self.output = output
        self.metadata = metadata


def _make_fake_langfuse_module(observations):
    class FakeLangfuseClient:
        def __init__(self, **_kwargs):
            pass

        def fetch_observations(self, **_kwargs):
            return type('R', (), {'data': observations})()

    fake_module = type(sys)('langfuse')
    fake_module.Langfuse = FakeLangfuseClient
    return fake_module


def test_langfuse_reports_zero_pairs_when_only_one_model_answers(monkeypatch, capsys):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')
    observations = [
        _Obs('qwen/qwen3-vl-8b-instruct', {'channel': '5'}, {'image_hash': 'abc'}),
    ]
    monkeypatch.setitem(sys.modules, 'langfuse', _make_fake_langfuse_module(observations))
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert unmapped == []


def test_langfuse_pair_with_sample_id_becomes_a_mapped_record(monkeypatch):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')
    observations = [
        _Obs('qwen/qwen3-vl-8b-instruct', {'channel': '5'},
             {'image_hash': 'abc', 'sample_id': 'sample-123'}),
        _Obs('claude-sonnet-4', {'channel': '6'}, {'image_hash': 'abc'}),
    ]
    monkeypatch.setitem(sys.modules, 'langfuse', _make_fake_langfuse_module(observations))
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert unmapped == []
    assert len(mapped) == 1
    assert mapped[0]['sample_id'] == 'sample-123'
    assert mapped[0]['reason'] == 'langfuse_disagreement'
    assert set(mapped[0].keys()) == set(mine_failures.CSV_HEADER)


def test_langfuse_pair_without_sample_id_is_reported_unmapped_not_invented(monkeypatch):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')
    observations = [
        _Obs('qwen/qwen3-vl-8b-instruct', {'channel': '5'}, {'image_hash': 'xyz'}),
        _Obs('claude-sonnet-4', {'channel': '6'}, {'image_hash': 'xyz'}),
    ]
    monkeypatch.setitem(sys.modules, 'langfuse', _make_fake_langfuse_module(observations))
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert len(unmapped) == 1
    assert 'xyz' in unmapped[0]


def test_langfuse_agreeing_models_are_not_a_disagreement(monkeypatch):
    monkeypatch.setenv('LANGFUSE_HOST', 'http://fake-langfuse:3001')
    observations = [
        _Obs('qwen/qwen3-vl-8b-instruct', {'channel': '5'}, {'image_hash': 'same'}),
        _Obs('claude-sonnet-4', {'channel': '5'}, {'image_hash': 'same'}),
    ]
    monkeypatch.setitem(sys.modules, 'langfuse', _make_fake_langfuse_module(observations))
    mapped, unmapped = mine_failures.fetch_langfuse_disagreements(TEAM, FAMILY, limit=10)
    assert mapped == []
    assert unmapped == []


# ---------------------------------------------------------------------------
# End-to-end: run() still succeeds when Langfuse is entirely unavailable
# ---------------------------------------------------------------------------

def test_run_still_succeeds_when_langfuse_is_unavailable(monkeypatch, tmp_path):
    rows = [_row('a', is_failure=True), _row('b')]
    fake_client = FakeSupabaseClient(rows)

    fake_supabase_utils = type(sys)('shared.src.lib.utils.supabase_utils')
    fake_supabase_utils.get_supabase_client = lambda: fake_client
    monkeypatch.setitem(sys.modules, 'shared.src.lib.utils.supabase_utils', fake_supabase_utils)
    monkeypatch.delenv('LANGFUSE_HOST', raising=False)

    out_path = str(tmp_path / "out.csv")
    rc = mine_failures.run(['--team', TEAM, '--family', FAMILY, '--out', out_path])
    assert rc == 0
    with open(out_path, newline='', encoding='utf-8') as f:
        rows_out = list(csv.DictReader(f))
    assert [r['sample_id'] for r in rows_out] == ['a', 'b']


def test_run_with_no_langfuse_flag_skips_the_lookup_entirely(monkeypatch, tmp_path):
    rows = [_row('a')]
    fake_client = FakeSupabaseClient(rows)

    fake_supabase_utils = type(sys)('shared.src.lib.utils.supabase_utils')
    fake_supabase_utils.get_supabase_client = lambda: fake_client
    monkeypatch.setitem(sys.modules, 'shared.src.lib.utils.supabase_utils', fake_supabase_utils)

    called = {'value': False}

    def boom(*_args, **_kwargs):
        called['value'] = True
        raise AssertionError('fetch_langfuse_disagreements must not be called with --no-langfuse')

    monkeypatch.setattr(mine_failures, 'fetch_langfuse_disagreements', boom)

    out_path = str(tmp_path / "out.csv")
    rc = mine_failures.run(['--team', TEAM, '--family', FAMILY, '--out', out_path, '--no-langfuse'])
    assert rc == 0
    assert called['value'] is False


def test_family_argument_is_validated_against_the_six_families():
    with pytest.raises(SystemExit):
        mine_failures.build_arg_parser().parse_args(
            ['--team', TEAM, '--family', 'not-a-real-family'])


# ---------------------------------------------------------------------------
# Step 4d: failed-verification screen-id samples lead the list
# ---------------------------------------------------------------------------

FAILED = {'expected_node_id': 'n-home', 'expected_label': 'home', 'verified': False}


def test_failed_verification_screen_id_rows_come_first():
    rows = [
        _row('eval-failure', family='screen-id', split='eval', is_failure=True,
             created_at='2026-03-01T00:00:00Z'),
        _row('conflict', family='screen-id', split='eval', label_conflict=True),
        _row('fv-train-new', family='screen-id', split='train', model_answer=FAILED,
             created_at='2026-02-02T00:00:00Z'),
        _row('fv-eval-old', family='screen-id', split='eval', model_answer=FAILED,
             created_at='2026-01-01T00:00:00Z'),
        _row('fv-reviewed', family='screen-id', model_answer=FAILED, label_source='human'),
        _row('verified-ok', family='screen-id', model_answer={'verified': True}),
    ]
    out = mine_failures.fetch_candidates(FakeSupabaseClient(rows), TEAM, 'screen-id', limit=10)
    ids = [r['id'] for r in out]
    assert ids[:2] == ['fv-eval-old', 'fv-train-new']
    assert ids[2:4] == ['eval-failure', 'conflict']
    assert 'fv-reviewed' not in ids and len(ids) == len(set(ids)) == 5
    reasons = [r['reason'] for r in mine_failures.rows_to_records(out)]
    assert reasons[:4] == ['failed_verification', 'failed_verification', 'failure', 'conflict']


def test_failed_verification_rows_alone_fill_a_small_limit():
    rows = [_row(f'fv{i}', family='screen-id', model_answer=FAILED,
                 created_at=f'2026-01-0{i + 1}T00:00:00Z') for i in range(3)]
    rows.append(_row('failure', family='screen-id', is_failure=True))
    out = mine_failures.fetch_candidates(FakeSupabaseClient(rows), TEAM, 'screen-id', limit=2)
    assert [r['id'] for r in out] == ['fv2', 'fv1']


def test_other_families_do_not_look_for_failed_verifications():
    rows = [_row('banner-fv-shape', model_answer={'verified': False})]
    records = mine_failures.rows_to_records(
        mine_failures.fetch_candidates(FakeSupabaseClient(rows), TEAM, FAMILY, limit=10))
    assert [r['reason'] for r in records] == ['recent']
