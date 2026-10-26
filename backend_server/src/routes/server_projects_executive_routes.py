"""
Project Executive Routes (TASK-65 G4)
======================================

Manager view: a one-screen stand-up view per project. Different from the
per-project dashboard (G3) by leaning on fewer tiles with stronger "is this OK?"
signals and no per-script drill-down.

  GET /server/projects/<project_id>/executive?days=30

Response shape:

  {
    "project":  { ...full project row incl. owner_count + viewer_count... },
    "days":     int,
    "tiles": {
      "health": {
        "level":   "green" | "yellow" | "red",
        "current": "<pct>",
        "previous": "<pct>",
        "delta_pp": <number>
      },
      "pass_rate_trend": [
        { "day": "YYYY-MM-DD", "pass": int, "fail": int, "total": int,
          "pass_rate": float_in_0_100_or_null }, ...            # length == days
      ],
      "top_failures":     [ { script_name, failure_count, last_failure_at,
                              last_failure_result_id, last_failure_report_url }, ... ],
      "members":          {
        "owners":  [ { team_member_id, display_name, role: "owner" }, ... ],
        "viewers": [ { team_member_id, display_name, role: "viewer" }, ... ],
        "can_add": bool,    # caller is admin OR project owner -> can add members
        "can_remove": bool
      }
    }
  }

Access
------
Caller can view when they are:
  * a team member of the project's team (org_scope_team_ids), OR
  * a platform admin.
`members.can_add` / `members.can_remove` are caller-scoped flags (admin OR
project-owner) for the UI to hide / show the "Add" / "Remove" actions.

Performance: at most 4 small reads (script_results pass/fail counts, the trend
row pull, the previous-window pull, the projects_members
list + team_members join for display names). No N+1, no joins across tiles.
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from shared.src.lib.database import projects_db
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import (
    caller_is_admin,
    org_scope_team_ids,
)


logger = logging.getLogger(__name__)


server_projects_executive_bp = Blueprint(
    'server_projects_executive',
    __name__,
    url_prefix='/server/projects',
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _supabase():
    return get_supabase_client()


def _in_team_scope(team_id: str) -> bool:
    """Caller can act on this team (admin bypass via `scope is None`)."""
    scope = org_scope_team_ids()
    return scope is None or str(team_id) in scope


def _empty_buckets(days: int):
    """Zeroed per-day buckets for the 30-day trend when nothing matches."""
    today = datetime.now(timezone.utc).date()
    return [
        {
            'day': (today - timedelta(days=days - 1 - i)).isoformat(),
            'pass': 0,
            'fail': 0,
            'total': 0,
            'pass_rate': None,
        }
        for i in range(days)
    ]


def _script_names_for_project(tag_ids):
    """Return the set of script names referenced by the project's tag set.

    Used by every tile that filters `script_results` (pass-rate trend, top
    failures, last runs).
    """
    if not tag_ids:
        return []
    sb = _supabase()
    try:
        res = (
            sb.table('executable_tags')
            .select('executable_id')
            .eq('executable_type', 'script')
            .in_('tag_id', tag_ids)
            .execute()
        )
        return sorted({
            (r.get('executable_id') or '')
            for r in (res.data or [])
            if r.get('executable_id')
        })
    except Exception as e:
        logger.error("[@exec] _script_names_for_project error: %s", e)
        return []


# ---------------------------------------------------------------------------
# Tile 1 — Health (green/yellow/red)
# ---------------------------------------------------------------------------
def _health(pass_rate_30d: float, pass_rate_prev_30d: float) -> dict:
    """Map pass-rate deltas to a 3-bucket health signal.

    Rules (per brief §10 / tile 1):
      * Green : pass_rate_30d - pass_rate_prev_30d >= +2pp  OR  pass_rate_30d >= 95%
      * Yellow: pass_rate_30d >= 85% and not Green / Red
      * Red   : anything else (pass_rate_30d < 85%)
    """
    delta_pp = round(pass_rate_30d - pass_rate_prev_30d, 2)
    if delta_pp >= 2.0 or pass_rate_30d >= 95.0:
        level = 'green'
    elif pass_rate_30d >= 85.0:
        level = 'yellow'
    else:
        level = 'red'
    return {
        'level': level,
        'current': round(pass_rate_30d, 2),
        'previous': round(pass_rate_prev_30d, 2),
        'delta_pp': delta_pp,
    }


# ---------------------------------------------------------------------------
# Tile 2 — Pass rate trend (daily buckets for `days` days)
# ---------------------------------------------------------------------------
def _pass_rate_trend(team_id: str, script_names: list, days: int) -> list:
    """Return a list of length `days` (oldest -> newest).

    Each entry: { day, pass, fail, total, pass_rate } where pass_rate is 0..100
    (or null when total == 0).
    """
    if not script_names:
        return _empty_buckets(days)

    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        # Pull only the columns we need; bucketing happens client-side. The
        # 30-day * project-scope row set is small enough to fetch in one read.
        res = (
            sb.table('script_results')
            .select('success, started_at')
            .eq('team_id', team_id)
            .in_('script_name', script_names)
            .gte('started_at', cutoff)
            .execute()
        )
        buckets: dict = {}
        for r in (res.data or []):
            started = r.get('started_at')
            if not started:
                continue
            day = started[:10]  # YYYY-MM-DD
            b = buckets.setdefault(day, {'pass': 0, 'fail': 0, 'total': 0})
            if r.get('success'):
                b['pass'] += 1
            else:
                b['fail'] += 1
            b['total'] += 1

        today = datetime.now(timezone.utc).date()
        out = []
        for i in range(days):
            d = (today - timedelta(days=days - 1 - i)).isoformat()
            b = buckets.get(d, {'pass': 0, 'fail': 0, 'total': 0})
            pr = (b['pass'] / b['total'] * 100.0) if b['total'] else None
            out.append({
                'day': d,
                'pass': b['pass'],
                'fail': b['fail'],
                'total': b['total'],
                'pass_rate': round(pr, 2) if pr is not None else None,
            })
        return out
    except Exception as e:
        logger.error("[@exec] _pass_rate_trend error: %s", e)
        return _empty_buckets(days)


def _pass_rate_prev_window(team_id: str, script_names: list, days: int) -> float:
    """Pass rate over the prior `days`-long window (the window immediately
    preceding the current one). Returns 0..100."""
    if not script_names:
        return 0.0
    sb = _supabase()
    now = datetime.now(timezone.utc)
    cur_cutoff = now - timedelta(days=days)
    prev_start = now - timedelta(days=days * 2)
    try:
        res = (
            sb.table('script_results')
            .select('success')
            .eq('team_id', team_id)
            .gte('started_at', prev_start.isoformat())
            .lt('started_at', cur_cutoff.isoformat())
            .in_('script_name', script_names)
            .limit(5000)
            .execute()
        )
        prev_pass = prev_total = 0
        for r in (res.data or []):
            prev_total += 1
            if r.get('success'):
                prev_pass += 1
        return (prev_pass / prev_total * 100.0) if prev_total else 0.0
    except Exception as e:
        logger.error("[@exec] _pass_rate_prev_window error: %s", e)
        return 0.0


# ---------------------------------------------------------------------------
# Tile 3 — Top 5 failures (script-name aggregation, last failure timestamp)
# ---------------------------------------------------------------------------
def _top_failures(team_id: str, script_names: list, limit: int = 5) -> list:
    if not script_names:
        return []
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        res = (
            sb.table('script_results')
            .select('id, script_name, started_at, html_report_r2_url')
            .eq('team_id', team_id)
            .eq('success', False)
            .gte('started_at', cutoff)
            .in_('script_name', script_names)
            .order('started_at', desc=True)
            .limit(500)  # cap; aggregation is approximate (top of window)
            .execute()
        )
        agg: dict = {}
        for r in (res.data or []):
            name = r.get('script_name') or ''
            if not name:
                continue
            entry = agg.setdefault(name, {'failure_count': 0, 'last_failure_at': None,
                                          'last_failure_result_id': None, 'last_failure_report_url': None})
            entry['failure_count'] += 1
            ts = r.get('started_at')
            if ts and (entry['last_failure_at'] is None or ts > entry['last_failure_at']):
                entry['last_failure_at'] = ts
                entry['last_failure_result_id'] = r.get('id')
                entry['last_failure_report_url'] = r.get('html_report_r2_url')
        ranked = sorted(agg.items(), key=lambda kv: kv[1]['failure_count'], reverse=True)[:limit]
        return [
            {'script_name': name, **vals}
            for name, vals in ranked
        ]
    except Exception as e:
        logger.error("[@exec] _top_failures error: %s", e)
        return []


# ---------------------------------------------------------------------------
# Tile 6 — Members (owner + viewer chips, caller-scoped add/remove flag)
# ---------------------------------------------------------------------------
def _members(project_id: str) -> dict:
    """Return the project's owner + viewer chips with caller-scoped flags."""
    members_raw = projects_db.list_project_members(project_id)
    if not members_raw:
        owners: list = []
        viewers: list = []
    else:
        sb = _supabase()
        # Pull each member's profile in one batched read (by team_member_id).
        tm_ids = [m.get('team_member_id') for m in members_raw if m.get('team_member_id')]
        tm_rows: dict = {}
        if tm_ids:
            try:
                tm_res = (
                    sb.table('team_members')
                    .select('id, user_id, profile:profiles(id, display_name, email)')
                    .in_('id', tm_ids)
                    .execute()
                )
                for r in (tm_res.data or []):
                    tm_rows[r.get('id')] = r
            except Exception as e:
                logger.error("[@exec] members profile join error: %s", e)

        owners = []
        viewers = []
        for m in members_raw:
            tm_id = m.get('team_member_id')
            if not tm_id:
                continue
            tm_row = tm_rows.get(tm_id) or {}
            prof = tm_row.get('profile') or {}
            display_name = (
                prof.get('display_name')
                or prof.get('email')
                or tm_row.get('user_id')
                or tm_id
            )
            target = owners if m.get('role') == 'owner' else viewers
            target.append({
                'team_member_id': tm_id,
                'display_name': display_name,
                'role': m.get('role'),
            })

    return {
        'owners': owners,
        'viewers': viewers,
        'can_add': _is_project_owner(project_id),
        'can_remove': _is_project_owner(project_id),
    }


def _is_project_owner(project_id: str) -> bool:
    """True when caller is admin OR has a `projects_members` row with role='owner'."""
    if caller_is_admin():
        return True
    from flask import request as _req
    user_id = getattr(_req, 'user_id', None)
    if not user_id:
        return False
    sb = _supabase()
    try:
        tm_res = (
            sb.table('team_members')
            .select('id')
            .eq('user_id', user_id)
            .execute()
        )
        tm_ids = [r['id'] for r in (tm_res.data or [])]
        if not tm_ids:
            return False
        pm_res = (
            sb.table('projects_members')
            .select('role')
            .eq('project_id', project_id)
            .in_('team_member_id', tm_ids)
            .eq('role', 'owner')
            .limit(1)
            .execute()
        )
        return bool(pm_res.data)
    except Exception as e:
        logger.error("[@exec] _is_project_owner error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@server_projects_executive_bp.route('/<project_id>/executive', methods=['GET'])
@handle_route_exceptions('server_projects_executive:get_executive')
def get_project_executive(project_id: str):
    """Per-project manager view. Five small reads, six tiles."""
    days = 30
    try:
        days = int(request.args.get('days', '30'))
    except (TypeError, ValueError):
        days = 30
    days = max(7, min(days, 90))  # 7..90 days — chart pane width wise.

    project = projects_db.get_project(project_id)
    if project is None:
        return jsonify({"error": "Project not found"}), 404
    if not _in_team_scope(project['team_id']):
        return jsonify({"error": "Project not found"}), 404

    tag_ids = [t['tag_id'] for t in project.get('tags') or []]
    script_names = _script_names_for_project(tag_ids)

    trend = _pass_rate_trend(
        team_id=project['team_id'],
        script_names=script_names,
        days=days,
    )
    # Derive `current` from the trend (sum of all daily totals) and `previous`
    # from an explicit prior-window query — keeps the trend bucket pull and the
    # health tile independent.
    cur_pass = sum(b['pass'] for b in trend)
    cur_total = sum(b['total'] for b in trend)
    pass_rate_now = (cur_pass / cur_total * 100.0) if cur_total else 0.0
    pass_rate_prev = _pass_rate_prev_window(
        team_id=project['team_id'],
        script_names=script_names,
        days=days,
    )

    health = _health(pass_rate_now, pass_rate_prev)
    top_failures = _top_failures(team_id=project['team_id'], script_names=script_names)
    members = _members(project_id)

    return jsonify({
        'project': project,
        'days': days,
        'tiles': {
            'health': health,
            'pass_rate_trend': trend,
            'top_failures': top_failures,
            'members': members,
        },
    }), 200
