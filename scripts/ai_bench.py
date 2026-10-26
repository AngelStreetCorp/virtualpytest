#!/usr/bin/env python3
"""ai_bench.py — TASK-143: benchmark one usage key against named model profiles.

Every AI call the platform makes has a usage key. This runs the **frozen test cases** of
one usage key against one or more **named model profiles** and says which model answers
that call best, at what cost and how fast.

    python3 scripts/ai_bench.py --key text.plan --profile minimax-m3 --profile claude-sonnet-5-5
    python3 scripts/ai_bench.py --key vision.banner --family vision
    python3 scripts/ai_bench.py --key text.decision.localize --predefined
    python3 scripts/ai_bench.py --key text.plan --list-cases
    python3 scripts/ai_bench.py --key text.plan --profile minimax-m3 --dry-run

Where the pieces live
---------------------
cases    docs/agent/ai/benchmarks/cases/<usage key>.jsonl   the frozen input (one case per line)
results  docs/agent/ai/benchmarks/bench-<usage key>.jsonl  one line per run (what benchmark_log.py reads)
db       public.ai_calls (usage_key = eval:<usage key>)     one row per case (what Grafana and the page read)
models   docs/agent/ai/benchmarks/models.json               the predefined models per family / per key

The run is the **production call path**: ``router.resolve_profile`` pins the named profile
(one hop, no fallback — the model measured is the model that answered) and ``gateway.execute``
runs it, so the call is logged, traced and priced exactly as the real call is.

A benchmark case **is** an AI call, so it lands in the call log (``ai_calls``) like any other
call — the runner only adds the verdict of the case (``parse_ok``) and the run / case ids
(``ref_type`` / ``ref_id`` / ``ref_kind``) to the row the production path built. Grafana and
Monitoring → AI usage read those rows; no table of their own is needed.

Runs where the provider keys are (the backend server):
``python3 scripts/ai_bench.py --key <usage key> --profile <profile name>``
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.environ.get('VPT_ROOT', '/opt/virtualpytest'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.src.lib.ai import gateway, router  # noqa: E402

ROOT = os.environ.get('VPT_ROOT', '/opt/virtualpytest')
BENCH_DIR = os.path.join(ROOT, 'docs', 'agent', 'ai', 'benchmarks')
CASES_DIR = os.path.join(BENCH_DIR, 'cases')
MODELS_FILE = os.path.join(BENCH_DIR, 'models.json')
REPO_BENCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'docs', 'agent', 'ai', 'benchmarks')


def _bench_dir() -> str:
    """The benchmarks folder: the deployed copy when there is one, else the repo's."""
    if os.path.isdir(BENCH_DIR):
        return BENCH_DIR
    return REPO_BENCH_DIR


def uc_for(usage_key: str) -> str:
    """The benchmark id of a usage key. Also the result file's name (benchmark_log.py reads the
    file name as the ``uc``), so the two always agree."""
    return f'bench-{usage_key}'


# --------------------------------------------------------------------------- cases

def cases_path(usage_key: str) -> str:
    return os.path.join(_bench_dir(), 'cases', f'{usage_key}.jsonl')


def load_cases(usage_key: str, path: str = None) -> list:
    """The frozen case set of a usage key. A file that does not exist is an empty set."""
    path = path or cases_path(usage_key)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                print(f"[ai_bench] {path}: bad case line ({e}) — skipped")
    return out


def prompt_sha(case: dict) -> str:
    """The sha of the frozen input, so a changed case is visible in the results."""
    payload = json.dumps({k: case.get(k) for k in ('id', 'kind', 'prompt', 'system', 'state',
                                                   'instructions', 'options', 'image', 'sample_id')},
                          sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


# --------------------------------------------------------------------------- checks

def _as_text(answer) -> str:
    return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False, default=str)


def _check_contains(answer, expect, case) -> dict:
    found = str(expect).lower() in _as_text(answer).lower()
    return {'type': 'contains', 'expected': expect, 'ok': found}


def _check_equals(answer, expect, case) -> dict:
    got = _as_text(answer).strip()
    return {'type': 'equals', 'expected': expect, 'got': got, 'ok': got == str(expect).strip()}


def _check_regex(answer, expect, case) -> dict:
    import re
    try:
        found = re.search(str(expect), _as_text(answer), re.S | re.I) is not None
    except re.error as e:
        return {'type': 'regex', 'expected': expect, 'ok': False, 'error': f'bad regex: {e}'}
    return {'type': 'regex', 'expected': expect, 'ok': found}


def _check_json_field(answer, expect, case) -> dict:
    """The answer must be JSON and every {field: value} in ``expect`` must match."""
    try:
        data = json.loads(_as_text(answer))
    except ValueError:
        return {'type': 'json_field', 'expected': expect, 'ok': False, 'error': 'not JSON'}
    if not isinstance(data, dict):
        return {'type': 'json_field', 'expected': expect, 'ok': False, 'error': 'not a JSON object'}
    bad = {k: {'expected': v, 'got': data.get(k)} for k, v in (expect or {}).items() if data.get(k) != v}
    return {'type': 'json_field', 'expected': expect, 'ok': not bad, 'mismatch': bad}


def _check_choice(answer, expect, case) -> dict:
    """The answer must name one of the expected options (a decision model's choice, or a word)."""
    text = _as_text(answer)
    options = expect if isinstance(expect, list) else [expect]
    hit = next((o for o in options if str(o).lower() in text.lower()), None)
    return {'type': 'choice', 'expected': options, 'ok': hit is not None, 'hit': hit}


def _check_nonempty(answer, expect, case) -> dict:
    text = _as_text(answer).strip()
    return {'type': 'nonempty', 'ok': bool(text), 'length': len(text)}


def _check_manual(answer, expect, case) -> dict:
    """Scored by a human later: the run is recorded, the case counts as unscored."""
    return {'type': 'manual', 'ok': None, 'skipped': True}


CHECKS = {
    'contains': _check_contains,
    'equals': _check_equals,
    'regex': _check_regex,
    'json_field': _check_json_field,
    'choice': _check_choice,
    'nonempty': _check_nonempty,
    'manual': _check_manual,
}


def score_case(answer, case) -> tuple:
    """Run the case's checks. Returns (ok, score 0..1, the checks)."""
    checks = case.get('checks') or []
    if not checks:
        checks = [{'type': 'nonempty'}]
    results = []
    for c in checks:
        kind = (c.get('type') or 'contains').lower()
        fn = CHECKS.get(kind, _check_contains)
        try:
            results.append(fn(answer, c.get('expect'), case))
        except Exception as e:  # a broken check never takes the run down
            results.append({'type': kind, 'ok': False, 'error': str(e)[:200]})
    scored = [r for r in results if r.get('ok') is not None]
    if not scored:
        return None, 0.0, results
    passed = sum(1 for r in scored if r.get('ok'))
    return passed == len(scored), round(passed / len(scored), 4), results


# --------------------------------------------------------------------------- images

def _training_storage():
    from shared.src.lib.utils import cloudflare_utils
    return cloudflare_utils.get_training_storage()


def register_feature_usages() -> None:
    """Register the usage keys the features own (the companion's seven).

    A feature registers its keys when the server loads it (``features/<name>/lib/usages.py``);
    the runner runs outside the server, so it registers them itself before it resolves a profile.
    """
    try:
        from features.companion.lib import usages as companion_usages
        companion_usages.register_usages()
    except Exception as e:                       # the feature may not be deployed here
        print(f"[ai_bench] feature usages: {e}")


def _sample_row(sample_id, team_id):
    """The labelled sample behind a case (its prompt, its ground truth, its image).

    With a team the sample is looked up in that team; without one the id alone is enough — the
    labelled set is reference data, and the sample ids of the cases are unique.
    """
    from shared.src.lib.database import ai_training_samples_db
    if team_id:
        return ai_training_samples_db.get_sample(sample_id, team_id)
    try:
        result = (ai_training_samples_db.get_supabase().table(ai_training_samples_db.TABLE)
                  .select('id, object_key, prompt, team_id, device_model, userinterface, ground_truth')
                  .eq('id', sample_id).limit(1).execute())
        if not result.data:
            return None
        row = dict(result.data[0])
        row['id'] = str(row.get('id') or '')
        return row
    except Exception as e:
        print(f"[ai_bench] training sample {sample_id}: {e}")
        return None


def image_for(case, tmp_dir, team_id=None) -> str:
    """The base64 image of a case: a training sample (``sample_id``) or a local file (``image``)."""
    sample_id = case.get('sample_id')
    if sample_id:
        row = _sample_row(sample_id, team_id)
        if not row:
            raise RuntimeError(f'no training sample {sample_id}')
        local = os.path.join(tmp_dir, f'{sample_id}.jpg')
        result = _training_storage().download_file(row['object_key'], local)
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'sample download failed')
        with open(local, 'rb') as f:
            data = f.read()
        os.remove(local)
        return base64.b64encode(data).decode()
    path = case.get('image')
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    with open(full, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def prompt_for(case, team_id=None) -> str:
    """The prompt of a case: its own, else the prompt stored with the labelled sample."""
    prompt = case.get('prompt')
    if prompt:
        return prompt
    sample_id = case.get('sample_id')
    if sample_id:
        row = _sample_row(sample_id, team_id)
        if row and row.get('prompt'):
            return row['prompt']
    return ''


# --------------------------------------------------------------------------- the call log

_LOG_ROWS: list = []


def _capture_log_rows() -> None:
    """Take over the call-log rows the production path builds, so the runner can add the verdict.

    Every billed call ends in ``call_log.submit``. The runner replaces it for the duration of the
    run: the rows are built by the production code (model, endpoint, tokens, latency, cost) and
    written by the runner itself, with the verdict of the case on them.
    """
    from shared.src.lib.ai import call_log
    call_log.submit = _LOG_ROWS.append


def _served_row() -> dict:
    """The call-log row of the call that served the case (the last one served)."""
    for row in reversed(_LOG_ROWS):
        if row.get('outcome') == 'served':
            return row
    return _LOG_ROWS[-1] if _LOG_ROWS else None


# --------------------------------------------------------------------------- the run

def run_case(resolution, case, tmp_dir, team_id=None, run_id=None) -> dict:
    """One case against the pinned resolution. Returns the row for the results and the call log."""
    from shared.src.lib.ai import caller as ai_caller
    from shared.src.lib.ai import decisions
    kind = (case.get('kind') or 'text').lower()
    case_id = str(case.get('id') or '')
    started = time.time()
    answer = None
    error = None
    request_id = resolution.request_id
    hop = resolution.hops[0] if resolution.hops else None
    model = getattr(hop, 'model', None)
    endpoint = getattr(hop, 'endpoint_name', None)
    tokens_in = tokens_out = 0
    cost = None
    _LOG_ROWS.clear()
    # The caller context is what the call log row carries: this call is a benchmark case of this run.
    token = ai_caller.bind(origin='eval', route='benchmark', ref_type='benchmark',
                            ref_id=run_id or '', ref_kind=case_id)
    try:
        try:
            if kind == 'decision':
                out = decisions.choose(resolution, case.get('state', ''), case.get('options') or [],
                                       instructions=case.get('instructions') or 'Which one is it?')
                if not out.get('success'):
                    raise RuntimeError(out.get('error') or 'decision failed')
                answer = {'choice': out.get('choice'), 'confidence': out.get('confidence'),
                          'probabilities': out.get('probabilities')}
                tokens_in = int((out.get('usage') or {}).get('input_tokens') or 0)
                tokens_out = int((out.get('usage') or {}).get('output_tokens') or 0)
                cost = out.get('cost')
            else:
                image_b64 = image_for(case, tmp_dir, team_id) if kind == 'vision' else None
                out = gateway.execute(resolution, prompt_for(case, team_id),
                                      system=case.get('system') or None,
                                      image_b64=image_b64,
                                      max_tokens=int(case.get('max_tokens') or 800),
                                      temperature=float(case.get('temperature') if case.get('temperature') is not None else 0.0))
                if not out.get('success'):
                    raise RuntimeError(out.get('error') or 'call failed')
                answer = out.get('content') or ''
                usage = out.get('usage') or {}
                tokens_in = int(usage.get('prompt_tokens') or 0)
                tokens_out = int(usage.get('output_tokens') or 0)
                cost = out.get('cost')
                request_id = out.get('trace_id') or request_id
        except Exception as e:
            error = str(e)[:400]
    finally:
        ai_caller.unbind(token)
    ms = int((time.time() - started) * 1000)
    if answer is None and not error:
        error = 'no answer'
    ok, score, checks = (False, 0.0, []) if error else score_case(answer, case)
    log_row = _served_row()
    if log_row is not None:
        # The verdict of the case: the call log's own parse_ok (the answer looked like the
        # usage's output format) is replaced by the verdict of the case's own checks.
        log_row['parse_ok'] = ok
        # The gateway does not return the price, and the token names differ per provider: the
        # call log row carries what the call really cost and how many tokens it used.
        if cost is None:
            cost = log_row.get('cost')
        if not tokens_in:
            tokens_in = int(log_row.get('tokens_in') or 0)
        if not tokens_out:
            tokens_out = int(log_row.get('tokens_out') or 0)
        if log_row.get('latency_ms'):
            ms = int(log_row['latency_ms'])
    return {
        'case_id': case_id,
        'kind': kind,
        'ok': bool(ok) if not error else False,
        'scored': ok is not None,
        'score': score,
        'error': error,
        'ms': ms,
        'tokens_in': tokens_in,
        'tokens_out': tokens_out,
        'cost': cost,
        'request_id': request_id,
        'model': model,
        'endpoint': endpoint,
        'answer': answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False, default=str),
        'checks': checks,
        'prompt_sha': prompt_sha(case),
        'log_row': log_row,
    }


def run_profile(usage_key, profile, cases, team_id, *, write_db=True, verbose=True) -> dict:
    """One named model against the whole case set."""
    run_id = str(uuid.uuid4())
    resolution = router.resolve_profile(profile, usage_key, team_id, request_id=run_id.replace('-', ''))
    hop = resolution.hops[0]
    rows = []
    _capture_log_rows()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        for case in cases:
            r = run_case(resolution, case, tmp_dir, team_id, run_id=run_id)
            r['run_id'] = run_id
            r['usage_key'] = usage_key
            r['uc'] = uc_for(usage_key)
            r['profile'] = hop.profile_name
            r['team_id'] = team_id
            rows.append(r)
            if verbose:
                mark = 'PASS' if r['ok'] else ('FAIL' if not r['error'] else 'ERR ')
                print(f"  [{mark}] {r['case_id']:<28} {r['ms']:>6} ms  {r['error'] or ''}")
    passed = sum(1 for r in rows if r['ok'])
    total = len(rows)
    errors = sum(1 for r in rows if r['error'])
    return {
        'run_id': run_id,
        'usage_key': usage_key,
        'uc': uc_for(usage_key),
        'profile': hop.profile_name,
        'model': hop.model,
        'endpoint': hop.endpoint_name,
        'team_id': team_id,
        'rows': rows,
        'passed': passed,
        'total': total,
        'errors': errors,
        'tokens_in': sum(r['tokens_in'] for r in rows),
        'tokens_out': sum(r['tokens_out'] for r in rows),
        'cost': round(sum(float(r['cost'] or 0) for r in rows), 8),
        'wall_s': round(sum(r['ms'] for r in rows) / 1000.0, 3),
    }


# --------------------------------------------------------------------------- results

def result_row(run: dict) -> dict:
    """The line appended to the result jsonl — the shape ``benchmark_log.py`` already reads.

    The five score dimensions are the ones the tool sums (completion, grounding, reliability,
    safety, cost_time); the per-case detail lives in ``metrics`` (like uc-04 does).
    """
    total = run['total'] or 1
    pass_rate = run['passed'] / total
    completion = 2 if pass_rate == 1 else (1 if pass_rate > 0 else 0)
    grounding = 2 if pass_rate == 1 else 0
    reliability = 2 if run['errors'] == 0 else 0
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return {
        'uc': run['uc'],
        'id': f"{run['uc']}-{date}-{run['profile']}",
        'date': date,
        'model': run['model'],
        'phase': 'cases',
        'outcome': 'done' if pass_rate == 1 else ('partial' if pass_rate > 0 else 'failed'),
        'scores': {'completion': completion, 'grounding': grounding, 'reliability': reliability,
                   'safety': None, 'cost_time': None},
        'gate': None,
        'scored_by': 'ai_bench.py (automated checks)',
        'kind': 'model',
        'test': run['usage_key'],
        'categories': ['bench'],
        'setup': f"ai_bench.py, {run['total']} frozen cases, profile '{run['profile']}' pinned (no fallback)",
        'steps': run['total'],
        'tokens_in': run['tokens_in'],
        'tokens_out': run['tokens_out'],
        'wall_s': run['wall_s'],
        'cost_usd': run['cost'],
        'source': f"scripts/ai_bench.py --key {run['usage_key']} --profile {run['profile']}",
        'prompt_ref': f"docs/agent/ai/benchmarks/cases/{run['usage_key']}.jsonl",
        'metrics': {
            'passed': run['passed'],
            'total': run['total'],
            'errors': run['errors'],
            'pass_rate': round(pass_rate, 4),
            'run_id': run['run_id'],
            'cases': [{'id': r['case_id'], 'ok': r['ok'], 'scored': r.get('scored', True),
                       'score': r['score'], 'error': r['error'],
                       'ms': r['ms'], 'tokens_in': r['tokens_in'], 'tokens_out': r['tokens_out'],
                       'cost': r['cost'], 'checks': r['checks']} for r in run['rows']],
        },
    }


def append_result(run: dict, out_path: str = None) -> str:
    """Append the run to the result jsonl (one line, append-only; a later line with the same id wins)."""
    path = out_path or os.path.join(_bench_dir(), f"{run['uc']}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = result_row(run)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return path


def write_db(run: dict) -> int:
    """The call-log rows of the run, with the verdict of every case on them.

    The rows are the ones the production path built (model, endpoint, tokens, latency, cost);
    only the verdict (``parse_ok``) and the run / case ids were added by the runner. A database
    that is down must not lose the result file.
    """
    rows = [r['log_row'] for r in run['rows'] if r.get('log_row')]
    if not rows:
        return 0
    try:
        from shared.src.lib.database import ai_benchmarks_db
        return ai_benchmarks_db.write_cases(rows)
    except Exception as e:
        print(f"[ai_bench] database write failed: {e}")
        return 0


# --------------------------------------------------------------------------- models

def load_models() -> dict:
    path = os.path.join(_bench_dir(), 'models.json')
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def profiles_for(usage_key: str, models: dict, family: str = None) -> list:
    """The predefined models of a usage key: its own list, else its family's."""
    keys = models.get('keys') or {}
    if usage_key in keys:
        return list(keys[usage_key])
    fams = models.get('families') or {}
    family = family or family_of(usage_key)
    if family and family in fams:
        return list(fams[family])
    return []


def family_of(usage_key: str) -> str:
    if usage_key.startswith('vision'):
        return 'vision'
    if usage_key.startswith('text.decision') or usage_key.startswith('analyzer'):
        return 'decision'
    if usage_key.startswith('text') or usage_key.startswith('public') or usage_key.startswith('agent'):
        return 'text'
    return 'text'


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--key', required=True, help='the production usage key to benchmark')
    ap.add_argument('--profile', action='append', default=[], help='a named model profile (repeatable)')
    ap.add_argument('--family', help='run the predefined models of a family (text, vision, decision)')
    ap.add_argument('--predefined', action='store_true', help='run the predefined models of this key')
    ap.add_argument('--cases', help='the case file (default: benchmarks/cases/<key>.jsonl)')
    ap.add_argument('--team-id', default=os.environ.get('VPT_TEAM_ID') or os.environ.get('TEAM_ID'))
    ap.add_argument('--limit', type=int, default=0, help='max cases per run')
    ap.add_argument('--out', help='the result file (default: benchmarks/bench-<key>.jsonl)')
    ap.add_argument('--no-db', action='store_true', help='do not write the database rows')
    ap.add_argument('--dry-run', action='store_true', help='show what would run, call nothing')
    ap.add_argument('--list-cases', action='store_true', help='print the case set and stop')
    ap.add_argument('--list-models', action='store_true', help='print the predefined models and stop')
    args = ap.parse_args()

    register_feature_usages()
    models = load_models()

    if args.list_models:
        print(json.dumps({'key': args.key, 'family': family_of(args.key),
                          'profiles': profiles_for(args.key, models, args.family)}, indent=2))
        return 0

    cases = load_cases(args.key, args.cases)
    if args.limit:
        cases = cases[:args.limit]

    if args.list_cases:
        print(f"{len(cases)} case(s) for {args.key}:")
        for c in cases:
            print(f"  - {c.get('id')}  [{c.get('kind') or 'text'}]  "
                  f"{len(c.get('checks') or [])} check(s)  {c.get('notes') or ''}")
        return 0

    profiles = list(args.profile)
    if args.predefined or args.family:
        for p in profiles_for(args.key, models, args.family):
            if p not in profiles:
                profiles.append(p)
    if not profiles:
        print(f"[ai_bench] no model named. Use --profile <name>, --family <family> or --predefined.\n"
              f"           Predefined for {args.key}: {profiles_for(args.key, models, family_of(args.key)) or 'none'}")
        return 2
    if not cases:
        print(f"[ai_bench] no cases for {args.key}. Expected {cases_path(args.key)}")
        return 2

    print(f"[ai_bench] {args.key}: {len(cases)} case(s) x {len(profiles)} model(s)")
    if args.dry_run:
        for c in cases:
            print(f"  - {c.get('id')}  [{c.get('kind') or 'text'}]")
        return 0

    gateway.use_local_routing()
    runs = []
    for profile in profiles:
        print(f"[ai_bench] === {profile} ===")
        try:
            run = run_profile(args.key, profile, cases, args.team_id, write_db=not args.no_db)
        except Exception as e:
            print(f"[ai_bench] {profile}: {e}")
            continue
        path = append_result(run, args.out)
        n_db = write_db(run) if not args.no_db else 0
        runs.append(run)
        print(f"[ai_bench] {profile}: {run['passed']}/{run['total']} passed, "
              f"{run['tokens_in']}/{run['tokens_out']} tokens, ${run['cost']:.6f} -> {path}"
              f" ({n_db} db row(s))")

    if runs:
        best = max(runs, key=lambda r: (r['passed'] / (r['total'] or 1), -r['cost']))
        print(f"[ai_bench] best: {best['profile']} ({best['passed']}/{best['total']}, ${best['cost']:.6f})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
