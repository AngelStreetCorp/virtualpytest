"""Localize corrections (TASK-104 goal 11, TASK-88 row 12): "Wrong screen?" fixes the matcher.

- The operator names the true node -> the live fingerprint becomes an extra sample on that node
  (``navigation_nodes.data.fingerprint.extra``); ImageHelpers.identify_screen matches it like the
  node's own fingerprint on the next run.
- The operator says "Unknown screen" -> the live fingerprint becomes a negative on the node that
  wrongly claimed the frame (``data.fingerprint.negatives``); that node stops claiming it.
- Every correction is a ``localize_verdicts`` row; each sample / negative carries its row id, so
  ``undo`` removes exactly what the row added.

Every query filters by ``team_id``. The list edits are pure functions, unit-tested.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'localize_verdicts'
MAX_EXTRA_SAMPLES = 8          # matches ImageHelpers.FP_MAX_EXTRA_SAMPLES
MAX_NEGATIVES = 16
SAMPLE_KEYS = ('v', 'dhash', 'regions', 'crop', 'focus')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample(live_fp: Dict[str, Any], verdict_id: str) -> Dict[str, Any]:
    out = {k: live_fp[k] for k in SAMPLE_KEYS if k in live_fp}
    out.update({'verdict_id': verdict_id, 'added_at': _now()})
    return out


def add_sample(fp: Dict[str, Any], live_fp: Dict[str, Any], verdict_id: str) -> Dict[str, Any]:
    """`fp` with the live fingerprint appended to `extra` (oldest dropped past MAX_EXTRA_SAMPLES)."""
    extra = list(fp.get('extra') or []) + [_sample(live_fp, verdict_id)]
    return {**fp, 'extra': extra[-MAX_EXTRA_SAMPLES:]}


def add_negative(fp: Dict[str, Any], live_fp: Dict[str, Any], verdict_id: str) -> Dict[str, Any]:
    negatives = list(fp.get('negatives') or []) + [_sample(live_fp, verdict_id)]
    return {**fp, 'negatives': negatives[-MAX_NEGATIVES:]}


def remove_verdict(fp: Dict[str, Any], verdict_id: str) -> Dict[str, Any]:
    """`fp` without any sample or negative this verdict added."""
    out = dict(fp)
    for key in ('extra', 'negatives'):
        if key in out:
            out[key] = [s for s in (out[key] or []) if not (isinstance(s, dict) and s.get('verdict_id') == verdict_id)]
    return out


def rebuild_corrections(fp: Dict[str, Any], verdict_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`fp` with its operator samples / negatives rebuilt from the ACTIVE audit rows of its node
    (TASK-107 goal 2). The audit table is the source of truth: a recaptured fingerprint (no
    `extra`) gets them back, an undone row stays gone, and a fingerprint that already carries
    them comes out unchanged. Entries without a verdict_id are kept as they are."""
    out = dict(fp)
    rows = sorted((r for r in verdict_rows if not r.get('undone_at') and r.get('live_fingerprint')),
                  key=lambda r: r.get('created_at') or '')
    for key, action, cap in (('extra', 'add_sample', MAX_EXTRA_SAMPLES), ('negatives', 'negative', MAX_NEGATIVES)):
        kept = [s for s in (out.get(key) or []) if not (isinstance(s, dict) and s.get('verdict_id'))]
        added = [{**_sample(r['live_fingerprint'], r['id']), 'added_at': r.get('created_at') or _now()}
                 for r in rows if r.get('action') == action]
        merged = (kept + added)[-cap:]
        if merged:
            out[key] = merged
        else:
            out.pop(key, None)
    return out


def _correction_target(row: Dict[str, Any]) -> Optional[str]:
    return row.get('true_node_id') if row.get('action') == 'add_sample' else row.get('wrong_node_id')


def carry_corrections(team_id: str, tree_id: str, nodes: List[Dict[str, Any]]) -> int:
    """Re-apply this tree's active corrections to every node about to be saved with a fingerprint
    (save_node / save_nodes_batch). Mutates `nodes`; returns how many fingerprints changed.
    One query per call; nothing is read when no node carries a fingerprint."""
    with_fp = [n for n in nodes if ((n.get('data') or {}).get('fingerprint') or {}).get('dhash')]
    if not with_fp or not tree_id:
        return 0
    db = get_supabase_client()
    res = (db.table(TABLE).select('id, action, wrong_node_id, true_node_id, live_fingerprint, created_at, undone_at')
           .eq('team_id', team_id).is_('undone_at', 'null').contains('tree_ids', [tree_id]).execute())
    by_node: Dict[str, List[Dict[str, Any]]] = {}
    for r in res.data or []:
        by_node.setdefault(_correction_target(r), []).append(r)
    changed = 0
    for n in with_fp:
        fp = n['data']['fingerprint']
        had = bool(fp.get('extra') or fp.get('negatives'))
        rows = by_node.get(n.get('node_id'), [])
        if not rows and not had:
            continue
        new = rebuild_corrections(fp, rows)
        if new != fp:
            n['data'] = {**n['data'], 'fingerprint': new}
            changed += 1
    return changed


def _tree_ids(db, team_id: str, userinterface_name: str) -> List[str]:
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    ui = get_userinterface_by_name(userinterface_name, team_id)
    if not ui or not ui.get('id'):
        return []
    res = (db.table('navigation_trees').select('id').eq('userinterface_id', ui['id'])
           .eq('team_id', team_id).execute())
    return [r['id'] for r in (res.data or [])]


def _node_rows(db, team_id: str, tree_ids: List[str], node_id: str) -> List[Dict[str, Any]]:
    """Every row of `node_id` in the interface's trees (a subtree repeats its parent as a reference row)."""
    if not tree_ids or not node_id:
        return []
    res = (db.table('navigation_nodes').select('id, tree_id, node_id, label, data').eq('team_id', team_id)
           .eq('node_id', node_id).in_('tree_id', tree_ids).execute())
    return res.data or []


def _write_fingerprint(db, team_id: str, row: Dict[str, Any], fp: Dict[str, Any]) -> None:
    data = dict(row.get('data') or {})
    data['fingerprint'] = fp
    db.table('navigation_nodes').update({'data': data}).eq('id', row['id']).eq('team_id', team_id).execute()


def record_correction(team_id: str, userinterface_name: str, live_fp: Dict[str, Any], *,
                      wrong_node_id: Optional[str], true_node_id: Optional[str],
                      frame_url: Optional[str] = None, host_name: Optional[str] = None,
                      device_id: Optional[str] = None, created_by: Optional[str] = None) -> Dict[str, Any]:
    """Apply one "Wrong screen?" answer and audit it. Returns {success, id, action, node_id, label,
    tree_ids} or {success: False, error}."""
    if not live_fp or not live_fp.get('regions'):
        return {'success': False, 'error': 'live_fingerprint with regions is required'}
    action = 'add_sample' if true_node_id else 'negative'
    target = true_node_id or wrong_node_id
    if not target:
        return {'success': False, 'error': 'Unknown screen needs the node that claimed the frame (wrong_node_id)'}
    db = get_supabase_client()
    tree_ids = _tree_ids(db, team_id, userinterface_name)
    rows = _node_rows(db, team_id, tree_ids, target)
    rows = [r for r in rows if ((r.get('data') or {}).get('fingerprint') or {}).get('dhash')]
    if not rows:
        return {'success': False, 'error': f'node {target} has no stored fingerprint in {userinterface_name}'}
    labels = {r['node_id']: r.get('label') for r in rows}
    wrong_label = None
    if wrong_node_id:
        wrong_rows = rows if wrong_node_id == target else _node_rows(db, team_id, tree_ids, wrong_node_id)
        wrong_label = wrong_rows[0].get('label') if wrong_rows else None
    ins = db.table(TABLE).insert({
        'team_id': team_id, 'userinterface_name': userinterface_name, 'host_name': host_name,
        'device_id': device_id, 'frame_url': frame_url, 'live_fingerprint': live_fp, 'action': action,
        'wrong_node_id': wrong_node_id, 'wrong_node_label': wrong_label,
        'true_node_id': true_node_id, 'true_node_label': labels.get(true_node_id) if true_node_id else None,
        'node_row_ids': [r['id'] for r in rows], 'tree_ids': sorted({r['tree_id'] for r in rows}),
        'created_by': created_by,
    }).execute()
    if not ins.data:
        return {'success': False, 'error': 'could not record the correction'}
    vid = ins.data[0]['id']
    edit = add_sample if action == 'add_sample' else add_negative
    for r in rows:
        _write_fingerprint(db, team_id, r, edit((r.get('data') or {}).get('fingerprint') or {}, live_fp, vid))
    return {'success': True, 'id': vid, 'action': action, 'node_id': target, 'label': labels.get(target),
            'tree_ids': sorted({r['tree_id'] for r in rows})}


def undo(team_id: str, verdict_id: str, undone_by: Optional[str] = None) -> Dict[str, Any]:
    """Remove what verdict `verdict_id` added and mark it undone. {success, tree_ids} or {success: False, error}."""
    db = get_supabase_client()
    res = db.table(TABLE).select('*').eq('id', verdict_id).eq('team_id', team_id).limit(1).execute()
    if not res.data:
        return {'success': False, 'error': 'correction not found'}
    row = res.data[0]
    if row.get('undone_at'):
        return {'success': False, 'error': 'already undone'}
    ids = row.get('node_row_ids') or []
    nodes = (db.table('navigation_nodes').select('id, tree_id, data').eq('team_id', team_id)
             .in_('id', ids).execute().data or []) if ids else []
    for n in nodes:
        _write_fingerprint(db, team_id, n, remove_verdict((n.get('data') or {}).get('fingerprint') or {}, verdict_id))
    db.table(TABLE).update({'undone_at': _now(), 'undone_by': undone_by}).eq('id', verdict_id) \
        .eq('team_id', team_id).execute()
    return {'success': True, 'id': verdict_id, 'action': row.get('action'),
            'tree_ids': row.get('tree_ids') or sorted({n['tree_id'] for n in nodes})}
