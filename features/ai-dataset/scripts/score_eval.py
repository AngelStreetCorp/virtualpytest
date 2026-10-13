#!/usr/bin/env python3
"""score_eval.py — TASK-27 step 5: score one AI profile on the eval samples of one family.

Reads human-verified eval rows (or a frozen ``eval-vN``) from ``ai_training_samples``,
fetches each image from the training bucket, asks the model through the TASK-30 gateway
with **one pinned profile and no fallback**, parses and compares the answer, and writes
one JSON result file per run. ``--report`` merges every result file into
``docs/tasks/TASK-27-eval-results.md``.

Read-only on data: never writes a sample, a label, a route or a profile. The only side
effects are the ones every AI call has (the ``ai_usage_stats`` hourly counter under the
family's usage key and the Langfuse trace) and the result file.

Langfuse (2026-10-04)
---------------------
After the result file is written, unless ``--no-langfuse`` or tracing is off, the run goes
to Langfuse as a **dataset run** (``lib/langfuse_scores.push_eval_run``): dataset
``vpt-eval-<family>`` (``vpt-eval-<family>-<eval-vN>`` with ``--source eval-version``), one
item per scored sample (id ``<dataset>:<sample id>``, input object_key / userinterface /
question, expected output the ground truth), each call's trace linked under the run
``run_id`` and scored ``correct`` (and ``focus_correct`` for a ``screen-id`` row with a
focus). Model comparison over time is Langfuse's dataset view. A Langfuse failure is a
warning: the run and its file are unchanged.

Routing
-------
``router.resolve_profile(<id or name>, usage)`` returns a single-hop resolution (no
fallback chain), run by ``gateway.execute``: the production call path (image resize to
the profile's ``image_max_edge``, empty-answer retries, endpoint semaphore, tracing,
stats) with nothing to fall back to. Each call is still checked: a result whose
``profile`` differs from the pinned one or with ``fallback_used`` aborts the run.
Usage key: ``vision.banner`` / ``vision.menu`` where production has one, else ``vision``.

Model identity
--------------
``model`` is the profile's model id. For an ``openai_compatible`` endpoint the script
also asks the server what it serves (``GET <base>/models`` and LM Studio's
``GET <root>/api/v0/models/<id>``) and records ``model_reported`` with the quantization
(e.g. ``Q4_K_M``), so every result says which GGUF was scored.

Screen groups (step 4k)
-----------------------
A ``screen-id`` prompt lists the app's **screen groups** (``lib/screen_group_scope``: Home with
any tab focused is ``home``), and a row is correct when the model names the row's group. A
row whose grouped label has a ``focus`` also gets the ``focus`` question on the same image
(a second call); it is scored apart as the ``screen-id/focus`` sub-metric
(``summary.focus``, its own row in the report) and never changes the screen accuracy. The
confusion table stays per group.

Usage
-----
    python3 features/ai-dataset/scripts/score_eval.py --team <uuid> --family screen-id --profile qwen3-vl-8b --limit 10
    python3 features/ai-dataset/scripts/score_eval.py --team <uuid> --family banner --profile <id> --source eval-version --eval-version eval-v1
    python3 features/ai-dataset/scripts/score_eval.py --team <uuid> --family focus --profile qwen3-vl-8b --dry-run
    python3 features/ai-dataset/scripts/score_eval.py --report
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FEATURE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '..'))  # features/ai-dataset/scripts -> repo
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_lib(name: str):
    """The feature's lib module next to this script (works from a copied tree too)."""
    path = os.path.join(_FEATURE_DIR, 'lib', f'{name}.py')
    spec = importlib.util.spec_from_file_location(f'ai_dataset_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


family_prompts = _load_lib('family_prompts')
comparators = _load_lib('comparators')
langfuse_scores = _load_lib('langfuse_scores')

FAMILIES = family_prompts.FAMILIES
USAGE_BY_FAMILY = {'banner': 'vision.banner', 'menu': 'vision.menu'}
DEFAULT_OUT = os.path.join(_FEATURE_DIR, 'results')
REPORT_PATH = os.path.join(_REPO_ROOT, 'docs', 'tasks', 'TASK-27-eval-results.md')
MAX_TOKENS = 600
TOP_CONFUSIONS = 10


class FallbackAbort(RuntimeError):
    """A call was answered by another profile than the pinned one: the run is invalid."""


def usage_for(family: str) -> str:
    return USAGE_BY_FAMILY.get(family, 'vision')


# ---- checks and scoring (pure) --------------------------------------------------------

def check_call(result: Dict[str, Any], pinned_profile: str) -> None:
    """Abort unless the call was served by the pinned profile, without fallback."""
    if result.get('fallback_used'):
        raise FallbackAbort(f"call used a fallback ({result.get('profile')}), pinned {pinned_profile}")
    answered = result.get('profile')
    if answered is not None and answered != pinned_profile:
        raise FallbackAbort(f"call answered by profile {answered}, pinned {pinned_profile}")


def score_samples(rows: List[Dict[str, Any]], family: str, *, pinned_profile: str,
                  call: Callable[[str, bytes], Dict[str, Any]],
                  image_for: Callable[[Dict[str, Any]], bytes],
                  context_for: Callable[[Dict[str, Any]], Optional[dict]],
                  log: Callable[[str], None] = lambda s: None) -> List[Dict[str, Any]]:
    """Score every row. ``call(prompt, image_bytes)`` returns a gateway result dict."""
    out = []
    for i, row in enumerate(rows, 1):
        context = context_for(row)
        prompt = family_prompts.build_prompt(family, row, context)
        entry: Dict[str, Any] = {'id': row['id'], 'truth': row.get('ground_truth'),
                                 'device_model': row.get('device_model'), 'userinterface': row.get('userinterface')}
        try:
            image = image_for(row)
        except Exception as e:
            entry.update({'answer_text': None, 'parsed': None, 'correct': False,
                          'detail': f'image unavailable: {e}', 'error': str(e), 'latency_ms': None,
                          'model': None, 'profile': None, 'tokens': None})
            out.append(entry)
            log(f"[{i}/{len(rows)}] {row['id']} image error: {e}")
            continue
        started = time.time()
        result = call(prompt, image)
        latency_ms = int((time.time() - started) * 1000)
        check_call(result, pinned_profile)
        text = result.get('content') or ''
        parsed = family_prompts.parse_answer(family, text, context) if result.get('success') else None
        correct, detail = comparators.compare(family, row.get('ground_truth') or {}, parsed)
        if not result.get('success'):
            detail = f"call failed: {result.get('error')}"
        entry.update({
            'answer_text': text, 'parsed': parsed, 'correct': correct, 'detail': detail,
            'error': None if result.get('success') else result.get('error'),
            'latency_ms': latency_ms, 'model': result.get('model'), 'profile': result.get('profile'),
            'provider_used': result.get('provider_used'), 'fallback_used': bool(result.get('fallback_used')),
            'tokens': result.get('usage'), 'trace_id': result.get('trace_id'),
        })
        if family == 'screen-id' and family_prompts.focus_truth(row.get('ground_truth')) is not None:
            entry['focus'] = score_focus(row, image, call, pinned_profile)
        out.append(entry)
        focus_note = ''
        if entry.get('focus'):
            focus_note = f"  focus {'OK' if entry['focus']['correct'] else 'BAD'} {entry['focus']['detail']}"
        log(f"[{i}/{len(rows)}] {row['id']} {'OK ' if correct else 'BAD'} {latency_ms} ms  {detail}{focus_note}")
    return out


def score_focus(row: Dict[str, Any], image: bytes, call: Callable[[str, bytes], Dict[str, Any]],
                pinned_profile: str) -> Dict[str, Any]:
    """Step 4k: the ``screen-id/focus`` sub-metric of one grouped row: the ``focus`` prompt on
    the same image, compared with the label's ``focus``."""
    truth = family_prompts.focus_truth(row.get('ground_truth'))
    started = time.time()
    result = call(family_prompts.build_prompt('focus', row), image)
    latency_ms = int((time.time() - started) * 1000)
    check_call(result, pinned_profile)
    text = result.get('content') or ''
    parsed = family_prompts.parse_answer('focus', text) if result.get('success') else None
    correct, detail = comparators.screen_focus(row.get('ground_truth') or {}, parsed)
    if not result.get('success'):
        detail = f"call failed: {result.get('error')}"
    return {'truth': truth, 'answer_text': text, 'parsed': parsed, 'correct': correct, 'detail': detail,
            'error': None if result.get('success') else result.get('error'),
            'latency_ms': latency_ms, 'tokens': result.get('usage'), 'trace_id': result.get('trace_id')}


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(samples)
    correct = sum(1 for s in samples if s.get('correct'))
    latencies = [s['latency_ms'] for s in samples if s.get('latency_ms') is not None and not s.get('error')]
    tokens_in = sum((s.get('tokens') or {}).get('prompt_tokens') or 0 for s in samples)
    tokens_out = sum((s.get('tokens') or {}).get('completion_tokens') or 0 for s in samples)
    return {
        'n': n,
        'correct': correct,
        'accuracy': round(correct / n, 4) if n else None,
        'errors': sum(1 for s in samples if s.get('error')),
        'unparsed': sum(1 for s in samples if not s.get('error') and s.get('parsed') is None),
        'avg_latency_ms': int(statistics.mean(latencies)) if latencies else None,
        'p50_latency_ms': int(statistics.median(latencies)) if latencies else None,
        'tokens_in': tokens_in,
        'tokens_out': tokens_out,
        # The gateway reports tokens, not money; no price table is guessed here.
        'cost_usd': None,
        **({'focus': summarize_focus(samples)} if any(s.get('focus') for s in samples) else {}),
    }


def summarize_focus(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Step 4k: the ``screen-id/focus`` sub-metric, over the rows that have a focus only."""
    scored = [s['focus'] for s in samples if s.get('focus')]
    n = len(scored)
    correct = sum(1 for f in scored if f.get('correct'))
    latencies = [f['latency_ms'] for f in scored if f.get('latency_ms') is not None and not f.get('error')]
    return {'metric': comparators.FOCUS_SUBMETRIC, 'n': n, 'correct': correct,
            'accuracy': round(correct / n, 4) if n else None,
            'errors': sum(1 for f in scored if f.get('error')),
            'avg_latency_ms': int(statistics.mean(latencies)) if latencies else None,
            'tokens_in': sum((f.get('tokens') or {}).get('prompt_tokens') or 0 for f in scored),
            'tokens_out': sum((f.get('tokens') or {}).get('completion_tokens') or 0 for f in scored),
            'cost_usd': None}


def confusion(family: str, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per expected class: n and correct, plus the (expected, predicted) error pairs."""
    per_class: Dict[str, Dict[str, int]] = defaultdict(lambda: {'n': 0, 'correct': 0})
    pairs: Counter = Counter()
    for s in samples:
        expected = comparators.confusion_key(family, s.get('truth') or {})
        per_class[expected]['n'] += 1
        if s.get('correct'):
            per_class[expected]['correct'] += 1
        else:
            predicted = '(error)' if s.get('error') else comparators.confusion_key(family, s.get('parsed'))
            pairs[(expected, predicted)] += 1
    return {'per_class': dict(per_class), 'pairs': pairs.most_common()}


# ---- report (pure) ---------------------------------------------------------------------

def _column(run: Dict[str, Any]) -> str:
    reported = run.get('model_reported') or {}
    quant = reported.get('quantization')
    model = reported.get('id') or run.get('model')
    return f"{run.get('profile')} ({model}{', ' + quant if quant else ''})"


AI_VERSION_SUFFIX = '-ai'
MIXED_LABELS = 'labels: human+AI (mixed)'


def label_kind(eval_version: Optional[str]) -> str:
    """Step 4i: an ``eval-vN-ai`` set holds human-verified rows **and** rows where the AI
    teacher agreed with the run label; every other set is human-verified only."""
    return 'human+ai' if (eval_version or '').endswith(AI_VERSION_SUFFIX) else 'human'


def label_mix(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts of ``<label_source>`` / ``<label_source>+ai-<triage status>`` in the scored rows."""
    mix: Counter = Counter()
    for r in rows:
        triage = r.get('triage')
        if isinstance(triage, str):
            try:
                triage = json.loads(triage)
            except ValueError:
                triage = None
        status = triage.get('status') if isinstance(triage, dict) else None
        source = r.get('label_source') or 'none'
        mix[f'{source}+ai-{status}' if status and source != 'human' else source] += 1
    return dict(mix)


def _row(run: Dict[str, Any]) -> str:
    if run.get('source') == 'eval-version':
        version = run.get('eval_version')
        if label_kind(version) == 'human+ai':
            return f"{run.get('family')} [{version}, {MIXED_LABELS}]"
        return f"{run.get('family')} [{version}]"
    return f"{run.get('family')} [human eval rows]"


def latest_runs(runs: List[Dict[str, Any]]) -> Dict[tuple, Dict[str, Any]]:
    """Newest run per (row, column): a rerun replaces the older one in the table."""
    latest: Dict[tuple, Dict[str, Any]] = {}
    for run in sorted(runs, key=lambda r: r.get('created_at') or ''):
        latest[(_row(run), _column(run))] = run
    return latest


def _cell(summary: Dict[str, Any]) -> str:
    acc = summary.get('accuracy')
    parts = [f"**{acc * 100:.1f}%** ({summary.get('correct')}/{summary.get('n')})" if acc is not None else 'n=0']
    if summary.get('avg_latency_ms') is not None:
        parts.append(f"{summary['avg_latency_ms']} ms")
    cost = summary.get('cost_usd')
    parts.append(f"${cost:.4f}" if isinstance(cost, (int, float)) else f"cost n/a ({summary.get('tokens_in', 0)}+{summary.get('tokens_out', 0)} tok)")
    if summary.get('errors'):
        parts.append(f"{summary['errors']} err")
    return ' · '.join(parts)


def _focus_row(row_name: str) -> str:
    return row_name.replace('screen-id', comparators.FOCUS_SUBMETRIC, 1)


def render_report(runs: List[Dict[str, Any]]) -> str:
    latest = latest_runs(runs)
    summaries = {k: run['summary'] for k, run in latest.items()}
    # Step 4k: the screen-id/focus sub-metric is its own row, next to its screen-id row.
    for (r, c), run in latest.items():
        if run.get('family') == 'screen-id' and (run['summary'] or {}).get('focus'):
            summaries[(_focus_row(r), c)] = run['summary']['focus']
    rows = sorted({k[0] for k in summaries})
    cols = sorted({k[1] for k in summaries})
    lines = [
        '# TASK-27 eval results',
        '',
        '> Generated by `features/ai-dataset/scripts/score_eval.py --report` from the result files in',
        '> `features/ai-dataset/results/` (not committed). Do not edit by hand: rerun the report.',
        '> Each cell: accuracy (correct/n) · average latency · cost. The gateway returns tokens, not',
        '> cost, so cost shows the token counts. Newest run per cell. Every call was pinned to the',
        '> column\'s profile with fallback disabled. A row marked "labels: human+AI (mixed)" is an',
        '> `eval-vN-ai` set (TASK-27 step 4i): human-verified rows plus rows where the AI teacher',
        '> agreed with the run label. It is a pilot, not a human-verified eval set.',
        '> Since TASK-27 step 4k a `screen-id` row is correct when the model names the screen',
        '> group (Home with any tab focused is `home`); `screen-id/focus` rows score the focused',
        '> item of the rows whose label has one (a second call with the `focus` prompt).',
        '',
        '## Accuracy by family and model',
        '',
        '| Family | ' + ' | '.join(cols) + ' |',
        '|---|' + '---|' * len(cols),
    ]
    for r in rows:
        cells = [_cell(summaries[(r, c)]) if (r, c) in summaries else '' for c in cols]
        lines.append(f'| {r} | ' + ' | '.join(cells) + ' |')
    lines += ['', '## Runs', '', '| Family | Column | Run | Date (UTC) | Usage key | Endpoint | Samples |',
              '|---|---|---|---|---|---|---|']
    for (r, c), run in sorted(latest.items()):
        lines.append(f"| {r} | {c} | `{run.get('run_id')}` | {run.get('created_at')} | "
                     f"`{run.get('usage_key')}` | {run.get('endpoint')} | {run['summary'].get('n')} |")
    for (r, c), run in sorted(latest.items()):
        family = run.get('family')
        if family not in ('screen-id', 'focus'):
            continue
        conf = confusion(family, run.get('samples') or [])
        lines += ['', f'## Confusion: {r} — {c}', '', '| Expected | n | Correct | Accuracy |', '|---|---|---|---|']
        for cls, stats in sorted(conf['per_class'].items(), key=lambda kv: (-kv[1]['n'], kv[0])):
            lines.append(f"| {cls} | {stats['n']} | {stats['correct']} | {stats['correct'] / stats['n'] * 100:.0f}% |")
        lines += ['', '| Expected | Predicted | Count |', '|---|---|---|']
        if conf['pairs']:
            for (expected, predicted), count in conf['pairs'][:TOP_CONFUSIONS]:
                lines.append(f'| {expected} | {predicted} | {count} |')
        else:
            lines.append('| (no confusions) | | |')
    return '\n'.join(lines) + '\n'


def load_result_files(out_dir: str) -> List[Dict[str, Any]]:
    runs = []
    if not os.path.isdir(out_dir):
        return runs
    for name in sorted(os.listdir(out_dir)):
        if name.endswith('.json'):
            with open(os.path.join(out_dir, name), encoding='utf-8') as f:
                runs.append(json.load(f))
    return runs


# ---- IO: DB, storage, endpoint (not unit-tested) --------------------------------------

def load_rows(team_id: str, family: str, source: str, eval_version: Optional[str], limit: Optional[int]) -> List[Dict[str, Any]]:
    from shared.src.lib.database import ai_training_samples_db as samples_db
    if source == 'human':
        rows, _total = samples_db.list_samples(team_id, family=family, split='eval', label_sources=['human'],
                                               limit=limit or 1000)
    else:
        # No core helper lists a frozen version; one read-only, team-scoped query.
        query = (samples_db.get_supabase().table(samples_db.TABLE).select('*')
                 .eq('team_id', team_id).eq('family', family).eq('eval_version', eval_version)
                 .order('created_at'))
        if limit:
            query = query.limit(limit)
        rows = [samples_db._parse_row(r) for r in (query.execute().data or [])]
    rows = [r for r in rows if r.get('ground_truth') is not None]
    return rows[:limit] if limit else rows


_screen_cache: Dict[tuple, List[dict]] = {}


def screen_labels(team_id: str, userinterface: Optional[str]) -> List[dict]:
    """Step 4k: the app's screen **groups** for ``userinterface``: ``[{'node_id', 'label'}]``
    (group node id and name), sorted, from ``lib/screen_group_scope`` (the whole tree
    hierarchy, ENTRY skipped, the core overrides applied)."""
    key = (team_id, userinterface)
    if key in _screen_cache:
        return _screen_cache[key]
    if not userinterface:
        raise RuntimeError('screen-id sample has no userinterface: cannot list its screens')
    scope = _load_lib('screen_group_scope')
    out = scope.screen_entries(scope.groups_for(team_id, userinterface))
    if not out:
        raise RuntimeError(f"no tree (no screen groups) for userinterface '{userinterface}'")
    _screen_cache[key] = out
    return out


def fetch_image(storage, row: Dict[str, Any], tmp_dir: str) -> bytes:
    local = os.path.join(tmp_dir, f"{row['id']}.jpg")
    result = storage.download_file(row['object_key'], local)
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'download failed')
    with open(local, 'rb') as f:
        data = f.read()
    os.remove(local)
    return data


def endpoint_model_info(hop) -> Dict[str, Any]:
    """What the endpoint says it serves for the profile's model (best effort, read-only)."""
    info: Dict[str, Any] = {'id': hop.model}
    if hop.preset != 'openai_compatible' or not hop.base_url:
        return info
    import requests
    base = hop.base_url.rstrip('/')
    try:
        listed = [m.get('id') for m in requests.get(f'{base}/models', timeout=10).json().get('data', [])]
        info['listed'] = hop.model in listed
    except Exception as e:
        info['listed_error'] = str(e)
    root = base[:-3] if base.endswith('/v1') else base
    try:
        resp = requests.get(f'{root}/api/v0/models/{hop.model}', timeout=10)  # LM Studio only
        if resp.ok:
            data = resp.json()
            info.update({k: data.get(k) for k in ('id', 'quantization', 'arch', 'type',
                                                  'compatibility_type', 'state') if data.get(k) is not None})
    except Exception:
        pass
    return info


def _git_commit() -> Optional[str]:
    try:
        import subprocess
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=_REPO_ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def run(args) -> int:
    from shared.src.lib.ai import gateway, router
    from shared.src.lib.utils.cloudflare_utils import get_training_storage

    gateway.use_local_routing()
    family, usage = args.family, usage_for(args.family)
    resolution = router.resolve_profile(args.profile, usage, args.team)
    hop = resolution.primary
    if hop.reach == 'host':
        raise SystemExit(f"profile {hop.profile_name} is on reach=host endpoint {hop.endpoint_name}: "
                         f"the server cannot call it, so it cannot be scored from here")
    print(f"[score_eval] profile={hop.profile_name} ({hop.profile['id']}) endpoint={hop.endpoint_name} "
          f"preset={hop.preset} model={hop.model} usage={usage} fallback=disabled", file=sys.stderr)

    rows = load_rows(args.team, family, args.source, args.eval_version, args.limit)
    print(f"[score_eval] {len(rows)} labelled {family} rows ({args.source}"
          f"{' ' + args.eval_version if args.eval_version else ''}; labels {label_mix(rows)})", file=sys.stderr)
    if not rows:
        return 1
    # A screen-id row whose app has no tree any more (a temporary tree that was deleted, e.g.
    # an acceptance run's copy) cannot be asked: skip and count it instead of aborting the run.
    skipped_no_tree: Dict[str, int] = {}
    if family == 'screen-id':
        kept = []
        for row in rows:
            try:
                screen_labels(args.team, row.get('userinterface'))
                kept.append(row)
            except RuntimeError:
                ui = row.get('userinterface') or '(none)'
                skipped_no_tree[ui] = skipped_no_tree.get(ui, 0) + 1
        if skipped_no_tree:
            print(f"[score_eval] skipped {sum(skipped_no_tree.values())} rows whose app has no tree: "
                  f"{json.dumps(skipped_no_tree)}", file=sys.stderr)
        rows = kept
        if not rows:
            return 1

    def context_for(row):
        return {'screen_labels': screen_labels(args.team, row.get('userinterface'))} if family == 'screen-id' else None

    storage = get_training_storage()
    model_reported = endpoint_model_info(hop)
    print(f"[score_eval] endpoint reports: {json.dumps(model_reported)}", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix='score_eval_') as tmp_dir:
        if args.dry_run:
            prompt = family_prompts.build_prompt(family, rows[0], context_for(rows[0]))
            size = len(fetch_image(storage, rows[0], tmp_dir))
            print(f"[score_eval] dry run: first image {rows[0]['object_key']} ({size} bytes), prompt:\n{prompt}")
            print(f"[score_eval] dry run: would call {len(rows)} times; nothing called, nothing written")
            return 0

        def call(prompt, image):
            # A fresh single-hop resolution per call: new request id, same pinned profile.
            pinned = router.resolve_profile(args.profile, usage, args.team)
            return gateway.execute(pinned, prompt, image_b64=base64.b64encode(image).decode(),
                                   media_type='image/jpeg', max_tokens=MAX_TOKENS, temperature=0.0)

        try:
            samples = score_samples(rows, family, pinned_profile=hop.profile_name, call=call,
                                    image_for=lambda r: fetch_image(storage, r, tmp_dir),
                                    context_for=context_for, log=lambda s: print(s, file=sys.stderr))
        except FallbackAbort as e:
            print(f"[score_eval] ABORT: {e}. No result file written.", file=sys.stderr)
            return 2

    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    result = {
        'run_id': f"{family}-{hop.profile_name}-{created.replace(':', '')}-{uuid.uuid4().hex[:6]}",
        'created_at': created, 'team_id': args.team, 'family': family, 'source': args.source,
        'eval_version': args.eval_version, 'usage_key': usage,
        'profile': hop.profile_name, 'profile_id': str(hop.profile['id']), 'endpoint': hop.endpoint_name,
        'preset': hop.preset, 'model': hop.model, 'model_reported': model_reported,
        'thinking': hop.thinking(usage), 'fallback': 'disabled', 'git_commit': _git_commit(),
        'labels': label_kind(args.eval_version if args.source == 'eval-version' else None),
        'label_mix': label_mix(rows),
        'summary': summarize(samples), 'skipped_no_tree': skipped_no_tree, 'samples': samples,
    }
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{result['run_id']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(json.dumps({'result_file': path, 'profile': hop.profile_name, 'model': hop.model,
                      'model_reported': model_reported, **result['summary']}, indent=2))
    push_langfuse(result, rows, context_for, args.no_langfuse)
    return 0


def push_langfuse(result: Dict[str, Any], rows: List[Dict[str, Any]],
                  context_for: Callable[[Dict[str, Any]], Optional[dict]], skip: bool = False,
                  client=None) -> Optional[Dict[str, Any]]:
    """2026-10-04: the run as a Langfuse dataset run (``lib/langfuse_scores.push_eval_run``),
    after the result file is written. Skipped with ``--no-langfuse`` or when tracing is off;
    a Langfuse failure is a warning and never changes the run or its file."""
    if skip:
        return None
    client = client or langfuse_scores.get_client()
    if client is None:
        print("[score_eval] Langfuse: tracing off, no dataset run", file=sys.stderr)
        return None
    try:
        summary = langfuse_scores.push_eval_run(
            result, rows, lambda row: family_prompts.build_prompt(result['family'], row, context_for(row)),
            client=client, log=lambda s: print(s, file=sys.stderr))
    except Exception as e:  # push_eval_run never raises; belt and braces for the run's exit code
        print(f"[score_eval] Langfuse: WARNING push failed: {e}", file=sys.stderr)
        return None
    errors = summary.pop('errors')
    print(f"[score_eval] Langfuse: {json.dumps(summary)}"
          + (f"; WARNING {len(errors)} errors, first: {errors[0]}" if errors else ''), file=sys.stderr)
    return {**summary, 'errors': errors}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--team', help='team_id (uuid); every query filters by it')
    parser.add_argument('--family', choices=FAMILIES)
    parser.add_argument('--source', choices=('human', 'eval-version'), default='human',
                        help="human: split='eval' rows with label_source='human' (no freeze needed); "
                             'eval-version: the frozen rows of --eval-version')
    parser.add_argument('--eval-version', help='e.g. eval-v1, or eval-v0-ai (step 4i: human + AI-agreed '
                                               'labels, reported as mixed) (implies --source eval-version)')
    parser.add_argument('--profile', help='ai_profiles id or name to score (pinned, no fallback)')
    parser.add_argument('--limit', type=int, default=None, help='max samples')
    parser.add_argument('--out', default=DEFAULT_OUT, help='result files directory')
    parser.add_argument('--dry-run', action='store_true', help='load rows, build a prompt, fetch one image; no AI call')
    parser.add_argument('--no-langfuse', action='store_true',
                        help='do not push the run to Langfuse (dataset vpt-eval-<family>, run = run_id, '
                             'scores correct / focus_correct)')
    parser.add_argument('--report', action='store_true', help=f'merge the result files into {REPORT_PATH}')
    parser.add_argument('--report-path', default=REPORT_PATH, help=argparse.SUPPRESS)
    parser.add_argument('--env-file', default=os.path.join(_REPO_ROOT, '.env'),
                        help='dotenv file to load (read-only; existing env vars win)')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.report:
        runs = load_result_files(args.out)
        if not runs:
            print(f"[score_eval] no result files in {args.out}: report not written", file=sys.stderr)
            return 1
        with open(args.report_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(render_report(runs))
        print(f"[score_eval] report from {len(runs)} result files -> {args.report_path}")
        return 0
    if args.eval_version:
        args.source = 'eval-version'
    missing = [f for f in ('team', 'family', 'profile') if not getattr(args, f)]
    if missing or (args.source == 'eval-version' and not args.eval_version):
        build_arg_parser().error(f"needs --team, --family, --profile{' and --eval-version' if args.source == 'eval-version' else ''}")
    if os.path.isfile(args.env_file):
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
