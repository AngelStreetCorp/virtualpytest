"""Localize coverage audit (TASK-107 goal 3): per userinterface, how much of the tree Localize can name.

For each userinterface (dev mode): screen nodes, how many carry a fingerprint (pixels) and a device
identity (android activity / web URL, TASK-107 goal 4), the live node (the node named `live`), the fingerprint
age, and the active "Wrong screen?" corrections. Read by `GET /server/navigation/localize/coverage`,
the Localize Coverage page and the MCP `localize_coverage` tool.

A node counts once per interface (a subtree repeats its parent as a reference row). Screen nodes
are every node that is not an `entry` or `action` node. Every query filters by ``team_id``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from shared.src.lib.database.in_filter import chunked_in
from shared.src.lib.utils.localize_verdict import is_live_node
from shared.src.lib.utils.supabase_utils import get_supabase_client

NOT_SCREENS = ('entry', 'action')
# Interfaces whose nodes also carry a device identity (android activity / web URL); same list as scripts/localize/audit.py
IDENTITY_MODELS = ('android_mobile', 'android_tablet', 'web', 'host_vnc')
STALE_DAYS = 90
SCREENS_TO_FIX_MAX = 100
NODE_SELECT = ('node_id, tree_id, node_type, label, updated_at, '
               'dhash:data->fingerprint->>dhash, captured_at:data->fingerprint->>captured_at, '
               'identity:data->fingerprint->identity->>kind, shot_ts:data->>screenshot_timestamp')


def _parse_ts(value: Any) -> Optional[datetime]:
    """An ISO string or an epoch (s or ms) -> aware datetime; None when unreadable."""
    if value in (None, ''):
        return None
    try:
        num = float(value)
        return datetime.fromtimestamp(num / 1000.0 if num > 1e11 else num, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fingerprint_time(node: Dict[str, Any]) -> Optional[datetime]:
    """When the node's fingerprint was taken: its own `captured_at`, else the screenshot time, else
    the row's last save (an upper bound: a fingerprint is never newer than the row that holds it)."""
    for key in ('captured_at', 'shot_ts', 'updated_at'):
        dt = _parse_ts(node.get(key))
        if dt:
            return dt
    return None


def screens_to_fix(rows: List[Dict[str, Any]], models: Iterable[str], now: datetime) -> List[Dict[str, Any]]:
    """The screens that are not fully taught, each with reason codes (pure): `no_reference` (no pixel
    fingerprint), `no_identity` (android / web interface, node without identity), `old_reference`
    (fingerprint older than STALE_DAYS). Worst first, capped to keep the payload small."""
    needs_identity = bool(set(models or []) & set(IDENTITY_MODELS))
    out: List[Dict[str, Any]] = []
    for r in rows:
        reasons: List[str] = []
        age_days: Optional[float] = None
        if not r.get('dhash'):
            reasons.append('no_reference')
        else:
            t = fingerprint_time(r)
            if t:
                age_days = round((now - t).total_seconds() / 86400.0, 1)
                if age_days > STALE_DAYS:
                    reasons.append('old_reference')
        if needs_identity and not r.get('identity'):
            reasons.append('no_identity')
        if reasons:
            out.append({'node_id': r['node_id'], 'tree_id': r.get('tree_id'), 'label': r.get('label') or r['node_id'],
                        'reasons': reasons, 'age_days': age_days})
    out.sort(key=lambda x: (-len(x['reasons']), x['label'].lower()))
    return out[:SCREENS_TO_FIX_MAX]


def summarize(ui: Dict[str, Any], nodes: Iterable[Dict[str, Any]], corrections: int = 0,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """One coverage row from an interface's node rows (pure)."""
    now = now or datetime.now(timezone.utc)
    screens: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        if (n.get('node_type') or 'screen') in NOT_SCREENS or not n.get('node_id'):
            continue
        prev = screens.get(n['node_id'])
        # a node repeated in a subtree: keep the row that knows the most
        if prev is None or (n.get('dhash') and not prev.get('dhash')):
            screens[n['node_id']] = n
    rows = list(screens.values())
    total = len(rows)
    fp_rows = [r for r in rows if r.get('dhash')]
    ages = sorted((now - t).total_seconds() / 86400.0 for t in (fingerprint_time(r) for r in fp_rows) if t)
    live = [r for r in rows if is_live_node(r.get('label'))]
    pct = lambda k: round(100.0 * k / total, 1) if total else 0.0
    return {
        'userinterface_id': ui.get('id'),
        'userinterface_name': ui.get('name'),
        'models': ui.get('models') or [],
        'screens': total,
        'fingerprinted': len(fp_rows),
        'fingerprinted_pct': pct(len(fp_rows)),
        'identity': sum(1 for r in rows if r.get('identity')),
        'identity_pct': pct(sum(1 for r in rows if r.get('identity'))),
        'live_node': ({'node_id': live[0]['node_id'], 'label': live[0].get('label') or live[0]['node_id']}
                      if live else None),
        'fingerprint_age_days': ({'newest': round(ages[0], 1), 'median': round(ages[len(ages) // 2], 1),
                                  'oldest': round(ages[-1], 1)} if ages else None),
        'missing': sorted((r.get('label') or r['node_id']) for r in rows if not r.get('dhash'))[:50],
        'corrections': corrections,
        'screens_to_fix': screens_to_fix(rows, ui.get('models') or [], now),
    }


def get_coverage(team_id: str, userinterface_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Coverage rows for every dev-mode userinterface of the team (or the one named), most screens first."""
    db = get_supabase_client()
    q = db.table('userinterfaces').select('id, name, models, mode').eq('team_id', team_id)
    if userinterface_name:
        q = q.eq('name', userinterface_name)
    uis = [u for u in (q.execute().data or []) if (u.get('mode') or 'dev') == 'dev']
    if not uis:
        return []
    ui_ids = [u['id'] for u in uis]
    trees = chunked_in(lambda c: db.table('navigation_trees').select('id, userinterface_id')
                       .eq('team_id', team_id).in_('userinterface_id', c), ui_ids)
    ui_of_tree = {t['id']: t['userinterface_id'] for t in trees}
    nodes = chunked_in(lambda c: db.table('navigation_nodes').select(NODE_SELECT)
                       .eq('team_id', team_id).in_('tree_id', c), list(ui_of_tree))
    by_ui: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        by_ui.setdefault(ui_of_tree.get(n.get('tree_id')), []).append(n)
    corrections: Dict[str, int] = {}
    try:
        cq = db.table('localize_verdicts').select('userinterface_name').eq('team_id', team_id).is_('undone_at', 'null')
        if userinterface_name:
            cq = cq.eq('userinterface_name', userinterface_name)
        for r in cq.execute().data or []:
            corrections[r['userinterface_name']] = corrections.get(r['userinterface_name'], 0) + 1
    except Exception as e:                       # a DB without the TASK-104 table
        print(f"[@db:localize_coverage] corrections not read: {e}")
    now = datetime.now(timezone.utc)
    out = [summarize(u, by_ui.get(u['id'], []), corrections.get(u['name'], 0), now) for u in uis]
    return sorted(out, key=lambda r: (-r['screens'], r['userinterface_name'] or ''))
