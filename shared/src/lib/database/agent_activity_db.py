"""
Agent Activity Database Operations (TASK-54)

Read queries behind the Agent Dashboard (usage rollups, decisions, chat history, script and alert
verdicts, Test Prompt runs), plus the ``agent_turns`` chat transcript table and ``agent_feedback``.

Rules:
- Every query filters by ``team_id``. ``ai_usage_stats`` / ``ai_decisions`` rows with ``team_id IS NULL``
  are platform-wide host calls: they are included only when ``include_platform`` is True (admins).
- ``alerts`` has no ``team_id`` column; it is scoped by ``host_names`` (the hosts of this server).
- Every query is bounded: a time window (at most ``MAX_DAYS``) and a row limit.
- Read functions raise on a database error (the route reports it); write helpers used on the chat
  path (``insert_turns``, ``prune_turns``) never raise.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

MAX_DAYS = 30
PAGE = 1000
USAGE_MAX_ROWS = 20000
DECISIONS_MAX_ROWS = 5000
MAX_LIMIT = 200
TURNS_RETENTION_DAYS = 30
AI_CHECK_TYPE_LIKE = 'ai*'  # script_results.check_type: ai_auto_openrouter, ai_auto_jev, ai_error, ai_strategy_skip


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def clamp_hours(hours: Any, default: int = 24) -> int:
    try:
        value = int(hours)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, MAX_DAYS * 24))


def since_iso(hours: int, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=clamp_hours(hours))).isoformat()


def _limit(limit: Any, default: int = 50) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, MAX_LIMIT))


def _team_scope(query, team_id: str, include_platform: bool):
    """team_id uuid column: this team, plus NULL (platform) rows for admins."""
    if not team_id:
        raise ValueError('team_id is required')
    if include_platform:
        return query.or_(f'team_id.eq.{team_id},team_id.is.null')
    return query.eq('team_id', team_id)


def _paged(build, max_rows: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    while len(rows) < max_rows:
        end = min(len(rows) + PAGE, max_rows) - 1
        page = build().range(len(rows), end).execute().data or []
        rows.extend(page)
        if len(page) < PAGE:
            break
    return rows


# ---------------------------------------------------------------- usage / decisions

def list_usage_stats(team_id: str, since: str, include_platform: bool = False,
                     max_rows: int = USAGE_MAX_ROWS) -> List[Dict[str, Any]]:
    """Hourly ``ai_usage_stats`` rollup rows since ``since`` (aggregate in Python)."""
    def build():
        q = get_supabase().table('ai_usage_stats').select(
            'bucket,usage_key,calls,errors,fallbacks,total_ms,tokens_in,tokens_out,team_id')
        return _team_scope(q, team_id, include_platform).gte('bucket', since).order('bucket', desc=True)
    return _paged(build, max_rows)


def list_decisions_window(team_id: str, since: str, include_platform: bool = False,
                          max_rows: int = DECISIONS_MAX_ROWS) -> List[Dict[str, Any]]:
    """Narrow ``ai_decisions`` columns for aggregation (counts, failures, outcomes) since ``since``."""
    def build():
        q = get_supabase().table('ai_decisions').select(
            'id,usage_key,ok,ms,tokens_in,error,created_at,outcome_at')
        return _team_scope(q, team_id, include_platform).gte('created_at', since).order('created_at', desc=True)
    return _paged(build, max_rows)


def list_decisions_for_logs(team_id: str, prefixes: List[str], since: str, before: Optional[str] = None,
                            include_platform: bool = False, ok: Optional[bool] = None,
                            limit: int = 50) -> List[Dict[str, Any]]:
    """Newest decisions whose usage_key starts with one of ``prefixes`` (boundary filtering is done by the caller)."""
    if not prefixes:
        return []
    q = get_supabase().table('ai_decisions').select(
        'id,usage_key,model,ok,error,ms,tokens_in,questions,answers,refs,outcome,created_at')
    q = _team_scope(q, team_id, include_platform).gte('created_at', since)
    q = q.or_(','.join(f'usage_key.like.{p}*' for p in prefixes))
    if before:
        q = q.lt('created_at', before)
    if ok is not None:
        q = q.eq('ok', ok)
    return q.order('created_at', desc=True).limit(_limit(limit)).execute().data or []


# ---------------------------------------------------------------- chat history

def list_executions(team_id: str, agent_ids: List[str], since: str, before: Optional[str] = None,
                    limit: int = 50) -> List[Dict[str, Any]]:
    """``agent_execution_history`` rows of this team for the given registry agent ids, newest first."""
    if not team_id or not agent_ids:
        return []
    q = (get_supabase().table('agent_execution_history')
         .select('id,instance_id,agent_id,task_id,event_type,started_at,completed_at,duration_seconds,'
                 'status,tool_calls,error_message,token_usage,metadata')
         .eq('team_id', str(team_id)).in_('agent_id', agent_ids).gte('started_at', since))
    if before:
        q = q.lt('started_at', before)
    return q.order('started_at', desc=True).limit(_limit(limit)).execute().data or []


def list_open_executions(team_id: str, since: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Executions that started after ``since`` and have no ``completed_at`` (running now)."""
    if not team_id:
        return []
    return (get_supabase().table('agent_execution_history')
            .select('id,agent_id,task_id,started_at,metadata')
            .eq('team_id', str(team_id)).is_('completed_at', 'null').gte('started_at', since)
            .order('started_at', desc=True).limit(_limit(limit)).execute().data or [])


def list_executions_window(team_id: str, since: str, max_rows: int = 5000) -> List[Dict[str, Any]]:
    """Narrow execution rows of all agents for the overview counts."""
    def build():
        return (get_supabase().table('agent_execution_history')
                .select('id,agent_id,started_at,completed_at,status,error_message,token_usage,metadata')
                .eq('team_id', str(team_id)).gte('started_at', since).order('started_at', desc=True))
    return _paged(build, max_rows) if team_id else []


# ---------------------------------------------------------------- verdicts

SCRIPT_VERDICT_COLUMNS = ('id,script_name,script_type,host_name,device_name,userinterface_name,success,checked,'
                          'check_type,discard,discard_comment,html_report_r2_url,updated_at')


def list_script_ai_verdicts(team_id: str, since: str, before: Optional[str] = None,
                            limit: int = 50) -> List[Dict[str, Any]]:
    """script_results rows judged by Sherlock (``check_type`` starting ``ai``), newest verdict first."""
    if not team_id:
        return []
    q = (get_supabase().table('script_results').select(SCRIPT_VERDICT_COLUMNS)
         .eq('team_id', str(team_id)).eq('checked', True).like('check_type', AI_CHECK_TYPE_LIKE)
         .gte('updated_at', since))
    if before:
        q = q.lt('updated_at', before)
    return q.order('updated_at', desc=True).limit(_limit(limit)).execute().data or []


def list_script_ai_verdicts_window(team_id: str, since: str, max_rows: int = 5000) -> List[Dict[str, Any]]:
    def build():
        return (get_supabase().table('script_results').select('id,check_type,discard,discard_comment,script_name,updated_at')
                .eq('team_id', str(team_id)).eq('checked', True).like('check_type', AI_CHECK_TYPE_LIKE)
                .gte('updated_at', since).order('updated_at', desc=True))
    return _paged(build, max_rows) if team_id else []


ALERT_VERDICT_COLUMNS = ('id,host_name,device_id,device_name,incident_type,status,checked,check_type,discard,'
                         'discard_type,discard_comment,updated_at')


def list_alert_ai_verdicts(host_names: List[str], since: str, before: Optional[str] = None,
                           limit: int = 50) -> List[Dict[str, Any]]:
    """alerts judged by Nightwatch (``check_type='ai'``). ``alerts`` has no team_id: scoped by host."""
    if not host_names:
        return []
    q = (get_supabase().table('alerts').select(ALERT_VERDICT_COLUMNS)
         .in_('host_name', host_names).eq('check_type', 'ai').gte('updated_at', since))
    if before:
        q = q.lt('updated_at', before)
    return q.order('updated_at', desc=True).limit(_limit(limit)).execute().data or []


def list_alert_ai_verdicts_window(host_names: List[str], since: str, max_rows: int = 5000) -> List[Dict[str, Any]]:
    if not host_names:
        return []

    def build():
        return (get_supabase().table('alerts').select('id,discard,updated_at')
                .in_('host_name', host_names).eq('check_type', 'ai').gte('updated_at', since)
                .order('updated_at', desc=True))
    return _paged(build, max_rows)


# ---------------------------------------------------------------- Test Prompt runs

TESTPROMPT_COLUMNS = ('id,test_prompt_id,host_name,device_id,status,script_result_id,report_url,'
                      'execution_time_ms,human_feedback,created_at,executed_by,run_mode')


def list_testprompt_executions(team_id: str, since: str, before: Optional[str] = None,
                               limit: int = 50) -> List[Dict[str, Any]]:
    if not team_id:
        return []
    q = (get_supabase().table('test_prompt_executions').select(TESTPROMPT_COLUMNS)
         .eq('team_id', str(team_id)).gte('created_at', since))
    if before:
        q = q.lt('created_at', before)
    return q.order('created_at', desc=True).limit(_limit(limit)).execute().data or []


def list_open_testprompt_executions(team_id: str, since: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not team_id:
        return []
    return (get_supabase().table('test_prompt_executions').select(TESTPROMPT_COLUMNS)
            .eq('team_id', str(team_id)).in_('status', ['running', 'pending']).gte('created_at', since)
            .order('created_at', desc=True).limit(_limit(limit)).execute().data or [])


def get_testprompt_names(team_id: str, prompt_ids: List[str]) -> Dict[str, str]:
    ids = sorted({str(i) for i in prompt_ids if i})
    if not team_id or not ids:
        return {}
    rows = (get_supabase().table('test_prompts').select('id,name').eq('team_id', str(team_id))
            .in_('id', ids).execute().data or [])
    return {str(r['id']): r.get('name') or '' for r in rows}


# ---------------------------------------------------------------- agent_turns

def insert_turns(rows: List[Dict[str, Any]]) -> bool:
    """Insert transcript rows (each must carry ``team_id``). Never raises."""
    rows = [r for r in rows if r.get('team_id')]
    if not rows:
        return False
    try:
        get_supabase().table('agent_turns').insert(rows).execute()
        return True
    except Exception as e:
        print(f"[@db:agent_activity:insert_turns] Error: {e}")
        return False


def next_turn_index(team_id: str, session_id: str) -> int:
    """0 for a new session, else max(turn_index)+1. Never raises (0 on error)."""
    try:
        rows = (get_supabase().table('agent_turns').select('turn_index').eq('team_id', str(team_id))
                .eq('session_id', session_id).order('turn_index', desc=True).limit(1).execute().data or [])
        return int(rows[0]['turn_index']) + 1 if rows else 0
    except Exception as e:
        print(f"[@db:agent_activity:next_turn_index] Error: {e}")
        return 0


def list_turns(team_id: str, session_id: str, agent_id: Optional[str] = None,
               limit: int = 200) -> List[Dict[str, Any]]:
    """Transcript of one chat session in order."""
    if not team_id or not session_id:
        return []
    q = (get_supabase().table('agent_turns').select(
        'id,agent_id,session_id,task_id,turn_index,role,content,tool_calls,tokens_in,tokens_out,trace_id,created_at')
        .eq('team_id', str(team_id)).eq('session_id', session_id))
    if agent_id:
        q = q.eq('agent_id', agent_id)
    return q.order('turn_index').limit(max(1, min(int(limit), 500))).execute().data or []


def list_turns_by_task(team_id: str, task_ids: List[str]) -> List[Dict[str, Any]]:
    """Turns (user + agent) of the given chat tasks, for the question/answer detail of a log row."""
    ids = sorted({str(t) for t in task_ids if t})
    if not team_id or not ids:
        return []
    return (get_supabase().table('agent_turns').select(
        'task_id,role,content,tool_calls,tokens_in,tokens_out,trace_id,created_at')
        .eq('team_id', str(team_id)).in_('task_id', ids[:MAX_LIMIT]).order('turn_index')
        .limit(MAX_LIMIT * 4).execute().data or [])


def prune_turns(team_id: str, older_than_days: int = TURNS_RETENTION_DAYS) -> int:
    """Delete that team's turns older than N days. Never raises."""
    if not team_id:
        return 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(older_than_days))).isoformat()
        result = (get_supabase().table('agent_turns').delete().eq('team_id', str(team_id))
                  .lt('created_at', cutoff).execute())
        return len(result.data or [])
    except Exception as e:
        print(f"[@db:agent_activity:prune_turns] Error: {e}")
        return 0


# ---------------------------------------------------------------- agent_feedback

def insert_feedback(team_id: str, agent_id: str, agent_version: str, rating: int,
                    comment: Optional[str] = None, task_description: Optional[str] = None,
                    execution_id: Optional[str] = None, user_id: Optional[str] = None,
                    feedback_type: str = 'task_completion') -> Optional[str]:
    """Insert one feedback row (``rating`` 1-5). Returns the id or None."""
    if not team_id or rating < 1 or rating > 5:
        return None
    row = {'agent_id': agent_id, 'agent_version': agent_version or 'unknown', 'rating': rating,
           'comment': comment, 'task_description': task_description, 'team_id': str(team_id),
           'feedback_type': feedback_type}
    if execution_id:
        row['execution_id'] = execution_id
    if user_id:
        row['user_id'] = user_id
    result = get_supabase().table('agent_feedback').insert(row).execute()
    return str(result.data[0]['id']) if result.data else None


def find_latest_feedback_by_ref(team_id: str, agent_id: str, message_ref: str) -> Optional[str]:
    """Find the id of the most recent feedback row for ``(team_id, agent_id)`` whose comment
    ends with ``[message_ref]`` (``message_ref`` is the bracketed session/task/msg marker the
    route stamps in front of the user text). Returns None when no row matches. Read-only."""
    if not team_id or not agent_id or not message_ref:
        return None
    marker = f'[{message_ref}]'
    try:
        result = (get_supabase().table('agent_feedback').select('id,comment,created_at')
                  .eq('team_id', str(team_id)).eq('agent_id', agent_id)
                  .ilike('comment', f'%{marker}').order('created_at', desc=True).limit(1).execute())
    except Exception:
        return None
    rows = result.data or []
    return str(rows[0]['id']) if rows else None


def update_feedback_comment(feedback_id: str, team_id: str, agent_id: str,
                            comment: Optional[str], rating: Optional[int] = None,
                            keep_existing_comment: bool = False) -> bool:
    """Update the comment (and optionally the rating) of one feedback row, scoped by
    ``team_id`` and ``agent_id`` so a caller cannot rewrite another team's data. When
    ``keep_existing_comment`` is True, ``comment`` is ignored and only the rating is touched
    (used when the caller re-clicks a thumb without sending a new comment). Returns True on
    success."""
    if not feedback_id or not team_id or not agent_id:
        return False
    if keep_existing_comment:
        update: Dict[str, Any] = {}
    else:
        update = {'comment': comment}
    if rating is not None and 1 <= int(rating) <= 5:
        update['rating'] = int(rating)
    if not update:
        return False
    try:
        result = (get_supabase().table('agent_feedback').update(update)
                  .eq('id', feedback_id).eq('team_id', str(team_id))
                  .eq('agent_id', agent_id).execute())
    except Exception:
        return False
    return bool(result.data)


def list_feedback_window(team_id: str, since: str, max_rows: int = 5000) -> List[Dict[str, Any]]:
    def build():
        return (get_supabase().table('agent_feedback').select('agent_id,rating,created_at')
                .eq('team_id', str(team_id)).gte('created_at', since).order('created_at', desc=True))
    return _paged(build, max_rows) if team_id else []
