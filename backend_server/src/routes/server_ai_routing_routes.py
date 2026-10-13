"""
AI usage routing API (TASK-30).

Settings → AI (read: settings.models:view):
    GET    /server/ai/config?team_id=          catalogue, presets, endpoints, profiles, routes, effective routing
    GET    /server/ai/stats?team_id=&hours=24  per-usage calls / errors / fallbacks / avg latency / tokens

Server default — endpoints, profiles, default routes (platform super admin):
    POST   /server/ai/endpoints                 {name, preset, base_url?, reach?, timeout_s?, max_concurrency?,
                                                 allowed_team_ids?, enabled?, api_key?}
    PUT    /server/ai/endpoints/<id>            same fields; api_key sets the key, clear_api_key removes it
    DELETE /server/ai/endpoints/<id>
    POST   /server/ai/endpoints/<id>/test       {api_key?, model?} → models list and/or connectivity check
    POST   /server/ai/profiles                  {name, endpoint_id, model, temperature?, max_tokens_cap?, thinking?,
                                                 image_max_edge?, extra?, fallback_profile_id?, capabilities?, enabled?}
    PUT    /server/ai/profiles/<id>
    DELETE /server/ai/profiles/<id>
    POST   /server/ai/profiles/<id>/test        {kind: text|vision|tools} → live check; success records the capability

Routes (server default: platform super admin; team override: settings.models:edit):
    POST   /server/ai/routes                    {team_id|null, usage_key, profile_id, host_name?, device_model?,
                                                 userinterface_name?, split_profile_id?, split_percent?, priority?, enabled?}
    PUT    /server/ai/routes/<id>               (layer from ?team_id=, absent = server default)
    DELETE /server/ai/routes/<id>

Gateway (hosts only: requires the server API_KEY in X-API-Key, see require_service_key):
    POST   /server/ai/complete                  {usage, prompt, image_b64?, media_type?, system?, max_tokens?,
                                                 temperature?, team_id?, context?, start?}
    GET    /server/ai/credits                   OpenRouter account credit per endpoint (read-only)
    POST   /server/ai/decide                    {usage, state, questions, profile?, team_id?, context?, refs?,
                                                 log?, timeout_s?} → the decisions.decide result: a typed
                                                 decision (Jev) for a host, which holds no provider key
    POST   /server/ai/resolve                   {usage, team_id?, context?} → {available, routing}
    POST   /server/ai/stats                     stats report after a direct (host-reach) call
    POST   /server/ai/openai/<usage>/chat/completions
                                                OpenAI-compatible passthrough for libraries that need an
                                                OpenAI client (browser-use): the server swaps in the routed
                                                model and key. Team via the X-VPT-Team-Id header.

Decision log (external tools, e.g. the session manager; service X-API-Key, team_id required, never cross-team):
    GET    /server/ai/decisions                 ?team_id=&usage=&since=&until=&ok=&has_outcome=&ref.<key>=<value>
                                                &include=state&limit=100(max 500)&offset=0 → {success, count, decisions}
                                                newest first, no ``state`` unless include=state. ``usage`` ending in "."
                                                is a prefix ("text.decision."), otherwise exact.
    GET    /server/ai/decisions/summary         ?team_id=&since= → per usage_key: calls, failed, cost, last_at,
                                                with_outcome, without_outcome, per_day (last 14 UTC days)
    POST   /server/ai/decisions/<id>/outcome    {team_id, outcome: {label, by, ...}} → decisions.set_outcome; 404 when
                                                the id is not in that team

API keys are never returned: endpoints expose ``has_secret`` only.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional

import requests
from flask import Blueprint, Response, jsonify, request

from backend_server.src.lib.auth_middleware import (
    _caller_is_platform_admin,
    _caller_team_ids,
    principal_holds_permission,
    _is_valid_service_api_key,
    require_permission,
    require_platform_admin,
    require_user_auth,
)
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.ai import budgets, call_log, decisions, gateway, health, prices, router, secrets_store, tracing, usage_caller, usage_report, usage_view, usages
from shared.src.lib.ai.config import REACH_VALUES, THINKING_VALUES, get_preset, presets_catalogue
from shared.src.lib.ai.provider_client import (
    classify_error,
    connectivity_response,
    create_client,
    http_timeout,
    is_connection_error,
    openai_call_usage,
    response_sources,
    response_usage,
    response_text,
    single_completion,
)
from shared.src.lib.database import ai_decisions_db, ai_routing_db, workspaces_db

server_ai_routing_bp = Blueprint('server_ai_routing', __name__, url_prefix='/server/ai')


# ------------------------------------------------------------------------ helpers
def require_service_key(f):
    """Gateway routes spend AI quota on behalf of hosts: only the shared service key
    (X-API-Key == the server's API_KEY, sent by server_auth_headers()) may call them —
    not browser users, not open mode, not auto-sign."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_valid_service_api_key():
            return _bad('AI gateway routes require the service X-API-Key', 403)
        return f(*args, **kwargs)
    return decorated


def _is_admin() -> bool:
    return getattr(request, 'user_role', None) == 'service' or _caller_is_platform_admin()


def _team_id() -> Optional[str]:
    body = request.get_json(silent=True) or {}
    return request.args.get('team_id') or body.get('team_id') or None


def _bad(message: str, status: int = 400):
    return jsonify({'success': False, 'error': message}), status


def _db_error(e: Exception):
    message = getattr(e, 'message', None) or str(e)
    return _bad(f'Database refused the change: {message}')


def _endpoint_view(endpoint: dict) -> dict:
    view = dict(endpoint)
    view['has_secret'] = secrets_store.has_secret(endpoint.get('secret_name'))
    view['needs_key'] = get_preset(endpoint['preset']).needs_key
    # Seconds this server process will keep skipping the endpoint after a connection failure.
    view['down_for_s'] = router.endpoint_down_for(endpoint['id'])
    return view


def _agent_skill_usages() -> list[dict]:
    """agent.<name>.skill.<skill> entries for every selectable agent's skills."""
    rows = []
    try:
        from agent.registry import get_agent_registry
        for agent in get_agent_registry().list_agents():
            base = usages.agent_usage(agent.metadata.id)
            for skill in getattr(agent, 'available_skills', None) or []:
                key = f'{base}.skill.{skill}'
                rows.append({'key': key, 'label': skill, 'description': f'{agent.metadata.nickname} skill',
                             'parent': base, 'needs': sorted(usages.needs(key)), 'output': 'text',
                             'thinking': 'auto'})
    except Exception as e:
        print(f'[@server_ai_routing] agent skill catalogue unavailable: {e}')
    return rows


def _check_fallback_chain(profile_id: Optional[str], fallback_id: Optional[str]) -> Optional[str]:
    """Error message if setting fallback_id would create a cycle or too long a chain."""
    if not fallback_id:
        return None
    profiles = {p['id']: p for p in ai_routing_db.list_profiles()}
    if fallback_id not in profiles:
        return 'Fallback profile not found'
    seen = {profile_id} if profile_id else set()
    current: Optional[str] = fallback_id
    depth = 1
    while current:
        if current in seen:
            return 'Fallback chain would loop back to this profile'
        seen.add(current)
        current = profiles.get(current, {}).get('fallback_profile_id')
        depth += 1
        if depth > router.MAX_CHAIN:
            return f'Fallback chain longer than {router.MAX_CHAIN} profiles'
    return None


def _validate_endpoint(data: dict, existing: Optional[dict] = None) -> Optional[str]:
    merged = {**(existing or {}), **data}
    try:
        preset = get_preset(merged.get('preset'))
    except ValueError as e:
        return str(e)
    if not (merged.get('name') or '').strip():
        return 'name is required'
    if preset.base_url is None and preset.client == 'openai_compatible' and not (merged.get('base_url') or '').strip():
        return 'base_url is required for an OpenAI-compatible endpoint (e.g. http://10.0.0.5:1234/v1)'
    if (merged.get('reach') or 'server') not in REACH_VALUES:
        return f"reach must be one of {', '.join(REACH_VALUES)}"
    keeps_secret = merged.get('secret_name') and not data.get('clear_api_key')
    if merged.get('reach') == 'host' and (data.get('api_key') or keeps_secret):
        return 'Host-reach endpoints must be keyless (hosts never hold API keys)'
    return None


def _validate_profile(data: dict, profile_id: Optional[str] = None) -> Optional[str]:
    if 'endpoint_id' in data and not ai_routing_db.get_row('ai_endpoints', data['endpoint_id']):
        return 'Endpoint not found'
    if 'thinking' in data and data['thinking'] not in THINKING_VALUES:
        return f"thinking must be one of {', '.join(THINKING_VALUES)}"
    caps = data.get('capabilities')
    if caps is not None and not set(caps) <= set(usages.CAPABILITIES):
        return f"capabilities must be within {', '.join(usages.CAPABILITIES)}"
    if 'extra' in data and not isinstance(data['extra'] or {}, dict):
        return 'extra must be a JSON object'
    if 'fallback_profile_id' in data:
        return _check_fallback_chain(profile_id, data.get('fallback_profile_id'))
    return None


def _validate_route(data: dict, team_id: Optional[str], existing: Optional[dict] = None) -> Optional[str]:
    merged = {**(existing or {}), **data}
    try:
        usage = usages.get(merged.get('usage_key') or '')
    except usages.UnknownUsageError as e:
        return str(e)
    for field in ('profile_id', 'split_profile_id'):
        profile_id = merged.get(field)
        if not profile_id:
            continue
        profile = ai_routing_db.get_row('ai_profiles', profile_id)
        if not profile:
            return f'{field}: profile not found'
        declared = set(profile.get('capabilities') or [])
        missing = usages.needs(usage.key) - declared
        if declared and missing:
            return (f"Profile '{profile['name']}' lacks {', '.join(sorted(missing))} "
                    f"required by '{usage.key}' (run its Test to record capabilities)")
        endpoint = ai_routing_db.get_row('ai_endpoints', profile['endpoint_id'])
        allowed = (endpoint or {}).get('allowed_team_ids')
        if team_id and allowed and team_id not in allowed:
            return f"Endpoint '{endpoint['name']}' is not available to this team"
    if bool(merged.get('split_profile_id')) != bool(merged.get('split_percent')):
        return 'split_profile_id and split_percent go together'
    return None


def _effective(team_id: Optional[str], keys: list[str]) -> dict:
    result = {}
    for key in keys:
        try:
            resolution = router.resolve(key, team_id, request_id='settings-preview')
            result[key] = resolution.summary()
        except Exception as e:
            result[key] = {'error': str(e)}
    return result


# ------------------------------------------------------------------ settings reads
def _settings_team() -> tuple[Optional[str], bool, Optional[tuple]]:
    """``(team_id, all_view, error)`` of the Settings → AI team dropdown: ``scope_team=<team id>`` (a member may pick
    only their own teams), ``scope_team=all`` (every team's overrides: all teams for an admin, the caller's own
    otherwise), absent = the request's own ``team_id``."""
    scope = request.args.get('scope_team')
    if scope == 'all':
        return None, True, None
    if scope:
        if not _is_admin() and scope not in _caller_team_ids():
            return None, False, ('Not your team', 403)
        return scope, False, None
    return request.args.get('team_id'), False, None


def _scope_options() -> dict:
    """Teams and projects the Settings → AI dropdowns offer: an admin sees all, anyone else their own."""
    from shared.src.lib.database import teams_db
    try:
        teams = teams_db.get_all_teams()
        if not _is_admin():
            own = _caller_team_ids()
            teams = [t for t in teams if t['id'] in own]
        team_options = [{'key': t['id'], 'label': t.get('name') or t['id']} for t in teams]
    except Exception as e:  # noqa: BLE001 - the dropdown is a convenience
        print(f'[AI settings] team list unavailable: {e}')
        team_options = []
    try:
        workspaces = (workspaces_db.get_all_workspaces() if _is_admin()
                      else workspaces_db.get_user_workspaces(getattr(request, 'user_id', None) or ''))
        projects = [{'key': w['id'], 'label': w.get('name') or w['id']} for w in workspaces]
    except Exception as e:  # noqa: BLE001
        print(f'[AI settings] project list unavailable: {e}')
        projects = []
    return {'team': team_options, 'project': projects}


@server_ai_routing_bp.route('/config', methods=['GET'])
@require_user_auth
@require_permission('settings.models:view')
@handle_route_exceptions('server_ai_routing:config')
def get_config():
    team_id, all_view, error = _settings_team()
    if error:
        return _bad(*error)
    admin = _is_admin()
    catalogue = usages.catalogue() + _agent_skill_usages()
    endpoints = [_endpoint_view(e) for e in ai_routing_db.list_endpoints()]
    if not admin:
        own = _caller_team_ids()
        endpoints = [e for e in endpoints if not e.get('allowed_team_ids')
                     or (set(e['allowed_team_ids']) & own if all_view else team_id in e['allowed_team_ids'])]
    if all_view:
        own = _caller_team_ids()
        routes = [r for r in ai_routing_db.list_routes_all() if admin or not r.get('team_id') or r['team_id'] in own]
    else:
        routes = ai_routing_db.list_routes(team_id)
    return jsonify({
        'success': True,
        'is_platform_admin': admin,
        'jev_enabled': decisions.enabled(),
        'usages': catalogue,
        'presets': presets_catalogue(),
        'endpoints': endpoints,
        'profiles': ai_routing_db.list_profiles(),
        'routes': routes,
        'effective': _effective(team_id, [u['key'] for u in catalogue]),
        'scope': {'team': 'all' if all_view else team_id, 'options': _scope_options()},
    })


@server_ai_routing_bp.route('/stats', methods=['GET'])
@require_user_auth
@require_permission('settings.models:view')
@handle_route_exceptions('server_ai_routing:get_stats')
def get_stats():
    team_id, all_view, error = _settings_team()
    if error:
        return _bad(*error)
    hours = max(1, min(int(request.args.get('hours', 24)), 24 * 30))
    project = request.args.get('scope_project')
    per_usage: dict[str, dict[str, Any]] = {}
    if project:  # a project's own calls: the per-call log (7 days at most) filtered to its teams and people
        scope = _UsageArgs._load_project(project)
        if scope is None:
            return _bad('Unknown project', 404)
        teams, users = scope
        hours = min(hours, CALLS_MAX_HOURS)
        if all_view and _is_admin():
            fetched = ai_routing_db.get_calls_rollup(None, hours, True, 'hour')
        else:
            fetched = []
            for tid in ([team_id] if team_id else sorted(_caller_team_ids())[:20]):
                fetched.extend(r for r in ai_routing_db.get_calls_rollup(tid, hours, False, 'hour') if r.get('team_id'))
        calls = [r for r in fetched if str(r.get('team_id')) in teams or str(r.get('user_id')) in users]
        for r in usage_report.aggregate(calls, 'usage', hours=hours)['rows']:
            per_usage[r['key']] = {k: r[k] for k in ('calls', 'errors', 'fallbacks', 'total_ms', 'tokens_in', 'tokens_out')}
            per_usage[r['key']]['profiles'] = dict(r['profiles'])
    else:
        rows = (ai_routing_db.get_usage_rows(None, hours, all_teams=_is_admin()) if all_view
                else ai_routing_db.get_stats(team_id, hours))
        for row in rows:
            agg = per_usage.setdefault(row['usage_key'], {'calls': 0, 'errors': 0, 'fallbacks': 0, 'total_ms': 0,
                                                           'tokens_in': 0, 'tokens_out': 0, 'profiles': {}})
            for field in ('calls', 'errors', 'fallbacks', 'total_ms', 'tokens_in', 'tokens_out'):
                agg[field] += int(row.get(field) or 0)
            arm = f"{row['profile']}{' (' + row['split_arm'] + ')' if row.get('split_arm') else ''}"
            agg['profiles'][arm] = agg['profiles'].get(arm, 0) + int(row.get('calls') or 0)
    for agg in per_usage.values():
        agg['avg_ms'] = int(agg['total_ms'] / agg['calls']) if agg['calls'] else 0
        agg['error_rate'] = round(agg['errors'] / agg['calls'], 3) if agg['calls'] else 0.0
    return jsonify({'success': True, 'hours': hours, 'usages': per_usage})


_USAGE_RANGES_H = (1, 24, 24 * 7, 24 * 30)
_DERIVED_FILTERS = ('category', 'caller', 'result')  # not columns of ai_calls
CALLS_MAX_HOURS = 24 * 7  # ai_calls is kept 90 days, but the page reads it for up to 7 days only; 30 d = rollup


def _routing_view(usage_key: str, team_id: Optional[str], served: dict[str, int],
                  failed: Optional[dict[str, int]] = None, causes: Optional[dict[str, dict]] = None) -> Optional[dict]:
    """Who answers ``usage_key`` today: the chain (main, backups) with effort and, per hop, the requests it
    tried, answered and failed in the window (``served``: profile -> requests, ``failed``: profile -> failures,
    ``causes``: profile -> {error type: failures})."""
    try:
        resolution = router.resolve(usage_key, team_id, request_id='usage-preview')
    except Exception:  # noqa: BLE001 - an unroutable key just has no routing line
        return None
    total = sum(served.values()) or 0
    chain = []
    for i, hop in enumerate(resolution.hops):
        calls = sum(n for name, n in served.items() if name.split(' (')[0] == hop.profile_name)
        errors = sum(n for name, n in (failed or {}).items() if name.split(' (')[0] == hop.profile_name)
        kinds: dict[str, int] = {}
        for name, per in (causes or {}).items():
            if name.split(' (')[0] == hop.profile_name:
                for kind, n in per.items():
                    kinds[kind] = kinds.get(kind, 0) + n
        chain.append({
            'tried': calls, 'failed': errors, 'answered': calls - errors,
            'reason': max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else None,
            'endpoint_label': usage_view.provider_label(hop.endpoint)['name'],
            'role': 'main' if i == 0 else 'backup', 'profile': hop.profile_name, 'endpoint': hop.endpoint_name,
            'preset': hop.preset, 'model': hop.model, 'effort': hop.effort(usage_key), 'reach': hop.reach,
            'region': hop.endpoint.get('region'),
            'down_for_s': router.endpoint_down_for(hop.endpoint['id']),
            'share': round(calls / total, 4) if total else None,
        })
    return {'via': resolution.via_key, 'layer': resolution.layer, 'chain': chain}


class _UsageArgs:
    """Parsed, authorised query of the usage endpoints. ``error`` is set instead of raising.

    Team scope: ``scope=all`` (platform admin: every team), ``scope=mine`` (everyone else: all the caller's teams),
    ``team_ids=a,b`` (admin: any team; others: only teams they belong to), else the ``team_id`` of the request.
    ``project=<workspace id>`` keeps the calls of that workspace's teams and people (7 days or less)."""

    def __init__(self) -> None:
        self.error: Optional[tuple] = None
        self.team_id = request.args.get('team_id')
        self.team_ids: list[str] = []
        try:
            self.hours = int(request.args.get('hours', 24))
        except ValueError:
            self.hours = 0
        if self.hours not in _USAGE_RANGES_H:
            self.error = (f'hours must be one of {list(_USAGE_RANGES_H)}', 400)
        self.group_by = request.args.get('group_by', 'usage')
        self.all_teams = request.args.get('scope') == 'all' and _is_admin()
        asked = [t for t in (request.args.get('team_ids') or '').split(',') if t.strip()][:20]
        if request.args.get('scope') in ('mine', 'all') and not _is_admin():  # "all teams" of a member = their own teams
            asked = sorted(_caller_team_ids())[:20]
        if asked and not _is_admin():
            allowed = _caller_team_ids()
            asked = [t for t in asked if t in allowed]
            if not asked:
                self.error = ('None of these teams is yours', 403)
        if asked and not self.all_teams:
            self.team_ids = asked
            self.team_id = asked[0]
        # Without settings.models:view a user sees only their own calls.
        self.user_only = None if (_is_admin() or principal_holds_permission('settings.models:view')) \
            else getattr(request, 'user_id', None) or '-'
        self.source = 'calls' if self.hours <= CALLS_MAX_HOURS else 'rollup'
        self.groups = usage_report.CALL_GROUPS if self.source == 'calls' else usage_report.ROLLUP_GROUPS
        if self.user_only and self.source == 'rollup':
            self.error = ('Your own usage is available for up to 7 days', 400)
        if self.group_by not in self.groups and not self.error:
            self.error = (f'group_by must be one of {list(self.groups)} for this period', 400)
        self.filters = {g: request.args[f'filter_{g}'] for g in usage_report.CALL_GROUPS
                        if request.args.get(f'filter_{g}')}
        if any(g not in self.groups for g in self.filters) and not self.error:
            self.error = ('A filter on this field needs a period of 7 days or less', 400)
        self.project = request.args.get('project') or None
        self.project_scope: Optional[tuple[set, set]] = None
        if self.project and not self.error:
            if self.source != 'calls':
                self.error = ('A project filter needs a period of 7 days or less', 400)
            else:
                self.project_scope = self._load_project(self.project)
                if self.project_scope is None:
                    self.error = ('Unknown project', 404)
        if not self.team_id and not self.all_teams and not self.error:
            self.error = ('team_id is required', 400)

    @staticmethod
    def _load_project(workspace_id: str) -> Optional[tuple[set, set]]:
        """``(team ids, user ids)`` of a workspace the caller may see, or None."""
        if not _is_admin():
            mine = {w['id'] for w in workspaces_db.get_user_workspaces(getattr(request, 'user_id', None) or '')}
            if workspace_id not in mine:
                return None
        elif workspaces_db.get_workspace(workspace_id) is None:
            return None
        teams, users = set(), set()
        for m in workspaces_db.get_workspace_members(workspace_id):
            (teams if m.get('type') == 'team' else users).add(str(m.get('team_id') if m.get('type') == 'team' else m.get('user_id')))
        return teams, users

    def in_project(self, row: dict) -> bool:
        if self.project_scope is None:
            return True
        teams, users = self.project_scope
        return str(row.get('team_id')) in teams or str(row.get('user_id')) in users

    def rows(self, hours: Optional[int] = None) -> list[dict]:
        hours = hours or self.hours
        if self.source != 'calls':
            return ai_routing_db.get_usage_rows(self.team_id, hours, all_teams=self.all_teams)
        if len(self.team_ids) > 1:  # several teams: team-less (server default) rows come back with each, keep one copy
            rows: list[dict] = []
            for i, team in enumerate(self.team_ids):
                part = ai_routing_db.get_calls_rollup(team, hours, False, 'hour', self.user_only)
                rows.extend(part if i == 0 else [r for r in part if r.get('team_id')])
        else:
            rows = ai_routing_db.get_calls_rollup(self.team_id, hours, self.all_teams, 'hour', self.user_only)
        return [r for r in rows if self.in_project(r)] if self.project_scope is not None else rows


def _banner(args: '_UsageArgs', rows24: list[dict], endpoints: list[dict]) -> dict:
    """``health.evaluate`` over the last 24 h with each cause's provider named for people."""
    skipped = ai_routing_db.get_skipped_paused(args.team_id, 24, args.all_teams)
    banner = health.evaluate(rows24, skipped=skipped)
    meta = {ep['name']: ep for ep in endpoints}
    for cause in banner['causes']:
        ep = meta.get(cause['endpoint'], {'name': cause['endpoint'], 'preset': ''})
        cause.update(provider=usage_view.provider_label(ep)['name'], preset=ep.get('preset'),
                     type=usage_view.provider_label(ep)['type'])
        for f in cause['features']:
            f['label'] = usages.short_label(f['usage'])
    for b in banner['backup']:
        b['label'] = usages.short_label(b['usage'])
    return banner


def _label_rows(report: dict, team_id: Optional[str]) -> None:
    group = report['group_by']
    keys = [r['key'] for r in report['rows'] if r['key'] != usage_report.NONE_KEY]
    if group == 'team':
        names = ai_routing_db.get_team_names(keys)
        for r in report['rows']:
            r['label'] = names.get(r['key']) or r['key']
    elif group == 'user':
        names = ai_routing_db.get_user_names(keys)
        for r in report['rows']:
            r['label'] = names.get(r['key']) or r['key']
    elif group == 'usage':
        for r in report['rows']:
            r['routing'] = _routing_view(r['key'], team_id, r['profiles'], r['profile_errors'], r['profile_causes'])
            r['label'] = usages.short_label(r['key'])
            r['family'] = usages.family_of(r['key'])


@server_ai_routing_bp.route('/usage', methods=['GET'])
@require_user_auth
@require_permission('monitoring.ai_queue:view')
@handle_route_exceptions('server_ai_routing:get_usage')
def get_usage():
    """Monitoring → AI usage: calls, tokens, speed, errors, cost for a window, grouped by ``group_by``
    (usage | model | endpoint | team | origin | host, and for 7 days or less also device | script |
    campaign | user | server) with ``filter_<group>=value``. 1 h - 7 d read ``ai_calls``, 30 d the hourly
    rollup. A team sees its own calls plus the server-default (background) ones; a platform admin gets
    ``scope=all``; without ``settings.models:view`` only the caller's own calls."""
    args = _UsageArgs()
    if args.error:
        return _bad(*args.error)
    now = datetime.now(timezone.utc)
    rows = args.rows()
    report = usage_report.aggregate(rows, args.group_by, hours=args.hours, filters=args.filters, now=now)
    # One wider fetch gives the chart window (at least 24 h, also for the 1 h view), the previous period for the
    # "vs previous" arrows and, from the last 24 h, the failure causes behind the Providers section.
    wide = args.rows(max(args.hours * 2, 24))
    chart_rows, previous_rows = usage_view.split_periods(wide, args.hours, now)
    chart_hours = max(args.hours, 24)
    usage_view.apply_chart(report, usage_report.aggregate(chart_rows, args.group_by, hours=chart_hours,
                                                          filters=args.filters, now=now))
    report['previous'] = usage_view.previous_totals(previous_rows, args.group_by, args.hours, args.filters, now)
    report['chart_hours'] = chart_hours
    _label_rows(report, args.team_id)
    report.update(success=True, hours=args.hours, scope='all' if args.all_teams else 'team', source=args.source,
                  groups=list(args.groups), can_view_all=_is_admin(), restricted_to_self=bool(args.user_only))
    shown = usage_report.filter_rows(rows, args.filters)
    report['overview'] = usage_view.overview(shown)
    report['options'] = _filter_options(args, rows)
    if args.user_only:
        report['providers'] = []
        report['errors'] = {'count': 0, 'causes': []}
    else:
        endpoints = ai_routing_db.list_endpoints()
        rows24 = args.rows(24) if args.source != 'calls' else chart_rows
        rows24 = usage_report.filter_rows(rows24, args.filters)
        causes = _banner(args, rows24, endpoints)['causes']
        for cause in causes:
            cause['categories'] = sorted({usages.category_of(f['usage']) for f in cause['features']})
        report['errors'] = {'count': len(causes), 'causes': causes}
        chart_all = usage_report.aggregate(usage_report.filter_rows(chart_rows, args.filters), 'endpoint',
                                           hours=chart_hours, now=now)
        report['providers'] = usage_view.provider_view(
            endpoints, shown, chart_all, causes, {str(ep['id']): router.endpoint_down_for(ep['id']) for ep in endpoints})
    return jsonify(report)


def _filter_options(args: '_UsageArgs', rows: list[dict]) -> dict:
    """What the filter bar offers: teams, projects, users, providers, models — each independent of its own filter,
    so a dropdown still lists its siblings after one is picked. ``key`` is the value sent back as the filter."""
    def distinct(group: str, skip: str) -> list[dict]:
        others = {g: v for g, v in args.filters.items() if g != skip}
        agg = usage_report.aggregate(usage_report.filter_rows(rows, others), group, hours=args.hours)['rows']
        return [{'key': r['key'], 'calls': r['calls']} for r in agg if r['key'] != usage_report.NONE_KEY]

    teams = distinct('team', 'team')
    names = ai_routing_db.get_team_names([t['key'] for t in teams])
    if not _is_admin():  # a member picks among their own teams, whether or not they made calls
        own = ai_routing_db.get_team_names(sorted(_caller_team_ids()))
        names = {**own, **names}
        teams = [{'key': k, 'calls': next((t['calls'] for t in teams if t['key'] == k), 0)} for k in own]
    for t in teams:
        t['label'] = names.get(t['key']) or t['key']
    options = {'team': teams, 'provider': distinct('endpoint', 'endpoint'), 'model': distinct('model', 'model'),
               'project': [], 'user': []}
    if args.source == 'calls':
        users = distinct('user', 'user')
        user_names = ai_routing_db.get_user_names([u['key'] for u in users])
        options['user'] = [{**u, 'label': user_names.get(u['key']) or u['key']} for u in users]
    try:
        workspaces = (workspaces_db.get_all_workspaces() if _is_admin()
                      else workspaces_db.get_user_workspaces(getattr(request, 'user_id', None) or ''))
        options['project'] = [{'key': w['id'], 'label': w.get('name') or w['id']} for w in workspaces]
    except Exception as e:  # noqa: BLE001 - the project list is a convenience
        print(f'[AI usage] project list unavailable: {e}')
    return options


CSV_COLUMNS = ('key', 'label', 'calls', 'errors', 'error_rate', 'fallbacks', 'fallback_rate', 'tokens_in',
               'tokens_out', 'tokens_cache_read', 'tokens_cache_write', 'avg_ms', 'tokens_per_s', 'cost',
               'priced_calls', 'avoided', 'saved_cost')


@server_ai_routing_bp.route('/usage/export', methods=['GET'])
@require_user_auth
@require_permission('monitoring.ai_queue:view')
@handle_route_exceptions('server_ai_routing:export_usage')
def export_usage():
    """The grouped table of ``/usage`` as CSV (charge back to a team, invoice a customer)."""
    import csv
    import io
    args = _UsageArgs()
    if args.error:
        return _bad(*args.error)
    report = usage_report.aggregate(args.rows(), args.group_by, hours=args.hours, filters=args.filters)
    _label_rows(report, args.team_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow((args.group_by, 'name', *CSV_COLUMNS[2:]))
    for r in [*report['rows'], {**report['totals'], 'key': 'TOTAL', 'label': ''}]:
        writer.writerow(['' if r.get(c) is None else r.get(c) for c in CSV_COLUMNS])
    return Response(out.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename="ai-usage-{args.group_by}-{args.hours}h.csv"'})


@server_ai_routing_bp.route('/usage/calls', methods=['GET'])
@require_user_auth
@require_permission('monitoring.ai_queue:view')
@handle_route_exceptions('server_ai_routing:usage_calls')
def usage_calls():
    """Newest calls behind a number: ``filter_<group>=value`` (also ``script_result_id`` / ``request_id``),
    ``only_errors=1``, ``limit`` (max 200). Adds p50 / p95 latency of up to 1000 matching calls."""
    args = _UsageArgs()
    if args.error:
        return _bad(*args.error)
    if args.source != 'calls':
        return _bad('Single calls are listed for up to 7 days', 400)
    filters = {g: v for g, v in args.filters.items() if g not in _DERIVED_FILTERS}
    for extra in ('script_result_id', 'request_id'):
        if request.args.get(extra):
            filters[extra] = request.args[extra]
    limit = max(1, min(int(request.args.get('limit', 50)), 200))
    result = args.filters.get('result')
    only_errors = request.args.get('only_errors') in ('1', 'true') or result == 'failed'
    derived = {g: v for g, v in args.filters.items() if g in ('category', 'caller')}
    sample = ai_routing_db.get_recent_calls(args.team_id, args.hours, filters, 1000, args.all_teams, args.user_only,
                                            only_errors, only_ok=result == 'success', team_ids=args.team_ids)
    if derived or args.project_scope is not None:  # derived from several columns: filter the newest 1000 here
        sample = [c for c in sample if args.in_project(c)
                  and all(usage_report.row_value(c, g) == v for g, v in derived.items())]
    latencies = sorted(int(c.get('latency_ms') or 0) for c in sample if c.get('outcome') == 'served')

    def pct(p: float) -> Optional[int]:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))] if latencies else None

    langfuse = tracing.trace_url_base()
    calls = sample[:limit]
    for c in calls:
        c['trace_url'] = f"{langfuse}/{c['request_id']}" if langfuse and c.get('request_id') else None
        c['usage_label'] = usages.short_label(c['usage_key'])
        c['category'] = usages.category_of(c['usage_key'])
        c['caller'] = usage_caller.caller_of(c)
    return jsonify({'success': True, 'calls': calls, 'sampled': len(sample),
                    'latency': {'p50': pct(0.5), 'p95': pct(0.95), 'n': len(latencies)}})


@server_ai_routing_bp.route('/usage/credits', methods=['GET'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:usage_credits')
def usage_credits():
    """Prepaid OpenRouter credit left, for the AI usage page (platform admin; spends nothing)."""
    return jsonify({'success': True, 'at': int(time.time()), 'endpoints': _openrouter_credits()})


@server_ai_routing_bp.route('/usage/run', methods=['GET'])
@require_user_auth
@require_permission('reports.tests:view')
@handle_route_exceptions('server_ai_routing:usage_run')
def usage_run():
    """AI cost of one or more script runs (a run report's cost line): ``script_result_ids=a,b`` (max 200)."""
    team_id = request.args.get('team_id')
    ids = [i for i in (request.args.get('script_result_ids') or '').split(',') if i.strip()][:200]
    if not team_id or not ids:
        return _bad('team_id and script_result_ids are required')
    return jsonify({'success': True, **ai_routing_db.get_run_cost(team_id, ids)})


# ------------------------------------------------------------------------ prices
@server_ai_routing_bp.route('/prices', methods=['GET'])
@require_user_auth
@require_permission('settings.models:view')
@handle_route_exceptions('server_ai_routing:list_prices')
def list_prices():
    rows = [{**r, 'source': prices.source_of(r.get('note'))} for r in ai_routing_db.list_prices()]
    # Endpoints with no per-call price: a flat plan (included) or a local PC (free).
    free = [{'endpoint': e['name'], 'kind': 'plan' if prices.is_flat_plan(e) else 'local'}
            for e in ai_routing_db.list_endpoints()
            if prices.is_flat_plan(e) or usage_view.provider_label(e)['type'] == 'local']
    return jsonify({'success': True, 'prices': rows, 'unpriced': free})


def _validate_price(data: dict) -> Optional[str]:
    names = {e['name'] for e in ai_routing_db.list_endpoints()}
    if data.get('endpoint') not in names:
        return 'endpoint must be an existing endpoint'
    if not str(data.get('model') or '').strip():
        return "model is required (use * for every model of the endpoint)"
    for field in ('price_in', 'price_out'):
        if not isinstance(data.get(field), (int, float)) or isinstance(data.get(field), bool) or data[field] < 0:
            return f'{field} must be a number >= 0 (USD per 1M tokens)'
    for field in ('price_cache_read', 'price_cache_write', 'price_web_search'):
        value = data.get(field)
        if value not in (None, '') and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            return f'{field} must be a number >= 0'
    if data.get('valid_from'):
        try:
            from datetime import datetime
            datetime.fromisoformat(str(data['valid_from']).replace('Z', '+00:00'))
        except ValueError:
            return 'valid_from must be an ISO date'
    return None


@server_ai_routing_bp.route('/prices', methods=['POST'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:create_price')
def create_price():
    """A price from ``valid_from`` on (default now). Calls already logged keep the cost they were stored with."""
    data = request.get_json() or {}
    error = _validate_price(data)
    if error:
        return _bad(error)
    try:
        price = ai_routing_db.create_price(data)
    except Exception as e:
        return _db_error(e)
    prices.invalidate()
    return jsonify({'success': True, 'price': price})


@server_ai_routing_bp.route('/prices/<price_id>', methods=['DELETE'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:delete_price')
def delete_price(price_id):
    if not ai_routing_db.delete_price(price_id):
        return _bad('Price not found', 404)
    prices.invalidate()
    return jsonify({'success': True})


@server_ai_routing_bp.route('/usage/alerts', methods=['GET'])
@require_user_auth
@require_permission('monitoring.ai_queue:view')
@handle_route_exceptions('server_ai_routing:usage_alerts')
def usage_alerts():
    """The health banner: failures grouped by cause (provider + reason) with every feature hit, when they began
    and were last seen, and the calls held back by a no-credit pause; plus features leaning on their backup.
    Last 24 h of ``ai_calls``; thresholds in ``shared/src/lib/ai/health.py``. Team scope as ``/usage``."""
    args = _UsageArgs()
    args.error = None  # only the scope matters here; the period is fixed
    if not args.team_id and not args.all_teams:
        return _bad('team_id is required')
    rows = ai_routing_db.get_calls_rollup(args.team_id, 24, args.all_teams, 'hour')
    return jsonify({'success': True, **_banner(args, rows, ai_routing_db.list_endpoints()),
                    'thresholds': health.thresholds()})


@server_ai_routing_bp.route('/usage/budget', methods=['GET'])
@require_user_auth
@require_permission('monitoring.ai_queue:view')
@handle_route_exceptions('server_ai_routing:usage_budget')
def usage_budget():
    """This month's priced spend of the team, the linear month-end forecast and its budget (null = none set)."""
    team_id = request.args.get('team_id')
    if not team_id:
        return _bad('team_id is required')
    spent = ai_routing_db.get_month_spend(team_id, budgets.month_start())
    budget = ai_routing_db.get_budget(team_id)
    return jsonify({'success': True, 'spent': round(spent, 4), 'forecast': round(usage_report.forecast_month(spent), 4),
                    'budget': budgets.status_from(budget, spent) if budget else None})


@server_ai_routing_bp.route('/budget', methods=['PUT'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:set_budget')
def set_budget():
    """Set the team's monthly budget: ``{team_id, month_limit_usd > 0, mode: warn|block, warn_at: 0-1}``.
    Platform admin only (a team admin must not lift their own limit)."""
    data = request.get_json() or {}
    team_id = data.get('team_id')
    limit, mode, warn_at = data.get('month_limit_usd'), data.get('mode') or 'warn', data.get('warn_at', 0.8)
    if not team_id:
        return _bad('team_id is required')
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
        return _bad('month_limit_usd must be a number above 0')
    if mode not in ('warn', 'block'):
        return _bad("mode must be 'warn' or 'block'")
    if not isinstance(warn_at, (int, float)) or isinstance(warn_at, bool) or not 0 < warn_at <= 1:
        return _bad('warn_at must be above 0 and at most 1')
    try:
        ai_routing_db.set_budget(team_id, limit, mode, warn_at, getattr(request, 'user_id', None))
    except Exception as e:
        return _db_error(e)
    budgets.invalidate(team_id)
    return jsonify({'success': True})


@server_ai_routing_bp.route('/budget', methods=['DELETE'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:delete_budget')
def delete_budget():
    team_id = request.args.get('team_id')
    if not team_id:
        return _bad('team_id is required')
    ai_routing_db.delete_budget(team_id)
    budgets.invalidate(team_id)
    return jsonify({'success': True})


@server_ai_routing_bp.route('/usage/training', methods=['GET'])
@require_user_auth
@require_permission('settings.models:view')
@handle_route_exceptions('server_ai_routing:usage_training')
def usage_training():
    """Training data next to the call log (TASK-27 samples): samples per family / device model, who labelled
    them, label conflicts, and production accuracy per model next to its cost. Counts only, no images."""
    from shared.src.lib.ai import training_report
    from shared.src.lib.database import ai_training_samples_db
    team_id = request.args.get('team_id')
    picked = (request.args.get('team_ids') or '').split(',')[0].strip()
    if picked:  # the page's team filter: a member may only pick one of their own teams
        if not _is_admin() and picked not in _caller_team_ids():
            return _bad('Not your team', 403)
        team_id = picked
    all_teams = request.args.get('scope') == 'all' and _is_admin() and not picked
    if not team_id and not all_teams:
        return _bad('team_id is required')
    samples = ai_training_samples_db.list_for_report(team_id, all_teams)
    summary = training_report.summarize(samples)
    request_ids = sorted({r for r in (training_report.request_id_of(s) for s in samples
                                       if (s.get('label_source') or 'none') != 'none') if r})
    calls = ai_routing_db.get_calls_by_request_ids(request_ids, team_id, all_teams) if request_ids else {}
    opted_in = (ai_training_samples_db.count_opted_in_teams() if all_teams
                else int(ai_training_samples_db.team_opted_in(team_id)))
    accuracy = training_report.accuracy_by_model(samples, calls)
    for row in accuracy:
        row['label'] = usages.short_label(row['usage'])
    return jsonify({'success': True, **summary, 'accuracy': accuracy,
                    'opted_in_teams': opted_in, 'scope': 'all' if all_teams else 'team'})


# ------------------------------------------------------------------------ endpoints
def _store_endpoint_secret(endpoint: dict, data: dict) -> dict:
    """Apply api_key / clear_api_key from a request body. Returns updates for the row."""
    updates = {}
    if data.get('clear_api_key') and endpoint.get('secret_name'):
        secrets_store.delete_secret(endpoint['secret_name'])
    api_key = (data.get('api_key') or '').strip()
    if api_key:
        secret_name = endpoint.get('secret_name') or endpoint['name']
        secrets_store.set_secret(secret_name, api_key)
        if endpoint.get('secret_name') != secret_name:
            updates['secret_name'] = secret_name
    return updates


@server_ai_routing_bp.route('/endpoints', methods=['POST'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:create_endpoint')
def create_endpoint():
    data = request.get_json() or {}
    error = _validate_endpoint(data)
    if error:
        return _bad(error)
    try:
        endpoint = ai_routing_db.create_row('ai_endpoints', {k: v for k, v in data.items() if k != 'secret_name'})
    except Exception as e:
        return _db_error(e)
    updates = _store_endpoint_secret(endpoint, data)
    if updates:
        endpoint = ai_routing_db.update_row('ai_endpoints', endpoint['id'], updates) or endpoint
    router.invalidate()
    return jsonify({'success': True, 'endpoint': _endpoint_view(endpoint)})


@server_ai_routing_bp.route('/endpoints/<endpoint_id>', methods=['PUT'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:update_endpoint')
def update_endpoint(endpoint_id):
    data = request.get_json() or {}
    existing = ai_routing_db.get_row('ai_endpoints', endpoint_id)
    if not existing:
        return _bad('Endpoint not found', 404)
    error = _validate_endpoint(data, existing)
    if error:
        return _bad(error)
    updates = {k: v for k, v in data.items() if k != 'secret_name'}
    if data.get('clear_api_key'):
        updates['secret_name'] = None
    updates.update(_store_endpoint_secret(existing, data))
    try:
        endpoint = ai_routing_db.update_row('ai_endpoints', endpoint_id, updates)
    except Exception as e:
        return _db_error(e)
    router.invalidate()
    return jsonify({'success': True, 'endpoint': _endpoint_view(endpoint or existing)})


@server_ai_routing_bp.route('/endpoints/<endpoint_id>', methods=['DELETE'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:delete_endpoint')
def delete_endpoint(endpoint_id):
    existing = ai_routing_db.get_row('ai_endpoints', endpoint_id)
    if not existing:
        return _bad('Endpoint not found', 404)
    try:
        ai_routing_db.delete_row('ai_endpoints', endpoint_id)
    except Exception as e:
        return _db_error(e)  # profiles still use it (ON DELETE RESTRICT)
    if existing.get('secret_name'):
        secrets_store.delete_secret(existing['secret_name'])
    router.invalidate()
    return jsonify({'success': True})


@server_ai_routing_bp.route('/endpoints/<endpoint_id>/test', methods=['POST'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:test_endpoint')
def test_endpoint(endpoint_id):
    """List the endpoint's models and/or run a tiny completion on ``model``."""
    data = request.get_json() or {}
    endpoint = ai_routing_db.get_row('ai_endpoints', endpoint_id)
    if not endpoint:
        return _bad('Endpoint not found', 404)
    preset = get_preset(endpoint['preset'])
    api_key = (data.get('api_key') or '').strip() or secrets_store.get_secret(endpoint.get('secret_name'))
    base_url = endpoint.get('base_url') or preset.base_url
    result: dict[str, Any] = {'success': True, 'endpoint': endpoint['name']}
    if endpoint.get('reach') == 'host':
        result['note'] = 'Host-reach endpoint: the server may not be able to reach it; test from a host.'
    if preset.lists_models and base_url:
        try:
            headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
            response = requests.get(f"{base_url.rstrip('/')}/models", headers=headers,
                                    timeout=min(int(endpoint.get('timeout_s') or 30), 30))
            response.raise_for_status()
            result['models'] = sorted(m.get('id') for m in (response.json().get('data') or []) if m.get('id'))
        except Exception as e:
            result['success'] = False
            result['error'] = f'Could not list models: {e}'
    model = (data.get('model') or '').strip()
    if model:
        try:
            client = create_client(endpoint['preset'], api_key, base_url=endpoint.get('base_url'),
                                   timeout=int(endpoint.get('timeout_s') or 120))
            test_hop = router.Hop(profile={'id': '', 'name': f'(test) {model}', 'model': model}, endpoint=endpoint)
            result['reply'] = response_text(_counted_test(test_hop, 'text', lambda: connectivity_response(client, model)))
        except Exception as e:
            result['success'] = False
            result['error'] = f'Completion failed: {e}'
    return jsonify(result)


def _http_error_type(status: int) -> str:
    return {429: 'rate_limit', 402: 'no_credit', 401: 'auth', 403: 'auth'}.get(status, 'server' if status >= 500 else 'bad_request')


def _counted_test(hop, kind: str, call):
    """Run a Settings Test call (``call() -> raw response``) and count it as ``test:<kind>``.

    The call is billed whatever its verdict, so it goes through ``router.record`` like any other."""
    resolution = router.test_resolution(hop, kind)
    started = time.time()
    try:
        resp = call()
    except Exception as e:
        router.record(resolution, hop, ok=False, ms=int((time.time() - started) * 1000), error_type=classify_error(e))
        raise
    used = response_usage(resp)
    router.record(resolution, hop, ok=True, ms=int((time.time() - started) * 1000), tokens_in=used.tokens_in,
                  tokens_out=used.tokens_out, usage=used)
    return resp


# ------------------------------------------------------------------------ profiles
@server_ai_routing_bp.route('/profiles', methods=['POST'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:create_profile')
def create_profile():
    data = request.get_json() or {}
    for field in ('name', 'endpoint_id', 'model'):
        if not data.get(field):
            return _bad(f'{field} is required')
    error = _validate_profile(data)
    if error:
        return _bad(error)
    try:
        profile = ai_routing_db.create_row('ai_profiles', data)
    except Exception as e:
        return _db_error(e)
    router.invalidate()
    return jsonify({'success': True, 'profile': profile})


@server_ai_routing_bp.route('/profiles/<profile_id>', methods=['PUT'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:update_profile')
def update_profile(profile_id):
    data = request.get_json() or {}
    if not ai_routing_db.get_row('ai_profiles', profile_id):
        return _bad('Profile not found', 404)
    error = _validate_profile(data, profile_id)
    if error:
        return _bad(error)
    try:
        profile = ai_routing_db.update_row('ai_profiles', profile_id, data)
    except Exception as e:
        return _db_error(e)
    router.invalidate()
    return jsonify({'success': True, 'profile': profile})


@server_ai_routing_bp.route('/profiles/<profile_id>', methods=['DELETE'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:delete_profile')
def delete_profile(profile_id):
    try:
        deleted = ai_routing_db.delete_row('ai_profiles', profile_id)
    except Exception as e:
        return _db_error(e)  # routes still use it (ON DELETE RESTRICT)
    router.invalidate()
    return jsonify({'success': deleted})


def _test_image_b64() -> str:
    """A small synthetic frame with a known number, for the vision test."""
    import cv2
    import numpy as np
    img = np.full((240, 640, 3), 30, dtype=np.uint8)
    cv2.putText(img, 'CHANNEL 427', (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 255), 5)
    ok, buf = cv2.imencode('.jpg', img)
    return base64.b64encode(buf.tobytes()).decode()


# Needs today's web to answer; success = the provider returned at least one source page.
_WEB_TEST_PROMPT = 'Search the web: what is the top headline on bbc.com/news right now? One sentence.'

_TEST_TOOL = {
    'name': 'report_number',
    'description': 'Report a number back to the system.',
    'input_schema': {'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']},
}


@server_ai_routing_bp.route('/profiles/<profile_id>/test', methods=['POST'])
@require_user_auth
@require_platform_admin
@handle_route_exceptions('server_ai_routing:test_profile')
def test_profile(profile_id):
    """Live check of one capability. On success the capability is recorded on the profile."""
    kind = (request.get_json() or {}).get('kind', 'text')
    profile = ai_routing_db.get_row('ai_profiles', profile_id)
    if not profile:
        return _bad('Profile not found', 404)
    endpoint = ai_routing_db.get_row('ai_endpoints', profile['endpoint_id'])
    hop = router.Hop(profile=profile, endpoint=endpoint)
    try:
        client = hop.client()
        if kind == 'vision':
            resp = _counted_test(hop, 'vision', lambda: single_completion(
                client, model=hop.model, prompt='What number is written in this image? Reply with the number only.',
                image_b64=_test_image_b64(), max_tokens=hop.max_tokens(64), temperature=hop.temperature(0.0),
                extra_body=hop.extra_body('vision')))
            reply = response_text(resp)
            ok = '427' in reply
        elif kind == 'tools':
            resp = _counted_test(hop, 'tools', lambda: client.messages.create(
                model=hop.model, max_tokens=hop.max_tokens(256), system=[],
                messages=[{'role': 'user', 'content': 'Call report_number with value 7.'}],
                tools=[_TEST_TOOL], tool_choice={'type': 'auto'}, temperature=None, extra_headers=None,
            ))
            calls = [b for b in (getattr(resp, 'content', None) or []) if getattr(b, 'type', None) == 'tool_use']
            reply = f'tool calls: {[getattr(c, "name", None) for c in calls]}'
            ok = any(getattr(c, 'name', None) == 'report_number' for c in calls)
        elif kind == 'web':
            mechanism = get_preset(hop.preset).web_search
            if not mechanism:
                return jsonify({'success': False, 'kind': kind,
                                'error': f"The {hop.preset} preset cannot search the web"})
            resp = _counted_test(hop, 'web', lambda: single_completion(
                client, model=hop.model, prompt=_WEB_TEST_PROMPT, max_tokens=hop.max_tokens(1024),
                temperature=hop.temperature(None), extra_body=hop.extra_body('text.web'), web_search=mechanism))
            sources = response_sources(resp)
            reply = f"{response_text(resp)[:200]} ({len(sources)} source(s))"
            ok = bool(sources)
        else:
            reply = response_text(_counted_test(hop, 'text', lambda: connectivity_response(client, hop.model)))
            ok = bool(reply)
    except Exception as e:
        return jsonify({'success': False, 'kind': kind, 'error': str(e)})

    capability = {'vision': 'vision', 'tools': 'tools', 'web': 'web'}.get(kind)
    if ok and capability and capability not in (profile.get('capabilities') or []):
        ai_routing_db.update_row('ai_profiles', profile_id,
                                 {'capabilities': sorted({*(profile.get('capabilities') or []), capability})})
        router.invalidate()
    return jsonify({'success': ok, 'kind': kind, 'reply': reply})


# ------------------------------------------------------------------------ routes
def _can_edit_layer(team_id: Optional[str]) -> bool:
    """Server default: super admin only. Team layer: settings.models:edit (checked by decorator)."""
    return bool(team_id) or _is_admin()


@server_ai_routing_bp.route('/routes', methods=['POST'])
@require_user_auth
@require_permission('settings.models:edit')
@handle_route_exceptions('server_ai_routing:create_route')
def create_route():
    data = request.get_json() or {}
    team_id = data.get('team_id') or None
    if not _can_edit_layer(team_id):
        return _bad('Only the platform super admin can change the server default', 403)
    if not data.get('profile_id'):
        return _bad('profile_id is required')
    error = _validate_route(data, team_id)
    if error:
        return _bad(error)
    try:
        route = ai_routing_db.create_row('ai_routes', {**data, 'team_id': team_id})
    except Exception as e:
        return _db_error(e)
    router.invalidate()
    return jsonify({'success': True, 'route': route})


@server_ai_routing_bp.route('/routes/<route_id>', methods=['PUT'])
@require_user_auth
@require_permission('settings.models:edit')
@handle_route_exceptions('server_ai_routing:update_route')
def update_route(route_id):
    data = request.get_json() or {}
    team_id = request.args.get('team_id') or None
    if not _can_edit_layer(team_id):
        return _bad('Only the platform super admin can change the server default', 403)
    existing = ai_routing_db.get_row('ai_routes', route_id)
    if not existing or (existing.get('team_id') or None) != team_id:
        return _bad('Route not found', 404)
    error = _validate_route(data, team_id, existing)
    if error:
        return _bad(error)
    try:
        route = ai_routing_db.update_row('ai_routes', route_id, data, team_id=team_id)
    except Exception as e:
        return _db_error(e)
    router.invalidate()
    return jsonify({'success': True, 'route': route})


@server_ai_routing_bp.route('/routes/<route_id>', methods=['DELETE'])
@require_user_auth
@require_permission('settings.models:edit')
@handle_route_exceptions('server_ai_routing:delete_route')
def delete_route(route_id):
    team_id = request.args.get('team_id') or None
    if not _can_edit_layer(team_id):
        return _bad('Only the platform super admin can change the server default', 403)
    try:
        deleted = ai_routing_db.delete_row('ai_routes', route_id, team_id=team_id)
    except Exception as e:
        return _db_error(e)  # root routes of the server default are protected by a trigger
    router.invalidate()
    return jsonify({'success': deleted})


# ------------------------------------------------------------------------ gateway
@server_ai_routing_bp.route('/complete', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:complete')
def complete():
    """Run one AI call for a host. Hands keyless host-reach endpoints back to the host."""
    data = request.get_json() or {}
    usage = data.get('usage') or ''
    team_id = data.get('team_id') or None
    try:
        resolution = router.resolve(usage, team_id, data.get('context') or {})
    except (router.AIRoutingError, usages.UnknownUsageError) as e:
        tracing.trace_call(name=f'AI {usage}', usage=usage, input={'prompt': data.get('prompt') or ''},
                           attempts=[], ok=False, error=str(e), team_id=team_id)
        return jsonify({'success': False, 'error': str(e), 'content': ''})
    start = int(data.get('start') or 0)
    max_tokens = int(data.get('max_tokens') or 1000)
    temperature = data.get('temperature')
    primary = resolution.primary
    # A host-reach endpoint is a keyless local model: it cannot search, so web usages stay here.
    if start == 0 and primary.reach == 'host' and not gateway.needs_web(usage):
        return jsonify({
            'success': False,
            'direct': {
                'hop': primary.describe(),
                'max_tokens': primary.max_tokens(max_tokens),
                'temperature': primary.temperature(temperature),
                'extra_body': primary.extra_body(usage),
                'split_arm': resolution.split_arm,
                'via': resolution.via_key,
                'request_id': resolution.request_id,
            },
        })
    timeout_s = int(data['timeout_s']) if data.get('timeout_s') else None
    result = gateway.execute(
        resolution, data.get('prompt') or '', image_b64=data.get('image_b64'),
        media_type=data.get('media_type') or 'image/jpeg', system=data.get('system'),
        max_tokens=max_tokens, temperature=temperature, start=start, timeout_s=timeout_s,
    )
    if not result['success'] and data.get('direct_error'):
        result['error'] = f"{data['direct_error']}; {result['error']}"
    return jsonify(result)


@server_ai_routing_bp.route('/decide', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:decide')
def decide():
    """Run one typed decision for a host (``decisions.decide``): the server holds the key,
    counts the call and writes the ``ai_decisions`` log. ``profile`` pins one profile with no
    fallback (``router.resolve_profile``); otherwise ``usage`` is routed."""
    data = request.get_json() or {}
    usage = data.get('usage') or ''
    team_id = data.get('team_id') or None
    if not decisions.enabled(usage):  # JEV_ENABLED / JEV_DISABLED_USAGES: not an error, the caller keeps its path
        return jsonify({**decisions.disabled_result(), 'answers': {}, 'decision_id': None})
    try:
        if data.get('profile'):
            resolution = router.resolve_profile(data['profile'], usage, team_id)
        else:
            resolution = router.resolve(usage, team_id, data.get('context') or {})
    except (router.AIRoutingError, usages.UnknownUsageError) as e:
        return jsonify({'success': False, 'error': str(e), 'answers': {}, 'decision_id': None})
    timeout_s = int(data['timeout_s']) if data.get('timeout_s') else None
    return jsonify(decisions.decide(resolution, data.get('state'), data.get('questions') or {},
                                    timeout_s=timeout_s, refs=data.get('refs') or None,
                                    log=data.get('log') is not False))


def _iso_arg(name: str) -> Optional[str]:
    """An ISO timestamp query arg, normalised ('+' arrives as a space in a URL); ValueError when invalid."""
    raw = (request.args.get(name) or '').strip()
    if not raw:
        return None
    from datetime import datetime
    datetime.fromisoformat(raw.replace(' ', '+').replace('Z', '+00:00'))
    return raw.replace(' ', '+')


def _bool_arg(name: str) -> Optional[bool]:
    raw = (request.args.get(name) or '').strip().lower()
    if not raw:
        return None
    if raw not in ('true', 'false'):
        raise ValueError(f'{name} must be true or false')
    return raw == 'true'


@server_ai_routing_bp.route('/decisions', methods=['GET'])
@require_service_key
@handle_route_exceptions('server_ai_routing:list_decisions')
def list_decisions():
    team_id = request.args.get('team_id')
    if not team_id:
        return _bad('team_id is required')
    refs = {k[4:]: v for k, v in request.args.items() if k.startswith('ref.') and len(k) > 4}
    try:
        limit = int(request.args.get('limit') or 100)
        offset = int(request.args.get('offset') or 0)
        rows = ai_decisions_db.query_decisions(
            team_id, usage=request.args.get('usage') or None, since=_iso_arg('since'), until=_iso_arg('until'),
            ok=_bool_arg('ok'), has_outcome=_bool_arg('has_outcome'), refs=refs,
            include_state='state' in (request.args.get('include') or '').split(','),
            limit=limit, offset=offset)
    except ValueError as e:
        return _bad(str(e))
    return jsonify({'success': True, 'count': len(rows), 'decisions': rows})


@server_ai_routing_bp.route('/decisions/summary', methods=['GET'])
@require_service_key
@handle_route_exceptions('server_ai_routing:decisions_summary')
def decisions_summary():
    team_id = request.args.get('team_id')
    if not team_id:
        return _bad('team_id is required')
    try:
        since = _iso_arg('since')
    except ValueError as e:
        return _bad(str(e))
    return jsonify({'success': True, **ai_decisions_db.summarize_decisions(team_id, since=since)})


def _openrouter_credits() -> list[dict[str, Any]]:
    """Account credit of every OpenRouter endpoint that has a key (read-only, spends nothing)."""
    out = []
    for ep in ai_routing_db.list_endpoints():
        # Preset endpoints keep base_url empty (the preset supplies it): match on either.
        if ep.get('preset') != 'openrouter' and 'openrouter.ai' not in (ep.get('base_url') or ''):
            continue
        key = secrets_store.get_secret(ep.get('secret_name'))
        row: dict[str, Any] = {'endpoint': ep.get('name'), 'has_key': bool(key)}
        if key:
            hdr = {'Authorization': f'Bearer {key}'}
            try:
                c = (requests.get('https://openrouter.ai/api/v1/credits', headers=hdr, timeout=10).json() or {}).get('data') or {}
                total, used = float(c.get('total_credits') or 0), float(c.get('total_usage') or 0)
                row.update(total_credits=total, total_usage=round(used, 6), balance=round(total - used, 6))
            except Exception as e:  # noqa: BLE001 - report, never raise
                row['credits_error'] = str(e)[:200]
            try:
                k = (requests.get('https://openrouter.ai/api/v1/key', headers=hdr, timeout=10).json() or {}).get('data') or {}
                row['key'] = {f: k.get(f) for f in ('limit', 'limit_remaining', 'usage', 'usage_daily', 'usage_monthly', 'is_free_tier')}
            except Exception as e:  # noqa: BLE001
                row['key_error'] = str(e)[:200]
        out.append(row)
    return out


@server_ai_routing_bp.route('/credits', methods=['GET'])
@require_service_key
@handle_route_exceptions('server_ai_routing:credits')
def provider_credits():
    """Account credit of every OpenRouter endpoint that has a key, read-only: OpenRouter's
    ``/api/v1/credits`` (account: bought, used, balance) and ``/api/v1/key`` (this key's own limit).
    Spends nothing. A 402 "Insufficient credits" on calls means ``balance <= 0`` here."""
    return jsonify({'success': True, 'at': int(time.time()), 'endpoints': _openrouter_credits()})


@server_ai_routing_bp.route('/decisions/<decision_id>/outcome', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:set_decision_outcome')
def set_decision_outcome(decision_id):
    data = request.get_json(silent=True) or {}
    team_id = data.get('team_id')
    outcome = data.get('outcome')
    if not team_id:
        return _bad('team_id is required')
    if not isinstance(outcome, dict) or not outcome.get('label'):
        return _bad('outcome must be an object with a label')
    if not decisions.set_outcome(decision_id, team_id, outcome):
        return _bad('Decision not found for this team', 404)
    return jsonify({'success': True, 'decision_id': decision_id})


@server_ai_routing_bp.route('/resolve', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:resolve')
def resolve():
    data = request.get_json() or {}
    usage = data.get('usage') or ''
    team_id = data.get('team_id') or None
    try:
        resolution = router.resolve(usage, team_id, data.get('context') or {})
    except (router.AIRoutingError, usages.UnknownUsageError) as e:
        return jsonify({'success': True, 'available': False, 'error': str(e)})
    available = any(h.has_credentials() for h in resolution.hops)
    return jsonify({'success': True, 'available': available, 'routing': resolution.summary()})


@server_ai_routing_bp.route('/stats', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:report_stats')
def report_stats():
    """Stats for a call a host made directly to a host-reach endpoint."""
    data = request.get_json() or {}
    # The host's caller (X-VPT-Caller) is already bound by the request hook; the row carries it.
    reported = call_log.reported_row(data, tracing.deployment_context().get('server'))
    call_log.submit(reported)
    tracing.trace_reported_call(
        usage=data.get('usage') or 'unknown', team_id=data.get('team_id') or None,
        profile=data.get('profile') or '?', endpoint=data.get('endpoint') or '?', ok=bool(data.get('ok')),
        ms=int(data.get('ms') or 0), tokens=(int(data.get('tokens_in') or 0), int(data.get('tokens_out') or 0)),
        split_arm=data.get('split_arm') or '', cost=reported.get('cost'),
    )
    return jsonify({'success': True})


# Payload keys that are VPT profile flags, not provider parameters.
_PROFILE_FLAGS = ('max_tokens_param', 'omit_temperature')


@server_ai_routing_bp.route('/openai/<usage>/chat/completions', methods=['POST'])
@require_service_key
@handle_route_exceptions('server_ai_routing:openai_passthrough')
def openai_passthrough(usage):
    """Forward an OpenAI chat-completions request to the routed OpenAI-compatible endpoint."""
    body = request.get_json() or {}
    if body.get('stream'):
        return _bad('Streaming is not supported by the AI gateway passthrough')
    team_id = request.headers.get('X-VPT-Team-Id') or None
    try:
        resolution = router.resolve(usage, team_id)
    except (router.AIRoutingError, usages.UnknownUsageError) as e:
        return _bad(str(e), 404)
    attempts: list = []
    response, answer, error = _passthrough_hops(usage, body, resolution, attempts)
    tracing.trace_call(
        name=f'AI {usage} (openai passthrough)', usage=usage, input=body.get('messages') or [],
        attempts=attempts, resolution=resolution, output=answer, ok=error is None, error=error,
        team_id=team_id, session_id=resolution.request_id,
    )
    return response


def _passthrough_hops(usage, body, resolution, attempts):
    """Try each hop; returns (flask response, answer text or None, error or None)."""
    errors = []
    for hop in resolution.hops:
        if hop.reach == 'host' or get_preset(hop.preset).client != 'openai_compatible':
            errors.append(f'{hop.profile_name}: not an OpenAI-compatible server-reachable endpoint')
            continue
        attempt = tracing.Attempt(hop)
        attempt.fallback = resolution.is_fallback(hop)
        attempts.append(attempt)
        extra = {k: v for k, v in hop.extra_body(usage).items() if k not in _PROFILE_FLAGS}
        payload = {**body, **extra, 'model': hop.model}
        if hop.preset == 'openrouter':
            payload.setdefault('usage', {'include': True})  # OpenRouter then reports the billed cost (usage.cost)
        headers = {'Authorization': f"Bearer {secrets_store.get_secret(hop.endpoint.get('secret_name')) or 'local'}",
                   'Content-Type': 'application/json', **get_preset(hop.preset).extra_headers}
        started = time.time()
        try:
            upstream = requests.post(f"{hop.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers,
                                     timeout=http_timeout(hop.timeout))
        except Exception as e:
            router.record(resolution, hop, ok=False, ms=int((time.time() - started) * 1000),
                          fallback=resolution.is_fallback(hop), error_type=classify_error(e))
            if is_connection_error(e):
                router.mark_down(hop)
            errors.append(f'{hop.endpoint_name}: {e}')
            attempt.finish(ok=False, error=errors[-1])
            continue
        ms = int((time.time() - started) * 1000)
        data = {}
        try:
            data = upstream.json()
        except ValueError:
            pass
        usage_block = data.get('usage') or {}
        used = openai_call_usage(usage_block)
        tokens = (used.tokens_in, used.tokens_out)
        router.record(resolution, hop, ok=upstream.status_code < 400, ms=ms,
                      tokens_in=tokens[0], tokens_out=tokens[1], fallback=resolution.is_fallback(hop), usage=used,
                      error_type=None if upstream.status_code < 400 else _http_error_type(upstream.status_code))
        if upstream.status_code >= 500:
            errors.append(f'{hop.endpoint_name}: HTTP {upstream.status_code}')
            attempt.finish(ok=False, error=errors[-1], tokens=tokens)
            continue
        answer = None
        try:
            message = (data.get('choices') or [{}])[0].get('message') or {}
            answer = message.get('content') or (json.dumps(message.get('tool_calls')) if message.get('tool_calls') else None)
        except Exception:
            pass
        ok = upstream.status_code < 400
        attempt.finish(ok=ok, output=answer, tokens=tokens, usage=used,
                       error=None if ok else f'HTTP {upstream.status_code}: {upstream.text[:300]}')
        response = Response(upstream.content, status=upstream.status_code,
                            content_type=upstream.headers.get('Content-Type', 'application/json'))
        return response, answer, attempt.error
    error = '; '.join(errors) or 'no usable AI profile'
    return (jsonify({'error': {'message': error, 'type': 'gateway_error'}}), 502), None, error
