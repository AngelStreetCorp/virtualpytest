#!/usr/bin/env python3
"""export_dataset.py — TASK-27 step 6: export ONE combined training dataset.

Dumps the labelled ``train``-split rows of ``ai_training_samples`` for the given
teams and families into one versioned folder, the input of the single combined
LoRA adapter (TASK-27 §10.1)::

    <out>/dataset-combined-<version>/
        train.jsonl      one chat-format line per sample (see below)
        images/<id>.jpg  the sample's image, downloaded read-only from the training bucket
        manifest.json    counts, balance, git hash, date, prompt hash per family

Read-only: this script never writes to the DB or to object storage.

JSONL line (the format ``training/train_combined.py`` loads; it is the chat
"content list" shape Unsloth / TRL vision fine-tuning uses, see training/README.md)::

    {"messages": [
        {"role": "user", "content": [
            {"type": "image", "image": "images/<id>.jpg"},
            {"type": "text",  "text": "<family_prompts.build_prompt(...)>"}]},
        {"role": "assistant", "content": "<family_prompts.answer_to_text(...)>"}],
     "family": "<family>", "id": "<sample id>"}

Guards (each one refuses the whole export, never skips silently):
  * ``--teams`` is required (§9: lab teams only until the customer data-use clause).
  * no exported row has ``split`` in (``eval``, ``holdout``) or an ``eval_version``;
  * no exported row has ``label_source='none'`` or a null ``ground_truth``;
  * ``teacher`` labels only with ``--include-teacher``.

Skipped and counted (not a refusal): a row whose triage status is ``excluded`` (a second
AI pass could not settle it, ``triage_batch.py --second-pass``) never trains.

Prompts come from ``features/ai-dataset/lib/family_prompts.py`` (TASK-27 step 5),
imported as the module ``family_prompts``: ``FAMILY_PROMPTS``, ``build_prompt``,
``answer_to_text``. ``screen-id`` prompts get the tree's screen labels of the
sample's userinterface (``context={'screen_labels': [...]}``), read with the same
DB chain as the node dropdown (userinterface -> root tree -> full hierarchy).
A freeze-strip sample (``model_answer.evidence == 'strip'``) is one object, so it
exports as its single strip image.

Step 4k: a ``screen-id`` prompt lists the app's **screen groups** (``lib/screen_group_scope``),
and a ``screen-id`` row whose label has a ``focus`` exports **two** lessons on the same image:
the screen question (answer: the group), then the focus question (``build_prompt('focus')``,
answer ``{"focused": "<focus>"}``) as a ``focus`` line with id ``<id>:focus``. A null focus
(the group's own node, a pre-4k label, a screen not in the tree) exports the screen lesson only.
The manifest counts those extra lines in ``counts.focus_from_screen_id``.

Environment: the DB (``SUPABASE_*``) and the training bucket (``MINIO_TRAINING_*``
or ``R2_TRAINING_BUCKET``) must be in the environment; nothing loads a ``.env``.

Usage
-----
    python3 features/ai-dataset/scripts/export_dataset.py --teams <uuid> --version v0 --dry-run
    python3 features/ai-dataset/scripts/export_dataset.py --teams <uuid> --version v1 --out /tmp/ds
    python3 features/ai-dataset/scripts/export_dataset.py --teams <a>,<b> --families screen-id,banner \\
        --version v1 --out /data/ds --cap-per-family 2000 --include-teacher
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))  # features/ai-dataset/scripts -> repo
# Copied elsewhere (e.g. /tmp) the three-levels-up guess is wrong: then rely on PYTHONPATH/cwd.
if os.path.isdir(os.path.join(_REPO_ROOT, "shared")) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_LIB_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "lib"))  # features/ai-dataset/lib (step 5)
if _LIB_DIR not in sys.path:
    sys.path.append(_LIB_DIR)

# Trainable families, in report order. Kept in sync with
# shared/src/lib/ai/training_samples.py:FAMILIES minus 'other' (free JSON, no prompt).
TRAINABLE_FAMILIES = ('screen-id', 'focus', 'menu', 'banner', 'av-fault')
BASE_LABEL_SOURCES = ('run', 'human')
TEACHER = 'teacher'
FORBIDDEN_SPLITS = ('eval', 'holdout')
DATASET_PREFIX = 'dataset-combined-'
PAGE_SIZE = 500
# Rows with these sources are kept first when --cap-per-family trims a family.
_SOURCE_PRIORITY = {'human': 0, 'run': 1, 'teacher': 2}
FORMAT_NAME = 'chat-content-list-v1'


class ExportError(Exception):
    """A guard failed: the export is refused as a whole."""


# ---- guards ---------------------------------------------------------------------------

def parse_list(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or '').split(',') if v.strip()]


def allowed_label_sources(include_teacher: bool) -> List[str]:
    return list(BASE_LABEL_SOURCES) + ([TEACHER] if include_teacher else [])


def check_row(row: Dict[str, Any], include_teacher: bool) -> None:
    """Raise ExportError if ``row`` must never enter a training set."""
    rid = row.get('id')
    if row.get('split') in FORBIDDEN_SPLITS or row.get('split') != 'train':
        raise ExportError(f"row {rid}: split={row.get('split')!r}, only 'train' is exportable")
    if row.get('eval_version') is not None:
        raise ExportError(f"row {rid}: eval_version={row.get('eval_version')!r} (frozen eval row)")
    source = row.get('label_source')
    if source == 'none' or source not in allowed_label_sources(True):
        raise ExportError(f"row {rid}: label_source={source!r} is refused")
    if source == TEACHER and not include_teacher:
        raise ExportError(f"row {rid}: teacher label without --include-teacher")
    if row.get('ground_truth') is None:
        raise ExportError(f"row {rid}: no ground_truth")
    if not row.get('object_key'):
        raise ExportError(f"row {rid}: no object_key")


def is_strip(row: Dict[str, Any]) -> bool:
    """A step-4g freeze strip: one JPEG holding several frames side by side."""
    answer = row.get('model_answer')
    return isinstance(answer, dict) and answer.get('evidence') == 'strip'


def excluded_by_triage(row: Dict[str, Any]) -> bool:
    """A second AI pass could not settle the row (triage status ``excluded``,
    ``triage_batch.py --second-pass``): it never trains. A human answer later resolves it."""
    triage = row.get('triage')
    if isinstance(triage, str):
        try:
            triage = json.loads(triage)
        except ValueError:
            return False
    return isinstance(triage, dict) and triage.get('status') == 'excluded'


# ---- DB access (read-only) ---------------------------------------------------------------

def fetch_rows(team_id: str, family: str, label_sources: Sequence[str],
               list_fn: Optional[Callable] = None, page_size: int = PAGE_SIZE) -> List[Dict[str, Any]]:
    """Every labelled ``train`` row of one team and family (existing ``list_samples`` helper,
    paged). Rows with no ``ground_truth`` are dropped here; everything else goes through
    ``check_row``, which refuses the export on a frozen, eval or ``none`` row."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page, total = list_fn(team_id, family=family, split='train',
                              label_sources=list(label_sources), limit=page_size, offset=offset)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    seen = set()
    out = []
    for r in rows:
        if r.get('id') in seen or r.get('ground_truth') is None:
            continue
        seen.add(r.get('id'))
        out.append(r)
    return out


def tree_screen_labels(team_id: str, userinterface_name: str) -> Optional[List[str]]:
    """Step 4k: the app's screen **group** names (``lib/screen_group_scope``: its whole tree
    hierarchy, ENTRY skipped, the core overrides applied), sorted: the list the review
    page's screen dropdown shows. None when there is no tree."""
    import screen_group_scope  # features/ai-dataset/lib (step 4k)
    entries = screen_group_scope.screen_entries(screen_group_scope.groups_for(team_id, userinterface_name))
    return [e['label'] for e in entries] if entries else None


class ScreenLabels:
    """Per (team, userinterface) cache over ``tree_screen_labels``."""

    def __init__(self, fn: Callable[[str, str], Optional[List[str]]] = tree_screen_labels):
        self._fn = fn
        self._cache: Dict[tuple, Optional[List[str]]] = {}

    def get(self, team_id: str, userinterface: Optional[str]) -> Optional[List[str]]:
        if not userinterface:
            return None
        key = (team_id, userinterface)
        if key not in self._cache:
            self._cache[key] = self._fn(team_id, userinterface)
        return self._cache[key]


# ---- selection and balance -----------------------------------------------------------------

def _stable_rank(row: Dict[str, Any], seed: str) -> str:
    return hashlib.sha256(f"{seed}:{row.get('id')}".encode()).hexdigest()


def order_rows(rows: Iterable[Dict[str, Any]], seed: str) -> List[Dict[str, Any]]:
    """Deterministic order: human, then run, then teacher; failures first; then a seeded hash."""
    return sorted(rows, key=lambda r: (_SOURCE_PRIORITY.get(r.get('label_source'), 9),
                                       0 if r.get('is_failure') else 1,
                                       _stable_rank(r, seed)))


def cap_per_family(by_family: Dict[str, List[Dict[str, Any]]], cap: Optional[int],
                   seed: str) -> Dict[str, List[Dict[str, Any]]]:
    out = {}
    for family, rows in by_family.items():
        ordered = order_rows(rows, seed)
        out[family] = ordered[:cap] if cap else ordered
    return out


def limit_round_robin(by_family: Dict[str, List[Dict[str, Any]]], limit: Optional[int]
                      ) -> Dict[str, List[Dict[str, Any]]]:
    """Keep at most ``limit`` rows in total, taken one per family in turn."""
    if not limit:
        return by_family
    out: Dict[str, List[Dict[str, Any]]] = {f: [] for f in by_family}
    queues = {f: list(rows) for f, rows in by_family.items()}
    taken = 0
    while taken < limit and any(queues.values()):
        for family in by_family:
            if taken >= limit:
                break
            if queues[family]:
                out[family].append(queues[family].pop(0))
                taken += 1
    return out


def balance_report(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, Any]:
    total_after = sum(after.values()) or 1
    return {family: {'available': before.get(family, 0), 'exported': after.get(family, 0),
                     'share_pct': round(100.0 * after.get(family, 0) / total_after, 1)}
            for family in before}


# ---- records ---------------------------------------------------------------------------------

def image_rel_path(row: Dict[str, Any]) -> str:
    return f"images/{row['id']}.jpg"


def focus_record(row: Dict[str, Any], prompts) -> Optional[Dict[str, Any]]:
    """Step 4k: the second lesson of a grouped ``screen-id`` row with a focus (same image,
    the ``focus`` prompt and answer), or None when the row has no focus question."""
    if row.get('family') != 'screen-id':
        return None
    truth = prompts.focus_truth(row.get('ground_truth'))
    if truth is None:
        return None
    return {
        'messages': [
            {'role': 'user', 'content': [
                {'type': 'image', 'image': image_rel_path(row)},
                {'type': 'text', 'text': prompts.build_prompt('focus', row)},
            ]},
            {'role': 'assistant', 'content': prompts.answer_to_text('focus', truth)},
        ],
        'family': 'focus',
        'id': f"{row['id']}:focus",
    }


def build_record(row: Dict[str, Any], prompts, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    family = row['family']
    return {
        'messages': [
            {'role': 'user', 'content': [
                {'type': 'image', 'image': image_rel_path(row)},
                {'type': 'text', 'text': prompts.build_prompt(family, row, context)},
            ]},
            {'role': 'assistant', 'content': prompts.answer_to_text(family, row['ground_truth'])},
        ],
        'family': family,
        'id': str(row['id']),
    }


def prompt_hashes(prompts, families: Iterable[str]) -> Dict[str, str]:
    return {f: hashlib.sha256(prompts.FAMILY_PROMPTS[f].encode('utf-8')).hexdigest()[:16]
            for f in families}


def git_hash() -> str:
    """``VPT_GIT_HASH``, else ``git rev-parse HEAD``, else the deployed ``VERSION.txt`` line."""
    env = os.environ.get('VPT_GIT_HASH', '').strip()
    if env:
        return env
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=_SCRIPT_DIR,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        pass
    # Deployed trees (rsync, no .git) carry VERSION.txt: "current:<branch>-<date>-<n>[-<sha>]".
    try:
        with open(os.path.join(_REPO_ROOT, 'VERSION.txt'), encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('current:'):
                    return 'version:' + line.split(':', 1)[1].strip()
    except OSError:
        pass
    return 'unknown'


def build_manifest(version: str, teams: Sequence[str], families: Sequence[str],
                   exported: List[Dict[str, Any]], balance: Dict[str, Any],
                   skipped: Dict[str, int], prompts, args_summary: Dict[str, Any]) -> Dict[str, Any]:
    per_family = Counter(r['family'] for r in exported)
    by_source: Dict[str, Counter] = defaultdict(Counter)
    by_model: Dict[str, Counter] = defaultdict(Counter)
    by_split: Dict[str, Counter] = defaultdict(Counter)
    by_team: Dict[str, Counter] = defaultdict(Counter)
    conflicts: Counter = Counter()
    failures: Counter = Counter()
    strips = 0
    focus_lessons = sum(1 for r in exported if prompts.focus_truth(r.get('ground_truth'))
                        and r.get('family') == 'screen-id')
    for r in exported:
        f = r['family']
        by_source[f][r.get('label_source')] += 1
        by_model[f][r.get('device_model') or 'unknown'] += 1
        by_split[f][r.get('split')] += 1
        by_team[str(r.get('team_id'))][f] += 1
        conflicts[f] += 1 if r.get('label_conflict') else 0
        failures[f] += 1 if r.get('is_failure') else 0
        strips += 1 if is_strip(r) else 0
    eval_rows = sum(1 for r in exported
                    if r.get('split') in FORBIDDEN_SPLITS or r.get('eval_version') is not None)
    return {
        'name': f"{DATASET_PREFIX}{version}",
        'version': version,
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'git_hash': git_hash(),
        'format': FORMAT_NAME,
        'teams': list(teams),
        'families': list(families),
        'total': len(exported),
        'eval_rows': eval_rows,
        'counts': {
            'family': dict(per_family),
            'label_source': {f: dict(c) for f, c in by_source.items()},
            'device_model': {f: dict(c) for f, c in by_model.items()},
            'split': {f: dict(c) for f, c in by_split.items()},
            'team': {t: dict(c) for t, c in by_team.items()},
            'label_conflict': dict(conflicts),
            'is_failure': dict(failures),
            'freeze_strip': strips,
            # step 4k: extra focus lines from grouped screen-id rows (train.jsonl has
            # total + focus_from_screen_id lines)
            'focus_from_screen_id': focus_lessons,
        },
        'balance': balance,
        'skipped': dict(skipped),
        'prompt_hash': prompt_hashes(prompts, families),
        'options': args_summary,
    }


# ---- main ------------------------------------------------------------------------------------

def load_prompts():
    try:
        import family_prompts  # features/ai-dataset/lib/family_prompts.py (TASK-27 step 5)
    except ImportError as e:
        raise ExportError(f"family_prompts not importable ({e}); it is "
                          "features/ai-dataset/lib/family_prompts.py (step 5)")
    return family_prompts


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='TASK-27 step 6: export one combined training dataset '
                                            '(read-only).')
    p.add_argument('--teams', required=True,
                   help='comma-separated team ids (required; §9: lab teams only until the '
                        'customer data-use clause)')
    p.add_argument('--families', default='',
                   help='comma-separated families (default: every family with labelled train rows)')
    p.add_argument('--version', default='v1', help='dataset version, e.g. v1 (folder '
                                                   'dataset-combined-<version>)')
    p.add_argument('--out', default='.', help='parent folder of dataset-combined-<version>/')
    p.add_argument('--include-teacher', action='store_true',
                   help="also export label_source='teacher' rows (spot-checked batches only)")
    p.add_argument('--cap-per-family', type=int, default=None,
                   help='keep at most N rows per family (human > run > teacher, failures first)')
    p.add_argument('--limit', type=int, default=None,
                   help='keep at most N rows in total, round-robin across families (smoke exports)')
    p.add_argument('--seed', default='task27', help='seed of the deterministic cap order')
    p.add_argument('--dry-run', action='store_true',
                   help='count and validate only: no download, nothing written')
    return p


def run(argv: Optional[List[str]] = None, *, list_fn: Optional[Callable] = None,
        screen_label_fn: Optional[Callable] = None, storage=None, prompts=None) -> int:
    args = build_arg_parser().parse_args(argv)
    teams = parse_list(args.teams)
    if not teams:
        raise ExportError('--teams needs at least one team id')
    if args.cap_per_family is not None and args.cap_per_family < 1:
        raise ExportError('--cap-per-family must be >= 1')
    if not args.version or '/' in args.version or os.sep in args.version:
        raise ExportError(f'bad --version {args.version!r}')
    prompts = prompts or load_prompts()
    prompt_families = set(prompts.FAMILY_PROMPTS)

    requested = parse_list(args.families)
    for f in requested:
        if f not in TRAINABLE_FAMILIES:
            raise ExportError(f"unknown or untrainable family {f!r}; one of {TRAINABLE_FAMILIES}")
        if f not in prompt_families:
            raise ExportError(f"family {f!r} has no prompt in family_prompts.FAMILY_PROMPTS")
    candidates = requested or [f for f in TRAINABLE_FAMILIES if f in prompt_families]
    sources = allowed_label_sources(args.include_teacher)

    by_family: Dict[str, List[Dict[str, Any]]] = {}
    for family in candidates:
        rows = []
        for team in teams:
            for r in fetch_rows(team, family, sources, list_fn=list_fn):
                r.setdefault('team_id', team)
                check_row(r, args.include_teacher)
                rows.append(r)
        if rows or requested:
            by_family[family] = rows
    families = [f for f in candidates if by_family.get(f)]
    if not families:
        print('[export_dataset] no labelled train rows for these teams/families', file=sys.stderr)

    # screen-id needs the tree's screen labels; a sample without a tree cannot be prompted.
    skipped: Counter = Counter()
    labels = ScreenLabels(screen_label_fn or tree_screen_labels)
    contexts: Dict[str, Optional[Dict[str, Any]]] = {}
    for family in families:
        kept = []
        for r in by_family[family]:
            if excluded_by_triage(r):
                skipped[f'{family}:excluded_by_triage'] += 1
                continue
            if family == 'screen-id':
                screen_labels = labels.get(str(r['team_id']), r.get('userinterface'))
                if not screen_labels:
                    skipped['screen-id:no_tree_labels'] += 1
                    continue
                contexts[str(r['id'])] = {'screen_labels': screen_labels}
            kept.append(r)
        by_family[family] = kept

    before = {f: len(by_family[f]) for f in families}
    selected = limit_round_robin(cap_per_family({f: by_family[f] for f in families},
                                                args.cap_per_family, args.seed), args.limit)
    after = {f: len(selected[f]) for f in families}
    balance = balance_report(before, after)

    records = []
    exported = []
    for family in families:
        for r in selected[family]:
            check_row(r, args.include_teacher)  # again, on exactly what is written
            lessons = [build_record(r, prompts, contexts.get(str(r['id'])))]
            focus = focus_record(r, prompts)  # step 4k: the focus question on the same image
            if focus is not None:
                lessons.append(focus)
            records.append((r, lessons))
            exported.append(r)

    summary = {'include_teacher': args.include_teacher, 'label_sources': sources,
               'cap_per_family': args.cap_per_family, 'limit': args.limit, 'seed': args.seed,
               'dry_run': args.dry_run}
    print('[export_dataset] family balance (available -> exported, share):', file=sys.stderr)
    for f, b in balance.items():
        print(f"  {f:10s} {b['available']:6d} -> {b['exported']:6d}  {b['share_pct']:5.1f}%",
              file=sys.stderr)
    for reason, n in skipped.items():
        print(f'  skipped {reason}: {n}', file=sys.stderr)

    if args.dry_run:
        manifest = build_manifest(args.version, teams, families, exported, balance, skipped,
                                  prompts, summary)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    target = os.path.join(args.out, f"{DATASET_PREFIX}{args.version}")
    if os.path.exists(target) and os.listdir(target):
        raise ExportError(f'{target} exists and is not empty; pick a new --version')
    os.makedirs(os.path.join(target, 'images'), exist_ok=True)
    if storage is None:
        from shared.src.lib.utils.cloudflare_utils import get_training_storage
        storage = get_training_storage()

    written = []
    with open(os.path.join(target, 'train.jsonl'), 'w', encoding='utf-8') as fh:
        for row, lessons in records:
            local = os.path.join(target, image_rel_path(row))
            result = storage.download_file(row['object_key'], local)
            if not result.get('success'):
                skipped['image_missing'] += 1
                print(f"[export_dataset] skip {row['id']}: {result.get('error')}", file=sys.stderr)
                continue
            for record in lessons:
                fh.write(json.dumps(record, ensure_ascii=False) + '\n')
            written.append(row)

    after = Counter(r['family'] for r in written)
    balance = balance_report(before, {f: after.get(f, 0) for f in families})
    manifest = build_manifest(args.version, teams, families, written, balance, skipped, prompts,
                              summary)
    with open(os.path.join(target, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print(f'[export_dataset] wrote {len(written)} sample(s) to {target}', file=sys.stderr)
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except ExportError as e:
        print(f'[export_dataset] REFUSED: {e}', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
