"""
AI Routing Database Operations (TASK-30)

Tables (setup/db/schema/055_ai_routing.sql):
- ai_endpoints   server-level: where requests go (preset, base URL, secret name)
- ai_profiles    server-level: a model on an endpoint + parameters + fallback
- ai_routes      usage -> profile; team_id NULL = server default, else a team override
- ai_usage_stats hourly rollup per usage

Team filtering (named exception to CONTRACTS §7): endpoints and profiles have no
team; routes and stats are read as ``team_id = X OR team_id IS NULL`` so a team sees
the server default plus its own overrides. X always comes from the auth-checked
request, never from a body field alone.

Reads raise on failure so the resolver can keep serving its last good snapshot;
writes raise so routes can report the database's message (e.g. the root-route
protection trigger).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

_ENDPOINT_FIELDS = ('name', 'preset', 'base_url', 'secret_name', 'reach', 'timeout_s',
                    'max_concurrency', 'allowed_team_ids', 'enabled', 'region')
_PROFILE_FIELDS = ('name', 'endpoint_id', 'model', 'temperature', 'max_tokens_cap', 'thinking',
                   'image_max_edge', 'extra', 'fallback_profile_id', 'capabilities', 'enabled')
_ROUTE_FIELDS = ('team_id', 'usage_key', 'profile_id', 'host_name', 'device_model',
                 'userinterface_name', 'split_profile_id', 'split_percent', 'priority', 'enabled')

_TABLE_FIELDS = {
    'ai_endpoints': _ENDPOINT_FIELDS,
    'ai_profiles': _PROFILE_FIELDS,
    'ai_routes': _ROUTE_FIELDS,
}


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _clean(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    allowed = _TABLE_FIELDS[table]
    row = {k: v for k, v in data.items() if k in allowed}
    # Empty strings from forms mean "not set".
    return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in row.items()}


def load_snapshot() -> Dict[str, List[Dict]]:
    """Every endpoint, profile and route (all teams) — the resolver's working set."""
    supabase = get_supabase()
    return {
        'endpoints': supabase.table('ai_endpoints').select('*').execute().data or [],
        'profiles': supabase.table('ai_profiles').select('*').execute().data or [],
        'routes': supabase.table('ai_routes').select('*').execute().data or [],
    }


def list_endpoints() -> List[Dict]:
    return get_supabase().table('ai_endpoints').select('*').order('name').execute().data or []


def list_profiles() -> List[Dict]:
    return get_supabase().table('ai_profiles').select('*').order('name').execute().data or []


def list_routes(team_id: Optional[str]) -> List[Dict]:
    """Server-default routes plus ``team_id``'s overrides (only defaults when None)."""
    query = get_supabase().table('ai_routes').select('*')
    if team_id:
        query = query.or_(f'team_id.is.null,team_id.eq.{team_id}')
    else:
        query = query.is_('team_id', 'null')
    return query.order('usage_key').execute().data or []


def get_row(table: str, row_id: str) -> Optional[Dict]:
    rows = get_supabase().table(table).select('*').eq('id', row_id).limit(1).execute().data or []
    return rows[0] if rows else None


def create_row(table: str, data: Dict[str, Any]) -> Dict:
    row = _clean(table, data)
    now = datetime.now(timezone.utc).isoformat()
    row.update({'created_at': now, 'updated_at': now})
    result = get_supabase().table(table).insert(row).execute()
    return (result.data or [{}])[0]


def update_row(table: str, row_id: str, data: Dict[str, Any], team_id: Optional[str] = None) -> Optional[Dict]:
    """Update one row. For ai_routes, ``team_id`` pins the layer being edited."""
    row = _clean(table, data)
    row.pop('team_id', None)  # a route never changes layer
    row['updated_at'] = datetime.now(timezone.utc).isoformat()
    query = get_supabase().table(table).update(row).eq('id', row_id)
    if table == 'ai_routes':
        query = query.eq('team_id', team_id) if team_id else query.is_('team_id', 'null')
    result = query.execute()
    return (result.data or [None])[0]


def delete_row(table: str, row_id: str, team_id: Optional[str] = None) -> bool:
    query = get_supabase().table(table).delete().eq('id', row_id)
    if table == 'ai_routes':
        query = query.eq('team_id', team_id) if team_id else query.is_('team_id', 'null')
    result = query.execute()
    return bool(result.data)


def ingest_calls(rows: List[Dict]) -> int:
    """Insert call-log rows and bump the hourly rollup in one round trip (``ai_calls_ingest``)."""
    if not rows:
        return 0
    result = get_supabase().rpc('ai_calls_ingest', {'p_rows': rows}).execute()
    return int(result.data or 0)


def get_stats(team_id: Optional[str], hours: int = 24) -> List[Dict]:
    """Hourly rows of the last ``hours`` for the server default + ``team_id``."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    query = get_supabase().table('ai_usage_stats').select('*').gte('bucket', since)
    if team_id:
        query = query.or_(f'team_id.is.null,team_id.eq.{team_id}')
    else:
        query = query.is_('team_id', 'null')
    return query.execute().data or []


def list_routes_all() -> List[Dict]:
    """Every route of every layer (server default and all team overrides): the "All teams" view of Settings → AI."""
    return get_supabase().table('ai_routes').select('*').order('usage_key').execute().data or []


def get_usage_rows(team_id: Optional[str], hours: int, all_teams: bool = False) -> List[Dict]:
    """Hourly ``ai_usage_stats`` rows of the last ``hours``, paged past PostgREST's row cap.

    ``team_id`` set: that team plus the server-default rows (team NULL: background callers).
    ``all_teams``: no team filter (platform admin only — the route enforces it)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows: List[Dict] = []
    offset, page = 0, 1000
    while True:
        query = get_supabase().table('ai_usage_stats').select('*').gte('bucket', since)
        if not all_teams:
            query = query.or_(f'team_id.is.null,team_id.eq.{team_id}') if team_id else query.is_('team_id', 'null')
        batch = query.order('bucket').range(offset, offset + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def get_team_names(team_ids: List[str]) -> Dict[str, str]:
    if not team_ids:
        return {}
    data = get_supabase().table('teams').select('id,name').in_('id', team_ids).execute().data or []
    return {t['id']: t.get('name') or t['id'] for t in data}


def get_calls_rollup(team_id: Optional[str], hours: int, all_teams: bool = False, step: str = 'hour',
                     user_id: Optional[str] = None) -> List[Dict]:
    """``ai_calls`` aggregated by every dimension (``ai_calls_rollup``): the rows behind the 1 h - 7 d views.

    ``user_id`` limits to one person's calls; ``all_teams`` drops the team filter (platform admin)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = get_supabase().rpc('ai_calls_rollup', {
        'p_since': since, 'p_team': team_id, 'p_all': all_teams, 'p_step': step, 'p_user': user_id,
    }).execute()
    return result.data or []


# group name -> ai_calls column, for filtering the call list
CALL_FILTER_COLUMNS = {
    'usage': 'usage_key', 'model': 'profile', 'endpoint': 'endpoint', 'team': 'team_id', 'origin': 'origin',
    'host': 'host_name', 'script': 'script_name', 'campaign': 'campaign_id', 'user': 'user_id',
    'server': 'server', 'script_result_id': 'script_result_id', 'request_id': 'request_id',
    'arm': 'split_arm', 'error': 'error_type', 'client': 'client_hash',
}


def get_recent_calls(team_id: Optional[str], hours: int, filters: Dict[str, str], limit: int = 200,
                     all_teams: bool = False, user_id: Optional[str] = None, only_errors: bool = False,
                     only_ok: bool = False, team_ids: Optional[List[str]] = None) -> List[Dict]:
    """Newest ``ai_calls`` rows of the window matching ``filters`` (a ``CALL_FILTER_COLUMNS`` name -> value)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    query = get_supabase().table('ai_calls').select('*').gte('ts', since).neq('outcome', 'skipped')
    if not all_teams:
        if team_ids and len(team_ids) > 1:
            query = query.or_('team_id.is.null,' + ','.join(f'team_id.eq.{t}' for t in team_ids))
        else:
            query = query.or_(f'team_id.is.null,team_id.eq.{team_id}') if team_id else query.is_('team_id', 'null')
    if user_id:
        query = query.eq('user_id', user_id)
    for name, value in filters.items():
        if name == 'device':
            host, _, device = value.partition(' / ')
            query = query.eq('host_name', host)
            if device:
                query = query.eq('device_id', device)
        elif name in CALL_FILTER_COLUMNS:
            query = query.eq(CALL_FILTER_COLUMNS[name], value)
    if only_errors:
        query = query.eq('ok', False)
    elif only_ok:
        query = query.eq('ok', True)
    return query.order('ts', desc=True).limit(limit).execute().data or []


def get_skipped_paused(team_id: Optional[str], hours: int, all_teams: bool = False) -> Dict[str, List[str]]:
    """``{endpoint: [ts, ...]}`` of calls skipped because their provider was paused for no credit
    (``outcome = skipped``, ``stop_reason = provider_paused``). Counted for the banner, never listed."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    query = (get_supabase().table('ai_calls').select('endpoint,ts').gte('ts', since)
             .eq('outcome', 'skipped').eq('stop_reason', 'provider_paused'))
    if not all_teams:
        query = query.or_(f'team_id.is.null,team_id.eq.{team_id}') if team_id else query.is_('team_id', 'null')
    out: Dict[str, List[str]] = {}
    for row in query.order('ts', desc=True).limit(10000).execute().data or []:
        out.setdefault(row['endpoint'], []).append(row['ts'])
    return out


def get_user_names(user_ids: List[str]) -> Dict[str, str]:
    """``profiles`` display names (full name, else email) for UUID user ids."""
    import re
    ids = [u for u in user_ids if re.match(r'^[0-9a-fA-F-]{36}$', u or '')]
    if not ids:
        return {}
    rows = get_supabase().table('profiles').select('id,full_name,email').in_('id', ids).execute().data or []
    return {r['id']: (r.get('full_name') or r.get('email') or r['id']) for r in rows}


def get_calls_by_request_ids(request_ids: List[str], team_id: Optional[str], all_teams: bool = False) -> Dict[str, Dict]:
    """``{request_id: call}`` (usage, profile, model, cost, ok) for the first served call of each request id."""
    out: Dict[str, Dict] = {}
    for i in range(0, len(request_ids), 150):
        query = (get_supabase().table('ai_calls').select('request_id,usage_key,profile,model,cost,ok,team_id')
                 .in_('request_id', request_ids[i:i + 150]).eq('outcome', 'served').eq('ok', True))
        if not all_teams:
            query = query.eq('team_id', team_id)
        for row in query.execute().data or []:
            out.setdefault(row['request_id'], row)
    return out


_PRICE_FIELDS = ('endpoint', 'model', 'price_in', 'price_out', 'price_cache_read', 'price_cache_write',
                 'price_web_search', 'valid_from', 'note')


def list_prices() -> List[Dict]:
    """Every ``ai_prices`` row (server-level, no team): the price table behind cost at write time."""
    return (get_supabase().table('ai_prices').select('*').order('endpoint').order('model')
            .order('valid_from', desc=True).execute().data or [])


def create_price(data: Dict[str, Any]) -> Dict:
    row = {k: v for k, v in data.items() if k in _PRICE_FIELDS and v not in ('', None)}
    return (get_supabase().table('ai_prices').insert(row).execute().data or [{}])[0]


def delete_price(price_id: str) -> bool:
    return bool(get_supabase().table('ai_prices').delete().eq('id', price_id).execute().data)


def get_run_cost(team_id: str, script_result_ids: List[str]) -> Dict[str, Any]:
    """AI requests, tokens and cost of the given script runs (``ai_calls`` by ``script_result_id``).

    Always filtered by ``team_id``. ``cost`` is None when no call of the runs carries a price."""
    totals: Dict[str, Any] = {'calls': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'cost': None, 'priced_calls': 0}
    for i in range(0, len(script_result_ids), 100):
        rows = (get_supabase().table('ai_calls').select('ok,tokens_in,tokens_out,cost,outcome')
                .eq('team_id', team_id).eq('outcome', 'served')
                .in_('script_result_id', script_result_ids[i:i + 100]).limit(10000).execute().data or [])
        for r in rows:
            totals['calls'] += 1
            totals['errors'] += 0 if r.get('ok') else 1
            totals['tokens_in'] += int(r.get('tokens_in') or 0)
            totals['tokens_out'] += int(r.get('tokens_out') or 0)
            if r.get('cost') is not None:
                totals['cost'] = (totals['cost'] or 0.0) + float(r['cost'])
                totals['priced_calls'] += 1
    return totals


def get_budget(team_id: str) -> Optional[Dict]:
    """The team's monthly AI budget row (``ai_budgets``), or None."""
    rows = get_supabase().table('ai_budgets').select('*').eq('team_id', team_id).limit(1).execute().data or []
    return rows[0] if rows else None


def set_budget(team_id: str, month_limit_usd: float, mode: str, warn_at: float, updated_by: Optional[str]) -> Dict:
    row = {'team_id': team_id, 'month_limit_usd': month_limit_usd, 'mode': mode, 'warn_at': warn_at,
           'updated_by': updated_by, 'updated_at': datetime.now(timezone.utc).isoformat()}
    return (get_supabase().table('ai_budgets').upsert(row, on_conflict='team_id').execute().data or [row])[0]


def delete_budget(team_id: str) -> bool:
    return bool(get_supabase().table('ai_budgets').delete().eq('team_id', team_id).execute().data)


def get_month_spend(team_id: str, since: datetime) -> float:
    """Priced AI cost (USD) of ``team_id`` since ``since``, from the hourly rollup. Unpriced calls add nothing."""
    total, offset, page = 0.0, 0, 1000
    while True:
        rows = (get_supabase().table('ai_usage_stats').select('cost').eq('team_id', team_id)
                .gte('bucket', since.isoformat()).range(offset, offset + page - 1).execute().data or [])
        total += sum(float(r.get('cost') or 0) for r in rows)
        if len(rows) < page:
            return total
        offset += page
