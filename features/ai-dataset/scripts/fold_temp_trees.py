#!/usr/bin/env python3
"""fold_temp_trees.py — file the samples of temporary trees under their canonical app (TASK-27).

The stb4 acceptance pipeline builds its own copy of the STB tree on every run
(``acceptance-stb4-tv-<date>-stb``, ``qa-anchor-check-stb``) and deletes it later. Its frames
are real ``stb-<operator>`` screens with the same screen names, but their labels point at the copy's
node ids, so once the copy is gone they have no screen list. Owner decision 2026-10-04: keep
them (keeping is reversible, dropping is not) and file them under ``stb-<operator>``.

For every row of a team whose ``userinterface`` matches ``dataset_scope.TEMP_TREE_ALIASES``:

* ``userinterface`` becomes the canonical app;
* a ``screen-id`` label is re-pointed at the canonical app's screen group with the same name:
  the node's own name first (``node_label``, e.g. ``home_apps``), then the group name
  (``home``), then a checked synonym (``dataset_scope.TEMP_TREE_SCREEN_SYNONYMS``: the copies
  call ``live`` ``live_channel``), giving the canonical grouped label (with its focus);
* the triage record's ``teacher_label`` the same way, and ``teacher_answer`` keeps its name;
* the ``node_id`` **column** is left alone (the stable key of dedup and split).

A screen with no match in the canonical app leaves the row untouched (``unmapped``, listed);
a screen not in any tree (``node_id: null``) only changes app. Frozen rows are never written.
Each write is guarded in its own statement (``triage_db.regroup_write``: not frozen, same
``label_source`` as read). Idempotent: a second run changes 0 rows. Dry run by default.

Usage (on the server, as vpt_user with the .env loaded)
-----
    python3 features/ai-dataset/scripts/fold_temp_trees.py --team <uuid>            # dry run
    python3 features/ai-dataset/scripts/fold_temp_trees.py --team <uuid> --apply
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import importlib.util
import json
import os
import sys
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FEATURE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '..'))
if os.path.isdir(os.path.join(_REPO_ROOT, 'shared')) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_lib(name: str):
    path = os.path.join(_FEATURE_DIR, 'lib', f'{name}.py')
    spec = importlib.util.spec_from_file_location(f'ai_dataset_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dataset_scope = _load_lib('dataset_scope')
PAGE_SIZE = 500
MAX_ROWS = 20000


def canonical_for(userinterface: Optional[str], canonical: str) -> Optional[str]:
    """``canonical`` when the temporary tree is a copy of that app's platform, else None."""
    platform = dataset_scope.platform_of(canonical)
    for pattern, alias_platform in dataset_scope.TEMP_TREE_ALIASES.items():
        if userinterface and alias_platform == platform and fnmatch.fnmatch(userinterface, pattern):
            return canonical
    return None


def _triage(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    value = row.get('triage')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def remap_label(label: Any, groups) -> Any:
    """A grouped (or node) ``screen-id`` label of the copy, re-pointed at the canonical app.
    Returns the label unchanged when it names no screen (off-tree), and None when the screen
    has no match in the canonical app."""
    if not isinstance(label, dict) or label.get('node_id') is None:
        return label
    names = [label.get('node_label'), label.get('label')]
    names += [dataset_scope.TEMP_TREE_SCREEN_SYNONYMS.get(str(n)) for n in list(names) if n]
    for name in names:
        nid = groups.node_by_label(name) if name else None
        if nid is not None:
            return groups.label_for(nid)
    return None


def plan_row(row: Dict[str, Any], canonical: str, groups) -> Dict[str, Any]:
    """``{'status': change|unmapped|unchanged, 'fields': {...}}`` for one row (pure)."""
    fields: Dict[str, Any] = {'userinterface': canonical}
    if row.get('family') == 'screen-id':
        truth = row.get('ground_truth')
        if truth is not None:
            new = remap_label(truth, groups)
            if new is None:
                return {'status': 'unmapped', 'fields': {}}
            if new != truth:
                fields['ground_truth'] = new
        triage = _triage(row)
        if triage and isinstance(triage.get('teacher_label'), dict):
            new_label = remap_label(triage['teacher_label'], groups)
            if new_label is not None and new_label != triage['teacher_label']:
                new_triage = copy.deepcopy(triage)
                new_triage['teacher_label'] = new_label
                fields['triage'] = new_triage
    if row.get('userinterface') == canonical and len(fields) == 1:
        return {'status': 'unchanged', 'fields': {}}
    return {'status': 'change', 'fields': fields}


def fetch_rows(team_id: str, list_fn=None) -> List[Dict[str, Any]]:
    """Every row of the team (all families), paged through core ``list_samples``."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset = 0
    while offset < MAX_ROWS:
        page, total = list_fn(team_id, limit=PAGE_SIZE, offset=offset)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    return rows


def fold(team_id: str, rows: List[Dict[str, Any]], groups_for: Callable[[str], Any],
         write_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], bool]],
         canonical_name: str) -> Dict[str, Any]:
    """Plan (and with ``write_fn`` apply) the fold of every temporary-tree row into ``canonical_name``."""
    counts: Counter = Counter()
    unmapped: Counter = Counter()
    for row in rows:
        canonical = canonical_for(row.get('userinterface'), canonical_name)
        if canonical is None:
            continue
        if row.get('eval_version'):
            counts['frozen'] += 1
            continue
        groups = groups_for(canonical)
        if groups is None:
            counts['no_canonical_tree'] += 1
            continue
        plan = plan_row(row, canonical, groups)
        if plan['status'] == 'unmapped':
            label = (row.get('ground_truth') or {}).get('node_label') or (row.get('ground_truth') or {}).get('label')
            unmapped[str(label)] += 1
        if plan['status'] == 'change' and write_fn is not None:
            counts['written' if write_fn(row, plan['fields']) else 'write_refused'] += 1
        counts[plan['status']] += 1
    return {'counts': dict(counts), 'unmapped': dict(unmapped)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    parser.add_argument('--canonical', required=True, help='the canonical app the copies are filed under')
    parser.add_argument('--apply', action='store_true', help='write (default: dry run)')
    args = parser.parse_args(argv)
    from shared.src.lib.ai import screen_groups
    scope = _load_lib('screen_group_scope')
    triage_db = _load_lib('triage_db')
    cache: Dict[str, Any] = {}

    def groups_for(ui: str):
        if ui not in cache:
            graph = scope.load_app_graph(args.team, ui)
            cache[ui] = scope.groups_for(args.team, ui, loader=lambda _t, _u: graph) if graph else None
        return cache[ui]

    def write(row, fields):
        return triage_db.regroup_write(args.team, str(row['id']), fields, row.get('label_source'))

    report = fold(args.team, fetch_rows(args.team), groups_for, write if args.apply else None, args.canonical)
    print(json.dumps({'dry_run': not args.apply, **report}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
