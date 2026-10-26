"""match_runs table access (TASK-115: matcher history).

One row per matcher run across all sources (verify_node, the Localize
button, the monitor's per-frame localize, the post-verify localize_check,
and nightwatch).  Hosts write; the server reads.

The single public function is ``record_match_run``; everything else is
internal.  The function:

1. Resolves the previous event for the (team_id, device_id, userinterface_name)
   chain so a sequence is walkable with one self-join.
2. Computes the runner-up margin from the top-3 candidates (winner - 2nd).
3. Inserts the row.

Failures never raise — a missing match_runs row is a missing insight, not
a crashed service.  The function returns ``{'success': bool, 'id': uuid|None,
'error': str|None}``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'match_runs'

# 5 minutes with no event = a new session.  Picked to cover "I left the
# TV on the menu" (an idle STB) without breaking short test cycles
# (a verify run that takes 30s).
SESSION_GAP_SECONDS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_n(result: Dict[str, Any], n: int = 3) -> List[Dict[str, Any]]:
    """The top-N candidates from a matcher result, ordered by confidence desc.

    The matcher already returns a 'candidates' list sorted by confidence
    descending (see ImageHelpers.match_fingerprint_v5/v6).  'ranked' is the
    pre-narrowing list, also sorted.  We prefer 'candidates' because it has
    been through the abstain doors — the runner-up is a real second
    opinion, not a candidate the matcher already decided to drop.
    """
    src = result.get('candidates') or result.get('ranked') or []
    out = []
    for i, c in enumerate(src[:n], start=1):
        out.append({
            'node_id': c.get('node_id'),
            'label': c.get('label'),
            'score': c.get('confidence'),
            'rank': i,
        })
    return out


def _live_fingerprint(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The live frame's fingerprint when the matcher computed one (needs ``regions``,
    which /localize/verdict requires), else None.  Never computed here."""
    fp = result.get('live_fingerprint')
    return fp if isinstance(fp, dict) and fp.get('regions') else None


def _floor_hit(top3: List[Dict[str, Any]], floor: float) -> bool:
    return bool(top3) and (top3[0].get('score') or 0.0) >= floor


def _runner_up_margin(top3: List[Dict[str, Any]]) -> Optional[float]:
    if len(top3) < 2:
        return None
    try:
        a = float(top3[0].get('score') or 0.0)
        b = float(top3[1].get('score') or 0.0)
        return round(a - b, 4)
    except (TypeError, ValueError):
        return None


def _previous_event(db, team_id: str, device_id: Optional[str],
                    userinterface_name: str) -> Dict[str, Optional[str]]:
    """Resolve the prior match_run for the chain on this device+UI.

    Returns ``{'id': uuid|None, 'matched_node_id': uuid|None,
    'session_id': uuid|None, 'step': int|None}``.  ``step`` is the prior
    step_in_session + 1, or 1 if a new session.

    The session boundary is "more than SESSION_GAP_SECONDS since the prior
    event" — short enough that a verify cycle (30s) stays one session,
    long enough that an idle TV menu does not pollute the step count.
    """
    if not device_id:
        return {'id': None, 'matched_node_id': None, 'session_id': None, 'step': None}
    try:
        res = (db.table(TABLE).select('id, matched_node_id, started_at, session_id, step_in_session')
               .eq('team_id', team_id).eq('device_id', device_id)
               .eq('userinterface_name', userinterface_name)
               .order('started_at', desc=True).limit(1).execute())
        rows = res.data or []
    except Exception as e:
        print(f'[@db:match_runs:_previous_event] {e}')
        return {'id': None, 'matched_node_id': None, 'session_id': None, 'step': None}
    if not rows:
        return {'id': None, 'matched_node_id': None, 'session_id': None, 'step': None}
    prior = rows[0]
    try:
        prior_at = datetime.fromisoformat(prior['started_at'].replace('Z', '+00:00'))
    except Exception:
        prior_at = None
    now = datetime.now(timezone.utc)
    if prior_at and (now - prior_at).total_seconds() > SESSION_GAP_SECONDS:
        return {'id': prior['id'], 'matched_node_id': prior.get('matched_node_id'),
                'session_id': None, 'step': 1}
    return {'id': prior['id'], 'matched_node_id': prior.get('matched_node_id'),
            'session_id': prior.get('session_id'), 'step': (prior.get('step_in_session') or 0) + 1}


def record_match_run(
    *,
    team_id: str,
    host_name: str,
    userinterface_name: str,
    source: str,                       # verify|localize_button|monitor_localize|localize_check|nightwatch
    result: Dict[str, Any],            # the matcher result (or the operator's button payload)
    confidence_floor: float = 0.80,
    top_n: int = 3,
    server_id: Optional[str] = None,
    device_id: Optional[str] = None,
    device_name: Optional[str] = None,
    device_model: Optional[str] = None,
    tree_id: Optional[str] = None,
    variant: Optional[str] = None,
    source_ref: Optional[Dict[str, Any]] = None,
    dhash: Optional[int] = None,
    frame_url: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert one match_runs row from a matcher result.

    The matcher result can be in either shape:
      - ImageHelpers.identify_screen output: ``{candidates, ranked, ...}``
      - The API's post-_after_match output: ``{kind, node_id, label, ...}``

    The first is the matcher view (full ranked list), the second is the
    button view (just the winner).  We pick the right field per case.

    `profile` is the matcher profile (tv_app, pc, drone, ...).  Only the
    monitor path fills it in (sources='monitor_localize' or 'nightwatch');
    verify / localize_button / localize_check leave it NULL — the profile
    concept does not apply to those sources.

    Returns ``{'success': True, 'id': uuid}`` or
    ``{'success': False, 'error': str}``.  Never raises.
    """
    if not team_id or not host_name or not userinterface_name or not source:
        return {'success': False, 'error': 'team_id, host_name, userinterface_name, source are required'}

    try:
        db = get_supabase_client()
    except Exception as e:
        return {'success': False, 'error': f'supabase client unavailable: {e}'}

    # Build the top-N from whichever field the result carries.
    top3 = _top_n(result, n=top_n)
    floor_hit = _floor_hit(top3, confidence_floor)
    margin = _runner_up_margin(top3)

    # Verdict: pick from the matcher's `kind` if present (post-_after_match),
    # else fall back to a 'unknown' for an empty result or 'known_node' for
    # a populated one.  Anything less than the floor becomes 'low_confidence'.
    kind = result.get('kind')
    if kind in ('signal', 'live', 'overlay', 'no_signal', 'black_screen', 'no_signal_at_all'):
        verdict = 'live' if kind == 'live' else ('no_signal' if 'signal' in (kind or '') or 'screen' in (kind or '') else 'overlay')
    elif not top3:
        verdict = 'unknown'
    elif not floor_hit:
        verdict = 'low_confidence'
    else:
        verdict = 'known_node'

    winner = top3[0] if top3 else None
    matched_node_id = (winner or {}).get('node_id') if verdict == 'known_node' else None
    matched_confidence = (winner or {}).get('score') if verdict == 'known_node' else None

    # Sequence chain.  Best-effort: a DB hiccup here just drops the chain on
    # this row, the next row resolves the prior again, so we self-heal.
    chain = _previous_event(db, team_id, device_id, userinterface_name)
    import uuid as _uuid
    session_id = chain.get('session_id') or str(_uuid.uuid4())

    payload = {
        'team_id': team_id,
        'server_id': server_id,
        'host_name': host_name,
        'device_id': device_id,
        'device_name': device_name,
        'device_model': device_model,
        'userinterface_name': userinterface_name,
        'tree_id': tree_id,
        'variant': variant,
        'profile': profile,
        'source': source,
        'source_ref': source_ref or {},
        'started_at': started_at or _now(),
        'completed_at': completed_at or _now(),
        'elapsed_ms': elapsed_ms,
        'verdict': verdict,
        'matched_node_id': matched_node_id,
        'matched_confidence': matched_confidence,
        'runner_up_margin': margin,
        'candidates_top_3': top3,
        'candidate_threshold': confidence_floor,
        'candidate_floor_hit': floor_hit,
        'dhash': dhash,
        'frame_url': frame_url,
        'previous_event_id': chain.get('id'),
        'previous_node_id': chain.get('matched_node_id'),
        'step_in_session': chain.get('step'),
        'session_id': session_id,
        'live_fingerprint': _live_fingerprint(result),
    }

    try:
        res = db.table(TABLE).insert(payload).execute()
        if not res.data:
            return {'success': False, 'error': 'insert returned no rows'}
        return {'success': True, 'id': res.data[0]['id'], 'verdict': verdict, 'floor_hit': floor_hit}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_recent(team_id: str, *, device_id: Optional[str] = None,
                userinterface_name: Optional[str] = None, limit: int = 50,
                host_name: Optional[str] = None, device_name: Optional[str] = None,
                host_only: bool = False,
                include_fingerprint: bool = False) -> List[Dict[str, Any]]:
    """The most recent N match_runs for a team / device / UI / host.  Read-only.

    ``host_only`` selects the runs of ``host_name`` that carry no device_name (the "(host only)" row).

    Each row gets ``has_fingerprint``; the fingerprint itself (large) is returned only with
    ``include_fingerprint``."""
    try:
        db = get_supabase_client()
        q = db.table(TABLE).select('*').eq('team_id', team_id)
        if device_id:
            q = q.eq('device_id', device_id)
        if userinterface_name:
            q = q.eq('userinterface_name', userinterface_name)
        if host_name:
            q = q.eq('host_name', host_name)
        if host_only:
            q = q.is_('device_name', 'null')
        elif device_name:
            q = q.eq('device_name', device_name)
        res = q.order('started_at', desc=True).limit(limit).execute()
        rows = res.data or []
        for r in rows:
            fp = r.get('live_fingerprint')
            r['has_fingerprint'] = bool(fp)
            if not include_fingerprint:
                r.pop('live_fingerprint', None)
        return rows
    except Exception as e:
        print(f'[@db:match_runs:list_recent] {e}')
        return []


def transitions(team_id: str, userinterface_name: str,
                from_node_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """P(to_node | from_node, ui): the prediction matrix.

    Reads ``v_node_transitions`` (defined in the migration) and filters
    server-side.  No extra aggregation; the view does the work.
    """
    try:
        db = get_supabase_client()
        q = (db.table('v_node_transitions').select('*')
             .eq('team_id', team_id).eq('userinterface_name', userinterface_name))
        if from_node_id:
            q = q.eq('from_node_id', from_node_id)
        res = q.order('occurrences', desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        print(f'[@db:match_runs:transitions] {e}')
        return []


def uncertain_hits(team_id: str, *, userinterface_name: Optional[str] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
    """The 'matcher said yes but barely' backlog — the operator's TODO list."""
    try:
        db = get_supabase_client()
        q = db.table('v_uncertain_hits').select('*').eq('team_id', team_id)
        if userinterface_name:
            q = q.eq('userinterface_name', userinterface_name)
        res = q.order('started_at', desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        print(f'[@db:match_runs:uncertain_hits] {e}')
        return []


# ---------------------------------------------------------------------------
# Dashboard aggregations (BUG-0569: dedicated matcher dashboard).
# Single SELECT per function — no Python postprocessing.  Each returns a
# list of dicts (or one dict, for summary) so the front end can render the
# row directly.  All filters are optional except team_id; the time window
# is `since_iso` (defaults to now-24h) and applies to started_at.
# ---------------------------------------------------------------------------

def summary(team_id: str, *, since_iso: Optional[str] = None,
            until_iso: Optional[str] = None,
            userinterface_name: Optional[str] = None,
            device_name: Optional[str] = None) -> Dict[str, Any]:
    """One-row dashboard KPI strip.

    Counts: total, matched, uncertain (margin < 5%, matched only),
    unknown_or_low_conf, distinct_devices, distinct_profiles, and the
    distinct host_names.  Window is the last ``since_iso`` (defaults to
    24h via the caller); matches are filtered by UI / device if either is
    given.  ``until_iso`` closes the window (``started_at < until_iso``): with
    it the same call summarises an earlier window (the trend baseline).
    Returns ``{'': 0, ..., 'window_started_at': iso}`` on success
    or ``{'error': str}`` on failure.
    """
    try:
        db = get_supabase_client()
        q = db.table(TABLE).select('verdict, runner_up_margin, matched_confidence, device_name, host_name, profile').eq('team_id', team_id)
        if userinterface_name:
            q = q.eq('userinterface_name', userinterface_name)
        if device_name:
            q = q.eq('device_name', device_name)
        if since_iso:
            q = q.gte('started_at', since_iso)
        if until_iso:
            q = q.lt('started_at', until_iso)
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        print(f'[@db:match_runs:summary] {e}')
        return {'total': 0, 'matched': 0, 'uncertain': 0, 'unknown_or_low_conf': 0,
                'distinct_devices': 0, 'distinct_profiles': 0, 'distinct_hosts': 0,
                'avg_confidence': None, 'window_started_at': since_iso}
    total = len(rows)
    matched = 0
    uncertain = 0
    unknown = 0
    devices = set()
    hosts = set()
    profiles = set()
    confidences = []
    for r in rows:
        verdict = r.get('verdict')
        margin = r.get('runner_up_margin')
        if verdict == 'known_node':
            matched += 1
            if r.get('matched_confidence') is not None:
                confidences.append(float(r['matched_confidence']))
            if margin is not None and margin < 0.05:
                uncertain += 1
        elif verdict in ('unknown', 'low_confidence'):
            unknown += 1
        if r.get('device_name'):
            devices.add(r['device_name'])
        if r.get('host_name'):
            hosts.add(r['host_name'])
        if r.get('profile'):
            profiles.add(r['profile'])
    return {
        'total': total,
        'matched': matched,
        'uncertain': uncertain,
        'unknown_or_low_conf': unknown,
        'distinct_devices': len(devices),
        'distinct_profiles': len(profiles),
        'distinct_hosts': len(hosts),
        'avg_confidence': round(sum(confidences) / len(confidences), 3) if confidences else None,
        'window_started_at': since_iso,
    }


def per_device(team_id: str, *, since_iso: Optional[str] = None,
               userinterface_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per (host_name, device_name) — the heatmap axis.

    Returns the row keys the heatmap and the per-device table need:
    host_name, device_name, total, matched, uncertain, unknown, last_match_at.
    Sorted by total desc so the busiest devices appear at the top.
    """
    try:
        db = get_supabase_client()
        q = (db.table(TABLE)
             .select('host_name, device_name, verdict, runner_up_margin, started_at')
             .eq('team_id', team_id))
        if userinterface_name:
            q = q.eq('userinterface_name', userinterface_name)
        if since_iso:
            q = q.gte('started_at', since_iso)
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        print(f'[@db:match_runs:per_device] {e}')
        return []
    bucket: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        key = (r.get('host_name') or '', r.get('device_name') or '')
        b = bucket.setdefault(key, {
            'host_name': key[0], 'device_name': key[1],
            'total': 0, 'matched': 0, 'uncertain': 0, 'unknown': 0,
            'last_match_at': r.get('started_at'),
        })
        b['total'] += 1
        verdict = r.get('verdict')
        if verdict == 'known_node':
            b['matched'] += 1
            if r.get('runner_up_margin') is not None and r['runner_up_margin'] < 0.05:
                b['uncertain'] += 1
        elif verdict in ('unknown', 'low_confidence'):
            b['unknown'] += 1
        try:
            cur = r.get('started_at') or ''
            if cur and (not b['last_match_at'] or cur > b['last_match_at']):
                b['last_match_at'] = cur
        except Exception:
            pass
    out = list(bucket.values())
    out.sort(key=lambda x: -x['total'])
    return out


def verdict_distribution(team_id: str, *, since_iso: str,
                          userinterface_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Per-hour verdict tally (last ``since_iso``).

    Returns rows of ``{bucket, verdict, count}`` ordered by bucket asc.
    Zero-count verdicts are dropped — the chart layer treats absence as
    zero-height bars anyway, and emitting 0 rows costs the operator a
    render of empty buckets.  The backend groups in Python so the
    supabase/postgrest client does not need aggregate routes — same
    trick the rest of the module uses.
    """
    try:
        db = get_supabase_client()
        q = (db.table(TABLE)
             .select('started_at, verdict')
             .eq('team_id', team_id)
             .gte('started_at', since_iso))
        if userinterface_name:
            q = q.eq('userinterface_name', userinterface_name)
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        print(f'[@db:match_runs:verdict_distribution] {e}')
        return []
    bucket: Dict[str, Dict[str, int]] = {}
    for r in rows:
        started = r.get('started_at') or ''
        bucket_key = started[:13] + ':00:00'  # truncate to hour
        d = bucket.setdefault(bucket_key, {})
        v = r.get('verdict') or 'unknown'
        d[v] = d.get(v, 0) + 1
    out: List[Dict[str, Any]] = []
    for k in sorted(bucket.keys()):
        for verdict, count in bucket[k].items():
            if count <= 0:
                continue
            out.append({'bucket': k, 'verdict': verdict, 'count': count})
    return out


def sequence(team_id: str, *, device_id: str, userinterface_name: str,
             session_id: Optional[str] = None,
             limit: int = 20) -> List[Dict[str, Any]]:
    """The last ``limit`` match_runs for one device in one UI.

    The session_id filter is optional; without it the result is "last 20
    across all sessions for this device+UI" — enough for the replay panel.
    The top-3 candidates and the runner-up margin come straight from the
    row's ``candidates_top_3`` JSONB and ``runner_up_margin`` column, so
    this function does no recomputation.
    """
    try:
        db = get_supabase_client()
        q = (db.table(TABLE).select(
            'id, started_at, verdict, matched_node_id, matched_confidence, '
            'runner_up_margin, candidates_top_3, source, step_in_session, '
            'session_id, previous_event_id, previous_node_id')
             .eq('team_id', team_id).eq('device_id', device_id)
             .eq('userinterface_name', userinterface_name))
        if session_id:
            q = q.eq('session_id', session_id)
        res = q.order('started_at', desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        print(f'[@db:match_runs:sequence] {e}')
        return []
