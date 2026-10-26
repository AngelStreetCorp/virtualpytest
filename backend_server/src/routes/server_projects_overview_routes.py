"""
Project Overview Routes (TASK-65 G3)
=====================================

One server endpoint, six tiles, one DB read per tile. Used by `/projects/<id>`.

  GET /server/projects/<project_id>/overview?days=30

Response shape:

  {
    "project": { ...full project row incl. tags + members... },
    "tiles": {
      "scripts_count":     int,
      "runs_30d":          { "pass": int, "fail": int, "total": int },
      "last_failures":     [ {script_result_id, script_name, host_name,
                                started_at, duration_s, ...}, ... ],
      "devices":           { "count": int, "states": {"online": n,
                                                       "offline": m,
                                                       "unknown": k} },
      "ai_tokens_30d":     int,
      "active_users":      [ {team_member_id, last_seen_at, ...}, ... ]
    }
  }

Filtering
---------

Every tile is filtered by `projects_tags.tag_id IN (...)` against
`executable_tags.executable_id` (for scripts / testcases) or by `team_id` (for
AI tokens, active users, devices). The scope is additive: a script that lives in
the project's tag set counts toward the project, regardless of the user's role
outside `projects_members`.

No N+1. Each tile is one query (or one small aggregation).
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from shared.src.lib.database import projects_db, script_results_db
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import org_scope_team_ids
from backend_server.src.routes.server_projects_routes import (
    caller_project_role,
    can_edit_project,
)


logger = logging.getLogger(__name__)


# Module-level blueprint (Flask). Imported from app.py and registered under
# url_prefix '/server/projects' so the paths mirror `server_projects_routes.py`.
from flask import Blueprint
server_projects_overview_bp = Blueprint(
    'server_projects_overview',
    __name__,
    url_prefix='/server/projects',
)


def _supabase():
    return get_supabase_client()


def _in_team_scope(team_id: str) -> bool:
    """Caller can act on this team (admin bypass via `scope is None`)."""
    scope = org_scope_team_ids()
    return scope is None or str(team_id) in scope


# ---------------------------------------------------------------------------
# Tile helpers — one DB read each
# ---------------------------------------------------------------------------
def _scripts_count(project_id: str, tag_ids: list) -> int:
    """Distinct virtual scripts tagged with one of `tag_ids`."""
    if not tag_ids:
        return 0
    sb = _supabase()
    try:
        res = (
            sb.table('executable_tags')
            .select('executable_id', count='exact')
            .eq('executable_type', 'script')
            .in_('tag_id', tag_ids)
            .execute()
        )
        return res.count or len(res.data or [])
    except Exception as e:
        logger.error("[@overview] _scripts_count error: %s", e)
        return 0


def _runs_30d(team_id: str, tag_ids: list, days: int) -> dict:
    """Pass / fail totals in the last `days` days, filtered to project-scope scripts.

    Scope derivation is in script_ids; we use the JSON path because `script_results`
    is keyed by `script_name` (text), and `executable_tags` for scripts also uses
    `script.name` as the executor_id. We resolve `tag_ids -> script_names`, then
    `script_results.script_name IN (...)` AND `started_at > cutoff`.

    Script results may carry a `virtual_script_id`; we don't have a direct index on
    that, and `script_name` is the human-key. Acceptable for a 30-day tile.
    """
    if not tag_ids:
        return {'pass': 0, 'fail': 0, 'total': 0}

    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        # Step A: tag_ids -> script names (small set; <= a few hundred per project)
        tag_res = (
            sb.table('executable_tags')
            .select('executable_id')
            .eq('executable_type', 'script')
            .in_('tag_id', tag_ids)
            .execute()
        )
        script_names = sorted({(r.get('executable_id') or '') for r in (tag_res.data or []) if r.get('executable_id')})
        if not script_names:
            return {'pass': 0, 'fail': 0, 'total': 0}

        # Step B: count pass + fail in the last `days` for those script names.
        # We don't pull every row; PostgREST's count='exact' with a range filter
        # is cheap on `idx_script_results_team_started` (script_results_db).
        pass_res = (
            sb.table('script_results')
            .select('id', count='exact')
            .eq('team_id', team_id)
            .eq('success', True)
            .gte('started_at', cutoff)
            .in_('script_name', script_names)
            .execute()
        )
        fail_res = (
            sb.table('script_results')
            .select('id', count='exact')
            .eq('team_id', team_id)
            .eq('success', False)
            .gte('started_at', cutoff)
            .in_('script_name', script_names)
            .execute()
        )
        passed = pass_res.count if pass_res.count is not None else 0
        failed = fail_res.count if fail_res.count is not None else 0
        return {'pass': passed, 'fail': failed, 'total': passed + failed}
    except Exception as e:
        logger.error("[@overview] _runs_30d error: %s", e)
        return {'pass': 0, 'fail': 0, 'total': 0}


def _last_failures(team_id: str, tag_ids: list, limit: int = 10) -> list:
    """Top `limit` failed runs in scope, newest first."""
    if not tag_ids:
        return []
    sb = _supabase()
    try:
        tag_res = (
            sb.table('executable_tags')
            .select('executable_id')
            .eq('executable_type', 'script')
            .in_('tag_id', tag_ids)
            .execute()
        )
        script_names = sorted({(r.get('executable_id') or '') for r in (tag_res.data or []) if r.get('executable_id')})
        if not script_names:
            return []

        res = (
            sb.table('script_results')
            .select('id, script_name, host_name, device_name, started_at, completed_at, environment')
            .eq('team_id', team_id)
            .eq('success', False)
            .in_('script_name', script_names)
            .order('started_at', desc=True)
            .limit(limit)
            .execute()
        )
        out = []
        for r in res.data or []:
            started = r.get('started_at')
            completed = r.get('completed_at')
            duration_s = None
            try:
                if started and completed:
                    duration_s = round(
                        (datetime.fromisoformat(completed.replace('Z', '+00:00'))
                         - datetime.fromisoformat(started.replace('Z', '+00:00'))).total_seconds(),
                        1,
                    )
            except Exception:
                pass
            out.append({
                'script_result_id': r.get('id'),
                'script_name': r.get('script_name'),
                'host_name': r.get('host_name'),
                'device_name': r.get('device_name'),
                'environment': r.get('environment'),
                'started_at': started,
                'duration_s': duration_s,
            })
        return out
    except Exception as e:
        logger.error("[@overview] _last_failures error: %s", e)
        return []


def _devices(team_id: str, days: int) -> dict:
    """Devices that ran a project-scope script in the last `days` days, grouped by
    a coarse online/offline/unknown state.

    State derivation: a device with a successful run in the last 5 minutes is
    `online`; a successful run in the last 30 minutes is `offline`; otherwise
    `unknown`. Cheap SQL aggregation (one query).
    """
    sb = _supabase()
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cutoff_5m = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    cutoff_30m = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    try:
        # Distinct devices in the team that ran something in the window.
        res = (
            sb.table('script_results')
            .select('device_name, host_name, success, started_at')
            .eq('team_id', team_id)
            .gte('started_at', cutoff_30d)
            .not_.is_('device_name', 'null')
            .execute()
        )
        # Group by (host_name, device_name) -> most-recent success timestamp.
        latest: dict = {}
        for r in res.data or []:
            key = (r.get('host_name'), r.get('device_name'))
            ts = r.get('started_at')
            if not (key[0] and key[1] and ts):
                continue
            if key not in latest or ts > latest[key]['started_at']:
                latest[key] = {
                    'host_name': key[0],
                    'device_name': key[1],
                    'started_at': ts,
                    'success': bool(r.get('success')),
                }
        online = 0
        offline = 0
        unknown = 0
        for v in latest.values():
            ts = v['started_at']
            if ts >= cutoff_5m:
                online += 1
            elif ts >= cutoff_30m:
                offline += 1
            else:
                unknown += 1
        return {
            'count': len(latest),
            'states': {'online': online, 'offline': offline, 'unknown': unknown},
        }
    except Exception as e:
        logger.error("[@overview] _devices error: %s", e)
        return {'count': 0, 'states': {'online': 0, 'offline': 0, 'unknown': 0}}


def _ai_tokens_30d(team_id: str, days: int) -> int:
    """Sum of tokens_in + tokens_out from ai_usage_stats in the last `days` days."""
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        # Sum in SQL via PostgREST: `select=sum:tokens_in.sum:tokens_out` is the
        # older shape; the JS SDK surface a Python-side reduction by pulling each
        # row (the table is bucketed hourly, so O(#days * #usage_keys) rows max).
        # We cap at 5000 rows — well over a typical 30 d * 6 endpoints load.
        res = (
            sb.table('ai_usage_stats')
            .select('tokens_in, tokens_out')
            .eq('team_id', team_id)
            .gte('bucket', cutoff)
            .limit(5000)
            .execute()
        )
        total = 0
        for r in (res.data or []):
            total += int(r.get('tokens_in') or 0) + int(r.get('tokens_out') or 0)
        return total
    except Exception as e:
        logger.error("[@overview] _ai_tokens_30d error: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@server_projects_overview_bp.route('/<project_id>/overview', methods=['GET'])
@handle_route_exceptions('server_projects_overview:get_overview')
def get_project_overview(project_id: str):
    """Per-project dashboard data. Six tiles, one DB read each (plus one for the
    project row itself, and one for `executable_tags` -> script names shared by
    `_runs_30d` and `_last_failures`).

    Caller must be inside the project's team scope (admin bypass via the global
    org_scope helper).
    """
    days = 30
    try:
        days = int(request.args.get('days', '30'))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))

    project = projects_db.get_project(project_id)
    if project is None:
        return jsonify({"error": "Project not found"}), 404
    if not _in_team_scope(project['team_id']):
        return jsonify({"error": "Project not found"}), 404

    tag_ids = [t['tag_id'] for t in project.get('tags') or []]

    # Six tiles, six DB reads (plus the shared `tags -> script_name` look-up).
    scripts_count = _scripts_count(tag_ids=tag_ids, project_id=project_id)
    runs = _runs_30d(team_id=project['team_id'], tag_ids=tag_ids, days=days)
    failures = _last_failures(team_id=project['team_id'], tag_ids=tag_ids, limit=10)
    devices = _devices(team_id=project['team_id'], days=days)
    ai_tokens = _ai_tokens_30d(team_id=project['team_id'], days=days)
    active = projects_db.list_active_users(project['team_id'])

    # BUG-0577 — caller's edit rights on this project. The route layer is the
    # single source of truth (admin OR owner = true) and the frontend mirrors it
    # to gate the Rename / Delete buttons on the ProjectDetail page.
    my_role = caller_project_role(project_id)
    can_edit = can_edit_project(project_id)

    return jsonify({
        'project': project,
        'days': days,
        'tiles': {
            'scripts_count': scripts_count,
            'runs_30d': runs,
            'last_failures': failures,
            'devices': devices,
            'ai_tokens_30d': ai_tokens,
            'active_users': active,
        },
        'permissions': {
            # 'owner' | 'viewer' | None — None means "no row in projects_members
            # for the caller", which can still be an admin (then `can_edit` is true).
            'my_role': my_role,
            # True when caller can PATCH / DELETE this project (admin OR owner).
            'can_edit': can_edit,
        },
    }), 200