"""Pure logic of the Agent Dashboard (TASK-54): health rule, log rows, overview aggregation.

No database, no Flask: every function takes plain rows (dicts as the DB module returns them) and
returns plain dicts, so it is unit-tested offline (tests/backend_server/test_agent_activity.py).

Error text (``error_message``, ``ai_decisions.error``, ``discard_comment`` of an ``ai_error`` verdict)
can hold secrets or user content: it is shown to admins only (``is_admin``); everybody else gets the
generic ``FAILED_TEXT``. Same rule as ``GET /server/logs/agent``.
"""

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from .sources import AGENT_SOURCES, OTHER, agent_for_registry_id, agent_for_usage_key

FAILED_TEXT = 'Execution failed'
ERROR_RATE_ERROR = 0.25
ERROR_RATE_WARN = 0.05
RUNNING_WINDOW_HOURS = 1
SUMMARY_MAX = 140
DETAIL_MAX = 2000
LEVELS = ('ok', 'error', 'fallback', 'running')
ERROR_STATUSES = ('failed', 'error')


# ------------------------------------------------------------------ small helpers

def parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00').replace(' ', 'T', 1))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(value: Any) -> Optional[str]:
    dt = parse_ts(value)
    return dt.isoformat() if dt else None


def clip(text: Any, limit: int = SUMMARY_MAX) -> str:
    s = ' '.join(str(text or '').split())
    return s if len(s) <= limit else s[:limit - 1] + '…'


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def trace_url(trace_id: Optional[str], host: Optional[str] = None) -> Optional[str]:
    """Langfuse trace link: needs LANGFUSE_HOST; None otherwise."""
    host = (host if host is not None else os.getenv('LANGFUSE_HOST', '')).strip().rstrip('/')
    return f'{host}/trace/{trace_id}' if host and trace_id else None


def new_row(row_id: str, ts: Any, part: str, level: str, summary: str, *, tokens_in: int = 0,
            tokens_out: int = 0, duration_ms: int = 0, links: Optional[Dict[str, Any]] = None,
            detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base_links = {'report': None, 'alert': None, 'chat_session': None, 'trace': None, 'testprompt': None}
    base_links.update(links or {})
    return {'id': str(row_id), 'ts': iso(ts), 'part': part, 'level': level, 'summary': clip(summary),
            'tokens_in': int(tokens_in or 0), 'tokens_out': int(tokens_out or 0),
            'duration_ms': int(duration_ms or 0), 'links': base_links, 'detail': detail}


# ------------------------------------------------------------------ health

def compute_health(calls: int, errors: int, has_activity: bool) -> str:
    """error: errors/calls >= .25; warn: >= .05; idle: no activity in the window; else ok."""
    if not has_activity and not calls:
        return 'idle'
    if calls <= 0:
        return 'ok'
    rate = errors / calls
    if rate >= ERROR_RATE_ERROR:
        return 'error'
    if rate >= ERROR_RATE_WARN:
        return 'warn'
    return 'ok'


# ------------------------------------------------------------------ usage aggregation

def aggregate_usage(stat_rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """ai_usage_stats rows -> {agent_id: {calls, errors, fallbacks, tokens_in, tokens_out, total_ms, last}}."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in stat_rows:
        agent = agent_for_usage_key(r.get('usage_key'))
        a = out.setdefault(agent, {'calls': 0, 'errors': 0, 'fallbacks': 0, 'tokens_in': 0,
                                   'tokens_out': 0, 'total_ms': 0, 'last': None})
        for k in ('calls', 'errors', 'fallbacks', 'tokens_in', 'tokens_out', 'total_ms'):
            a[k] += int(r.get(k) or 0)
        ts = parse_ts(r.get('bucket'))
        if ts and (a['last'] is None or ts > a['last']):
            a['last'] = ts
    return out


def usage_by_key(stat_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys: Dict[str, Dict[str, Any]] = {}
    for r in stat_rows:
        k = r.get('usage_key') or ''
        e = keys.setdefault(k, {'usage_key': k, 'agent': agent_for_usage_key(k), 'calls': 0, 'errors': 0,
                                'fallbacks': 0, 'tokens_in': 0, 'tokens_out': 0, 'total_ms': 0})
        for f in ('calls', 'errors', 'fallbacks', 'tokens_in', 'tokens_out', 'total_ms'):
            e[f] += int(r.get(f) or 0)
    out = []
    for e in keys.values():
        e['avg_ms'] = int(e['total_ms'] / e['calls']) if e['calls'] else 0
        del e['total_ms']
        out.append(e)
    return sorted(out, key=lambda e: (-e['calls'], e['usage_key']))


def usage_by_agent_day(stat_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    days: Dict[tuple, Dict[str, Any]] = {}
    for r in stat_rows:
        ts = parse_ts(r.get('bucket'))
        if not ts:
            continue
        key = (agent_for_usage_key(r.get('usage_key')), ts.astimezone(timezone.utc).date().isoformat())
        e = days.setdefault(key, {'agent': key[0], 'day': key[1], 'tokens_in': 0, 'tokens_out': 0, 'calls': 0})
        e['tokens_in'] += int(r.get('tokens_in') or 0)
        e['tokens_out'] += int(r.get('tokens_out') or 0)
        e['calls'] += int(r.get('calls') or 0)
    return sorted(days.values(), key=lambda e: (e['day'], e['agent']))


def decision_quality(decision_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per usage_key: ok / fail counts and how many have a checked outcome."""
    keys: Dict[str, Dict[str, Any]] = {}
    for r in decision_rows:
        k = r.get('usage_key') or ''
        e = keys.setdefault(k, {'usage_key': k, 'ok': 0, 'fail': 0, 'outcome_known': 0})
        e['ok' if r.get('ok') else 'fail'] += 1
        if r.get('outcome_at'):
            e['outcome_known'] += 1
    return sorted(keys.values(), key=lambda e: (-(e['ok'] + e['fail']), e['usage_key']))


# ------------------------------------------------------------------ log rows

def chat_level(row: Dict[str, Any], now: datetime) -> str:
    if not row.get('completed_at'):
        started = parse_ts(row.get('started_at'))
        if started and now - started <= timedelta(hours=RUNNING_WINDOW_HOURS):
            return 'running'
    return 'error' if (row.get('status') in ERROR_STATUSES or row.get('error_message')) else 'ok'


def turn_detail(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Question / answer / token totals of one chat task from its agent_turns rows."""
    question = next((t.get('content') for t in turns if t.get('role') == 'user'), None)
    agent = [t for t in turns if t.get('role') == 'agent']
    answer = agent[-1].get('content') if agent else None
    return {'question': question, 'answer': answer,
            'tokens_in': sum(int(t.get('tokens_in') or 0) for t in agent),
            'tokens_out': sum(int(t.get('tokens_out') or 0) for t in agent),
            'trace_id': next((t.get('trace_id') for t in reversed(agent) if t.get('trace_id')), None)}


def build_chat_row(row: Dict[str, Any], turns: List[Dict[str, Any]], is_admin: bool,
                   now: Optional[datetime] = None, langfuse_host: Optional[str] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    meta = _json(row.get('metadata')) or {}
    level = chat_level(row, now)
    td = turn_detail(turns)
    prompt = td['question'] or meta.get('prompt') or ''
    summary = prompt or (clip(row.get('error_message')) if is_admin and row.get('error_message') else 'Chat turn')
    detail: Dict[str, Any] = {'question': clip(prompt, DETAIL_MAX) or None,
                              'answer': clip(td['answer'], DETAIL_MAX) if td['answer'] else None}
    if level == 'error':
        if is_admin and row.get('error_message'):
            detail['error'] = clip(row['error_message'], DETAIL_MAX)
        elif not prompt:
            summary = FAILED_TEXT
    duration = row.get('duration_seconds')
    return new_row(row.get('id'), row.get('started_at'), 'chat', level, summary,
                   tokens_in=td['tokens_in'] or 0, tokens_out=td['tokens_out'] or 0,
                   duration_ms=int(float(duration) * 1000) if duration else 0,
                   links={'chat_session': meta.get('session_id'),
                          'trace': trace_url(td['trace_id'], langfuse_host)},
                   detail=detail)


def build_testprompt_row(row: Dict[str, Any], names: Dict[str, str], is_admin: bool) -> Dict[str, Any]:
    status = row.get('status') or ''
    level = 'running' if status in ('running', 'pending') else ('error' if status in ERROR_STATUSES else 'ok')
    name = names.get(str(row.get('test_prompt_id'))) or 'Test Prompt'
    where = f" on {row['device_id']}" if row.get('device_id') else ''
    summary = f'{name}{where} — {status}'
    return new_row(row.get('id'), row.get('created_at'), 'testprompt', level, summary,
                   duration_ms=row.get('execution_time_ms') or 0,
                   links={'report': row.get('report_url'), 'testprompt': str(row.get('test_prompt_id') or '') or None},
                   detail={'question': None, 'answer': row.get('human_feedback')} if row.get('human_feedback') else None)


def script_level(row: Dict[str, Any]) -> str:
    check_type = row.get('check_type') or ''
    if check_type == 'ai_error':
        return 'error'
    if check_type == 'ai_auto_jev':  # the Jev analyzer is Sherlock's fallback
        return 'fallback'
    return 'ok'


def build_script_row(row: Dict[str, Any], is_admin: bool) -> Dict[str, Any]:
    level = script_level(row)
    comment = row.get('discard_comment') or ''
    if level == 'error' and not is_admin:
        comment = FAILED_TEXT
    verdict = 'discarded' if row.get('discard') else 'kept'
    summary = f"{row.get('script_name') or 'script'}: {verdict} — {comment}" if comment else \
        f"{row.get('script_name') or 'script'}: {verdict}"
    if level == 'error':
        summary = f"{row.get('script_name') or 'script'}: {comment}"
    detail = {'question': row.get('script_name'), 'answer': clip(comment, DETAIL_MAX)} if comment else None
    return new_row(row.get('id'), row.get('updated_at'), 'triage', level, summary,
                   links={'report': row.get('html_report_r2_url')}, detail=detail)


def build_alert_row(row: Dict[str, Any], is_admin: bool) -> Dict[str, Any]:
    verdict = row.get('discard_type') or ('discard' if row.get('discard') else 'real')
    where = '/'.join(str(x) for x in (row.get('host_name'), row.get('device_name') or row.get('device_id')) if x)
    summary = f"{row.get('incident_type') or 'alert'} on {where}: {verdict}"
    comment = row.get('discard_comment')
    return new_row(row.get('id'), row.get('updated_at'), 'triage', 'ok', summary,
                   links={'alert': str(row.get('id'))},
                   detail={'question': None, 'answer': clip(comment, DETAIL_MAX)} if comment else None)


def summarize_answers(answers: Any) -> str:
    """One short line from the typed answers of a decision ({key: {choice|value…}})."""
    data = _json(answers)
    if not isinstance(data, dict):
        return ''
    parts = []
    for key, val in list(data.items())[:4]:
        if isinstance(val, dict):
            shown = val.get('choice')
            if shown is None:
                shown = next((v for k, v in val.items() if k not in ('type', 'probabilities') and
                              isinstance(v, (str, int, float, bool))), None)
        else:
            shown = val
        if shown is not None:
            parts.append(f'{key}={clip(shown, 40)}')
    return ', '.join(parts)


def _dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return clip(text, DETAIL_MAX)


def build_decision_row(row: Dict[str, Any], part: str, is_admin: bool) -> Dict[str, Any]:
    ok = bool(row.get('ok'))
    summary = summarize_answers(row.get('answers')) or row.get('usage_key') or 'decision'
    detail = {'question': _dump(row.get('questions')), 'answer': _dump(row.get('answers'))}
    if not ok:
        if is_admin and row.get('error'):
            summary = clip(row['error'])
            detail['error'] = clip(row['error'], DETAIL_MAX)
        else:
            summary = FAILED_TEXT
    return new_row(row.get('id'), row.get('created_at'), part, 'ok' if ok else 'error',
                   f"{row.get('usage_key')}: {summary}" if ok else summary,
                   tokens_in=row.get('tokens_in') or 0, duration_ms=row.get('ms') or 0, detail=detail)


def merge_rows(groups: Iterable[List[Dict[str, Any]]], level: Optional[str] = None, q: Optional[str] = None,
               limit: int = 50) -> Dict[str, Any]:
    """Merge row lists newest first, apply the level and text filters, page by ``limit``."""
    rows = [r for g in groups for r in g]
    if level:
        rows = [r for r in rows if r['level'] == level]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in (r['summary'] or '').lower()]
    rows.sort(key=lambda r: r['ts'] or '', reverse=True)
    page = rows[:limit]
    next_before = page[-1]['ts'] if len(rows) > limit and page else None
    return {'rows': page, 'next_before': next_before}


# ------------------------------------------------------------------ overview

def group_errors(error_items: Iterable[Dict[str, Any]], is_admin: bool, limit: int = 5) -> List[Dict[str, Any]]:
    """[{ts, part, summary}] -> grouped by (part, summary), newest first, max ``limit``."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for item in error_items:
        summary = item.get('summary') if is_admin else FAILED_TEXT
        key = (item.get('part'), summary)
        g = groups.setdefault(key, {'ts': item.get('ts'), 'part': item.get('part'),
                                    'summary': clip(summary), 'count': 0})
        g['count'] += 1
        if (item.get('ts') or '') > (g['ts'] or ''):
            g['ts'] = item.get('ts')
    return sorted(groups.values(), key=lambda g: g['ts'] or '', reverse=True)[:limit]


def build_overview(*, hours: int, registry: Dict[str, Dict[str, Any]], usage: Dict[str, Dict[str, Any]],
                   part_counts: Dict[str, Dict[str, Dict[str, int]]], now_items: Dict[str, List[Dict[str, Any]]],
                   error_items: Dict[str, List[Dict[str, Any]]], last_activity: Dict[str, Optional[datetime]],
                   feedback: Dict[str, Dict[str, Any]], is_admin: bool) -> Dict[str, Any]:
    """Assemble the GET /server/agents/overview payload from already-aggregated inputs.

    ``registry`` {agent_id: {description, version, model}}; ``part_counts`` {agent: {part: {calls, errors}}};
    the ``other`` agent is returned to admins only.
    """
    agents = []
    for agent_id, spec in AGENT_SOURCES.items():
        if spec.get('admin_only') and not is_admin:
            continue
        u = usage.get(agent_id, {})
        counts = part_counts.get(agent_id, {})
        calls = int(u.get('calls', 0))
        errors = int(u.get('errors', 0))
        # Work recorded outside ai_usage_stats (script verdicts, Test Prompt runs, chat rows) counts too.
        part_calls = sum(c.get('calls', 0) for c in counts.values())
        part_errors = sum(c.get('errors', 0) for c in counts.values())
        health_calls, health_errors = max(calls, part_calls), max(errors, part_errors)
        times = [t for t in (u.get('last'), last_activity.get(agent_id)) if t]
        last = max(times) if times else None
        reg = registry.get(agent_id, {})
        fb = feedback.get(agent_id, {})
        agents.append({
            'id': agent_id, 'name': spec['name'], 'role': spec['role'],
            'description': reg.get('description'), 'version': reg.get('version'), 'model': reg.get('model'),
            'health': compute_health(health_calls, health_errors, bool(last)),
            'last_activity': iso(last),
            'now': now_items.get(agent_id, []),
            'stats': {'calls': calls, 'errors': errors, 'fallbacks': int(u.get('fallbacks', 0)),
                      'tokens_in': int(u.get('tokens_in', 0)), 'tokens_out': int(u.get('tokens_out', 0)),
                      'avg_ms': int(u['total_ms'] / u['calls']) if u.get('calls') else 0},
            'feedback': {'up': int(fb.get('up', 0)), 'down': int(fb.get('down', 0)),
                         'avg_rating': fb.get('avg_rating')},
            'parts': [{'key': p['key'], 'label': p['label'],
                       'calls': int(counts.get(p['key'], {}).get('calls', 0)),
                       'errors': int(counts.get(p['key'], {}).get('errors', 0))} for p in spec['parts']],
            'recent_errors': group_errors(error_items.get(agent_id, []), is_admin),
            'links': spec['links'],
        })
    return {'window_hours': hours, 'agents': agents}


def aggregate_feedback(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """agent_feedback rows -> {agent_id(dashboard): {up (rating>=4), down (rating<=2), avg_rating}}."""
    acc: Dict[str, List[int]] = {}
    for r in rows:
        acc.setdefault(agent_for_registry_id(r.get('agent_id')), []).append(int(r.get('rating') or 0))
    out = {}
    for agent, ratings in acc.items():
        out[agent] = {'up': sum(1 for x in ratings if x >= 4), 'down': sum(1 for x in ratings if x <= 2),
                      'avg_rating': round(sum(ratings) / len(ratings), 2) if ratings else None}
    return out


def count_chat_rows(rows: Iterable[Dict[str, Any]], now: datetime):
    """agent_execution_history window rows -> (part counts per agent, error items, last activity)."""
    counts: Dict[str, Counter] = {}
    errors: Dict[str, List[Dict[str, Any]]] = {}
    last: Dict[str, datetime] = {}
    for r in rows:
        agent = agent_for_registry_id(r.get('agent_id'))
        c = counts.setdefault(agent, Counter())
        c['calls'] += 1
        started = parse_ts(r.get('started_at'))
        if started and (agent not in last or started > last[agent]):
            last[agent] = started
        if chat_level(r, now) == 'error':
            c['errors'] += 1
            meta = _json(r.get('metadata')) or {}
            errors.setdefault(agent, []).append({'ts': iso(started), 'part': 'chat',
                                                 'summary': r.get('error_message') or meta.get('prompt') or FAILED_TEXT})
    return counts, errors, last
