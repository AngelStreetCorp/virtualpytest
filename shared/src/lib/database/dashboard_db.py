"""
Dashboard database reads (TASK-123).

Read-only, one bounded query per function so the dashboard endpoints stay cheap behind the
single WAN gevent worker. Every team-owned query filters by team_id. No new tables.
"""

from typing import Any, Dict, List

from shared.src.lib.utils.supabase_utils import get_supabase_client

_RESULT_COLUMNS = 'id,script_name,host_name,device_name,success,started_at,completed_at,error_msg'
# PostgREST returns at most this many rows per request (max_rows), whatever .limit() asks for.
_PAGE = 1000


def get_supabase():
    return get_supabase_client()


def get_results_since(team_id: str, since_iso: str, limit: int = 20000) -> List[Dict[str, Any]]:
    """Newest-first script results created since `since_iso` (discarded rows excluded), paged past the
    1000-row response cap so 7 d / 30 d counts are not cut at the newest 1000 runs (BUG-0614)."""
    rows: List[Dict[str, Any]] = []
    while len(rows) < limit:
        start = len(rows)
        page = (get_supabase().table('script_results').select(_RESULT_COLUMNS)
                .eq('team_id', team_id).eq('discard', False)
                .gte('created_at', since_iso)
                .order('created_at', desc=True)
                .range(start, min(start + _PAGE, limit) - 1).execute()).data or []
        rows.extend(page)
        if len(page) < min(_PAGE, limit - start):
            break
    return rows


def get_recent_results(team_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """Newest-first script results regardless of age (flaky detection looks at the last N runs per script)."""
    result = (get_supabase().table('script_results').select(_RESULT_COLUMNS)
              .eq('team_id', team_id).eq('discard', False)
              .order('created_at', desc=True).limit(limit).execute())
    return result.data or []


def get_active_executions(team_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """deployment_executions that are running or queued, with their deployment (team-scoped through the join)."""
    result = (get_supabase().table('deployment_executions')
              .select('status,started_at,scheduled_at,script_result_id,'
                      'deployments!inner(team_id,host_name,device_id,script_name,name)')
              .eq('deployments.team_id', team_id)
              .in_('status', ['running', 'queued'])
              .order('scheduled_at', desc=True).limit(limit).execute())
    return result.data or []


def get_active_deployments(team_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    result = (get_supabase().table('deployments')
              .select('id,name,status,cron_expression,max_executions,scheduled_today')
              .eq('team_id', team_id).eq('status', 'active')
              .limit(limit).execute())
    return result.data or []


def get_host_status_rows() -> List[Dict[str, Any]]:
    """analytics_host_status is a global monitoring view (no team column), as the Analytics > System tab reads it."""
    result = (get_supabase().table('analytics_host_status')
              .select('host_name,reachability,disk_percent').limit(2000).execute())
    return result.data or []
