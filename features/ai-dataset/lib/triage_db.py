"""Feature-local DB access for the step 4i AI triage (TASK-27).

The ``triage`` JSONB column is added by the feature's own migration
(``features/ai-dataset/db/001_triage.sql``); core never reads or writes it. Every query
here filters by ``team_id``. Writes that come from the teacher are guarded in the same
statement: never on a ``human`` row, never on a frozen (``eval_version``) row.

Triage record (``TRIAGE_STATUSES`` / ``TRIAGE_REASONS`` are the vocabulary the migration's
CHECK allows)::

    {"status": "agreed" | "needs_human" | "teacher_only" | "resolved" | "excluded",
     "reason": null | "disagrees_with_run" | "conflict" | "low_confidence"
               | "spot_check" | "no_independent_label" | "focus_low_confidence",
     "reasons": [...]  (step 4l: a later reason appended to a needs_human row),
     "focus_teacher": {...}  (step 4l, scripts/focus_text_pass.py; alone = not triaged),
     "teacher_model", "teacher_answer", "teacher_label", "teacher_confidence",
     "teacher_note", "batch_id", "triaged_at",
     "second_pass", "first_pass": {...}  (a second-pass import; excluded = it could not settle the row),
     "prior_status", "prior_reason", "resolved_at", "human_agreed_with_teacher"}
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.src.lib.database import ai_training_samples_db as samples_db

TRIAGE_STATUSES = ('agreed', 'needs_human', 'teacher_only', 'resolved', 'excluded')  # excluded: 002_triage_excluded.sql
TRIAGE_REASONS = ('disagrees_with_run', 'conflict', 'low_confidence', 'spot_check',
                  'no_independent_label', 'focus_low_confidence')
# "Needs you" order: the cases where the AI and the run disagree first, spot-checks last.
NEEDS_HUMAN_ORDER = {'disagrees_with_run': 0, 'conflict': 1, 'low_confidence': 2, 'focus_low_confidence': 3,
                     'spot_check': 9}
NEEDS_HUMAN_POOL = 2000
STATUS_PATH = 'triage->>status'
# An agreed row counts as AI-verified only while it is not a confusable pair: a conflict can
# be flagged after the triage (a later label write or a new near-identical capture), and the
# rule sends every confusable pair to a human.
AGREED_CLEAN = f'and({STATUS_PATH}.eq.agreed,label_conflict.is.false)'
AGREED_CONFLICT = f'and({STATUS_PATH}.eq.agreed,label_conflict.is.true)'


def _table():
    return samples_db.get_supabase().table(samples_db.TABLE)


def triage_of(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The row's triage record as a dict, or None (column absent, null, or bad JSON)."""
    value = (row or {}).get('triage')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def column_exists() -> bool:
    """True when the ``triage`` column is there (``001_triage.sql`` applied)."""
    try:
        _table().select('triage').limit(1).execute()
        return True
    except Exception as e:
        print(f"[@ai-dataset:triage_db:column_exists] {e}")
        return False


def _guarded_update(team_id: str, sample_id: str, fields: Dict[str, Any]) -> bool:
    try:
        result = (_table().update(fields)
                  .eq('id', str(sample_id)).eq('team_id', team_id)
                  .neq('label_source', 'human')
                  .is_('eval_version', 'null')
                  .execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:update] {sample_id}: {e}")
        return False


def set_triage(team_id: str, sample_id: str, triage: Dict[str, Any]) -> bool:
    """Record a teacher triage on a row whose label is not changed (agreed, disagreement,
    spot-check). Refused on a human or frozen row."""
    return _guarded_update(team_id, sample_id, {'triage': triage})


def teacher_label_writer(triage_for: Callable[[bool], Dict[str, Any]]):
    """A ``label_write.apply_label`` writer that stores the teacher label and its triage
    record in one statement, refused on a human or frozen row. ``triage_for(conflict)``
    builds the record once the conflict check is known."""
    def write(sample_id: str, team_id: str, ground_truth: Any, label_source: str,
              is_failure: bool, label_conflict: bool) -> bool:
        return _guarded_update(team_id, sample_id, {
            'ground_truth': ground_truth, 'label_source': label_source,
            'is_failure': bool(is_failure), 'label_conflict': bool(label_conflict),
            'triage': triage_for(bool(label_conflict)),
        })
    return write


def regroup_write(team_id: str, sample_id: str, fields: Dict[str, Any], label_source: Optional[str]) -> bool:
    """Step 4k (``scripts/regroup_screen_labels.py``): rewrite a row's label and/or triage
    in the group form. Guarded in the same statement: never a frozen row, and only while the
    row still has the ``label_source`` it was read with (a label written in between wins)."""
    try:
        query = (_table().update(fields)
                 .eq('id', str(sample_id)).eq('team_id', team_id)
                 .is_('eval_version', 'null'))
        query = query.is_('label_source', 'null') if label_source is None else query.eq('label_source', label_source)
        return bool(query.execute().data)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:regroup_write] {sample_id}: {e}")
        return False


def resolve_triage(team_id: str, sample_id: str, triage: Dict[str, Any]) -> bool:
    """After a human answer (the row is now ``human``): store the resolved record."""
    try:
        result = (_table().update({'triage': triage})
                  .eq('id', str(sample_id)).eq('team_id', team_id).execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:resolve_triage] {sample_id}: {e}")
        return False


def needs_human_reason(row: Dict[str, Any]) -> Optional[str]:
    """Why a row is in "Needs you": its triage reason, or ``conflict`` for an agreed row that
    became a confusable pair after the triage. None when it does not need a human. Pure."""
    triage = triage_of(row) or {}
    if triage.get('status') == 'needs_human':
        return triage.get('reason')
    if triage.get('status') == 'agreed' and row.get('label_conflict'):
        return 'conflict'
    return None


def order_needs_human(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Disagreements, conflicts and low confidence first, spot-checks last; newest first
    within a reason. Pure."""
    ordered = sorted(rows, key=lambda r: str(r.get('created_at') or ''), reverse=True)
    return sorted(ordered, key=lambda r: NEEDS_HUMAN_ORDER.get(needs_human_reason(r), 5))


def list_needs_human(team_id: str, family: Optional[str] = None, split: Optional[str] = None,
                     device_model: Optional[str] = None, limit: int = 50,
                     offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """The "Needs you" view: rows with ``triage.status = needs_human``, plus agreed rows that
    became a confusable pair after the triage, not frozen, in ``order_needs_human`` order.
    Returns ``(page, total)``."""
    try:
        query = (_table().select('*').eq('team_id', team_id)
                 .or_(f'{STATUS_PATH}.eq.needs_human,{AGREED_CONFLICT}').is_('eval_version', 'null'))
        if family:
            query = query.eq('family', family)
        if split:
            query = query.eq('split', split)
        if device_model:
            query = query.eq('device_model', device_model)
        result = query.order('created_at', desc=True).limit(NEEDS_HUMAN_POOL).execute()
        rows = [samples_db._parse_row(r) for r in (result.data or [])]
        for r in rows:
            r['triage'] = triage_of(r)
        ordered = order_needs_human(rows)
        return ordered[offset:offset + limit], len(ordered)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:list_needs_human] {e}")
        return [], 0


def _ai_candidates(query):
    return (query.eq('split', 'eval').is_('eval_version', 'null')
            .or_(f'label_source.eq.human,{AGREED_CLEAN}'))


def count_agreed_eval(team_id: str, family: str) -> int:
    """Eval rows not frozen whose run label the AI teacher agreed with (AI-verified), and
    that are not a confusable pair."""
    try:
        result = (_table().select('id', count='exact')
                  .eq('team_id', team_id).eq('family', family)
                  .eq('split', 'eval').is_('eval_version', 'null')
                  .eq(STATUS_PATH, 'agreed').neq('label_source', 'human')
                  .eq('label_conflict', False)
                  .limit(1).execute())
        return int(result.count or 0)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:count_agreed_eval] {e}")
        return 0


def count_ai_freeze_candidates(team_id: str, family: str) -> int:
    """Rows an ``eval-vN-ai`` freeze would take: eval, not frozen, human, or agreed and not a
    confusable pair."""
    try:
        result = _ai_candidates(_table().select('id', count='exact')
                                .eq('team_id', team_id).eq('family', family)).limit(1).execute()
        return int(result.count or 0)
    except Exception as e:
        print(f"[@ai-dataset:triage_db:count_ai_freeze_candidates] {e}")
        return 0


def freeze_ai_eval(team_id: str, family: str, version: str) -> int:
    """Set ``eval_version`` on every ``eval-vN-ai`` candidate of this team and family."""
    try:
        result = _ai_candidates(_table().update({'eval_version': version})
                                .eq('team_id', team_id).eq('family', family)).execute()
        return len(result.data or [])
    except Exception as e:
        print(f"[@ai-dataset:triage_db:freeze_ai_eval] {e}")
        return 0
