"""TASK-143: the benchmark runner — the checks, the score and the result row.

No network, no keys, no database: the checks are pure functions and the result row is built from a
run dict. Run: pytest tests/shared/test_ai_bench.py -v
"""
import importlib.util
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

_spec = importlib.util.spec_from_file_location(
    "ai_bench", os.path.join(_repo_root, "scripts", "ai_bench.py"))
ai_bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai_bench)


# --- the checks -------------------------------------------------------------------

def test_contains_is_case_insensitive():
    ok, score, checks = ai_bench.score_case("The Movie is on AIR tonight", {"checks": [{"type": "contains", "expect": "air"}]})
    assert ok and score == 1.0 and checks[0]["ok"] is True


def test_contains_fails_when_the_word_is_absent():
    ok, score, _ = ai_bench.score_case("nothing to see here", {"checks": [{"type": "contains", "expect": "airplane"}]})
    assert not ok and score == 0.0


def test_equals_compares_the_trimmed_answer():
    assert ai_bench.score_case("  Paris  ", {"checks": [{"type": "equals", "expect": "Paris"}]})[0]
    assert not ai_bench.score_case("Paris, France", {"checks": [{"type": "equals", "expect": "Paris"}]})[0]


def test_regex_matches_anywhere():
    ok, _, _ = ai_bench.score_case("today is 2026-10-20", {"checks": [{"type": "regex", "expect": r"20\d\d-\d\d-\d\d"}]})
    assert ok


def test_a_broken_regex_never_raises():
    ok, score, checks = ai_bench.score_case("x", {"checks": [{"type": "regex", "expect": "([unclosed"}]})
    assert not ok and score == 0.0 and "error" in checks[0]


def test_json_field_needs_json_and_the_fields():
    ok, _, _ = ai_bench.score_case('{"channel_number": "2"}', {"checks": [{"type": "json_field", "expect": {"channel_number": "2"}}]})
    assert ok
    ok, _, checks = ai_bench.score_case('{"channel_number": "5"}', {"checks": [{"type": "json_field", "expect": {"channel_number": "2"}}]})
    assert not ok and checks[0]["mismatch"]["channel_number"]["expected"] == "2"
    ok, _, checks = ai_bench.score_case("not json", {"checks": [{"type": "json_field", "expect": {"a": 1}}]})
    assert not ok and checks[0]["error"] == "not JSON"


def test_choice_accepts_any_of_the_expected_options():
    ok, _, _ = ai_bench.score_case("up", {"checks": [{"type": "choice", "expect": ["up", "down", "left", "right"]}]})
    assert ok
    ok, _, _ = ai_bench.score_case("diagonal", {"checks": [{"type": "choice", "expect": ["up", "down"]}]})
    assert not ok


def test_nonempty_and_manual():
    assert ai_bench.score_case("something", {"checks": [{"type": "nonempty"}]})[0]
    assert not ai_bench.score_case("   ", {"checks": [{"type": "nonempty"}]})[0]
    ok, score, checks = ai_bench.score_case("anything", {"checks": [{"type": "manual"}]})
    assert ok is None and score == 0.0 and checks[0]["skipped"] is True


def test_a_case_without_checks_only_needs_an_answer():
    assert ai_bench.score_case("an answer", {})[0]
    assert not ai_bench.score_case("", {})[0]


def test_every_check_must_pass():
    ok, score, _ = ai_bench.score_case("airplane mode on", {"checks": [{"type": "contains", "expect": "airplane"},
                                                                     {"type": "contains", "expect": "satellite"}]})
    assert not ok and score == 0.5


# --- the uc and the case file ------------------------------------------------------

def test_the_uc_is_the_usage_key():
    assert ai_bench.uc_for("text.decision.localize") == "bench-text.decision.localize"


def test_the_case_file_of_a_key_is_where_it_says(tmp_path):
    path = tmp_path / "text.plan.jsonl"
    path.write_text('{"id": "a", "kind": "text", "prompt": "x", "checks": []}\n'
                    '\n'
                    '# a comment line\n'
                    '{"id": "b", "kind": "text", "prompt": "y", "checks": []}\n', encoding='utf-8')
    cases = ai_bench.load_cases("text.plan", str(path))
    assert [c["id"] for c in cases] == ["a", "b"]


def test_a_missing_case_file_is_an_empty_set(tmp_path):
    assert ai_bench.load_cases("no.such.key", str(tmp_path / "nope.jsonl")) == []


# --- the result row ---------------------------------------------------------------

def _run(**over):
    run = {
        'run_id': 'r-1', 'usage_key': 'text.plan', 'uc': 'bench-text.plan', 'profile': 'minimax-m3',
        'model': 'minimax-m3', 'endpoint': 'minimax', 'team_id': None,
        'rows': [{'case_id': 'c1', 'ok': True, 'score': 1.0, 'error': None, 'ms': 100, 'tokens_in': 10,
                  'tokens_out': 5, 'cost': 0.001, 'checks': [{'type': 'contains', 'ok': True}]},
                 {'case_id': 'c2', 'ok': False, 'score': 0.0, 'error': None, 'ms': 200, 'tokens_in': 20,
                  'tokens_out': 8, 'cost': 0.002, 'checks': [{'type': 'contains', 'ok': False}]}],
        'passed': 1, 'total': 2, 'errors': 0, 'tokens_in': 30, 'tokens_out': 13,
        'cost': 0.003, 'wall_s': 0.3,
    }
    run.update(over)
    return run


def test_the_result_row_carries_the_five_dimensions():
    row = ai_bench.result_row(_run())
    assert row['uc'] == 'bench-text.plan'
    assert row['scores']['completion'] == 1        # some passed
    assert row['scores']['grounding'] == 0
    assert row['scores']['reliability'] == 2       # no case errored
    assert row['scores']['safety'] is None and row['scores']['cost_time'] is None
    assert row['outcome'] == 'partial'
    assert row['metrics']['passed'] == 1 and row['metrics']['total'] == 2
    assert [c['id'] for c in row['metrics']['cases']] == ['c1', 'c2']


def test_a_run_where_everything_passed_is_done():
    run = _run(passed=2, rows=[_run()['rows'][0], dict(_run()['rows'][1], ok=True, score=1.0)])
    row = ai_bench.result_row(run)
    assert row['outcome'] == 'done' and row['scores']['completion'] == 2 and row['scores']['grounding'] == 2


def test_a_run_with_an_error_is_unreliable():
    row = ai_bench.result_row(_run(errors=1, passed=0, rows=[dict(_run()['rows'][1], ok=False, error='boom')]))
    assert row['scores']['reliability'] == 0 and row['outcome'] == 'failed'


def test_the_result_row_is_json_serialisable():
    row = ai_bench.result_row(_run())
    text = __import__('json').dumps(row)
    assert 'bench-text.plan' in text


# --- the models registry ----------------------------------------------------------

def test_the_models_registry_is_read():
    models = ai_bench.load_models()
    assert 'families' in models and 'keys' in models
    assert models['families']['text']


def test_the_family_of_a_usage_key():
    assert ai_bench.family_of('vision.banner') == 'vision'
    assert ai_bench.family_of('text.decision.localize') == 'decision'
    assert ai_bench.family_of('text.plan') == 'text'


# --- the call log: the case is an AI call -----------------------------------------

def _resolution(request_id='req-1'):
    class Hop:
        model = 'MiniMax-M3'
        endpoint_name = 'minimax'
    class Resolution:
        hops = [Hop()]
        stats_label = 'eval:text.plan'
    res = Resolution()
    res.request_id = request_id
    return res


def _fake_execute(monkeypatch, answer='Paris', ok=True, rows=None):
    """Stand in for the gateway: it builds the call-log row the way the real one does."""
    from shared.src.lib.ai import caller as ai_caller

    def _execute(resolution, prompt, **kwargs):
        fields = ai_caller.current()
        row = {
            'usage_key': resolution.stats_label, 'origin': 'eval', 'route': fields.get('route'),
            'ref_type': fields.get('ref_type'), 'ref_id': fields.get('ref_id'), 'ref_kind': fields.get('ref_kind'),
            'profile': 'minimax-m3', 'model': 'MiniMax-M3', 'endpoint': 'minimax',
            'ok': ok, 'outcome': 'served', 'latency_ms': 10, 'tokens_in': 1, 'tokens_out': 1,
            'cost': 0.002, 'request_id': resolution.request_id,
        }
        (rows if rows is not None else ai_bench._LOG_ROWS).append(row)
        return {'success': ok, 'content': answer, 'error': None if ok else 'boom',
                'usage': {'prompt_tokens': 1, 'output_tokens': 1}, 'trace_id': 'trace-1'}

    monkeypatch.setattr(ai_bench.gateway, 'execute', _execute)
    return _execute


def test_a_case_becomes_a_call_log_row_with_the_verdict(monkeypatch):
    _fake_execute(monkeypatch, answer='Paris')
    case = {'id': 'c1', 'kind': 'text', 'prompt': 'Capital of France?',
            'checks': [{'type': 'equals', 'expect': 'Paris'}]}
    row = ai_bench.run_case(_resolution(), case, '/tmp', None, run_id='run-9')
    log_row = row['log_row']
    assert log_row is not None
    assert log_row['parse_ok'] is True                     # the verdict of the case
    assert log_row['ref_type'] == 'benchmark'
    assert log_row['ref_id'] == 'run-9'
    assert log_row['ref_kind'] == 'c1'
    assert log_row['usage_key'] == 'eval:text.plan'
    assert row['ok'] is True


def test_a_key_without_its_own_models_falls_back_to_its_family():
    models = {'families': {'decision': ['jev', 'jev-router']}, 'keys': {'text.plan': ['minimax-m3']}}
    assert ai_bench.profiles_for('text.plan', models) == ['minimax-m3']
    assert ai_bench.profiles_for('text.decision.localize', models) == ['jev', 'jev-router']
    assert ai_bench.profiles_for('text.decision.localize', models, 'text') == []


def test_a_labelled_sample_is_found_without_a_team(monkeypatch):
    """A vision case points at a labelled sample; the team filter must not hide it."""
    from shared.src.lib.database import ai_training_samples_db

    class FakeQuery:
        def select(self, *a):
            return self

        def eq(self, *a):
            return self

        def limit(self, *a):
            return self

        def execute(self):
            return type('R', (), {'data': [{'id': 's1', 'object_key': 'team/screen.jpg', 'prompt': 'what is it?'}]})()

    class FakeTable:
        def __call__(self, *a):
            return FakeQuery()

    class FakeClient:
        table = FakeTable()

    monkeypatch.setattr(ai_training_samples_db, 'get_supabase', lambda: FakeClient())
    row = ai_bench._sample_row('s1', None)
    assert row and row['object_key'] == 'team/screen.jpg' and row['prompt'] == 'what is it?'


def test_the_cost_and_the_tokens_of_a_case_come_from_the_call_log(monkeypatch):
    _fake_execute(monkeypatch, answer='Paris')
    case = {'id': 'c1', 'kind': 'text', 'prompt': 'Capital of France?',
            'checks': [{'type': 'equals', 'expect': 'Paris'}]}
    row = ai_bench.run_case(_resolution(), case, '/tmp', None, run_id='run-9')
    assert row['cost'] == 0.002
    assert row['tokens_in'] == 1 and row['tokens_out'] == 1
    assert row['ms'] == 10            # the latency of the call, not the wall time of the case


def test_a_failed_check_is_a_failed_case_in_the_call_log(monkeypatch):
    _fake_execute(monkeypatch, answer='Berlin')
    case = {'id': 'c1', 'kind': 'text', 'prompt': 'Capital of France?',
            'checks': [{'type': 'equals', 'expect': 'Paris'}]}
    row = ai_bench.run_case(_resolution(), case, '/tmp', None, run_id='run-9')
    assert row['log_row']['parse_ok'] is False
    assert row['ok'] is False


def test_a_failed_call_is_a_failed_case(monkeypatch):
    _fake_execute(monkeypatch, ok=False)
    case = {'id': 'c1', 'kind': 'text', 'prompt': 'x', 'checks': [{'type': 'nonempty'}]}
    row = ai_bench.run_case(_resolution(), case, '/tmp', None, run_id='run-9')
    assert row['log_row']['parse_ok'] is False
    assert row['error']


def test_the_served_row_is_the_one_that_answered():
    ai_bench._LOG_ROWS.clear()
    ai_bench._LOG_ROWS.append({'outcome': 'skipped', 'ok': False})
    ai_bench._LOG_ROWS.append({'outcome': 'served', 'ok': True, 'parse_ok': None})
    assert ai_bench._served_row()['outcome'] == 'served'


def test_the_capture_takes_over_the_call_log(monkeypatch):
    from shared.src.lib.ai import call_log
    monkeypatch.setattr(call_log, 'submit', call_log.submit)   # restored after the test
    ai_bench._capture_log_rows()
    assert call_log.submit == ai_bench._LOG_ROWS.append


# --- the results in the database --------------------------------------------------

def test_the_stats_label_of_a_benchmark_call():
    from shared.src.lib.database import ai_benchmarks_db
    assert ai_benchmarks_db.eval_label('text.plan') == 'eval:text.plan'
    assert ai_benchmarks_db.usage_key_of('eval:text.plan') == 'text.plan'
    assert ai_benchmarks_db.usage_key_of('text.plan') == 'text.plan'


def test_the_kind_of_a_case():
    from shared.src.lib.database import ai_benchmarks_db
    assert ai_benchmarks_db.kind_of('vision.alert_triage') == 'vision'
    assert ai_benchmarks_db.kind_of('text.decision.localize') == 'decision'
    assert ai_benchmarks_db.kind_of('text.plan') == 'text'


def test_a_call_log_row_reads_as_a_case():
    from shared.src.lib.database import ai_benchmarks_db
    row = {'id': 7, 'ts': '2026-10-20T10:00:00+00:00', 'usage_key': 'eval:text.plan', 'team_id': None,
           'ref_id': 'run-1', 'ref_kind': 'c1', 'profile': 'minimax-m3', 'model': 'MiniMax-M3',
           'endpoint': 'minimax', 'latency_ms': 120, 'tokens_in': 10, 'tokens_out': 5, 'cost': 0.001,
           'parse_ok': True, 'ok': True, 'error_type': None, 'request_id': 'abc'}
    case = ai_benchmarks_db._case_view(row)
    assert case['run_id'] == 'run-1' and case['case_id'] == 'c1'
    assert case['usage_key'] == 'text.plan' and case['kind'] == 'text'
    assert case['ok'] is True and case['scored'] is True and case['score'] == 1.0
    assert case['ms'] == 120 and case['cost'] == 0.001


def test_a_failed_call_reads_as_an_error():
    from shared.src.lib.database import ai_benchmarks_db
    row = {'usage_key': 'eval:text.plan', 'ref_id': 'run-1', 'ref_kind': 'c1', 'parse_ok': False,
           'ok': False, 'error_type': 'timeout'}
    case = ai_benchmarks_db._case_view(row)
    assert case['ok'] is False and case['error'] == 'the model timed out'


def test_the_runs_are_aggregated_from_the_cases(monkeypatch):
    from shared.src.lib.database import ai_benchmarks_db
    cases = [
        {'run_id': 'r1', 'usage_key': 'text.plan', 'uc': 'text.plan', 'ts': '2026-10-20T10:00:00+00:00',
         'model': 'm', 'profile': 'p', 'endpoint': 'e', 'ok': True, 'scored': True, 'ms': 100,
         'tokens_in': 1, 'tokens_out': 2, 'cost': 0.001},
        {'run_id': 'r1', 'usage_key': 'text.plan', 'uc': 'text.plan', 'ts': '2026-10-20T10:00:01+00:00',
         'model': 'm', 'profile': 'p', 'endpoint': 'e', 'ok': False, 'scored': True, 'ms': 200,
         'tokens_in': 1, 'tokens_out': 2, 'cost': 0.002},
    ]
    monkeypatch.setattr(ai_benchmarks_db, 'list_cases', lambda *a, **k: cases)
    runs = ai_benchmarks_db.list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run['run_id'] == 'r1' and run['cases'] == 2 and run['scored'] == 2 and run['passed'] == 1
    assert run['pass_rate'] == 0.5
    assert run['ms'] == 300 and run['cost'] == 0.003

