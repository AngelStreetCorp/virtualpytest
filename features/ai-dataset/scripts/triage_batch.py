#!/usr/bin/env python3
"""triage_batch.py — TASK-27 step 4i: AI (teacher) triage of training samples.

An AI worker (a Claude Sonnet agent run from the orchestrator's session) labels samples
in place of the human; the human only sees the disagreements and a spot-check.

    export  pick the rows that need a teacher look, download their images read-only,
            write batch.jsonl (what the AI sees), key.json (what it must not see),
            INSTRUCTIONS.md (how to answer).
    import  validate the AI's answers.jsonl, decide the triage of each row, and apply
            labels through the review route's own write path (lib/label_write.py).

The rule (human decision, 2026-09-30)
-------------------------------------
* The AI answer counts as **checked** when it agrees with an independent label already on
  the row: ``label_source='run'`` (for ``banner`` that is the numeric-zap run label),
  compared with the family comparator (``lib/comparators.py``). Triage ``agreed``; the
  row keeps ``label_source='run'`` and its ground truth.
* The human must look (triage ``needs_human``) only when: the AI disagrees with the run
  label (``disagrees_with_run``, ground truth unchanged); the row is a confusable pair
  (``conflict``); the AI said low confidence / can't tell (``low_confidence``); or the row
  is in the deterministic spot-check of the AI's labels (``spot_check``, default 5%).
* ``conflict`` is always the live check under the current core rules
  (``training_samples.find_conflicts``), never the stored ``label_conflict`` flag, which can
  be stale (step 4j: low-information hashes and ``focus`` no longer conflict; run
  ``recompute_conflicts.py`` to refresh the stored flags before a real import).
* A row with no independent label gets the AI answer as ``ground_truth`` with
  ``label_source='teacher'`` and triage ``teacher_only`` / ``no_independent_label``: fine
  for training (``export_dataset.py --include-teacher``), never counted as checked.
* Human labels always win: a teacher label is never written over a ``human`` row, nor on a
  frozen (``eval_version``) row; a later human answer replaces a teacher label and marks
  the triage ``resolved`` (review route).

Second pass (human decision, 2026-10-01: the human is asked only when really necessary)
---------------------------------------------------------------------------------------
``export --second-pass`` takes the rows the AI could not settle (``needs_human`` with reason
``disagrees_with_run``, ``conflict`` or ``low_confidence``) and the rows with no triage yet.
A second blind AI answer then settles them without the human (``key.json`` says
``second_pass``; the import follows it):

* run label, the AI agrees, confident, no confusable pair -> ``agreed`` (as in the first pass);
* no run label, confident, no confusable pair -> the teacher label, ``teacher_only``;
* anything else (disagrees with the run, low confidence, confusable pair) -> ``excluded``:
  the label is not changed, ``export_dataset.py`` leaves the row out of training, and the row
  never goes to "Needs you". ``excluded`` is never final, so it is never spot-checked.

The spot-check of the final rows is unchanged: it is the only measure of the AI's accuracy.
A spot-check row (``needs_human`` / ``spot_check``) and a ``focus_low_confidence`` row (step 4l,
``focus_text_pass.py``) are never taken by the second pass.

Jev first (owner, 2026-10-04)
-----------------------------
``import-jev --bundle DIR`` reads a ``scripts/jev_review`` bundle exported with ``--sets open``
(the rows the second pass would take) and its ``decisions.jsonl``: Jev picked the screen group of
each frame from text facts (reference match, OCR, seed-frame distance). A decision at confidence
>= ``--min-confidence`` (0.8: 43/43 right on the 2026-10-04 benchmark) settles the row without a
Sonnet look when there is no run label (the Jev label is applied, ``label_source='teacher'``,
reason ``jev_settled``) or when it agrees with the run label (the label is kept, reason
``jev_agrees_with_run``). Status ``teacher_only`` in both cases, **never** ``agreed``: Jev's facts
come from the same node checks that produced the run label, so it is not an independent check
and never counts towards an eval-vN-ai freeze. Everything else (low confidence, a disagreement,
a confusable pair) stays open for the Sonnet second pass. The 5% spot-check applies.

Blind by default: ``batch.jsonl`` holds only ``id, family, image, question,
allowed_answers, answer_schema``. The run label, the model answer (which on a failed
verification names the expected screen), the node ids and the source pointer stay in
``key.json``. ``--no-blind`` adds ``run_label`` to each line (debugging only).

Storage: the ``triage`` JSONB column of ``features/ai-dataset/db/001_triage.sql``. The
export and ``import --dry-run`` do not need it; a real import refuses without it.

Langfuse (2026-10-04): after a real import, every decided row (``agreed``, ``teacher_only``,
``excluded``) whose ``source_ref.trace_id`` points at a real AI call (``banner`` zap rows
today) gets a ``verdict_ai`` score on that trace: the model's answer against the teacher
label, teacher model in the comment (``lib/langfuse_scores``). ``--no-langfuse`` skips it;
a Langfuse failure never changes the import.

Usage (on the server, as vpt_user with the .env loaded; nothing loads it for you)
-----
    python3 features/ai-dataset/scripts/triage_batch.py export --team <uuid> --family screen-id --limit 50 --out /var/tmp/tri
    # an AI worker reads /var/tmp/tri/INSTRUCTIONS.md and writes /var/tmp/tri/answers.jsonl
    python3 features/ai-dataset/scripts/triage_batch.py import --team <uuid> --in /var/tmp/tri --dry-run
    python3 features/ai-dataset/scripts/triage_batch.py import --team <uuid> --in /var/tmp/tri --teacher-model claude-sonnet-5
    # second pass (the rows the first could not settle), same export / answer / import loop:
    python3 features/ai-dataset/scripts/triage_batch.py export --team <uuid> --family screen-id --second-pass --out /var/tmp/tri2
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FEATURE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '..'))  # features/ai-dataset/scripts -> repo
if os.path.isdir(os.path.join(_REPO_ROOT, 'shared')) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_lib(name: str):
    """The feature's lib module next to this script (works from a copied tree too)."""
    path = os.path.join(_FEATURE_DIR, 'lib', f'{name}.py')
    spec = importlib.util.spec_from_file_location(f'ai_dataset_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


label_schema = _load_lib('label_schema')
comparators = _load_lib('comparators')
langfuse_scores = _load_lib('langfuse_scores')

FAMILIES = ('screen-id', 'focus', 'banner', 'menu', 'av-fault')
CONFIDENCES = ('high', 'low')
BLIND_KEYS = ('id', 'family', 'image', 'question', 'allowed_answers', 'answer_schema')
PAGE_SIZE = 500
MAX_ROWS = 20000
DEFAULT_MODEL = 'claude-sonnet-5'
DEFAULT_SPOT_CHECK_PCT = 5.0
# Export order (human decision): failed verifications, then unlabelled rows, then run labels.
PRIORITY_FAILED_VERIFICATION, PRIORITY_UNLABELLED, PRIORITY_RUN = 0, 1, 2
# The rows whose AI label is final unless a human looks: the spot-check pool.
FINAL_STATUSES = ('agreed', 'teacher_only')
# Second pass: the needs_human reasons a second AI answer may settle, and the status of a row
# it still cannot settle (left out of training, never sent to the human).
SECOND_PASS_REASONS = ('disagrees_with_run', 'conflict', 'low_confidence')
EXCLUDED = 'excluded'
# 2026-10-04: the decided rows whose Langfuse trace gets a verdict_ai score.
VERDICT_STATUSES = ('agreed', 'teacher_only', EXCLUDED)


class TriageError(Exception):
    """A guard failed: the whole command is refused."""


# ---- export (pure parts) -------------------------------------------------------------------

def triage_of(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    value = row.get('triage')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def has_status(row: Dict[str, Any]) -> bool:
    """The row has been triaged: its triage record carries a ``status``. Step 4l: a record
    holding only ``focus_teacher`` (``focus_text_pass.py`` on a never-triaged row) is not a
    triage, so the row stays open for this pass."""
    return bool((triage_of(row) or {}).get('status'))


def second_pass_open(row: Dict[str, Any]) -> bool:
    """The row is open to the second pass: no triage yet, or ``needs_human`` for a reason a
    second AI answer may settle (``SECOND_PASS_REASONS``)."""
    triage = triage_of(row) or {}
    if not triage.get('status'):
        return True
    return triage.get('status') == 'needs_human' and triage.get('reason') in SECOND_PASS_REASONS


def priority(row: Dict[str, Any], second_pass: bool = False) -> Optional[int]:
    """Export rank of a row, or None when it must never be exported (human, frozen,
    labelled by anything but a run; a teacher row only on the second pass)."""
    if row.get('eval_version'):
        return None
    source = row.get('label_source')
    if second_pass and source == 'teacher' and row.get('ground_truth') is not None:
        return PRIORITY_UNLABELLED
    if source == 'none' and row.get('ground_truth') is None:
        return PRIORITY_FAILED_VERIFICATION if label_schema.is_failed_verification(row) else PRIORITY_UNLABELLED
    if source == 'run' and row.get('ground_truth') is not None:
        return PRIORITY_RUN
    return None


def select_rows(rows: Sequence[Dict[str, Any]], family: str, userinterface: Optional[str] = None,
                split: Optional[str] = None, limit: Optional[int] = None,
                include_triaged: bool = False, second_pass: bool = False) -> Tuple[List[Dict[str, Any]], Counter]:
    """Rows that need a teacher look, in export order. Returns ``(rows, skipped)``.
    ``second_pass``: the rows ``second_pass_open`` (teacher rows included)."""
    skipped: Counter = Counter()
    ranked = []
    for i, row in enumerate(rows):
        if row.get('family') != family:
            continue
        if split and row.get('split') != split:
            continue
        if userinterface and row.get('userinterface') != userinterface:
            continue
        rank = priority(row, second_pass)
        if rank is None:
            skipped['frozen' if row.get('eval_version') else f"label_source:{row.get('label_source')}"] += 1
            continue
        if second_pass:
            if not second_pass_open(row):
                skipped['settled'] += 1
                continue
        elif has_status(row) and not include_triaged:
            skipped['already_triaged'] += 1
            continue
        ranked.append((rank, i, row))
    ranked.sort(key=lambda t: (t[0], t[1]))
    out = [r for _rank, _i, r in ranked]
    return (out[:limit] if limit else out), skipped


def screen_names(screen_labels: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    return [str(e['label']) for e in (screen_labels or []) if e.get('label')]


def allowed_answers(row: Dict[str, Any], screen_labels=None) -> Any:
    family = row['family']
    if family == 'screen-id':
        return screen_names(screen_labels)
    if family == 'av-fault':
        if label_schema.is_strip(row):
            return [dict(a) for a in label_schema.STRIP_ANSWERS]
        return [{'incident_type': t} for t in label_schema.AV_FAULT_TYPES] + [{'incident_type': None}]
    return None


def answer_schema(row: Dict[str, Any]) -> Dict[str, Any]:
    """What the answer object must look like. Wins over any format named in the question."""
    family = row['family']
    if family == 'screen-id':
        return {'shape': {'label': '<one screen name from allowed_answers, spelled as listed>'},
                'or_not_in_list': {'node_id': None, 'label': '<short lowercase name, e.g. popup, error / no signal, '
                                                              'loading / black, dialog, tip>'},
                'example': {'label': 'home'}}
    if family == 'focus':
        return {'shape': {'focused': '<visible text of the one highlighted element>'},
                'nothing_focused': {'focused': None},
                'example': {'focused': 'Settings'}}
    if family == 'banner':
        return {'shape': {'channel_number': '<number as shown, or null>', 'channel_name': '<name as shown, or null>'},
                'no_banner': {'channel_number': None, 'channel_name': None},
                'example': {'channel_number': '101', 'channel_name': 'BBC One'},
                'note': 'Give only these two fields. Omit a field you cannot read, or set it null. '
                        'Both null means there is no channel banner on the frame.'}
    if family == 'menu':
        return {'shape': {'items': ['<item>', '...'], 'selected': '<one of items, or null>'},
                'example': {'items': ['English', 'English - AD', 'French'], 'selected': 'English'}}
    if family == 'av-fault':
        if label_schema.is_strip(row):
            return {'shape': 'exactly one object of allowed_answers',
                    'meaning': {'{"incident_type": "freeze"}': 'frozen, a real problem',
                                '{"incident_type": null, "static_screen": true}': 'a still screen that is fine: '
                                'no continuous video motion (menu, guide, radio, pause, a promo carousel, a page '
                                'loading), even if it changes in steps between frames',
                                '{"incident_type": null, "static_screen": false}': 'video is actually playing '
                                'full-screen: a false alarm'}}
        return {'shape': {'incident_type': '"blackscreen" | "freeze" | "macroblocks" | null'},
                'example': {'incident_type': None}}
    raise TriageError(f"no answer schema for family {family!r}")


def image_rel_path(row: Dict[str, Any]) -> str:
    return f"images/{row['id']}.jpg"


def run_label_of(row: Dict[str, Any]) -> Any:
    return row.get('ground_truth') if row.get('label_source') == 'run' else None


def build_line(row: Dict[str, Any], question: str, screen_labels=None, blind: bool = True) -> Dict[str, Any]:
    """One ``batch.jsonl`` line. Blind: exactly ``BLIND_KEYS``, nothing else."""
    line = {
        'id': str(row['id']),
        'family': row['family'],
        'image': image_rel_path(row),
        'question': question,
        'allowed_answers': allowed_answers(row, screen_labels),
        'answer_schema': answer_schema(row),
    }
    if not blind:
        line['run_label'] = run_label_of(row)
    return line


def key_entry(row: Dict[str, Any], priority_rank: int) -> Dict[str, Any]:
    """What ``key.json`` keeps per sample: everything the AI must not see."""
    return {
        'family': row['family'],
        'label_source': row.get('label_source'),
        'run_label': run_label_of(row),
        'ground_truth': row.get('ground_truth'),
        'label_conflict': bool(row.get('label_conflict')),
        'is_failure': bool(row.get('is_failure')),
        'userinterface': row.get('userinterface'),
        'node_id': row.get('node_id'),
        'model_answer': row.get('model_answer'),
        'source_ref': row.get('source_ref'),
        'split': row.get('split'),
        'strip': label_schema.is_strip(row),
        'failed_verification': label_schema.is_failed_verification(row),
        'priority': priority_rank,
    }


INSTRUCTIONS = """# AI triage batch `{batch_id}`: instructions for the labelling worker

You label **{n} {family} sample(s)** in place of a human reviewer. Your answers are compared
with other evidence you cannot see; where they disagree, a human looks. Be accurate, not fast.

## Input

- `batch.jsonl`: one JSON object per line, one per sample, with these fields:
  - `id`: the sample id; copy it exactly into your answer.
  - `family`: `{family}`.
  - `image`: the screenshot, a path relative to this folder (`images/<id>.jpg`).
  - `question`: what to find out, in plain language. It is the prompt a production model
    gets; **if it names an answer format, ignore that format and use `answer_schema`.**
  - `allowed_answers`: when not null, your answer must be one of these (see below).
  - `answer_schema`: the exact shape of your `answer` object.
- `images/`: the screenshots.

Do not open any other file in this folder. In particular never read `key.json`.

## What to do, for every line of `batch.jsonl`, in order

1. Read the image with the **Read** tool: `{folder}/<image>`. Look at the whole frame.
2. Answer the `question` about that image.
3. Write the answer strictly in `answer_schema`:{family_rules}
4. Append **one line** to `{folder}/answers.jsonl`, valid JSON, no trailing comma:

   ```json
   {{"id": "<id>", "answer": {{...}}, "confidence": "high", "note": "optional, short"}}
   ```

   - `confidence`: `"high"` when you are sure; `"low"` when you are not sure **or cannot
     tell** (blurry, cut off, ambiguous, two screens look alike). "Can't tell" is always
     `"confidence": "low"` **with your best guess** in `answer`, never an empty answer.
   - `note`: optional, one short sentence (e.g. why you are unsure). Leave it out otherwise.

## Rules

- One line per sample, every sample, each `id` once. No other lines, no markdown in the file.
- `answer` is a JSON object, never a string. `null` is JSON `null`, not `"null"`.
- Never guess an id, a node id or a field that is not in `answer_schema`.
- Do not skip a sample: when unsure, answer with `"confidence": "low"`.
- When done, reply with the number of lines written and the ids you marked `low`.
"""

_FAMILY_RULES = {
    'screen-id': """
   - `{"label": "<name>"}` with a name **copied exactly** from `allowed_answers` (the screens
     of this app). A screen stays the same screen whichever tab, tile or menu entry is
     highlighted on it: Home with the Settings tab highlighted is `home`, while the Settings
     screen itself (opened with OK) is `settings`. Name the screen only; the highlighted item
     is a separate question.
   - If the frame is none of the listed screens (a popup, an error, a black or loading
     frame, a dialog, a tip), answer `{"node_id": null, "label": "<short lowercase name>"}`.""",
    'focus': """
   - `{"focused": "<text>"}`: the visible text of the one highlighted element (tile,
     button, menu entry), exactly as displayed.
   - `{"focused": null}` when **nothing** is highlighted (fullscreen video, a splash or
     loading screen). JSON `null`, not the string "null".""",
    'banner': """
   - `{"channel_number": "...", "channel_name": "..."}` as displayed on the channel banner.
     Leave out (or null) a field you cannot read. No banner on the frame:
     `{"channel_number": null, "channel_name": null}`. No other fields.""",
    'menu': """
   - `{"items": [...], "selected": "..."}`: the menu entries top to bottom, exactly as
     displayed, and the selected one (copied from `items`) or null.""",
    'av-fault': """
   - Copy **one object from `allowed_answers`** exactly. For a strip (several frames side
     by side with their times), compare the frames: identical over the whole time while
     video should play = frozen. **Still** (`static_screen: true`) = no continuous video
     motion: a menu, guide, radio screen, paused video, a promo carousel switching posters
     or a page loading, **even when it changes in steps between frames** (a small live
     preview tile inside a menu does not make it moving). **Moving** (`static_screen: false`)
     = video actually playing full-screen. (Owner's definition, 2026-10-05.)""",
}


def render_instructions(batch_id: str, family: str, n: int, folder: str) -> str:
    return INSTRUCTIONS.format(batch_id=batch_id, family=family, n=n, folder=folder.rstrip('/\\'),
                               family_rules=_FAMILY_RULES.get(family, ''))


# ---- import (pure parts) -------------------------------------------------------------------

def _screen_entries(key: Dict[str, Any], ui: Optional[str]) -> List[Dict[str, Any]]:
    return list((key.get('screen_labels') or {}).get(ui or '', []) or [])


def validate_answer(family: str, sample: Dict[str, Any], screen_labels: Sequence[Dict[str, Any]],
                    answer: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The AI answer as a label (normalised), or ``(None, reason)``. Strict: the answer must
    already be in the family's label shape (``answer_schema``) and within ``allowed_answers``."""
    if not isinstance(answer, dict):
        return None, 'answer must be a JSON object'
    if family == 'screen-id':
        extra = sorted(set(answer) - {'label', 'node_id'})
        if extra:
            return None, f'unknown fields {extra}'
        text = answer.get('label')
        if not isinstance(text, str) or not text.strip():
            return None, 'screen-id answer needs a non-empty label'
        if 'node_id' in answer:
            if answer['node_id'] is not None:
                return None, 'node_id must be null (a screen not in the list) or left out'
            label = {'node_id': None, 'label': text.strip().lower()}
        else:
            match = next((e for e in screen_labels
                          if str(e.get('label', '')).strip().lower() == text.strip().lower()), None)
            if match is None:
                return None, f'screen {text!r} is not in allowed_answers'
            if not match.get('node_id'):
                return None, f'screen {text!r} has no node id in the tree'
            label = {'node_id': str(match['node_id']), 'label': str(match['label'])}
    elif family == 'av-fault' and sample.get('strip'):
        if answer not in [dict(a) for a in label_schema.STRIP_ANSWERS]:
            return None, 'a freeze strip answer must be one of allowed_answers exactly'
        label = dict(answer)
    else:
        label = answer
    problem = label_schema.validate_label(family, label)
    if problem:
        return None, problem
    return label_schema.normalize_label(family, label), None


def parse_answers(lines: Sequence[str], key: Dict[str, Any]
                  ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """``answers.jsonl`` lines -> ``({id: {label, answer, confidence, note}}, rejected)``."""
    samples = key.get('samples') or {}
    accepted: Dict[str, Dict[str, Any]] = {}
    rejected: List[Dict[str, Any]] = []
    for n, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError as e:
            rejected.append({'line': n, 'id': None, 'reason': f'not JSON: {e}'})
            continue
        if not isinstance(obj, dict):
            rejected.append({'line': n, 'id': None, 'reason': 'line is not a JSON object'})
            continue
        sid = str(obj.get('id') or '')
        if sid not in samples:
            rejected.append({'line': n, 'id': sid or None, 'reason': 'id is not in this batch'})
            continue
        if sid in accepted:
            rejected.append({'line': n, 'id': sid, 'reason': 'duplicate id (the first answer is kept)'})
            continue
        confidence = obj.get('confidence')
        if confidence not in CONFIDENCES:
            rejected.append({'line': n, 'id': sid, 'reason': f"confidence must be one of {list(CONFIDENCES)}"})
            continue
        extra = sorted(set(obj) - {'id', 'answer', 'confidence', 'note'})
        if extra:
            rejected.append({'line': n, 'id': sid, 'reason': f'unknown keys {extra}'})
            continue
        sample = samples[sid]
        label, problem = validate_answer(sample['family'], sample,
                                         _screen_entries(key, sample.get('userinterface')), obj.get('answer'))
        if problem:
            rejected.append({'line': n, 'id': sid, 'reason': problem})
            continue
        note = obj.get('note')
        accepted[sid] = {'label': label, 'answer': obj.get('answer'), 'confidence': confidence,
                         'note': str(note)[:500] if note not in (None, '') else None}
    return accepted, rejected


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def skip_reason(sample: Dict[str, Any], row: Optional[Dict[str, Any]],
                second_pass: bool = False) -> Optional[str]:
    """Why the current DB row must not be touched, or None."""
    if row is None:
        return 'row_missing'
    if row.get('label_source') == 'human':
        return 'human_label'
    if row.get('eval_version'):
        return 'frozen'
    if row.get('label_source') != sample.get('label_source') \
            or _canonical(row.get('ground_truth')) != _canonical(sample.get('ground_truth')):
        return 'changed_since_export'
    if second_pass:
        return None if second_pass_open(row) else 'already_triaged'
    if has_status(row):
        return 'already_triaged'
    return None


def decide(family: str, sample: Dict[str, Any], row: Dict[str, Any], teacher_label: Dict[str, Any],
           confidence: str, conflict: bool) -> Tuple[str, str, Optional[str]]:
    """``(action, status, reason)``. ``action``: ``triage`` (record only, the label is not
    changed) or ``apply`` (write the teacher label with ``label_source='teacher'``).

    ``conflict`` is the live conflict check (step 4j): of the row's current label when it
    has a run label, of the teacher label otherwise.

    With a run label: agree -> agreed unless the row is a confusable pair or the AI was
    unsure; disagree -> needs_human, ground truth untouched. Without one: the teacher
    label is applied; needs_human on a conflict or low confidence, else teacher_only."""
    run_label = sample.get('run_label')
    low = confidence == 'low'
    if run_label is not None:
        agrees = comparators.compare(family, run_label, teacher_label)[0]
        if not agrees:
            return 'triage', 'needs_human', 'disagrees_with_run'
        if conflict:
            return 'triage', 'needs_human', 'conflict'
        if low:
            return 'triage', 'needs_human', 'low_confidence'
        return 'triage', 'agreed', None
    if conflict:
        return 'apply', 'needs_human', 'conflict'
    if low:
        return 'apply', 'needs_human', 'low_confidence'
    return 'apply', 'teacher_only', 'no_independent_label'


def decide_second(family: str, sample: Dict[str, Any], teacher_label: Dict[str, Any],
                  confidence: str, conflict: bool) -> Tuple[str, str, Optional[str]]:
    """Second pass ``(action, status, reason)``: settle without the human, or ``excluded``.
    Only a confident answer with no confusable pair settles a row; the label is changed only
    when it becomes ``teacher_only``."""
    run_label = sample.get('run_label')
    if run_label is not None and not comparators.compare(family, run_label, teacher_label)[0]:
        return 'triage', EXCLUDED, 'disagrees_with_run'
    if conflict:
        return 'triage', EXCLUDED, 'conflict'
    if confidence == 'low':
        return 'triage', EXCLUDED, 'low_confidence'
    if run_label is not None:
        return 'triage', 'agreed', None
    return 'apply', 'teacher_only', 'no_independent_label'


def spot_check_ids(ids: Sequence[str], batch_id: str, pct: float) -> List[str]:
    """Deterministic spot-check: ``ceil(len(ids) * pct / 100)`` ids, the lowest
    ``sha256(batch_id:id)``. Same batch, same ids -> same pick."""
    ids = sorted(set(str(i) for i in ids))
    if not ids or pct <= 0:
        return []
    n = min(len(ids), math.ceil(len(ids) * pct / 100.0))
    ranked = sorted(ids, key=lambda i: hashlib.sha256(f'{batch_id}:{i}'.encode()).hexdigest())
    return sorted(ranked[:n])


def triage_record(status: str, reason: Optional[str], accepted: Dict[str, Any], model: str,
                  batch_id: str, now: str, run_agreed: Optional[bool]) -> Dict[str, Any]:
    return {
        'status': status, 'reason': reason,
        'teacher_model': model,
        'teacher_answer': accepted['answer'],
        'teacher_label': accepted['label'],
        'teacher_confidence': accepted['confidence'],
        'teacher_note': accepted.get('note'),
        'run_label_agreed': run_agreed,
        'batch_id': batch_id,
        'triaged_at': now,
    }


def plan(key: Dict[str, Any], accepted: Dict[str, Dict[str, Any]], rows: Dict[str, Optional[Dict[str, Any]]],
         conflict_for: Callable[[Dict[str, Any], Dict[str, Any]], bool], model: str, pct: float,
         now: str) -> Tuple[List[Dict[str, Any]], Counter]:
    """Decide every accepted answer (pure but for ``conflict_for(row, label)``, the read-only
    conflict check: of the row's current label when it has a run label, of the teacher label
    otherwise; never the stored ``label_conflict`` flag). Returns ``(decisions, skipped)``."""
    batch_id = key['batch_id']
    samples = key['samples']
    second_pass = bool(key.get('second_pass'))
    decisions: List[Dict[str, Any]] = []
    skipped: Counter = Counter()
    for sid in sorted(accepted):
        sample, row, acc = samples[sid], rows.get(sid), accepted[sid]
        reason = skip_reason(sample, row, second_pass)
        if reason:
            skipped[reason] += 1
            decisions.append({'id': sid, 'family': sample['family'], 'action': 'skip', 'skip': reason})
            continue
        family = sample['family']
        has_run = sample.get('run_label') is not None
        conflict = conflict_for(row, row.get('ground_truth') if has_run else acc['label'])
        if second_pass:
            action, status, why = decide_second(family, sample, acc['label'], acc['confidence'], conflict)
        else:
            action, status, why = decide(family, sample, row, acc['label'], acc['confidence'], conflict)
        run_agreed = None
        if sample.get('run_label') is not None:
            run_agreed = comparators.compare(family, sample['run_label'], acc['label'])[0]
        record = triage_record(status, why, acc, model, batch_id, now, run_agreed)
        if second_pass:
            first = triage_of(row) or {}
            record['second_pass'] = True
            if first.get('status'):
                record['first_pass'] = {k: first.get(k) for k in
                                        ('status', 'reason', 'teacher_model', 'teacher_label',
                                         'teacher_confidence', 'batch_id', 'triaged_at')}
        focus_teacher = (triage_of(row) or {}).get('focus_teacher')
        if focus_teacher:  # step 4l: keep the focus-text record of focus_text_pass.py
            record['focus_teacher'] = focus_teacher
        decisions.append({'id': sid, 'family': family, 'action': action, 'status': status, 'reason': why,
                          'label': acc['label'], 'row': row, 'triage': record})
    # Spot-check, per family: the AI labels that would otherwise count as final.
    by_family: Dict[str, List[str]] = defaultdict(list)
    for d in decisions:
        if d['action'] != 'skip' and d['status'] in FINAL_STATUSES:
            by_family[d['family']].append(d['id'])
    picked = set()
    for family, ids in by_family.items():
        picked.update(spot_check_ids(ids, f'{batch_id}:{family}', pct))
    for d in decisions:
        if d['id'] in picked:
            d['triage'].update(status='needs_human', reason='spot_check', spot_check_of=d['status'])
            d['status'], d['reason'] = 'needs_human', 'spot_check'
    return decisions, skipped


def summarize(key: Dict[str, Any], decisions: List[Dict[str, Any]], rejected: List[Dict[str, Any]],
              accepted: Dict[str, Any], skipped: Counter) -> Dict[str, Any]:
    samples = key.get('samples') or {}
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'agreed': 0, 'teacher_only': 0, 'needs_human': Counter(),
                                                          EXCLUDED: Counter(), 'rejected': 0,
                                                          'skipped': Counter(), 'unanswered': 0})
    for d in decisions:
        f = per[d['family']]
        if d['action'] == 'skip':
            f['skipped'][d['skip']] += 1
        elif d['status'] in ('needs_human', EXCLUDED):
            f[d['status']][d['reason']] += 1
        else:
            f[d['status']] += 1
    for r in rejected:
        family = (samples.get(r.get('id') or '') or {}).get('family', '?')
        per[family]['rejected'] += 1
    answered = set(accepted) | {r['id'] for r in rejected if r.get('id')}
    unanswered = sorted(set(samples) - answered)
    for sid in unanswered:
        per[samples[sid]['family']]['unanswered'] += 1
    return {
        'batch_id': key.get('batch_id'),
        'second_pass': bool(key.get('second_pass')),
        'families': {f: {**v, 'needs_human': dict(v['needs_human']), EXCLUDED: dict(v[EXCLUDED]),
                         'skipped': dict(v['skipped'])}
                     for f, v in sorted(per.items())},
        'rejected': rejected,
        'unanswered': unanswered,
        'skipped': dict(skipped),
    }


def print_summary(summary: Dict[str, Any], dry_run: bool, out=None) -> None:
    out = out or sys.stdout
    print(f"[triage_batch] batch {summary['batch_id']}{' (dry run: nothing written)' if dry_run else ''}", file=out)
    if summary.get('second_pass'):
        print("  second pass: what it cannot settle is excluded from training, never sent to a human", file=out)
    print(f"  {'family':10s} {'agreed':>7s} {'teacher-only':>13s} {'needs_human':>12s} {'excluded':>9s}  {'rejected':>8s} {'skipped':>8s} {'unanswered':>10s}", file=out)
    for family, v in summary['families'].items():
        nh = sum(v['needs_human'].values())
        print(f"  {family:10s} {v['agreed']:7d} {v['teacher_only']:13d} {nh:12d} {sum(v[EXCLUDED].values()):9d}  "
              f"{v['rejected']:8d} {sum(v['skipped'].values()):8d} {v['unanswered']:10d}", file=out)
        for status in ('needs_human', EXCLUDED):
            for reason, n in sorted(v[status].items()):
                print(f"      {status}/{reason}: {n}", file=out)
        for reason, n in sorted(v['skipped'].items()):
            print(f"      skipped/{reason}: {n}", file=out)
    for r in summary['rejected']:
        print(f"  REJECTED line {r['line']} id={r.get('id')}: {r['reason']}", file=out)
    if summary['unanswered']:
        print(f"  unanswered: {', '.join(summary['unanswered'])}", file=out)


# ---- IO: DB, storage, trees (not unit-tested; injectable) ----------------------------------

def fetch_rows(team_id: str, family: str, split: Optional[str], list_fn=None,
               second_pass: bool = False) -> List[Dict[str, Any]]:
    """Unlabelled and run-labelled rows of one team and family (and teacher rows on the
    second pass), paged through the core ``list_samples`` (which has no userinterface /
    triage / eval_version filter)."""
    sources = ['none', 'run', 'teacher'] if second_pass else ['none', 'run']
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset = 0
    while offset < MAX_ROWS:
        page, total = list_fn(team_id, family=family, split=split, label_sources=sources,
                              limit=PAGE_SIZE, offset=offset)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    return rows


def tree_screen_labels(team_id: str, userinterface: str) -> Optional[List[Dict[str, Any]]]:
    """Step 4k: ``[{'node_id', 'label'}]`` of the app's screen **groups** (Home with any tab
    focused is ``home``), sorted: the list ``score_eval.py`` prompts with. From
    ``lib/screen_group_scope`` (the whole tree hierarchy, ENTRY skipped, the core
    overrides applied). None when the app has no tree."""
    scope = _load_lib('screen_group_scope')
    return scope.screen_entries(scope.groups_for(team_id, userinterface))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def run_export(args, *, list_fn=None, screen_fn=None, storage=None, prompts=None) -> int:
    if args.family not in FAMILIES:
        raise TriageError(f"family must be one of {FAMILIES}")
    if args.limit is not None and args.limit < 1:
        raise TriageError('--limit must be >= 1')
    prompts = prompts or _load_lib('family_prompts')
    screen_fn = screen_fn or tree_screen_labels
    out = os.path.abspath(args.out)
    if os.path.exists(out) and os.listdir(out):
        raise TriageError(f'{out} exists and is not empty; pick a new --out')

    second_pass = bool(getattr(args, 'second_pass', False))
    rows = fetch_rows(args.team, args.family, args.split, list_fn=list_fn, second_pass=second_pass)
    selected, skipped = select_rows(rows, args.family, args.userinterface, args.split, None, args.include_triaged,
                                    second_pass)

    cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}
    ready = []
    for row in selected:
        screens = None
        if args.family == 'screen-id':
            ui = row.get('userinterface')
            if not ui:
                skipped['no_userinterface'] += 1
                continue
            if ui not in cache:
                cache[ui] = screen_fn(args.team, ui)
            screens = cache[ui]
            if not screens:
                skipped['no_tree_screens'] += 1
                continue
        ready.append((row, screens))
        if args.limit and len(ready) >= args.limit:
            break

    os.makedirs(os.path.join(out, 'images'), exist_ok=True)
    if storage is None:
        from shared.src.lib.utils.cloudflare_utils import get_training_storage
        storage = get_training_storage()

    batch_id = f"tri-{args.family}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    lines, key_samples = [], {}
    for row, screens in ready:
        result = storage.download_file(row['object_key'], os.path.join(out, image_rel_path(row)))
        if not result.get('success'):
            skipped['image_missing'] += 1
            print(f"[triage_batch] skip {row['id']}: image {result.get('error')}", file=sys.stderr)
            continue
        context = {'screen_labels': screen_names(screens)} if screens else None
        question = prompts.build_prompt(args.family, row, context)
        lines.append(build_line(row, question, screens, blind=args.blind))
        key_samples[str(row['id'])] = key_entry(row, priority(row, second_pass))

    with open(os.path.join(out, 'batch.jsonl'), 'w', encoding='utf-8', newline='\n') as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + '\n')
    key = {'batch_id': batch_id, 'team_id': args.team, 'family': args.family, 'created_at': _now(),
           'blind': args.blind, 'second_pass': second_pass, 'userinterface': args.userinterface, 'split': args.split,
           'screen_labels': {ui: s for ui, s in cache.items() if s}, 'samples': key_samples}
    with open(os.path.join(out, 'key.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(key, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(out, 'INSTRUCTIONS.md'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(render_instructions(batch_id, args.family, len(lines), out))
    order = Counter(k['priority'] for k in key_samples.values())
    print(json.dumps({'batch_id': batch_id, 'out': out, 'samples': len(lines), 'blind': args.blind,
                      'second_pass': second_pass,
                      'failed_verification': order.get(PRIORITY_FAILED_VERIFICATION, 0),
                      'unlabelled': order.get(PRIORITY_UNLABELLED, 0), 'run_labelled': order.get(PRIORITY_RUN, 0),
                      'skipped': dict(skipped)}, indent=2))
    return 0


def _read_key(folder: str) -> Dict[str, Any]:
    path = os.path.join(folder, 'key.json')
    if not os.path.isfile(path):
        raise TriageError(f'{path} not found (run export first)')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def run_import(args, *, get_fn=None, conflict_fn=None, apply_fn=None, set_triage_fn=None,
               column_fn=None, opted_in_fn=None, langfuse_client=None, out=None) -> int:
    out = out or sys.stdout
    folder = os.path.abspath(args.in_dir)
    key = _read_key(folder)
    if str(key.get('team_id')) != str(args.team):
        raise TriageError(f"key.json is for team {key.get('team_id')}, not --team {args.team}")
    if not (0 <= args.spot_check_pct <= 100):
        raise TriageError('--spot-check-pct must be within 0..100')
    answers_path = os.path.join(folder, 'answers.jsonl')
    if not os.path.isfile(answers_path):
        raise TriageError(f'{answers_path} not found')
    with open(answers_path, encoding='utf-8') as fh:
        accepted, rejected = parse_answers(fh.read().splitlines(), key)

    if get_fn is None or conflict_fn is None:
        from shared.src.lib.ai import training_samples
        from shared.src.lib.database import ai_training_samples_db as samples_db
        get_fn = get_fn or samples_db.get_sample

        def conflict_fn(row, label):  # the read-only check apply_label would run
            return training_samples.find_conflicts(args.team, row['family'], row['device_model'],
                                                   row.get('node_id'), row.get('focus_label'),
                                                   str(row['id']), row['dhash'], label)[0]
    rows = {sid: get_fn(sid, args.team) for sid in accepted}
    decisions, skipped = plan(key, accepted, rows, conflict_fn, args.teacher_model, args.spot_check_pct, _now())

    if args.dry_run:
        for d in decisions:
            what = d['skip'] if d['action'] == 'skip' else f"{d['status']}{'/' + d['reason'] if d['reason'] else ''}"
            print(f"  {d['id']}  {d['family']:9s} {d['action']:6s} {what}"
                  + (f"  label={json.dumps(d['label'], ensure_ascii=False)}" if d.get('label') is not None else ''),
                  file=out)
    else:
        column_fn, opted_in_fn, apply_fn, set_triage_fn = _real_writers(column_fn, opted_in_fn, apply_fn, set_triage_fn)
        if not column_fn():
            raise TriageError('the triage column is missing: apply features/ai-dataset/db/001_triage.sql first')
        if not opted_in_fn(args.team):
            raise TriageError(f'team {args.team} has not opted in to training data (TASK-27 section 9)')
        _apply(args.team, decisions, apply_fn, set_triage_fn, get_fn, skipped, conflict_fn,
               unsettled=EXCLUDED if key.get('second_pass') else 'needs_human')
        if not args.no_langfuse:
            sent = post_verdicts(decisions, args.teacher_model, client=langfuse_client)
            if sent is not None:
                print(f"[triage_batch] Langfuse: {sent} verdict_ai scores on production traces", file=out)

    summary = summarize(key, decisions, rejected, accepted, skipped)
    print_summary(summary, args.dry_run, out=out)
    if args.json:
        print(json.dumps(summary, indent=2, default=str), file=out)
    return 0


# ---- Jev first (import-jev) ----------------------------------------------------------------

JEV_MODEL = 'typesafe/jev-1.13'
JEV_MIN_CONFIDENCE = 0.8


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        raise TriageError(f'{path} not found')
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def jev_groups(bundle: str, userinterface: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """``{group node id: {'node_id', 'label'}}`` of one app, from the bundle's groups.json."""
    path = os.path.join(bundle, 'ui', userinterface or '', 'groups.json')
    if not userinterface or not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return {str(g['node_id']): {'node_id': g['node_id'], 'label': g['label']} for g in json.load(fh)}


def plan_jev(snapshots: Dict[str, Dict[str, Any]], jev: List[Dict[str, Any]],
             rows: Dict[str, Optional[Dict[str, Any]]], groups_for: Callable[[Optional[str]], Dict[str, Any]],
             conflict_for: Callable[[Dict[str, Any], Any], bool], min_confidence: float, pct: float,
             batch_id: str, now: str) -> Tuple[List[Dict[str, Any]], Counter]:
    """Decide every Jev answer (pure but for ``conflict_for``). Only a confident answer with no
    run label, or one that agrees with the run label, settles a row; the rest is skipped, which
    leaves it open for the Sonnet second pass. Returns ``(decisions, skipped)``."""
    decisions: List[Dict[str, Any]] = []
    skipped: Counter = Counter()

    def skip(sid, family, why):
        skipped[why] += 1
        decisions.append({'id': sid, 'family': family, 'action': 'skip', 'skip': why})

    for d in jev:
        sid = str(d.get('id'))
        snap, row = snapshots.get(sid) or {}, rows.get(sid)
        family = (row or {}).get('family') or 'screen-id'
        confidence = d.get('confidence')
        if not d.get('success') or confidence is None:
            skip(sid, family, 'jev_failed')
            continue
        if float(confidence) < min_confidence:
            skip(sid, family, 'below_confidence')
            continue
        if row is None:
            skip(sid, family, 'row_missing')
            continue
        if row.get('label_source') == 'human':
            skip(sid, family, 'human_label')
            continue
        if row.get('eval_version'):
            skip(sid, family, 'frozen')
            continue
        if row.get('label_source') != snap.get('label_source') \
                or _canonical(row.get('ground_truth')) != _canonical(snap.get('ground_truth')):
            skip(sid, family, 'changed_since_export')
            continue
        if not second_pass_open(row):
            skip(sid, family, 'already_triaged')
            continue
        label = groups_for(row.get('userinterface')).get(str(d.get('choice')))
        if label is None:
            skip(sid, family, 'unknown_choice')
            continue
        run_label = run_label_of(row)
        if run_label is not None and not comparators.compare(family, run_label, label)[0]:
            skip(sid, family, 'disagrees_with_run')
            continue
        if conflict_for(row, run_label if run_label is not None else label):
            skip(sid, family, 'conflict')
            continue
        first = triage_of(row) or {}
        record = {
            'status': 'teacher_only',
            'reason': 'jev_agrees_with_run' if run_label is not None else 'jev_settled',
            'teacher_model': JEV_MODEL,
            'teacher_answer': {'choice': d.get('choice')},
            'teacher_label': label,
            'teacher_confidence': 'high',
            'jev': {'confidence': float(confidence), 'probabilities': d.get('probabilities') or {},
                    'decision_id': d.get('decision_id')},
            'run_label_agreed': True if run_label is not None else None,
            'batch_id': batch_id,
            'triaged_at': now,
        }
        if first.get('status'):
            record['first_pass'] = {k: first.get(k) for k in
                                    ('status', 'reason', 'teacher_model', 'teacher_label',
                                     'teacher_confidence', 'batch_id', 'triaged_at')}
        if first.get('focus_teacher'):
            record['focus_teacher'] = first['focus_teacher']
        decisions.append({'id': sid, 'family': family, 'action': 'triage' if run_label is not None else 'apply',
                          'status': 'teacher_only', 'reason': record['reason'], 'label': label,
                          'row': row, 'triage': record})
    by_family: Dict[str, List[str]] = defaultdict(list)
    for d in decisions:
        if d['action'] != 'skip':
            by_family[d['family']].append(d['id'])
    picked = set()
    for family, ids in by_family.items():
        picked.update(spot_check_ids(ids, f'{batch_id}:{family}', pct))
    for d in decisions:
        if d['id'] in picked:
            d['triage'].update(status='needs_human', reason='spot_check', spot_check_of=d['status'])
            d['status'], d['reason'] = 'needs_human', 'spot_check'
    return decisions, skipped


def run_import_jev(args, *, get_fn=None, conflict_fn=None, apply_fn=None, set_triage_fn=None,
                   column_fn=None, opted_in_fn=None, langfuse_client=None, out=None) -> int:
    out = out or sys.stdout
    bundle = os.path.abspath(args.bundle)
    if not (0 <= args.spot_check_pct <= 100):
        raise TriageError('--spot-check-pct must be within 0..100')
    snapshots = {str(r['id']): r for r in _read_jsonl(os.path.join(bundle, 'rows.jsonl'))}
    wrong_team = sorted({str(r.get('team_id')) for r in snapshots.values()} - {str(args.team)})
    if wrong_team:
        raise TriageError(f"bundle rows belong to team {wrong_team}, not --team {args.team}")
    jev = [d for d in _read_jsonl(os.path.join(bundle, 'decisions.jsonl')) if str(d.get('id')) in snapshots]
    if get_fn is None or conflict_fn is None:
        from shared.src.lib.ai import training_samples
        from shared.src.lib.database import ai_training_samples_db as samples_db
        get_fn = get_fn or samples_db.get_sample

        def conflict_fn(row, label):  # the read-only check apply_label would run
            return training_samples.find_conflicts(args.team, row['family'], row['device_model'],
                                                   row.get('node_id'), row.get('focus_label'),
                                                   str(row['id']), row['dhash'], label)[0]
    rows = {str(d['id']): get_fn(str(d['id']), args.team) for d in jev}
    cache: Dict[str, Dict[str, Any]] = {}

    def groups_for(ui):
        if ui not in cache:
            cache[ui] = jev_groups(bundle, ui)
        return cache[ui]
    batch_id = f"jev-{os.path.basename(bundle)}"
    decisions, skipped = plan_jev(snapshots, jev, rows, groups_for, conflict_fn, args.min_confidence,
                                  args.spot_check_pct, batch_id, _now())
    if args.dry_run:
        for d in decisions:
            what = d['skip'] if d['action'] == 'skip' else f"{d['status']}/{d['reason']}"
            print(f"  {d['id']}  {d['action']:6s} {what}"
                  + (f"  label={json.dumps(d['label'], ensure_ascii=False)}" if d.get('label') is not None else ''),
                  file=out)
    else:
        column_fn, opted_in_fn, apply_fn, set_triage_fn = _real_writers(column_fn, opted_in_fn, apply_fn, set_triage_fn)
        if not column_fn():
            raise TriageError('the triage column is missing: apply features/ai-dataset/db/001_triage.sql first')
        if not opted_in_fn(args.team):
            raise TriageError(f'team {args.team} has not opted in to training data (TASK-27 section 9)')
        # A confusable pair found at write time: excluded, as on the second pass (never the human).
        _apply(args.team, decisions, apply_fn, set_triage_fn, get_fn, skipped, conflict_fn, unsettled=EXCLUDED)
        if not args.no_langfuse:
            sent = post_verdicts(decisions, JEV_MODEL, client=langfuse_client)
            if sent is not None:
                print(f"[triage_batch] Langfuse: {sent} verdict_ai scores on production traces", file=out)
    settled = Counter(d['reason'] for d in decisions if d['action'] != 'skip')
    print(f"[triage_batch] Jev bundle {batch_id}{' (dry run: nothing written)' if args.dry_run else ''}: "
          f"{len(jev)} decisions, min confidence {args.min_confidence}", file=out)
    print(f"  settled: {dict(settled)}", file=out)
    print(f"  left open for the Sonnet second pass / skipped: {dict(skipped)}", file=out)
    return 0


def _real_writers(column_fn, opted_in_fn, apply_fn, set_triage_fn):
    triage_db = _load_lib('triage_db')
    label_write = _load_lib('label_write')
    from shared.src.lib.database import ai_training_samples_db as samples_db

    def default_apply(team_id, row, label, triage_for):
        return label_write.apply_label(team_id, row, label, 'teacher',
                                       write=triage_db.teacher_label_writer(triage_for))
    return (column_fn or triage_db.column_exists, opted_in_fn or samples_db.team_opted_in,
            apply_fn or default_apply, set_triage_fn or triage_db.set_triage)


def _apply(team_id: str, decisions: List[Dict[str, Any]], apply_fn, set_triage_fn, get_fn,
           skipped: Counter, conflict_fn, unsettled: str = 'needs_human') -> None:
    """Write every decision, then the conflict sweep: a teacher label written later in the
    batch can make an earlier row a confusable pair, so a final row that now conflicts
    (``conflict_fn`` on its current label, the live check, step 4j) goes to the human too
    (``unsettled``; on the second pass it is ``excluded`` instead)."""
    for d in decisions:
        if d['action'] == 'skip':
            continue
        if d['action'] == 'triage':
            if not set_triage_fn(team_id, d['id'], d['triage']):
                d.update(action='skip', skip='write_refused')
                skipped['write_refused'] += 1
            continue
        planned = d['triage']

        def triage_for(conflict, planned=planned, d=d):
            # The write's own conflict check wins: a confusable pair always goes to the human.
            if conflict and planned.get('reason') != 'conflict':
                planned = {**planned, 'status': unsettled, 'reason': 'conflict'}
                d.update(status=unsettled, reason='conflict', triage=planned)
            return planned
        try:
            result = apply_fn(team_id, d['row'], d['label'], triage_for)
        except Exception as e:  # label_write.LabelRefused (human / frozen) or a DB error
            d.update(action='skip', skip=f"refused:{getattr(e, 'reason', 'error')}")
            skipped[d['skip']] += 1
            continue
        if not result.get('ok'):
            d.update(action='skip', skip='write_refused')
            skipped['write_refused'] += 1
    for d in decisions:
        if d['action'] == 'skip' or d['status'] not in FINAL_STATUSES:
            continue
        row = get_fn(d['id'], team_id)
        if row and conflict_fn(row, row.get('ground_truth')):
            record = {**d['triage'], 'status': unsettled, 'reason': 'conflict'}
            if set_triage_fn(team_id, d['id'], record):
                d.update(status=unsettled, reason='conflict', triage=record)


def post_verdicts(decisions: List[Dict[str, Any]], teacher_model: str, client=None) -> Optional[int]:
    """2026-10-04: a ``verdict_ai`` score on the Langfuse trace of every decided row
    (``VERDICT_STATUSES``, after the write and the conflict sweep) that came from a real AI
    call (``source_ref.trace_id``): its model answer against the teacher label, under the
    family comparator (``lib/langfuse_scores``). None when there is nothing to send or
    tracing is off; never raises."""
    todo = [d for d in decisions if d.get('action') != 'skip' and d.get('status') in VERDICT_STATUSES
            and langfuse_scores.trace_id_of(d.get('row'))]
    if not todo:
        return None
    client = client or langfuse_scores.get_client()
    if client is None:
        return None
    sent = 0
    for d in todo:
        comment = langfuse_scores.ai_comment(teacher_model, d['label'], d['status'])
        if langfuse_scores.score_verdict(d['row'], d['label'], langfuse_scores.SCORE_AI, comment, client=client):
            sent += 1
    langfuse_scores.flush(client)
    return sent


# ---- CLI -----------------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='TASK-27 step 4i: AI (teacher) triage batches.')
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export', help='select rows, download images, write batch.jsonl + key.json + INSTRUCTIONS.md')
    exp.add_argument('--team', required=True, help='team_id (uuid); every query filters by it')
    exp.add_argument('--family', required=True, choices=FAMILIES)
    exp.add_argument('--userinterface', default=None, help='only rows of this userinterface')
    exp.add_argument('--split', default=None, choices=('train', 'eval', 'holdout'))
    exp.add_argument('--limit', type=int, default=None, help='at most N samples')
    exp.add_argument('--out', required=True, help='empty or new folder for the batch')
    blind = exp.add_mutually_exclusive_group()
    blind.add_argument('--blind', dest='blind', action='store_true', default=True,
                       help='default: the run label stays in key.json only')
    blind.add_argument('--no-blind', dest='blind', action='store_false',
                       help='also put run_label in batch.jsonl (debugging only, never for a real batch)')
    exp.add_argument('--include-triaged', action='store_true', help='also rows that already have a triage record')
    exp.add_argument('--second-pass', action='store_true',
                     help="the rows the AI could not settle (needs_human: disagrees_with_run / conflict / "
                          "low_confidence) and the untriaged ones; the import settles or excludes them, "
                          "never sends them to a human")
    imp = sub.add_parser('import', help='validate answers.jsonl, decide triage, apply labels')
    imp.add_argument('--team', required=True)
    imp.add_argument('--in', dest='in_dir', required=True, help='the batch folder (key.json, answers.jsonl)')
    imp.add_argument('--teacher-model', default=DEFAULT_MODEL, help='the AI that answered, recorded per row')
    imp.add_argument('--spot-check-pct', type=float, default=DEFAULT_SPOT_CHECK_PCT)
    imp.add_argument('--dry-run', action='store_true', help='decide and print; no DB write')
    imp.add_argument('--json', action='store_true', help='also print the summary as JSON')
    imp.add_argument('--no-langfuse', action='store_true',
                     help='do not post verdict_ai scores on the Langfuse traces of the decided rows')
    jev = sub.add_parser('import-jev', help='settle open rows from a scripts/jev_review bundle (Jev first)')
    jev.add_argument('--team', required=True)
    jev.add_argument('--bundle', required=True, help='jev_review bundle (rows.jsonl, decisions.jsonl, ui/)')
    jev.add_argument('--min-confidence', type=float, default=JEV_MIN_CONFIDENCE,
                     help='a Jev answer below this stays open for the Sonnet second pass')
    jev.add_argument('--spot-check-pct', type=float, default=DEFAULT_SPOT_CHECK_PCT)
    jev.add_argument('--dry-run', action='store_true', help='decide and print; no DB write')
    jev.add_argument('--no-langfuse', action='store_true',
                     help='do not post verdict_ai scores on the Langfuse traces of the settled rows')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.command == 'export':
            return run_export(args)
        return run_import_jev(args) if args.command == 'import-jev' else run_import(args)
    except TriageError as e:
        print(f'[triage_batch] REFUSED: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
