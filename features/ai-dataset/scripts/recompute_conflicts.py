#!/usr/bin/env python3
"""recompute_conflicts.py — TASK-27 step 4j: refresh ``label_conflict`` under the current rules.

One-off maintenance, idempotent. Step 4j changed the conflict rules (a low-information
dHash — black, no-signal colour bars, flat loading screens — is never compared, and
``focus`` has no conflicts), but the flags already stored were set under the old rules.
This script reads every row of one team, recomputes each row's flag with the core
``training_samples.recompute_conflict_flags`` and prints how many flags it would set and
clear, per family. Without ``--dry-run`` it writes only those flags, through core
``set_label_conflict`` (team-scoped; allowed on frozen eval rows, whose ``ground_truth``
and ``split`` it never touches). It never changes ``ground_truth``, ``split``,
``label_source``, ``is_failure`` or the triage record. A second run prints 0 / 0.

Run it before a real ``triage_batch.py import`` so the review UI's stored flags match the
import's live conflict check.

Step 4k: ``screen-id`` conflicts compare **screen groups**. Each ``screen-id`` label is read
through the app's groups (core ``screen_groups.regroup_label``, the feature's
``lib/screen_group_scope``) before the check, so Home with two different tabs focused is not a
conflict even on a label ``regroup_screen_labels.py`` has not rewritten yet. Only the
comparison sees the group form; ``ground_truth`` is never written here.

Usage (on the server, as vpt_user with the .env loaded; nothing loads it for you)
-----
    python3 features/ai-dataset/scripts/recompute_conflicts.py --team <uuid> --dry-run
    python3 features/ai-dataset/scripts/recompute_conflicts.py --team <uuid>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '..'))  # features/ai-dataset/scripts -> repo
if os.path.isdir(os.path.join(_REPO_ROOT, 'shared')) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PAGE_SIZE = 500
MAX_ROWS = 100000


class RecomputeError(Exception):
    """A guard failed: nothing is written."""


def fetch_all_rows(team_id: str, list_fn=None) -> List[Dict[str, Any]]:
    """Every row of one team (all families, splits and label sources), paged through core
    ``list_samples``. Refuses rather than recompute from a partial read."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset, total = 0, None
    while True:
        page, total = list_fn(team_id, limit=PAGE_SIZE, offset=offset)
        if total > MAX_ROWS:
            raise RecomputeError(f'team has {total} rows, more than MAX_ROWS={MAX_ROWS}')
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    if len(rows) != total or len({r['id'] for r in rows}) != len(rows):
        raise RecomputeError(f'read {len(rows)} rows ({len({r["id"] for r in rows})} distinct), '
                             f'expected {total}: rows changed while paging, run again')
    return rows


def as_groups(team_id: str, rows: List[Dict[str, Any]], groups_for) -> List[Dict[str, Any]]:
    """Step 4k: the rows with each ``screen-id`` label in the group form (a copy; other
    families, off-tree labels and apps without a tree unchanged). ``groups_for(team, ui)``."""
    if groups_for is None:
        return rows
    from shared.src.lib.ai import screen_groups
    out = []
    for r in rows:
        truth = r.get('ground_truth')
        if r.get('family') == 'screen-id' and isinstance(truth, dict) and truth.get('node_id') is not None:
            groups = groups_for(team_id, r.get('userinterface'))
            grouped = screen_groups.regroup_label(truth, groups)
            if grouped is not truth:
                r = dict(r, ground_truth=grouped)
        out.append(r)
    return out


def recompute(team_id: str, rows: List[Dict[str, Any]], dry_run: bool, set_fn=None,
              groups_for=None) -> Dict[str, Any]:
    """Plan (pure but for ``groups_for``) and, unless ``dry_run``, apply the flag changes.
    Returns the report."""
    from shared.src.lib.ai import training_samples
    foreign = [r['id'] for r in rows if str(r.get('team_id', team_id)) != str(team_id)]
    if foreign:
        raise RecomputeError(f'{len(foreign)} rows of another team in the input')
    view = as_groups(team_id, rows, groups_for)
    to_set, to_clear = (sorted(ids) for ids in training_samples.recompute_conflict_flags(view))
    family_of = {str(r['id']): r.get('family') for r in rows}
    per: Dict[str, Counter] = {}
    for r in rows:
        c = per.setdefault(r.get('family') or '?', Counter())
        c['rows'] += 1
        c['flagged_before'] += bool(r.get('label_conflict'))
        c['low_info'] += not training_samples.is_informative(r.get('dhash'))
    for sid in to_set:
        per[family_of[sid] or '?']['set'] += 1
    for sid in to_clear:
        per[family_of[sid] or '?']['clear'] += 1
    for c in per.values():
        c['flagged_after'] = c['flagged_before'] + c['set'] - c['clear']
    written = {'set': 0, 'clear': 0}
    if not dry_run:
        if set_fn is None:
            from shared.src.lib.database.ai_training_samples_db import set_label_conflict as set_fn
        for i in range(0, len(to_set), PAGE_SIZE):
            written['set'] += set_fn(team_id, to_set[i:i + PAGE_SIZE], True)
        for i in range(0, len(to_clear), PAGE_SIZE):
            written['clear'] += set_fn(team_id, to_clear[i:i + PAGE_SIZE], False)
    return {'team_id': team_id, 'dry_run': dry_run, 'rows': len(rows),
            'set': to_set, 'clear': to_clear, 'written': written,
            'families': {f: dict(c) for f, c in sorted(per.items())}}


def print_report(report: Dict[str, Any], out=None) -> None:
    out = out or sys.stdout
    mode = ' (dry run: nothing written)' if report['dry_run'] else ''
    print(f"[recompute_conflicts] team {report['team_id']}: {report['rows']} rows{mode}", file=out)
    print(f"  {'family':10s} {'rows':>6s} {'low-info':>8s} {'flagged':>8s} {'set':>5s} {'clear':>6s} {'after':>6s}",
          file=out)
    for family, c in report['families'].items():
        print(f"  {family:10s} {c.get('rows', 0):6d} {c.get('low_info', 0):8d} {c.get('flagged_before', 0):8d} "
              f"{c.get('set', 0):5d} {c.get('clear', 0):6d} {c.get('flagged_after', 0):6d}", file=out)
    verb = 'would set' if report['dry_run'] else 'set'
    print(f"  {verb} {len(report['set'])} flag(s), {'would clear' if report['dry_run'] else 'cleared'} "
          f"{len(report['clear'])} flag(s)", file=out)
    if not report['dry_run']:
        print(f"  rows updated: set {report['written']['set']}, cleared {report['written']['clear']}", file=out)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='TASK-27 step 4j: recompute label_conflict for one team.')
    p.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    p.add_argument('--dry-run', action='store_true', help='compute and print; no DB write')
    p.add_argument('--json', action='store_true', help='also print the report (with the ids) as JSON')
    return p


def _group_cache():
    """The feature's screen groups (step 4k), one derivation per app."""
    import importlib.util
    path = os.path.join(os.path.dirname(_SCRIPT_DIR), 'lib', 'screen_group_scope.py')
    spec = importlib.util.spec_from_file_location('ai_dataset_screen_group_scope', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GroupCache().get


def main(argv: Optional[List[str]] = None, *, list_fn=None, set_fn=None, groups_for=None,
         out=None) -> int:
    args = build_arg_parser().parse_args(argv)
    out = out or sys.stdout
    try:
        rows = fetch_all_rows(args.team, list_fn=list_fn)
        report = recompute(args.team, rows, args.dry_run, set_fn=set_fn,
                           groups_for=groups_for or _group_cache())
    except RecomputeError as e:
        print(f'[recompute_conflicts] REFUSED: {e}', file=sys.stderr)
        return 2
    print_report(report, out=out)
    if args.json:
        print(json.dumps(report, indent=2, default=str), file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
