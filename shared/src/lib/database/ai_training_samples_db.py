"""
AI Training Samples Database Operations (TASK-27)

Index rows for the vision-model training dataset. Images live in the training
bucket (``get_training_storage()``); this table owns dedup, split and labels.
Every query filters by ``team_id``.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'ai_training_samples'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _json_field(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def _eq_or_null(query, column: str, value):
    """Group keys may be NULL (no node / no focus): match NULL with IS NULL, not = NULL."""
    return query.is_(column, 'null') if value is None else query.eq(column, value)


def insert_sample(row: Dict[str, Any]) -> Optional[str]:
    """Insert one sample row. ``row`` must carry ``team_id``. Returns the id or None."""
    if not row.get('team_id'):
        print("[@db:ai_training_samples:insert_sample] refused: no team_id")
        return None
    try:
        result = get_supabase().table(TABLE).insert(row).execute()
        if result.data:
            return str(result.data[0]['id'])
        return None
    except Exception as e:
        print(f"[@db:ai_training_samples:insert_sample] Error: {e}")
        return None


def get_group(team_id: str, family: str, device_model: str, node_id: Optional[str],
              focus_label: Optional[str]) -> List[Tuple[str, str, Any, bool]]:
    """All samples in a dedup group, as ``[(id, dhash, ground_truth, is_failure)]``."""
    try:
        query = (get_supabase().table(TABLE)
                 .select('id, dhash, ground_truth, is_failure')
                 .eq('team_id', team_id)
                 .eq('family', family)
                 .eq('device_model', device_model))
        query = _eq_or_null(query, 'node_id', node_id)
        query = _eq_or_null(query, 'focus_label', focus_label)
        result = query.execute()
        return [(str(r['id']), r['dhash'], _json_field(r.get('ground_truth')), bool(r.get('is_failure')))
                for r in (result.data or [])]
    except Exception as e:
        print(f"[@db:ai_training_samples:get_group] Error: {e}")
        return []


def get_labelled_hashes(team_id: str, family: str, device_model: str,
                        limit: int = 2000) -> List[Tuple[str, str, Any]]:
    """Labelled rows of one ``(team_id, family, device_model)``, newest first, capped at
    ``limit``, as ``[(id, dhash, ground_truth)]``. Used for the step-4d cross-node
    conflict check (look-alike screens under different nodes)."""
    try:
        result = (get_supabase().table(TABLE)
                  .select('id, dhash, ground_truth')
                  .eq('team_id', team_id)
                  .eq('family', family)
                  .eq('device_model', device_model)
                  .not_.is_('ground_truth', 'null')
                  .order('created_at', desc=True)
                  .limit(limit)
                  .execute())
        return [(str(r['id']), r['dhash'], _json_field(r.get('ground_truth')))
                for r in (result.data or [])]
    except Exception as e:
        print(f"[@db:ai_training_samples:get_labelled_hashes] Error: {e}")
        return []


def set_label_conflict(team_id: str, sample_ids: List[str], value: bool = True) -> int:
    """Set ``label_conflict`` (true by default, false to clear a stale flag) on these rows
    of this team. Returns the rows updated.

    Allowed on frozen eval rows: the freeze trigger guards ``ground_truth`` and ``split`` only."""
    ids = [str(i) for i in (sample_ids or []) if i]
    if not team_id or not ids:
        return 0
    try:
        result = (get_supabase().table(TABLE).update({'label_conflict': bool(value)})
                  .eq('team_id', team_id).in_('id', ids).execute())
        return len(result.data or [])
    except Exception as e:
        print(f"[@db:ai_training_samples:set_label_conflict] Error: {e}")
        return 0


def get_sample(sample_id: str, team_id: str) -> Optional[Dict[str, Any]]:
    """One sample row, or None."""
    try:
        result = (get_supabase().table(TABLE).select('*')
                  .eq('id', sample_id).eq('team_id', team_id).limit(1).execute())
        if not result.data:
            return None
        row = result.data[0]
        row['id'] = str(row['id'])
        for key in ('model_answer', 'ground_truth', 'boxes', 'source_ref'):
            row[key] = _json_field(row.get(key))
        return row
    except Exception as e:
        print(f"[@db:ai_training_samples:get_sample] Error: {e}")
        return None


def update_label(sample_id: str, team_id: str, ground_truth: Any, label_source: str,
                 is_failure: bool, label_conflict: bool) -> bool:
    """Set the label fields of one sample. The DB trigger refuses this on frozen (eval) rows."""
    try:
        result = (get_supabase().table(TABLE)
                  .update({'ground_truth': ground_truth, 'label_source': label_source,
                           'is_failure': bool(is_failure), 'label_conflict': bool(label_conflict)})
                  .eq('id', sample_id).eq('team_id', team_id).execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@db:ai_training_samples:update_label] Error: {e}")
        return False


def get_offtree_labels(team_id: str, family: str = 'screen-id', limit: int = 2000) -> List[str]:
    """Distinct labels humans gave to screens not in the tree (TASK-27 step 4f):
    ``ground_truth = {'node_id': null, 'label': ...}`` with ``label_source='human'``,
    newest ``limit`` rows scanned. Trimmed, lowercased, sorted."""
    if not team_id:
        return []
    try:
        result = (get_supabase().table(TABLE)
                  .select('ground_truth')
                  .eq('team_id', team_id)
                  .eq('family', family)
                  .eq('label_source', 'human')
                  .contains('ground_truth', {'node_id': None})
                  .order('created_at', desc=True)
                  .limit(limit)
                  .execute())
        labels = set()
        for r in result.data or []:
            truth = _json_field(r.get('ground_truth'))
            if isinstance(truth, dict) and truth.get('node_id') is None:
                text = str(truth.get('label') or '').strip().lower()
                if text:
                    labels.add(text)
        return sorted(labels)
    except Exception as e:
        print(f"[@db:ai_training_samples:get_offtree_labels] Error: {e}")
        return []


def get_samples_by_source_ref(team_id: str, key: str, value: Any) -> List[Dict[str, Any]]:
    """Samples whose ``source_ref`` JSON has ``key == value`` (e.g. ``alert_id``)."""
    try:
        result = (get_supabase().table(TABLE).select('*')
                  .eq('team_id', team_id)
                  .contains('source_ref', {key: value})
                  .execute())
        rows = result.data or []
        for row in rows:
            row['id'] = str(row['id'])
            for k in ('model_answer', 'ground_truth', 'boxes', 'source_ref'):
                row[k] = _json_field(row.get(k))
        return rows
    except Exception as e:
        print(f"[@db:ai_training_samples:get_samples_by_source_ref] Error: {e}")
        return []


def team_opted_in(team_id: str) -> bool:
    """True only when the team row exists and ``training_data_opt_in`` is true. Fails closed."""
    if not team_id:
        return False
    try:
        result = (get_supabase().table('teams').select('training_data_opt_in')
                  .eq('id', team_id).limit(1).execute())
        return bool(result.data) and result.data[0].get('training_data_opt_in') is True
    except Exception as e:
        print(f"[@db:ai_training_samples:team_opted_in] Error: {e}")
        return False


# ---- review / eval freeze (TASK-27 step 4) ---------------------------------------------

def _parse_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row['id'] = str(row['id'])
    for key in ('model_answer', 'ground_truth', 'boxes', 'source_ref'):
        row[key] = _json_field(row.get(key))
    return row


def list_samples(team_id: str, family: Optional[str] = None, split: Optional[str] = None,
                 label_sources: Optional[List[str]] = None, is_failure: Optional[bool] = None,
                 device_model: Optional[str] = None, limit: int = 50,
                 offset: int = 0,
                 label_conflict: Optional[bool] = None) -> Tuple[List[Dict[str, Any]], int]:
    """One page of samples for review, hardest first
    (``is_failure desc, label_conflict desc, created_at desc``).

    Returns ``(rows, total)`` where ``total`` counts every row matching the filters.
    """
    try:
        query = get_supabase().table(TABLE).select('*', count='exact').eq('team_id', team_id)
        if family:
            query = query.eq('family', family)
        if split:
            query = query.eq('split', split)
        if label_sources:
            query = query.in_('label_source', list(label_sources))
        if is_failure is not None:
            query = query.eq('is_failure', bool(is_failure))
        if device_model:
            query = query.eq('device_model', device_model)
        if label_conflict is not None:
            query = query.eq('label_conflict', bool(label_conflict))
        result = (query.order('is_failure', desc=True)
                  .order('label_conflict', desc=True)
                  .order('created_at', desc=True)
                  .range(offset, offset + limit - 1)
                  .execute())
        rows = [_parse_row(r) for r in (result.data or [])]
        total = result.count if result.count is not None else len(rows)
        return rows, total
    except Exception as e:
        print(f"[@db:ai_training_samples:list_samples] Error: {e}")
        return [], 0


def count_freeze_candidates(team_id: str, family: str) -> int:
    """Rows ``freeze_eval`` would take: ``split='eval'``, ``label_source='human'``, not yet frozen."""
    try:
        result = (get_supabase().table(TABLE).select('id', count='exact')
                  .eq('team_id', team_id).eq('family', family)
                  .eq('split', 'eval').eq('label_source', 'human')
                  .is_('eval_version', 'null')
                  .limit(1).execute())
        return int(result.count or 0)
    except Exception as e:
        print(f"[@db:ai_training_samples:count_freeze_candidates] Error: {e}")
        return 0


def eval_version_exists(team_id: str, family: str, version: str) -> bool:
    """True when any row of this team and family already carries ``eval_version``."""
    try:
        result = (get_supabase().table(TABLE).select('id')
                  .eq('team_id', team_id).eq('family', family)
                  .eq('eval_version', version).limit(1).execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@db:ai_training_samples:eval_version_exists] Error: {e}")
        return False


def freeze_eval(team_id: str, family: str, version: str) -> int:
    """Set ``eval_version`` on every freeze candidate of this team and family.

    Returns the number of rows frozen. After this the DB trigger refuses any change
    to their ``ground_truth`` or ``split``.
    """
    try:
        result = (get_supabase().table(TABLE).update({'eval_version': version})
                  .eq('team_id', team_id).eq('family', family)
                  .eq('split', 'eval').eq('label_source', 'human')
                  .is_('eval_version', 'null').execute())
        return len(result.data or [])
    except Exception as e:
        print(f"[@db:ai_training_samples:freeze_eval] Error: {e}")
        return 0


def list_for_report(team_id: Optional[str], all_teams: bool = False, limit: int = 20000,
                    since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Light columns of the team's samples (newest first) for the AI usage page's training panel."""
    rows: List[Dict[str, Any]] = []
    offset, page = 0, 1000
    while len(rows) < limit:
        query = (get_supabase().table(TABLE)
                 .select('id, family, device_model, label_source, is_failure, label_conflict, source_ref')
                 .order('created_at', desc=True))
        if not all_teams:
            query = query.eq('team_id', team_id)
        if since:
            query = query.gte('created_at', since)
        batch = query.range(offset, offset + page - 1).execute().data or []
        rows.extend(_parse_row(r) if 'source_ref' in r else r for r in batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def count_opted_in_teams() -> int:
    """Teams that agreed to their frames entering the training dataset (platform-wide, a count only)."""
    result = get_supabase().table('teams').select('id', count='exact').eq('training_data_opt_in', True).execute()
    return int(result.count or 0)
