#!/usr/bin/env python3
"""regroup_screen_labels.py — TASK-27 step 4k: rewrite stored ``screen-id`` labels as screen groups.

Before step 4k a ``screen-id`` label named the node: ``{"node_id": <home_apps id>, "label":
"home_apps"}``. Home with the Apps tab focused and Home itself were two answers, near-identical
frames with different answers (19 conflicts for a human), and a model answering "home" was
marked wrong. Since step 4k the answer is the **screen group** (core
``shared/src/lib/ai/screen_groups.py``, derived from each app's tree, with its
``SCREEN_GROUP_OVERRIDES``)::

    {"node_id": <home id>, "label": "home", "node": <home_apps id>, "node_label": "home_apps",
     "focus": "apps"}

This script reads every ``screen-id`` row of one team and, for each row whose label is not
already in that form (or whose group changed, e.g. after an override edit):

* rewrites ``ground_truth`` to the group form (``screen_groups.regroup_label``), keeping
  ``label_source`` and leaving the ``node_id`` **column** untouched (the stable key of dedup
  and split);
* recomputes ``is_failure`` through the label path (``lib/label_write.failure_against``);
* rewrites the triage record's ``teacher_label`` (the same conversion) and ``teacher_answer``
  (``{"label": "home_apps"}`` -> ``{"label": "home"}``), when the ``triage`` column exists.

Left alone: screens not in the tree (``node_id: null``), nodes no longer in the app (stale),
rows of an app with no tree, unlabelled rows. **Frozen rows** (``eval_version``) that would
change are refused and listed; nothing else stops. Each write is guarded in its own statement
(``triage_db.regroup_write``: not frozen, same ``label_source`` as read). Idempotent: a second
run changes 0 rows.

It does not write ``label_conflict``. It prints the conflicts before (the stored labels) and
after (the group labels) as computed by core ``recompute_conflict_flags``; run
``recompute_conflicts.py`` next to store them.

Usage (on the server, as vpt_user with the .env loaded; nothing loads it for you)
-----
    python3 features/ai-dataset/scripts/regroup_screen_labels.py --team <uuid> --dry-run
    python3 features/ai-dataset/scripts/regroup_screen_labels.py --team <uuid>
    python3 features/ai-dataset/scripts/recompute_conflicts.py --team <uuid>
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
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


FAMILY = 'screen-id'
PAGE_SIZE = 500
MAX_ROWS = 100000


class RegroupError(Exception):
    """A guard failed: nothing is written."""


def fetch_rows(team_id: str, list_fn=None) -> List[Dict[str, Any]]:
    """Every ``screen-id`` row of the team, paged through core ``list_samples``. Refuses
    rather than work from a partial read."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset, total = 0, None
    while True:
        page, total = list_fn(team_id, family=FAMILY, limit=PAGE_SIZE, offset=offset)
        if total > MAX_ROWS:
            raise RegroupError(f'team has {total} {FAMILY} rows, more than MAX_ROWS={MAX_ROWS}')
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    if len(rows) != total or len({r['id'] for r in rows}) != len(rows):
        raise RegroupError(f'read {len(rows)} rows, expected {total}: rows changed while paging, run again')
    return rows


def _triage(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    value = row.get('triage')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def regroup_answer(answer: Any, groups) -> Any:
    """A teacher's raw ``screen-id`` answer ``{"label": "<node label>"}`` with the node label
    replaced by its group name; anything else (off-tree, unknown name) unchanged."""
    if groups is None or not isinstance(answer, dict) or 'node_id' in answer:
        return answer
    nid = groups.node_by_label(answer.get('label'))
    group = groups.group_of(nid) if nid else None
    if group is None or group['label'] == answer.get('label'):
        return answer
    return {**answer, 'label': group['label']}


def plan_row(row: Dict[str, Any], groups, failure_fn: Callable[[Dict[str, Any], Any], bool]
             ) -> Dict[str, Any]:
    """What to change on one row (pure but for ``failure_fn``). ``status`` is one of
    ``change``, ``unchanged``, ``no_tree``, ``offtree``, ``stale``, ``unlabelled``, and the
    ``fields`` to write when it changes."""
    truth = row.get('ground_truth')
    triage = _triage(row)
    fields: Dict[str, Any] = {}
    if groups is None:
        return {'status': 'no_tree', 'fields': fields}
    status = 'unchanged'
    if truth is None:
        status = 'unlabelled'
    elif not isinstance(truth, dict) or truth.get('node_id') is None:
        status = 'offtree'
    else:
        new = core_groups().regroup_label(truth, groups)
        if new is truth or new == truth:
            original = truth.get('node') if truth.get('node') is not None else truth.get('node_id')
            status = 'unchanged' if original in groups else 'stale'
        else:
            fields['ground_truth'] = new
            failure = bool(failure_fn(row, new))
            if failure != bool(row.get('is_failure')):
                fields['is_failure'] = failure
    if triage:
        new_triage = copy.deepcopy(triage)
        label = triage.get('teacher_label')
        if isinstance(label, dict) and label.get('node_id') is not None:
            new_triage['teacher_label'] = core_groups().regroup_label(label, groups)
        new_triage['teacher_answer'] = regroup_answer(triage.get('teacher_answer'), groups)
        if new_triage != triage:
            fields['triage'] = new_triage
    if fields:
        status = 'change'
    return {'status': status, 'fields': fields}


def core_groups():
    from shared.src.lib.ai import screen_groups
    return screen_groups


def _flagged(rows: List[Dict[str, Any]]) -> set:
    """Ids that conflict under the rows' labels (core rules), whatever the stored flag."""
    from shared.src.lib.ai import training_samples
    to_set, to_clear = training_samples.recompute_conflict_flags(rows)
    stored = {str(r['id']) for r in rows if r.get('label_conflict')}
    return (stored | set(to_set)) - set(to_clear)


def regroup(team_id: str, rows: List[Dict[str, Any]], groups_for: Callable[[str, str], Any],
            dry_run: bool, write_fn=None, failure_fn=None, triage_column: bool = True) -> Dict[str, Any]:
    """Plan and, unless ``dry_run``, apply. Returns the report."""
    if failure_fn is None:
        failure_fn = _load_lib('label_write').failure_against
    foreign = [r['id'] for r in rows if str(r.get('team_id', team_id)) != str(team_id)]
    if foreign:
        raise RegroupError(f'{len(foreign)} rows of another team in the input')
    per_app: Dict[str, Counter] = defaultdict(Counter)
    groups_by_app: Dict[str, Any] = {}
    plans: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    after_rows: List[Dict[str, Any]] = []
    for row in rows:
        ui = row.get('userinterface') or ''
        if ui not in groups_by_app:
            groups_by_app[ui] = groups_for(team_id, ui) if ui else None
        plan = plan_row(row, groups_by_app[ui], failure_fn)
        if not triage_column:
            plan['fields'].pop('triage', None)
            if not plan['fields'] and plan['status'] == 'change':
                plan['status'] = 'unchanged'
        c = per_app[ui or '(none)']
        c['rows'] += 1
        c[plan['status']] += 1
        if 'ground_truth' in plan['fields']:
            c['label'] += 1
        if 'is_failure' in plan['fields']:
            c['is_failure_flip'] += 1
        if 'triage' in plan['fields']:
            c['triage'] += 1
        new_row = dict(row, **{k: v for k, v in plan['fields'].items() if k in ('ground_truth', 'is_failure')})
        after_rows.append(new_row)
        if plan['status'] == 'change':
            if row.get('eval_version'):
                refused.append({'id': str(row['id']), 'eval_version': row['eval_version'],
                                'label': (row.get('ground_truth') or {}).get('label')})
                after_rows[-1] = row
                c['frozen_refused'] += 1
                continue
            plans.append({'row': row, **plan})

    before = _flagged(rows)
    after = _flagged(after_rows)
    written, failed = 0, []
    if not dry_run:
        if write_fn is None:
            write_fn = _load_lib('triage_db').regroup_write
        for p in plans:
            if write_fn(team_id, str(p['row']['id']), p['fields'], p['row'].get('label_source')):
                written += 1
            else:
                failed.append(str(p['row']['id']))
    apps = {}
    for ui, g in sorted(groups_by_app.items()):
        if not ui:
            continue
        apps[ui] = {'groups': len(g.groups) if g else None,
                    'multi_member': [{'group': x['label'], 'members': [m['label'] for m in x['members']],
                                      'focus': [m['focus'] for m in x['members']]}
                                     for x in (g.multi_member() if g else [])],
                    'warnings': list(g.warnings) if g else []}
    return {
        'team_id': team_id, 'dry_run': dry_run, 'rows': len(rows),
        'changed': len(plans), 'written': written, 'failed': failed,
        'frozen_refused': refused,
        'per_app': {ui: dict(c) for ui, c in sorted(per_app.items())},
        'apps': apps,
        'conflicts': {'before': len(before), 'after': len(after),
                      'stored_flags': sum(1 for r in rows if r.get('label_conflict'))},
        'changes': [{'id': str(p['row']['id']), 'userinterface': p['row'].get('userinterface'),
                     'from': (p['row'].get('ground_truth') or {}).get('label') if isinstance(p['row'].get('ground_truth'), dict) else None,
                     'to': (p['fields'].get('ground_truth') or {}).get('label'),
                     'fields': sorted(p['fields'])} for p in plans],
    }


def print_report(report: Dict[str, Any], out=None, describe=None) -> None:
    out = out or sys.stdout
    mode = ' (dry run: nothing written)' if report['dry_run'] else ''
    print(f"[regroup_screen_labels] team {report['team_id']}: {report['rows']} screen-id rows{mode}", file=out)
    for ui, a in report['apps'].items():
        print(f"  {ui}: {a['groups'] if a['groups'] is not None else 'no tree'} groups", file=out)
        for g in a['multi_member']:
            members = ', '.join(f"{m}" + (f" [{f}]" if f and f != m else '')
                                for m, f in zip(g['members'][1:], g['focus'][1:]))
            print(f"    {g['group']} ({len(g['members'])}) -> {members}", file=out)
        for w in a['warnings']:
            print(f"    WARNING {w}", file=out)
    print(f"  {'app':14s} {'rows':>5s} {'change':>6s} {'label':>5s} {'fail±':>5s} {'triage':>6s} "
          f"{'same':>5s} {'offtree':>7s} {'stale':>5s} {'unlab':>5s} {'notree':>6s} {'frozen':>6s}", file=out)
    for ui, c in report['per_app'].items():
        print(f"  {ui:14s} {c.get('rows', 0):5d} {c.get('change', 0):6d} {c.get('label', 0):5d} "
              f"{c.get('is_failure_flip', 0):5d} {c.get('triage', 0):6d} {c.get('unchanged', 0):5d} "
              f"{c.get('offtree', 0):7d} {c.get('stale', 0):5d} {c.get('unlabelled', 0):5d} "
              f"{c.get('no_tree', 0):6d} {c.get('frozen_refused', 0):6d}", file=out)
    k = report['conflicts']
    print(f"  conflicts (rows in a confusable pair): stored flags {k['stored_flags']}, "
          f"old labels {k['before']}, group labels {k['after']}", file=out)
    verb = 'would change' if report['dry_run'] else 'changed'
    print(f"  {verb} {report['changed']} row(s)" + ('' if report['dry_run'] else
          f", written {report['written']}, failed {len(report['failed'])}"), file=out)
    for r in report['frozen_refused']:
        print(f"  REFUSED frozen row {r['id']} ({r['eval_version']}, {r['label']})", file=out)
    if not report['dry_run'] and report['written']:
        print('  next: recompute_conflicts.py --team <id> to store the conflict flags', file=out)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='TASK-27 step 4k: rewrite screen-id labels as screen groups.')
    p.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    p.add_argument('--dry-run', action='store_true', help='compute and print; no DB write')
    p.add_argument('--json', action='store_true', help='also print the report (with the ids) as JSON')
    return p


def main(argv: Optional[List[str]] = None, *, list_fn=None, groups_for=None, write_fn=None,
         failure_fn=None, column_fn=None, out=None) -> int:
    args = build_arg_parser().parse_args(argv)
    out = out or sys.stdout
    if groups_for is None:
        groups_for = _load_lib('screen_group_scope').GroupCache().get
    if column_fn is None:
        column_fn = _load_lib('triage_db').column_exists
    try:
        rows = fetch_rows(args.team, list_fn=list_fn)
        report = regroup(args.team, rows, groups_for, args.dry_run, write_fn=write_fn,
                         failure_fn=failure_fn, triage_column=bool(column_fn()))
    except RegroupError as e:
        print(f'[regroup_screen_labels] REFUSED: {e}', file=sys.stderr)
        return 2
    print_report(report, out=out)
    if args.json:
        print(json.dumps(report, indent=2, default=str), file=out)
    return 0 if not report['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
