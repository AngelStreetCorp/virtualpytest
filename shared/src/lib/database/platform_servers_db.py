"""
Platform server list storage (TASK-179).

One row per server of the platform: ``name`` (= that server's SERVER_NAME) and ``url`` (public origin). The exception to
"every query filters by team_id": the table lists the platform's machines, so it is platform-level (like
platform_update_settings). Service role only (RLS on, no grant to anon/authenticated).
See setup/db/schema/086_platform_servers.sql.

``TableMissing`` is raised when the migration is not applied on this database (QualiAI and gcloud have their own databases).
"""

import re
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'platform_servers'
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
_FIELDS = 'name,url,enabled,sort_order'


class TableMissing(Exception):
    """The table does not exist (migration 20261026a not applied here) or the database client is not configured."""


class InvalidServers(ValueError):
    """The rows given to ``replace_servers`` are not valid; the message says which and why."""


def get_supabase():
    return get_supabase_client()


def _client():
    client = get_supabase()
    if client is None:
        raise TableMissing('no database client')
    return client


def _is_missing(exc: Exception) -> bool:
    text = f'{getattr(exc, "code", "")} {exc}'.lower()
    return 'pgrst205' in text or '42p01' in text or 'could not find the table' in text or 'does not exist' in text


def _is_lan_host(host: str) -> bool:
    if host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def validate_url(url: Any) -> str:
    """The URL is an origin (scheme + host[:port], no path, no trailing slash); http only for LAN / localhost."""
    if not isinstance(url, str) or not url:
        raise InvalidServers('url is required')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise InvalidServers(f'url "{url}" must start with https:// or http://')
    if parsed.path or parsed.params or parsed.query or parsed.fragment or url.endswith('/') or parsed.username:
        raise InvalidServers(f'url "{url}" must be an origin only (no path, query or trailing slash)')
    if parsed.scheme == 'http' and not _is_lan_host(parsed.hostname):
        raise InvalidServers(f'url "{url}" must use https (http is only allowed for LAN / localhost)')
    return url


def validate_rows(rows: Any) -> List[Dict[str, Any]]:
    """Normalised rows ``{name, url, enabled, sort_order}``. Names are unique case-insensitively."""
    if not isinstance(rows, list):
        raise InvalidServers('servers must be a list')
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InvalidServers(f'server #{i + 1} must be an object')
        name = row.get('name')
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise InvalidServers(f'server name "{name}" must match {NAME_RE.pattern}')
        if name.lower() in seen:
            raise InvalidServers(f'duplicate server name "{name}" (names are case-insensitive)')
        seen.add(name.lower())
        sort_order = row.get('sort_order', i * 10)
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            raise InvalidServers(f'server "{name}": sort_order must be an integer')
        enabled = row.get('enabled', True)
        if not isinstance(enabled, bool):
            raise InvalidServers(f'server "{name}": enabled must be true or false')
        try:
            url = validate_url(row.get('url'))
        except InvalidServers as exc:
            raise InvalidServers(f'server "{name}": {exc}') from exc
        out.append({'name': name, 'url': url, 'enabled': enabled, 'sort_order': sort_order})
    return out


def list_servers(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """Servers ordered by sort_order, name. Raises ``TableMissing`` when the table is not there."""
    try:
        query = _client().table(TABLE).select(_FIELDS)
        if not include_disabled:
            query = query.eq('enabled', True)
        result = query.order('sort_order').order('name').execute()
    except TableMissing:
        raise
    except Exception as exc:
        if _is_missing(exc):
            raise TableMissing(str(exc)) from exc
        raise
    return list(result.data or [])


def replace_servers(rows: Any) -> List[Dict[str, Any]]:
    """Validate, upsert the given rows, delete the rows not given. Returns the stored list (disabled rows included).

    The database client has no multi-statement transaction: the upsert runs first so a failure leaves the old list intact.
    """
    clean = validate_rows(rows)
    client = _client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        existing = [r['name'] for r in (client.table(TABLE).select('name').execute().data or [])]
        if clean:
            client.table(TABLE).upsert([dict(r, updated_at=now) for r in clean], on_conflict='name').execute()
        keep = {r['name'] for r in clean}
        for name in (n for n in existing if n not in keep):
            client.table(TABLE).delete().eq('name', name).execute()
    except Exception as exc:
        if _is_missing(exc):
            raise TableMissing(str(exc)) from exc
        raise
    return list_servers(include_disabled=True)
