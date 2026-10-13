#!/usr/bin/env python3
"""mine_failures.py — TASK-27 step 4, task 1: mine eval-set review candidates.

Lists ``ai_training_samples`` rows for one team and one task family for a
human to review towards ``eval-v1`` (docs/tasks/TASK-27-ai-training-dataset.md
§8, "Step 4. Eval set v1" card). Read-only: this script never writes to the
DB, to object storage, or to Langfuse.

DB ordering
-----------
Rows with ``split='eval'`` are listed first — they are what actually gets
frozen into the eval set (§8). Within each split group (eval, then
everything else) rows are ordered ``is_failure desc, label_conflict desc,
created_at desc``: the AI's known mistakes come first, then rows already
flagged as a labelling conflict, then the newest captures. Rows already
``label_source='human'`` (already reviewed by a person) or that already
carry an ``eval_version`` (already frozen — the DB trigger refuses further
label changes on those anyway) are skipped entirely, so a reviewer never
re-does finished work.

For ``screen-id`` (step 4d), failed-verification samples come before
everything else: frames where a node verification ran and failed, stored
unlabelled with ``model_answer={'expected_node_id', 'expected_label',
'verified': false}``. They are the hardest screen-id cases and have no label
at all until a human gives one. Among them, eval rows come first, then the
newest.

Langfuse
--------
TASK-27 §3/§7 imagined a further source of hard samples: Langfuse traces
where a qwen answer and a frontier-model answer disagree on the same image.
As of 2026-09-28 this repository has no such pairs to find, for two
independent reasons, both confirmed by reading the code (not assumed):

  1. Every one of the six families' vision calls goes through
     ``call_vision_ai`` in ``shared/src/lib/utils/ai_utils.py`` (the AI gateway
     since TASK-30). That path is **not** wrapped by
     ``ObservabilitySpan``/``track_generation``
     (``backend_server/src/agent/observability.py``) — only the AI *agent*
     chat manager's LLM calls (``backend_server/src/agent/core/manager.py``)
     are traced to Langfuse today. No vision call reaches Langfuse at all.
  2. Even if it did: TASK-27 step 0 found that only one model — OpenRouter
     ``qwen/qwen3-vl-8b-instruct`` — serves the ``vision`` task in production
     on both servers, so there is no second (frontier) answer for the same
     image to disagree with.
  3. A further, structural limitation: Langfuse traces carry no ``team_id``
     today (see ``track_generation``'s metadata), so even once vision calls
     are traced, this lookup cannot filter by team the way the DB part does
     — it can only be scoped by whatever Langfuse tag or metadata a future
     instrumentation change adds.

The lookup below is implemented against the langfuse v2 SDK's read API
(``requirements.txt`` pins ``langfuse>=2.0.0,<3``) so it is ready the day
either of the above changes, but it is expected to print a "0 found" note on
stderr and return nothing today. It never raises — a missing package, an
unset ``LANGFUSE_HOST``, an SDK without a read method, or any API error is
caught, reported on stderr, and the DB part of the script still runs and the
script still exits 0. Pass ``--no-langfuse`` to skip the lookup outright.

Output
------
CSV with header::

    sample_id,family,split,is_failure,label_conflict,label_source,device_model,node_id,created_at,reason

``reason`` is one of ``failed_verification``, ``failure``, ``conflict``, ``recent`` (DB rows) or
``langfuse_disagreement`` (a Langfuse pair that *could* be tied to a stored
``sample_id`` via trace metadata). A Langfuse pair that disagrees but cannot
be tied to any ``sample_id`` is never given an invented id: it is printed as
a separate note on stderr instead of becoming a CSV row.

Usage
-----
    python3 features/ai-dataset/scripts/mine_failures.py --team <uuid> --family banner
    python3 features/ai-dataset/scripts/mine_failures.py --team <uuid> --family av-fault --limit 200 --out eval_candidates.csv
    python3 features/ai-dataset/scripts/mine_failures.py --team <uuid> --family menu --no-langfuse
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))  # features/ai-dataset/scripts -> repo
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Kept in sync with shared/src/lib/ai/training_samples.py:FAMILIES.
FAMILIES = ('screen-id', 'focus', 'menu', 'banner', 'av-fault', 'content-type', 'other')

CSV_HEADER = ['sample_id', 'family', 'split', 'is_failure', 'label_conflict',
              'label_source', 'device_model', 'node_id', 'created_at', 'reason']

TABLE = 'ai_training_samples'


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _answer(row: Dict[str, Any]) -> Any:
    answer = row.get('model_answer')
    if isinstance(answer, str):
        try:
            return json.loads(answer)
        except (ValueError, TypeError):
            return answer
    return answer


def is_failed_verification(row: Dict[str, Any]) -> bool:
    """A screen-id frame on which a node verification failed (step 4d)."""
    answer = _answer(row)
    return (row.get('family') == 'screen-id' and isinstance(answer, dict)
            and answer.get('verified') is False)


def _reason_for(row: Dict[str, Any]) -> str:
    if is_failed_verification(row):
        return 'failed_verification'
    if row.get('is_failure'):
        return 'failure'
    if row.get('label_conflict'):
        return 'conflict'
    return 'recent'


def _bool_str(value: Any) -> str:
    return 'true' if value else 'false'


# --------------------------------------------------------------------------
# DB part
# --------------------------------------------------------------------------

def _base_query(client, team_id: str, family: str):
    """A fresh, unexecuted query builder for the candidate rows.

    Every call builds a new filter chain (the supabase/postgrest query
    builder mutates and returns ``self``, so the same builder instance must
    never be reused across two different ``.execute()`` calls).

    Skips rows that are already reviewed (``label_source='human'``) or
    already frozen (``eval_version`` set) — see the module docstring for why.
    """
    return (client.table(TABLE).select('*')
            .eq('team_id', team_id)
            .eq('family', family)
            .neq('label_source', 'human')
            .is_('eval_version', 'null'))


def fetch_candidates(client, team_id: str, family: str, limit: int) -> List[Dict[str, Any]]:
    """DB part of the mine: candidate rows for ``(team_id, family)``.

    Two DB round-trips, each doing the real ordering server-side
    (``is_failure desc, label_conflict desc, created_at desc``): first the
    ``split='eval'`` rows (§8 — these are what can be frozen), then, only if
    the limit was not already reached, everything else. Concatenating two
    correctly-ordered result sets keeps "eval rows first" honest without
    asking postgrest to order by an expression.

    For ``screen-id`` one more round-trip runs first: the failed-verification
    rows (step 4d), which then lead the list.
    """
    if limit <= 0:
        return []

    failed: List[Dict[str, Any]] = []
    if family == 'screen-id':
        failed = fetch_failed_verifications(client, team_id, limit)
        if len(failed) >= limit:
            return failed[:limit]
    # Fetch a full `limit`: the failed-verification rows reappear here and are dropped.
    regular = _fetch_ordered(client, team_id, family, limit)
    seen = {r.get('id') for r in failed}
    regular = [r for r in regular if r.get('id') not in seen]
    return (failed + regular)[:limit]


def fetch_failed_verifications(client, team_id: str, limit: int) -> List[Dict[str, Any]]:
    """Step 4d: unreviewed failed-verification ``screen-id`` rows, eval first, then newest."""
    rows = (_base_query(client, team_id, 'screen-id')
            .contains('model_answer', {'verified': False})
            .order('created_at', desc=True)
            .limit(limit)
            .execute().data or [])
    rows = [r for r in rows if is_failed_verification(r)]
    # stable: keeps newest-first inside each split group
    return sorted(rows, key=lambda r: r.get('split') != 'eval')


def _fetch_ordered(client, team_id: str, family: str, limit: int) -> List[Dict[str, Any]]:
    """The ordered candidate rows: eval split first, then the rest (see ``fetch_candidates``)."""
    if limit <= 0:
        return []
    eval_rows = (_base_query(client, team_id, family)
                 .eq('split', 'eval')
                 .order('is_failure', desc=True)
                 .order('label_conflict', desc=True)
                 .order('created_at', desc=True)
                 .limit(limit)
                 .execute().data or [])

    remaining = limit - len(eval_rows)
    other_rows: List[Dict[str, Any]] = []
    if remaining > 0:
        other_rows = (_base_query(client, team_id, family)
                      .neq('split', 'eval')
                      .order('is_failure', desc=True)
                      .order('label_conflict', desc=True)
                      .order('created_at', desc=True)
                      .limit(remaining)
                      .execute().data or [])

    return list(eval_rows) + list(other_rows)


def rows_to_records(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """DB rows -> CSV-ready dicts (§ Output)."""
    records = []
    for row in rows:
        records.append({
            'sample_id': row.get('id'),
            'family': row.get('family'),
            'split': row.get('split'),
            'is_failure': _bool_str(row.get('is_failure')),
            'label_conflict': _bool_str(row.get('label_conflict')),
            'label_source': row.get('label_source'),
            'device_model': row.get('device_model'),
            'node_id': row.get('node_id') or '',
            'created_at': row.get('created_at'),
            'reason': _reason_for(row),
        })
    return records


# --------------------------------------------------------------------------
# Langfuse part
# --------------------------------------------------------------------------

def fetch_langfuse_disagreements(
    team_id: str, family: str, limit: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Vision observations where two different models answer the same image
    differently. Returns ``(mapped_records, unmapped_notes)``.

    ``mapped_records`` are shaped like the DB records above
    (``reason='langfuse_disagreement'``), for pairs that carry a
    ``sample_id`` in their trace/observation metadata. ``unmapped_notes`` are
    one-line, human-readable descriptions of disagreeing pairs that carry no
    ``sample_id`` — the caller prints these to stderr rather than writing a
    CSV row with an invented id.

    Never raises: any failure (package missing, host unset, no read method
    on this SDK build, network/API error) is caught, printed to stderr, and
    reported as "found nothing" — this must never fail the run.
    """
    host = os.environ.get('LANGFUSE_HOST', '').strip()
    if not host:
        print('[mine_failures] Langfuse: LANGFUSE_HOST not set, skipping', file=sys.stderr)
        return [], []

    try:
        from langfuse import Langfuse  # type: ignore
    except ImportError:
        print('[mine_failures] Langfuse: the "langfuse" package is not installed, skipping',
              file=sys.stderr)
        return [], []

    try:
        client = Langfuse(
            public_key=os.environ.get('LANGFUSE_PUBLIC_KEY'),
            secret_key=os.environ.get('LANGFUSE_SECRET_KEY'),
            host=host,
        )
        fetch = getattr(client, 'fetch_observations', None) or getattr(client, 'fetch_traces', None)
        if fetch is None:
            print('[mine_failures] Langfuse: this SDK build exposes no read API '
                  '(no fetch_observations/fetch_traces), skipping', file=sys.stderr)
            return [], []
        # The Langfuse API caps this page size at 100 regardless of our --limit
        # (confirmed live 2026-09-28: a larger value 400s with "must be <= 100").
        response = fetch(name='vision', limit=min(max(limit, 1), 100))
        observations = list(getattr(response, 'data', None) or [])
    except Exception as e:  # noqa: BLE001 - must never fail the run
        print(f'[mine_failures] Langfuse: lookup failed ({e}), skipping', file=sys.stderr)
        return [], []

    if not observations:
        print('[mine_failures] Langfuse: 0 vision observations found. Expected: vision calls '
              '(all six families) are not traced to Langfuse today, and step 0 found only one '
              'model serves vision in production — see the module docstring.', file=sys.stderr)
        return [], []

    return _pair_disagreements(observations, family, limit)


def _pair_disagreements(
    observations: List[Any], family: str, limit: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Group observations by image identity, keep groups with >=2 distinct
    answers from >=2 models, split into mapped/unmapped by sample_id."""
    groups: Dict[str, List[Any]] = {}
    for obs in observations:
        meta = getattr(obs, 'metadata', None) or {}
        if not isinstance(meta, dict):
            continue
        image_key = meta.get('image_hash') or meta.get('sample_id') or meta.get('image_id')
        if not image_key:
            continue
        groups.setdefault(str(image_key), []).append(obs)

    mapped: List[Dict[str, Any]] = []
    unmapped: List[str] = []
    for image_key, obs_list in groups.items():
        by_model: Dict[str, Any] = {}
        for obs in obs_list:
            model = getattr(obs, 'model', None)
            if model:
                by_model[model] = getattr(obs, 'output', None)
        if len(by_model) < 2:
            continue
        distinct_answers = {_canonical(v) for v in by_model.values()}
        if len(distinct_answers) < 2:
            continue  # same answer from both models: not a disagreement

        sample_id = None
        for obs in obs_list:
            meta = getattr(obs, 'metadata', None) or {}
            if isinstance(meta, dict) and meta.get('sample_id'):
                sample_id = meta['sample_id']
                break

        if sample_id:
            mapped.append({
                'sample_id': sample_id,
                'family': family,
                'split': '',
                'is_failure': '',
                'label_conflict': '',
                'label_source': '',
                'device_model': '',
                'node_id': '',
                'created_at': '',
                'reason': 'langfuse_disagreement',
            })
        else:
            unmapped.append(f'image={image_key} models={sorted(by_model.keys())}')

        if len(mapped) >= limit:
            break

    return mapped, unmapped


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def write_csv(records: List[Dict[str, Any]], out_path: Optional[str]) -> None:
    out_fh = open(out_path, 'w', newline='', encoding='utf-8') if out_path else sys.stdout
    try:
        writer = csv.DictWriter(out_fh, fieldnames=CSV_HEADER)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
    finally:
        if out_path:
            out_fh.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='mine_failures.py',
        description=(
            'Mine ai_training_samples candidates for eval-set review (TASK-27 step 4). '
            'DB rows are ordered split=eval first, then is_failure desc, label_conflict desc, '
            'created_at desc within each group; rows already label_source=human or already '
            'carrying an eval_version are skipped. Also looks up Langfuse vision traces where '
            'a qwen answer and a frontier answer disagree on the same image (see --no-langfuse '
            'and the module docstring for why this is expected to find nothing today). '
            'Read-only: never writes to the DB, storage, or Langfuse.'
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    parser.add_argument('--family', required=True, choices=FAMILIES, help='task family to mine')
    parser.add_argument('--limit', type=int, default=500, help='max candidate rows to list')
    parser.add_argument('--out', default=None, help='CSV output path (default: stdout)')
    parser.add_argument('--no-langfuse', action='store_true',
                        help='skip the Langfuse disagreement lookup entirely')
    return parser


def run(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    from shared.src.lib.utils.supabase_utils import get_supabase_client
    client = get_supabase_client()

    rows = fetch_candidates(client, args.team, args.family, args.limit)
    records = rows_to_records(rows)

    if not args.no_langfuse:
        remaining = max(args.limit - len(records), 0)
        if remaining > 0:
            mapped, unmapped = fetch_langfuse_disagreements(args.team, args.family, remaining)
            records.extend(mapped)
            if unmapped:
                print('[mine_failures] Langfuse disagreements with no sample_id '
                      '(not written to the CSV):', file=sys.stderr)
                for line in unmapped:
                    print(f'  {line}', file=sys.stderr)

    write_csv(records, args.out)
    print(f'[mine_failures] {len(records)} candidate row(s) for team={args.team} '
          f'family={args.family}', file=sys.stderr)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == '__main__':
    main()
