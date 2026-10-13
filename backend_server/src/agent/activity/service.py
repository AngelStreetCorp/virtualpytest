"""Agent Dashboard service (TASK-54): reads the platform's own tables and shapes the §8 payloads.

Routes stay thin (``routes/agent_activity_routes.py``); the arithmetic is in ``rows.py`` (pure, tested
offline); the SQL is in ``shared/src/lib/database/agent_activity_db.py``. Every source is read with its
own try/except: one broken table degrades its agent card instead of failing the page.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.database import agent_activity_db as db

from . import rows as R
from .sources import AGENT_SOURCES, OTHER, agent_for_registry_id, decision_prefixes, matches_prefixes, part_for_usage_key

logger = logging.getLogger(__name__)

_PRUNE_INTERVAL_SECONDS = 3600
_last_prune_at: Dict[str, float] = {}
_prune_lock = threading.Lock()


def _safe(label: str, fn, default):
    try:
        return fn()
    except Exception as e:  # one broken source must not blank the whole page
        logger.warning('agent activity: %s failed: %s', label, e)
        return default


def registry_meta(agent_id: str) -> Dict[str, Any]:
    """description / version / model of the agent's registry entry ({} for non-registry agents)."""
    registry_id = AGENT_SOURCES[agent_id].get('registry_id')
    if not registry_id:
        return {}
    try:
        from agent.registry import get_agent_registry
        agent = get_agent_registry().get(registry_id)
        if not agent:
            return {}
        meta = {'description': agent.metadata.description, 'version': agent.metadata.version, 'model': None}
        try:
            from shared.src.lib.ai import router as ai_router, usages as ai_usages
            meta['model'] = ai_router.resolve(ai_usages.agent_usage(registry_id)).primary.model
        except Exception:
            pass
        return meta
    except Exception as e:
        logger.warning('agent activity: registry lookup failed for %s: %s', agent_id, e)
        return {}


# ------------------------------------------------------------------ overview

def get_overview(team_id: str, hours: int, is_admin: bool, host_names: List[str],
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hours = db.clamp_hours(hours)
    since = db.since_iso(hours, now)
    open_since = db.since_iso(R.RUNNING_WINDOW_HOURS, now)

    stats = _safe('usage', lambda: db.list_usage_stats(team_id, since, is_admin), [])
    usage = R.aggregate_usage(stats)
    part_counts: Dict[str, Dict[str, Dict[str, int]]] = {}
    error_items: Dict[str, List[Dict[str, Any]]] = {}
    last_activity: Dict[str, datetime] = {}
    now_items: Dict[str, List[Dict[str, Any]]] = {}

    def bump(agent: str, part: str, calls: int, errors: int) -> None:
        c = part_counts.setdefault(agent, {}).setdefault(part, {'calls': 0, 'errors': 0})
        c['calls'] += calls
        c['errors'] += errors

    def touch(agent: str, ts: Any) -> None:
        dt = R.parse_ts(ts)
        if dt and (agent not in last_activity or dt > last_activity[agent]):
            last_activity[agent] = dt

    # chat turns
    chat_rows = _safe('chat history', lambda: db.list_executions_window(team_id, since), [])
    chat_counts, chat_errors, chat_last = R.count_chat_rows(chat_rows, now)
    for agent, c in chat_counts.items():
        bump(agent, 'chat', c['calls'], c['errors'])
    for agent, items in chat_errors.items():
        error_items.setdefault(agent, []).extend(items)
    for agent, ts in chat_last.items():
        touch(agent, ts)

    # decisions
    for r in _safe('decisions', lambda: db.list_decisions_window(team_id, since, is_admin), []):
        agent = R.agent_for_usage_key(r.get('usage_key'))
        part = part_for_usage_key(agent, r.get('usage_key'))
        if not part:
            continue
        failed = not r.get('ok')
        bump(agent, part, 1, 1 if failed else 0)
        touch(agent, r.get('created_at'))
        if failed:
            error_items.setdefault(agent, []).append(
                {'ts': R.iso(r.get('created_at')), 'part': part, 'summary': r.get('error') or R.FAILED_TEXT})

    # Sherlock script verdicts
    for r in _safe('script verdicts', lambda: db.list_script_ai_verdicts_window(team_id, since), []):
        failed = r.get('check_type') == 'ai_error'
        bump('sherlock', 'triage', 1, 1 if failed else 0)
        touch('sherlock', r.get('updated_at'))
        if failed:
            error_items.setdefault('sherlock', []).append(
                {'ts': R.iso(r.get('updated_at')), 'part': 'triage',
                 'summary': r.get('discard_comment') or R.FAILED_TEXT})

    # Nightwatch alert verdicts (alerts has no team_id: scoped by this server's hosts)
    for r in _safe('alert verdicts', lambda: db.list_alert_ai_verdicts_window(host_names, since), []):
        bump('nightwatch', 'triage', 1, 0)
        touch('nightwatch', r.get('updated_at'))

    # Test Prompt runs
    tp_rows = _safe('test prompt runs', lambda: db.list_testprompt_executions(team_id, since, limit=db.MAX_LIMIT), [])
    for r in tp_rows:
        failed = r.get('status') in R.ERROR_STATUSES
        bump('atlas', 'testprompt', 1, 1 if failed else 0)
        touch('atlas', r.get('created_at'))
        if failed:
            error_items.setdefault('atlas', []).append(
                {'ts': R.iso(r.get('created_at')), 'part': 'testprompt',
                 'summary': f"Test Prompt run {r.get('status')}"})

    # now: open work
    for r in _safe('open chats', lambda: db.list_open_executions(team_id, open_since), []):
        agent = agent_for_registry_id(r.get('agent_id'))
        meta = R._json(r.get('metadata')) or {}
        now_items.setdefault(agent, []).append({
            'part': 'chat', 'summary': R.clip(meta.get('prompt') or 'Chat turn'),
            'started_at': R.iso(r.get('started_at')),
            'link': {'kind': 'chat', 'id': meta.get('session_id') or r.get('task_id'), 'url': None}})
    open_tp = _safe('open test prompts', lambda: db.list_open_testprompt_executions(team_id, open_since), [])
    names = _safe('test prompt names', lambda: db.get_testprompt_names(team_id, [r.get('test_prompt_id') for r in open_tp]), {})
    for r in open_tp:
        row = R.build_testprompt_row(r, names, is_admin)
        now_items.setdefault('atlas', []).append({
            'part': 'testprompt', 'summary': row['summary'], 'started_at': row['ts'],
            'link': {'kind': 'testprompt', 'id': str(r.get('test_prompt_id') or r.get('id')), 'url': r.get('report_url')}})

    feedback = R.aggregate_feedback(_safe('feedback', lambda: db.list_feedback_window(team_id, since), []))
    registry = {agent_id: registry_meta(agent_id) for agent_id in AGENT_SOURCES}
    for agent_id, meta in registry.items():
        meta['description'] = meta.get('description') or AGENT_SOURCES[agent_id]['role']
    return R.build_overview(hours=hours, registry=registry, usage=usage, part_counts=part_counts,
                            now_items=now_items, error_items=error_items, last_activity=last_activity,
                            feedback=feedback, is_admin=is_admin)


# ------------------------------------------------------------------ logs

def get_logs(agent_id: str, team_id: str, *, part: Optional[str], level: Optional[str], hours: int,
             q: Optional[str], limit: int, before: Optional[str], is_admin: bool,
             host_names: List[str]) -> Dict[str, Any]:
    spec = AGENT_SOURCES[agent_id]
    limit = max(1, min(int(limit), db.MAX_LIMIT))
    fetch = limit + 1
    since = db.since_iso(hours)
    now = datetime.now(timezone.utc)
    wanted = {part} if part else {p['key'] for p in spec['parts']}
    groups: List[List[Dict[str, Any]]] = []

    if 'chat' in wanted and spec.get('registry_id'):
        execs = db.list_executions(team_id, [spec['registry_id']], since, before, fetch)
        turns_by_task: Dict[str, List[Dict[str, Any]]] = {}
        for t in _safe('turns', lambda: db.list_turns_by_task(team_id, [e.get('task_id') for e in execs]), []):
            turns_by_task.setdefault(str(t.get('task_id')), []).append(t)
        groups.append([R.build_chat_row(e, turns_by_task.get(str(e.get('task_id')), []), is_admin, now)
                       for e in execs])
    if 'testprompt' in wanted and agent_id == 'atlas':
        tp = db.list_testprompt_executions(team_id, since, before, fetch)
        names = _safe('test prompt names', lambda: db.get_testprompt_names(team_id, [r.get('test_prompt_id') for r in tp]), {})
        groups.append([R.build_testprompt_row(r, names, is_admin) for r in tp])
    if 'triage' in wanted and agent_id == 'sherlock':
        groups.append([R.build_script_row(r, is_admin)
                       for r in db.list_script_ai_verdicts(team_id, since, before, fetch)])
    if 'triage' in wanted and agent_id == 'nightwatch':
        groups.append([R.build_alert_row(r, is_admin)
                       for r in db.list_alert_ai_verdicts(host_names, since, before, fetch)])
    if 'decision' in wanted:
        prefixes = decision_prefixes(agent_id)
        decisions = db.list_decisions_for_logs(team_id, prefixes, since, before, is_admin,
                                               ok=False if level == 'error' else None, limit=fetch)
        out = []
        for d in decisions:
            if not matches_prefixes(d.get('usage_key'), prefixes):
                continue
            out.append(R.build_decision_row(d, part_for_usage_key(agent_id, d.get('usage_key')) or 'decision', is_admin))
        groups.append(out)
    return R.merge_rows(groups, level=level, q=q, limit=limit)


# ------------------------------------------------------------------ turns

def get_turns(agent_id: str, team_id: str, session_id: str, langfuse_host: Optional[str] = None) -> Dict[str, Any]:
    registry_id = AGENT_SOURCES[agent_id].get('registry_id')
    turns = db.list_turns(team_id, session_id, registry_id) if registry_id else []
    return {'turns': [{
        'ts': R.iso(t.get('created_at')), 'role': t.get('role'), 'content': t.get('content'),
        'tool_calls': R._json(t.get('tool_calls')) or [], 'tokens_in': int(t.get('tokens_in') or 0),
        'tokens_out': int(t.get('tokens_out') or 0), 'trace_url': R.trace_url(t.get('trace_id'), langfuse_host),
    } for t in turns]}


# ------------------------------------------------------------------ usage (admin)

def get_usage(team_id: str, days: int) -> Dict[str, Any]:
    days = max(1, min(int(days), db.MAX_DAYS))
    since = db.since_iso(days * 24)
    stats = db.list_usage_stats(team_id, since, include_platform=True)
    decisions = db.list_decisions_window(team_id, since, include_platform=True)
    return {'days': days, 'by_agent_day': R.usage_by_agent_day(stats), 'by_key': R.usage_by_key(stats),
            'decisions': R.decision_quality(decisions), 'openrouter': None}


# ------------------------------------------------------------------ feedback

def thumbs_to_rating(value: Any) -> Optional[int]:
    """rating 1-5, or thumbs 'up'/'down' (5 / 1). None = invalid."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.lower() in ('up', 'down'):
        return 5 if value.lower() == 'up' else 1
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 5 else None


# ------------------------------------------------------------------ chat turn capture + live tail

_TOOL_PARAMS_MAX = 2000


def compact_tool_calls(calls: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    """Tool calls of a turn as stored in agent_turns.tool_calls: name, success, params (clipped)."""
    import json
    out = []
    for c in (calls or [])[:limit]:
        params = c.get('params')
        try:
            text = json.dumps(params, ensure_ascii=False, default=str) if params is not None else None
        except Exception:
            text = None
        out.append({'name': c.get('name'), 'success': c.get('success'),
                    'params': text[:_TOOL_PARAMS_MAX] if text else None})
    return out


def emit_activity(agent_id: str, team_id: str, row: Dict[str, Any]) -> None:
    """Live tail: broadcast one log row on /system. Never raises.

    /system is a broadcast room shared by every team, so ``team_id`` travels with the row and the text
    of the row is generic (no prompt, no answer, no error): the drawer refreshes the full row by polling.
    """
    try:
        from backend_server.src.routes.server_system_socket_routes import emit_system_update
        emit_system_update('agent_activity', {'domain': 'agent_activity', 'agent_id': agent_id,
                                              'team_id': str(team_id) if team_id else None, 'row': row})
    except Exception as e:
        logger.debug('agent activity emit failed: %s', e)


def public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """The row as broadcast: no free text, no detail."""
    generic = {'chat': 'Chat turn', 'triage': 'Verdict', 'decision': 'Decision', 'testprompt': 'Test Prompt run'}
    out = dict(row)
    out['summary'] = generic.get(row.get('part'), 'Activity') + (' failed' if row.get('level') == 'error' else '')
    out['detail'] = None
    out['links'] = {**row.get('links', {}), 'trace': None}
    return out


def _maybe_prune(team_id: str) -> None:
    now = time.time()
    with _prune_lock:
        last = _last_prune_at.get(team_id)
        if last is not None and now - last < _PRUNE_INTERVAL_SECONDS:
            return
        _last_prune_at[team_id] = now
    db.prune_turns(team_id, db.TURNS_RETENTION_DAYS)


def record_chat_turn(*, team_id: Optional[str], agent_id: str, session_id: str, task_id: str, message: str,
                     answer: Optional[str], tool_calls: List[Dict[str, Any]], tokens_in: int, tokens_out: int,
                     trace_id: Optional[str], started_at: datetime, completed_at: datetime, status: str,
                     history_id: Optional[str] = None) -> None:
    """Store the user + agent rows of one chat turn and emit the live row. Never raises."""
    try:
        if not team_id:
            return
        index = db.next_turn_index(team_id, session_id)
        base = {'team_id': str(team_id), 'agent_id': agent_id, 'session_id': session_id, 'task_id': task_id}
        rows = [{**base, 'turn_index': index, 'role': 'user', 'content': message, 'tool_calls': None,
                 'tokens_in': None, 'tokens_out': None, 'trace_id': None}]
        if answer or tool_calls:
            rows.append({**base, 'turn_index': index + 1, 'role': 'agent', 'content': answer or '',
                         'tool_calls': tool_calls or None, 'tokens_in': tokens_in, 'tokens_out': tokens_out,
                         'trace_id': trace_id})
        db.insert_turns(rows)
        _maybe_prune(str(team_id))
        exec_row = {'id': history_id or task_id, 'started_at': started_at.isoformat(),
                    'completed_at': completed_at.isoformat(), 'status': status,
                    'duration_seconds': (completed_at - started_at).total_seconds(),
                    'error_message': 'failed' if status == 'failed' else None,
                    'metadata': {'prompt': message, 'session_id': session_id}}
        row = R.build_chat_row(exec_row, [], is_admin=False)
        row['tokens_in'], row['tokens_out'] = tokens_in or 0, tokens_out or 0
        emit_activity(agent_for_registry_id(agent_id), team_id, public_row(row))
    except Exception as e:
        logger.error('agent activity: recording chat turn failed: %s', e)


def emit_verdict(agent_id: str, team_id: Optional[str], row: Dict[str, Any]) -> None:
    emit_activity(agent_id, team_id or '', public_row(row))
