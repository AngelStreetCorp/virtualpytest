#!/usr/bin/env python3
"""focus_text_pass.py — TASK-27 step 4l: an AI (teacher) reads the focus text of grouped
``screen-id`` rows.

Since step 4k a ``screen-id`` label is the screen group plus what is focused on it::

    {"node_id": <home id>, "label": "home", "node": <home_recodings id>,
     "node_label": "home_recodings", "focus": "recodings"}

That ``focus`` came from the node **name** (the label suffix). On screen the highlighted tab
reads "Aufnahmen", the tiles "Disney+" or "HBO Max". The ``focus`` family answers the
visible text, so the two disagree on the same frame. This pass asks an AI worker (Claude
Sonnet, the step 4i worker) for the visible text and writes it into ``ground_truth.focus``.

    export  pick the grouped rows with a non-null focus that no human set, download their
            images read-only, write batch.jsonl (blind: the group name, never the old focus),
            key.json (the old focus, what the AI must not see) and INSTRUCTIONS.md.
    import  validate answers.jsonl and set ``ground_truth.focus`` to the answer (null =
            nothing focused), the rest of the label untouched, through the label path
            (``lib/label_write.apply_label``: is_failure, conflicts, frozen / human refused)
            **keeping** ``label_source``. The row's triage gets ``focus_teacher``.

Rules
-----
* **Human focus is never touched.** A row is human-set when ``label_source='human'`` or its
  triage is ``resolved`` (a human answered it). A row whose ``label_source`` is neither
  ``run`` nor ``teacher`` is "unsure" and skipped, counted.
* ``label_source`` and the triage ``status`` / ``reason`` stay as they are; the pass only adds
  ``triage.focus_teacher = {model, answer, confidence, note, batch_id, previous_focus,
  triaged_at}``. A row with no triage record gets one with ``focus_teacher`` only (no
  ``status``: step 4i treats such a record as "not triaged", ``triage_batch.has_status``).
* **Low confidence:** the new text is still written, and the row goes to the human:
  ``status='needs_human'``, ``reason='focus_low_confidence'`` (the old status and reason in
  ``focus_teacher.previous_status`` / ``previous_reason``). A row already ``needs_human`` for
  another reason keeps its ``reason``; ``focus_low_confidence`` is appended to ``reasons``.
* ``focus`` is an annotation key (core ``training_samples.ANNOTATION_KEYS``): ``is_failure``
  and the conflict check do not look at it, so they come back unchanged.

Usage (on the server, as vpt_user with the .env loaded; nothing loads it for you)
-----
    python3 features/ai-dataset/scripts/focus_text_pass.py export --team <uuid> --dry-run
    python3 features/ai-dataset/scripts/focus_text_pass.py export --team <uuid> --limit 50 --out /var/tmp/ftp
    # an AI worker reads /var/tmp/ftp/INSTRUCTIONS.md and writes /var/tmp/ftp/answers.jsonl
    python3 features/ai-dataset/scripts/focus_text_pass.py import --team <uuid> --in /var/tmp/ftp --dry-run
    python3 features/ai-dataset/scripts/focus_text_pass.py import --team <uuid> --in /var/tmp/ftp --teacher-model claude-sonnet-5
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FEATURE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '..'))  # features/ai-dataset/scripts -> repo
if os.path.isdir(os.path.join(_REPO_ROOT, 'shared')) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The step 4i helpers (answer parsing and validation, answer schema, instructions, image path).
tb = _load('ai_dataset_triage_batch', os.path.join(_SCRIPT_DIR, 'triage_batch.py'))
_load_lib = tb._load_lib

FAMILY = 'screen-id'          # the rows this pass reads and writes
ANSWER_FAMILY = 'focus'       # the question the worker answers (validated as a focus label)
KIND = 'focus-text'           # key.json marker: a triage_batch key is never imported here
BLIND_KEYS = ('id', 'family', 'image', 'question', 'allowed_answers', 'answer_schema')
TEACHER_SOURCES = ('run', 'teacher')
LOW_REASON = 'focus_low_confidence'
PAGE_SIZE = 500
MAX_ROWS = 100000

QUESTION = ("This is the **{screen}** screen of a TV app. Which item has the focus (the highlighted "
            "tab, tile or menu entry)? Give its visible text exactly as shown, or say nothing is focused.\n"
            "Answer: {{\"focused\": \"<visible text>\"}}, or {{\"focused\": null}} when nothing is focused.")
ANSWER_SCHEMA = {'focused': '<text>|null',
                 'shape': {'focused': '<visible text of the one highlighted element, exactly as shown>'},
                 'nothing_focused': {'focused': None},
                 'example': {'focused': 'Kanal 7'}}


class FocusPassError(Exception):
    """A guard failed: the whole command is refused."""


# ---- export (pure parts) -------------------------------------------------------------------

def _gt(row: Dict[str, Any]) -> Dict[str, Any]:
    gt = row.get('ground_truth')
    if isinstance(gt, str):
        try:
            gt = json.loads(gt)
        except ValueError:
            return {}
    return gt if isinstance(gt, dict) else {}


def has_focus(row: Dict[str, Any]) -> bool:
    """A grouped ``screen-id`` label (a screen of the tree) with a non-null focus."""
    gt = _gt(row)
    return gt.get('node_id') is not None and 'node' in gt and tb.label_schema._text(gt.get('focus'))


def human_reason(row: Dict[str, Any]) -> Optional[str]:
    """Why the row's focus counts as set (or possibly set) by a human, or None.

    ``human_label``: ``label_source='human'``; ``human_resolved``: the triage was resolved by a
    human answer; ``unsure:<source>``: any source other than ``run`` / ``teacher``."""
    source = row.get('label_source')
    if source == 'human':
        return 'human_label'
    if (tb.triage_of(row) or {}).get('status') == 'resolved':
        return 'human_resolved'
    if source not in TEACHER_SOURCES:
        return f'unsure:{source}'
    return None


def select_rows(rows: Sequence[Dict[str, Any]], userinterface: Optional[str] = None,
                limit: Optional[int] = None, include_done: bool = False
                ) -> Tuple[List[Dict[str, Any]], Counter]:
    """Grouped ``screen-id`` rows with a focus that a teacher may rewrite. ``(rows, skipped)``.

    Rows without a focus (the group's own node, pre-4k labels, off-tree, unlabelled) are not
    candidates and are not counted; every other row not picked is counted by reason."""
    skipped: Counter = Counter()
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get('family') != FAMILY or not has_focus(row):
            continue
        if userinterface and row.get('userinterface') != userinterface:
            continue
        if row.get('eval_version'):
            skipped['frozen'] += 1
            continue
        reason = human_reason(row)
        if reason:
            skipped[reason] += 1
            continue
        if (tb.triage_of(row) or {}).get('focus_teacher') and not include_done:
            skipped['focus_done'] += 1
            continue
        out.append(row)
    return (out[:limit] if limit else out), skipped


def screen_name(row: Dict[str, Any]) -> str:
    """The group name as the question says it: ``home`` -> ``Home``, ``settings_system`` ->
    ``Settings system``."""
    name = str(_gt(row).get('label') or '').replace('_', ' ').strip()
    return name[:1].upper() + name[1:]


def question_for(row: Dict[str, Any]) -> str:
    return QUESTION.format(screen=screen_name(row))


def build_line(row: Dict[str, Any]) -> Dict[str, Any]:
    """One ``batch.jsonl`` line: exactly ``BLIND_KEYS``. The old focus, the node and its
    label stay in ``key.json``."""
    return {'id': str(row['id']), 'family': ANSWER_FAMILY, 'image': tb.image_rel_path(row),
            'question': question_for(row), 'allowed_answers': None, 'answer_schema': dict(ANSWER_SCHEMA)}


def key_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    gt = _gt(row)
    triage = tb.triage_of(row) or {}
    return {'family': ANSWER_FAMILY, 'row_family': FAMILY, 'label_source': row.get('label_source'),
            'ground_truth': row.get('ground_truth'), 'previous_focus': gt.get('focus'),
            'group': gt.get('label'), 'node_label': gt.get('node_label'),
            'userinterface': row.get('userinterface'), 'split': row.get('split'),
            'triage_status': triage.get('status')}


def group_counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """``{"<userinterface>/<group>": n}``, largest first."""
    c = Counter(f"{r.get('userinterface') or '?'}/{_gt(r).get('label')}" for r in rows)
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


INSTRUCTIONS_NOTE = """
## This batch: the focused item's visible text

Every image is a screen of a TV app; the `question` names the screen. Answer **which item is
highlighted** (the tab, tile, button or menu entry the remote's OK key would select) with its
**visible text, exactly as shown on screen**: same language, spelling, capitals, spaces and
symbols such as `+` (e.g. `Kanal 7`, `FooTV+`), not a translation and not a name you would expect. A
logo tile with no readable text: its brand name as the logo writes it, `"confidence": "low"`.
Nothing highlighted (fullscreen video, splash, black frame): `{"focused": null}`.
"""


def render_instructions(batch_id: str, n: int, folder: str) -> str:
    return tb.render_instructions(batch_id, ANSWER_FAMILY, n, folder) + INSTRUCTIONS_NOTE


# ---- import (pure parts) -------------------------------------------------------------------

def norm(text: Any) -> str:
    """Case- and punctuation-insensitive form: ``Disney+`` == ``disney``, ``HBO Max`` == ``hbomax``."""
    return re.sub(r'[\W_]+', '', str(text or '').casefold())


def skip_reason(sample: Dict[str, Any], row: Optional[Dict[str, Any]]) -> Optional[str]:
    if row is None:
        return 'row_missing'
    if row.get('eval_version'):
        return 'frozen'
    reason = human_reason(row)
    if reason:
        return reason
    if row.get('label_source') != sample.get('label_source') \
            or tb._canonical(row.get('ground_truth')) != tb._canonical(sample.get('ground_truth')):
        return 'changed_since_export'
    return None


def new_triage(old: Optional[Dict[str, Any]], focus_teacher: Dict[str, Any], low: bool) -> Dict[str, Any]:
    """The row's triage record with ``focus_teacher`` added; status and reason unchanged unless
    ``low`` (then ``needs_human`` / ``focus_low_confidence``, or the reason appended to
    ``reasons`` when the row already needs a human for another reason)."""
    record = dict(old or {})
    ft = dict(focus_teacher)
    if low:
        status, reason = record.get('status'), record.get('reason')
        if status == 'needs_human' and reason and reason != LOW_REASON:
            reasons = list(record.get('reasons') or [reason])
            if LOW_REASON not in reasons:
                reasons.append(LOW_REASON)
            record['reasons'] = reasons
        elif not (status == 'needs_human' and reason == LOW_REASON):
            ft.update(previous_status=status, previous_reason=reason)
            record.update(status='needs_human', reason=LOW_REASON)
    record['focus_teacher'] = ft
    return record


def plan(key: Dict[str, Any], accepted: Dict[str, Dict[str, Any]], rows: Dict[str, Optional[Dict[str, Any]]],
         model: str, now: str) -> Tuple[List[Dict[str, Any]], Counter]:
    """Decide every accepted answer. Pure. Returns ``(decisions, skipped)``."""
    samples = key['samples']
    decisions: List[Dict[str, Any]] = []
    skipped: Counter = Counter()
    for sid in sorted(accepted):
        sample, row, acc = samples[sid], rows.get(sid), accepted[sid]
        reason = skip_reason(sample, row)
        if reason:
            skipped[reason] += 1
            decisions.append({'id': sid, 'action': 'skip', 'skip': reason})
            continue
        old_gt = _gt(row)
        previous = old_gt.get('focus')
        focus = acc['label'].get('focused')          # normalised text, or None
        ground_truth = {**old_gt, 'focus': focus}
        low = acc['confidence'] == 'low'
        focus_teacher = {'model': model, 'answer': acc['answer'], 'confidence': acc['confidence'],
                         'note': acc.get('note'), 'batch_id': key['batch_id'],
                         'previous_focus': previous, 'triaged_at': now}
        triage = new_triage(tb.triage_of(row), focus_teacher, low)
        if focus is None:
            outcome = 'nothing_focused'
        else:
            outcome = 'same' if norm(focus) == norm(previous) else 'changed'
        decisions.append({'id': sid, 'action': 'write', 'row': row, 'ground_truth': ground_truth,
                          'triage': triage, 'low': low, 'outcome': outcome, 'group': old_gt.get('label'),
                          'previous_focus': previous, 'focus': focus})
    return decisions, skipped


def summarize(key: Dict[str, Any], decisions: List[Dict[str, Any]], rejected: List[Dict[str, Any]],
              accepted: Dict[str, Any], skipped: Counter) -> Dict[str, Any]:
    written = [d for d in decisions if d['action'] == 'write']
    outcomes = Counter(d['outcome'] for d in written)
    answered = set(accepted) | {r['id'] for r in rejected if r.get('id')}
    return {'batch_id': key.get('batch_id'), 'updated': len(written),
            'changed': outcomes.get('changed', 0), 'same': outcomes.get('same', 0),
            'nothing_focused': outcomes.get('nothing_focused', 0),
            'low_confidence': sum(1 for d in written if d['low']),
            'skipped': dict(skipped), 'rejected': rejected,
            'unanswered': sorted(set(key.get('samples') or {}) - answered)}


def print_summary(summary: Dict[str, Any], dry_run: bool, out=None) -> None:
    out = out or sys.stdout
    print(f"[focus_text_pass] batch {summary['batch_id']}{' (dry run: nothing written)' if dry_run else ''}", file=out)
    print(f"  updated {summary['updated']}: focus changed {summary['changed']}, same {summary['same']}, "
          f"nothing focused {summary['nothing_focused']}; low confidence (-> needs_human) "
          f"{summary['low_confidence']}", file=out)
    for reason, n in sorted(summary['skipped'].items()):
        print(f"  skipped/{reason}: {n}", file=out)
    for r in summary['rejected']:
        print(f"  REJECTED line {r['line']} id={r.get('id')}: {r['reason']}", file=out)
    if summary['unanswered']:
        print(f"  unanswered: {', '.join(summary['unanswered'])}", file=out)


# ---- IO: DB, storage (not unit-tested; injectable) -----------------------------------------

def fetch_rows(team_id: str, list_fn=None) -> List[Dict[str, Any]]:
    """Every ``screen-id`` row of the team (all label sources, so human rows are counted),
    paged through core ``list_samples``. Refuses rather than work from a partial read."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page, total = list_fn(team_id, family=FAMILY, limit=PAGE_SIZE, offset=offset)
        if total > MAX_ROWS:
            raise FocusPassError(f'team has {total} {FAMILY} rows, more than MAX_ROWS={MAX_ROWS}')
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    if len(rows) != total or len({r['id'] for r in rows}) != len(rows):
        raise FocusPassError(f'read {len(rows)} rows, expected {total}: rows changed while paging, run again')
    return rows


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def run_export(args, *, list_fn=None, storage=None, out=None) -> int:
    out = out or sys.stdout
    if args.limit is not None and args.limit < 1:
        raise FocusPassError('--limit must be >= 1')
    rows = fetch_rows(args.team, list_fn=list_fn)
    selected, skipped = select_rows(rows, args.userinterface, None, args.include_done)
    if args.dry_run:
        print(json.dumps({'would_select': len(selected), 'by_group': group_counts(selected),
                          'skipped': dict(skipped)}, indent=2), file=out)
        return 0
    if not args.out:
        raise FocusPassError('--out is required (or use --dry-run)')
    folder = os.path.abspath(args.out)
    if os.path.exists(folder) and os.listdir(folder):
        raise FocusPassError(f'{folder} exists and is not empty; pick a new --out')
    os.makedirs(os.path.join(folder, 'images'), exist_ok=True)
    if storage is None:
        from shared.src.lib.utils.cloudflare_utils import get_training_storage
        storage = get_training_storage()

    batch_id = f"ftp-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    lines, key_samples = [], {}
    for row in selected:
        if args.limit and len(lines) >= args.limit:
            break
        result = storage.download_file(row['object_key'], os.path.join(folder, tb.image_rel_path(row)))
        if not result.get('success'):
            skipped['image_missing'] += 1
            print(f"[focus_text_pass] skip {row['id']}: image {result.get('error')}", file=sys.stderr)
            continue
        lines.append(build_line(row))
        key_samples[str(row['id'])] = key_entry(row)

    with open(os.path.join(folder, 'batch.jsonl'), 'w', encoding='utf-8', newline='\n') as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + '\n')
    key = {'kind': KIND, 'batch_id': batch_id, 'team_id': args.team, 'family': ANSWER_FAMILY,
           'created_at': _now(), 'blind': True, 'userinterface': args.userinterface, 'samples': key_samples}
    with open(os.path.join(folder, 'key.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(key, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(folder, 'INSTRUCTIONS.md'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(render_instructions(batch_id, len(lines), folder))
    print(json.dumps({'batch_id': batch_id, 'out': folder, 'samples': len(lines),
                      'selected': len(selected), 'by_group': group_counts([r for r in selected
                                                                            if str(r['id']) in key_samples]),
                      'skipped': dict(skipped)}, indent=2), file=out)
    return 0


def focus_writer(triage: Dict[str, Any], label_source: str, write_fn=None):
    """A ``label_write.apply_label`` writer: the new label, ``is_failure``, ``label_conflict``
    and the triage record in one statement, guarded by ``triage_db.regroup_write`` (not
    frozen, still the ``label_source`` it was read with, so never a human row).
    ``label_source`` is not written."""
    if write_fn is None:
        write_fn = _load_lib('triage_db').regroup_write

    def write(sample_id: str, team_id: str, ground_truth: Any, _source: str,
              is_failure: bool, label_conflict: bool) -> bool:
        return write_fn(team_id, sample_id, {'ground_truth': ground_truth, 'is_failure': bool(is_failure),
                                             'label_conflict': bool(label_conflict), 'triage': triage},
                        label_source)
    return write


def apply(team_id: str, decisions: List[Dict[str, Any]], apply_fn, write_fn, skipped: Counter) -> None:
    """Write every ``write`` decision through the label path, keeping ``label_source``."""
    for d in decisions:
        if d['action'] != 'write':
            continue
        row = d['row']
        # apply_label refuses a non-human label over a human one; this pass keeps the row's
        # own source, so it must refuse a human (or unknown) source itself.
        if row.get('label_source') not in TEACHER_SOURCES:
            d.update(action='skip', skip='refused:human' if row.get('label_source') == 'human'
                     else f"refused:{row.get('label_source')}")
            skipped[d['skip']] += 1
            continue
        try:
            result = apply_fn(team_id, row, d['ground_truth'], row['label_source'],
                              write=focus_writer(d['triage'], row['label_source'], write_fn))
        except Exception as e:  # label_write.LabelRefused (human / frozen) or a DB error
            d.update(action='skip', skip=f"refused:{getattr(e, 'reason', 'error')}")
            skipped[d['skip']] += 1
            continue
        if not result.get('ok'):
            d.update(action='skip', skip='write_refused')
            skipped['write_refused'] += 1


def _read_key(folder: str) -> Dict[str, Any]:
    path = os.path.join(folder, 'key.json')
    if not os.path.isfile(path):
        raise FocusPassError(f'{path} not found (run export first)')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def run_import(args, *, get_fn=None, apply_fn=None, write_fn=None, column_fn=None, opted_in_fn=None,
               out=None) -> int:
    out = out or sys.stdout
    folder = os.path.abspath(args.in_dir)
    key = _read_key(folder)
    if key.get('kind') != KIND:
        raise FocusPassError(f'{folder}/key.json is not a {KIND} batch (a triage_batch key goes to triage_batch.py)')
    if str(key.get('team_id')) != str(args.team):
        raise FocusPassError(f"key.json is for team {key.get('team_id')}, not --team {args.team}")
    answers_path = os.path.join(folder, 'answers.jsonl')
    if not os.path.isfile(answers_path):
        raise FocusPassError(f'{answers_path} not found')
    with open(answers_path, encoding='utf-8') as fh:
        accepted, rejected = tb.parse_answers(fh.read().splitlines(), key)

    if get_fn is None:
        from shared.src.lib.database import ai_training_samples_db as samples_db
        get_fn = samples_db.get_sample
    rows = {sid: get_fn(sid, args.team) for sid in accepted}
    decisions, skipped = plan(key, accepted, rows, args.teacher_model, _now())

    if args.dry_run:
        for d in decisions:
            if d['action'] == 'skip':
                print(f"  {d['id']}  skip {d['skip']}", file=out)
            else:
                print(f"  {d['id']}  {d['group']}: {d['previous_focus']!r} -> {d['focus']!r}  {d['outcome']}"
                      + ('  LOW -> needs_human' if d['low'] else ''), file=out)
    else:
        if column_fn is None:
            column_fn = _load_lib('triage_db').column_exists
        if opted_in_fn is None:
            from shared.src.lib.database.ai_training_samples_db import team_opted_in as opted_in_fn
        if apply_fn is None:
            apply_fn = _load_lib('label_write').apply_label
        if not column_fn():
            raise FocusPassError('the triage column is missing: apply features/ai-dataset/db/001_triage.sql first')
        if not opted_in_fn(args.team):
            raise FocusPassError(f'team {args.team} has not opted in to training data (TASK-27 section 9)')
        apply(args.team, decisions, apply_fn, write_fn, skipped)

    summary = summarize(key, decisions, rejected, accepted, skipped)
    print_summary(summary, args.dry_run, out=out)
    if args.json:
        print(json.dumps(summary, indent=2, default=str), file=out)
    return 0


# ---- CLI -----------------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='TASK-27 step 4l: AI focus-text pass on grouped screen-id rows.')
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export', help='select rows, download images, write batch.jsonl + key.json + INSTRUCTIONS.md')
    exp.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    exp.add_argument('--userinterface', default=None, help='only rows of this userinterface')
    exp.add_argument('--limit', type=int, default=None, help='at most N samples')
    exp.add_argument('--out', default=None, help='empty or new folder for the batch')
    exp.add_argument('--dry-run', action='store_true', help='print what would be selected, by group; no download, no file')
    exp.add_argument('--include-done', action='store_true', help='also rows that already have a focus_teacher record')
    imp = sub.add_parser('import', help='validate answers.jsonl, write the focus text')
    imp.add_argument('--team', required=True)
    imp.add_argument('--in', dest='in_dir', required=True, help='the batch folder (key.json, answers.jsonl)')
    imp.add_argument('--teacher-model', default=tb.DEFAULT_MODEL, help='the AI that answered, recorded per row')
    imp.add_argument('--dry-run', action='store_true', help='decide and print; no DB write')
    imp.add_argument('--json', action='store_true', help='also print the summary as JSON')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return run_export(args) if args.command == 'export' else run_import(args)
    except FocusPassError as e:
        print(f'[focus_text_pass] REFUSED: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
