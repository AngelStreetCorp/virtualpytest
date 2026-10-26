"""
deploy_progress.py — read the `VPT_PROGRESS` lines `update_core.sh` prints (TASK-99 G9).

`update_core.sh` keeps its human log unchanged and adds one machine-readable line at each per-host
phase boundary:

    VPT_PROGRESS {"host":"vpt-pi1","role":"host","phase":"rsync","state":"start",
                  "ts":"2026-10-14T08:00:01Z","detail":""}

  phase  rsync | install | restart | health | stale-code
  state  start | ok | failed | skipped
  role   server | frontend | host | docker | windows   (a machine can be a server AND a host, so a
                                                       card is keyed by (role, host))

`stale-code` is a NOTE, not a phase of the deploy: it says that a service on that host was left
running the code from before this deploy (the aux services are only restarted with --restart, and
the code marker tracks the host service only, so nothing else could see it). It is always `skipped`,
so it never turns a host card into a failure, and it is deliberately not one of the four phases the
deployment view counts (the server keeps its own list of those).

`parse()` turns a run log into one record per (role, host) with each phase's state and duration.
The server uses it to draw the deployment view; the line may sit after any prefix (a log
timestamp, `[stdout] `), and anything that does not parse is counted, never fatal — a deploy log
is mostly human text.

    parse(open('deploy.log'))['hosts'][0]['phases']['rsync']['duration_s']
"""
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Union

MARKER = 'VPT_PROGRESS '
PHASES = ('rsync', 'install', 'restart', 'health', 'stale-code')
STATES = ('start', 'ok', 'failed', 'skipped')


def parse_line(line: str) -> Optional[Dict[str, str]]:
    """The event in one log line, or None when the line carries none (or a malformed one)."""
    at = line.find(MARKER)
    if at < 0:
        return None
    try:
        ev = json.loads(line[at + len(MARKER):].strip())
    except ValueError:
        return None
    if not isinstance(ev, dict) or ev.get('phase') not in PHASES or ev.get('state') not in STATES \
            or not ev.get('host') or not ev.get('ts'):
        return None
    return {'host': str(ev['host']), 'role': str(ev.get('role') or 'host'), 'phase': ev['phase'],
            'state': ev['state'], 'ts': str(ev['ts']), 'detail': str(ev.get('detail') or '')}


def _epoch(ts: str) -> Optional[float]:
    try:
        return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').timestamp()
    except ValueError:
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None


def _host_state(phases: Dict[str, Dict[str, Any]]) -> str:
    states = [p['state'] for p in phases.values()]
    if 'failed' in states:
        return 'failed'
    if 'running' in states:
        return 'running'
    if states and all(s == 'skipped' for s in states):
        return 'skipped'
    if states and all(s in ('ok', 'skipped') for s in states):
        return 'ok'
    return 'running' if states else 'pending'


def parse(source: Union[str, Iterable[str]]) -> Dict[str, Any]:
    """-> {'hosts': [...], 'state', 'started', 'ended', 'duration_s', 'events', 'ignored'}.

    Each host: {'host', 'role', 'state': pending|running|ok|failed|skipped, 'started', 'ended',
    'duration_s', 'phases': {phase: {'state': running|ok|failed|skipped, 'started', 'ended',
    'duration_s', 'detail'}}}. A phase that started and never ended is `running`; a duration is
    the end event minus its own start event (None for a phase with no start, e.g. skipped)."""
    lines = source.splitlines() if isinstance(source, str) else source
    cards: Dict[tuple, Dict[str, Any]] = {}
    events = ignored = 0
    for line in lines:
        ev = parse_line(line)
        if ev is None:
            if MARKER in line:
                ignored += 1
            continue
        events += 1
        card = cards.setdefault((ev['role'], ev['host']), {
            'host': ev['host'], 'role': ev['role'], 'state': 'pending',
            'started': None, 'ended': None, 'duration_s': None, 'phases': {}})
        ph = card['phases'].setdefault(ev['phase'], {
            'state': 'running', 'started': None, 'ended': None, 'duration_s': None, 'detail': ''})
        if ev['state'] == 'start':
            ph.update(state='running', started=ev['ts'], ended=None, duration_s=None)
        else:
            ph.update(state=ev['state'], ended=ev['ts'])
            t0, t1 = _epoch(ph['started'] or ''), _epoch(ev['ts'])
            ph['duration_s'] = round(max(0.0, t1 - t0), 3) if t0 is not None and t1 is not None else None
        if ev['detail']:
            ph['detail'] = ev['detail']

    hosts: List[Dict[str, Any]] = list(cards.values())
    for card in hosts:
        starts = [p['started'] for p in card['phases'].values() if p['started']]
        ends = [p['ended'] for p in card['phases'].values() if p['ended']]
        card['started'] = min(starts) if starts else None
        card['ended'] = max(ends) if ends and card_done(card) else None
        t0, t1 = _epoch(card['started'] or ''), _epoch(card['ended'] or '')
        card['duration_s'] = round(max(0.0, t1 - t0), 3) if t0 is not None and t1 is not None else None
        card['state'] = _host_state(card['phases'])

    starts = [h['started'] for h in hosts if h['started']]
    ends = [h['ended'] for h in hosts if h['ended']]
    t0, t1 = _epoch(min(starts)) if starts else None, _epoch(max(ends)) if ends else None
    states = [h['state'] for h in hosts]
    return {
        'hosts': hosts,
        'state': ('failed' if 'failed' in states else 'running' if 'running' in states
                  else 'ok' if hosts else 'pending'),
        'started': min(starts) if starts else None,
        'ended': max(ends) if ends and 'running' not in states else None,
        'duration_s': round(max(0.0, t1 - t0), 3) if t0 is not None and t1 is not None else None,
        'events': events,
        'ignored': ignored,
    }


def card_done(card: Dict[str, Any]) -> bool:
    return all(p['state'] != 'running' for p in card['phases'].values())
