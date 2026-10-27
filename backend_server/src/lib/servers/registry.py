"""
Cached reader of the platform server list (TASK-179).

``servers()`` reads ``platform_servers`` and keeps it 60 s in this process (one gevent process: a plain timestamp check is
enough, no lock, no thread pool: BUG-0700). ``invalidate()`` forces the next call to reload.
A database without the table (QualiAI, gcloud) gives an empty list and ``table_missing()`` is True.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from shared.src.lib.database import platform_servers_db

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
DEFAULT_SERVER_NAMES = {'server', 'default'}

_cache: Dict[str, Any] = {'at': None, 'rows': [], 'missing': False}


def invalidate() -> None:
    _cache['at'] = None


def _load() -> None:
    try:
        rows = platform_servers_db.list_servers(include_disabled=True)
        _cache.update(rows=rows, missing=False)
    except platform_servers_db.TableMissing as exc:
        logger.warning('server list table missing on this database: %s', exc)
        _cache.update(rows=[], missing=True)
    _cache['at'] = time.monotonic()


def _fresh() -> None:
    at = _cache['at']
    if at is None or time.monotonic() - at >= CACHE_TTL_SECONDS:
        _load()


def servers(include_disabled: bool = True) -> List[Dict[str, Any]]:
    """All servers of the list (disabled ones included by default), ordered by sort_order, name."""
    _fresh()
    rows = _cache['rows']
    return list(rows) if include_disabled else [r for r in rows if r.get('enabled', True)]


def table_missing() -> bool:
    _fresh()
    return bool(_cache['missing'])


def self_name() -> Optional[str]:
    """This server's SERVER_NAME; None when unset or a default (``server`` / ``default``)."""
    name = (os.getenv('SERVER_NAME') or '').strip()
    if not name or name.lower() in DEFAULT_SERVER_NAMES:
        return None
    return name


def self_in_list() -> bool:
    """Whether SERVER_NAME matches a row of the list (case-insensitive)."""
    me = self_name()
    return me is not None and any(r['name'].lower() == me.lower() for r in servers())


def others() -> List[Dict[str, Any]]:
    """Enabled servers other than this one (by name, case-insensitive)."""
    me = (self_name() or '').lower()
    return [r for r in servers(include_disabled=False) if r['name'].lower() != me]
