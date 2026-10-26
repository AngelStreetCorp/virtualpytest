"""
Atlas quick-step statistics (TASK-140 Q3/Q4).

Per (team, user, tool): ``uses`` in full Atlas turns, ``hits`` and ``misses`` of the quick step. The quick set of a
user is learned from these (``backend_server/src/agent/quick_step.py``).

Rules:
- Every query filters by ``team_id``.
- Every function fails soft: it logs and returns an empty result / False. A statistics problem never breaks a turn.
- Reads are cached for ``CACHE_TTL_S`` seconds (the database is a WAN hop); a write drops that team's cache.
"""

import logging
import threading
import time
from typing import Any, Dict

from shared.src.lib.utils.supabase_utils import get_supabase_client

logger = logging.getLogger(__name__)

TABLE = 'atlas_quick_tool_stats'
CACHE_TTL_S = 30
TEAM_MAX_ROWS = 5000

_cache: Dict[Any, Any] = {}
_cache_lock = threading.Lock()


def _cached(key, loader):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _drop_cache(team_id: str) -> None:
    with _cache_lock:
        for key in [k for k in _cache if k[1] == team_id]:
            del _cache[key]


def _rows_to_map(rows) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for row in rows or []:
        slot = out.setdefault(row['tool'], {'uses': 0, 'hits': 0, 'misses': 0})
        for field in ('uses', 'hits', 'misses'):
            slot[field] += int(row.get(field) or 0)
    return out


def load(team_id: str, user_id: str) -> Dict[str, Dict[str, int]]:
    """{tool: {uses, hits, misses}} of one user in one team; {} on any problem."""
    if not team_id or not user_id:
        return {}

    def _load():
        try:
            result = (get_supabase_client().table(TABLE).select('tool,uses,hits,misses')
                      .eq('team_id', team_id).eq('user_id', user_id).execute())
            return _rows_to_map(result.data)
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning('atlas quick stats load failed: %s', exc)
            return {}
    return _cached(('user', team_id, user_id), _load)


def load_team(team_id: str) -> Dict[str, Dict[str, int]]:
    """{tool: {uses, hits, misses}} summed over every user of the team; {} on any problem."""
    if not team_id:
        return {}

    def _load():
        try:
            result = (get_supabase_client().table(TABLE).select('tool,uses,hits,misses')
                      .eq('team_id', team_id).limit(TEAM_MAX_ROWS).execute())
            return _rows_to_map(result.data)
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning('atlas quick stats team load failed: %s', exc)
            return {}
    return _cached(('team', team_id), _load)


def _bump(team_id: str, user_id: str, tool: str, uses: int, hits: int, misses: int) -> bool:
    if not team_id or not user_id or not tool:
        return False
    try:
        get_supabase_client().rpc('atlas_quick_tool_bump', {
            'p_team_id': team_id, 'p_user_id': user_id, 'p_tool': tool,
            'p_uses': uses, 'p_hits': hits, 'p_misses': misses,
        }).execute()
        _drop_cache(team_id)
        return True
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning('atlas quick stats write failed: %s', exc)
        return False


def add_use(team_id: str, user_id: str, tool: str) -> bool:
    return _bump(team_id, user_id, tool, 1, 0, 0)


def add_hit(team_id: str, user_id: str, tool: str) -> bool:
    return _bump(team_id, user_id, tool, 0, 1, 0)


def add_miss(team_id: str, user_id: str, tool: str) -> bool:
    return _bump(team_id, user_id, tool, 0, 0, 1)
