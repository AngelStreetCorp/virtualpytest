"""
Per-team monthly AI budget (TASK-87 phase 4): month-to-date spend, a linear month-end forecast, and the warn / block
decision. Spend is the priced cost in the hourly rollup (``ai_usage_stats.cost``) for the calendar month (UTC);
unpriced calls cost nothing here, so a team with no prices never trips a budget.

``blocked(team_id)`` is what the gateway and the agent manager ask before a call: True only for a team whose budget
mode is ``block`` and whose month-to-date spend reached the limit. It fails open: no table, no row or a database
error mean "not blocked" (an AI outage must never come from a budget lookup).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from . import usage_report

CACHE_TTL_S = 60
DEFAULT_WARN_AT = 0.8

_lock = threading.Lock()
_cache: dict[str, tuple[float, Optional[dict]]] = {}


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def status_from(budget: Optional[dict], spent: float, now: Optional[datetime] = None) -> Optional[dict]:
    """Budget status for one team, or None without a budget. ``state``: ok | warn | over."""
    if not budget:
        return None
    limit = float(budget["month_limit_usd"])
    warn_at = float(budget.get("warn_at") or DEFAULT_WARN_AT)
    forecast = usage_report.forecast_month(spent, now)
    state = "over" if spent >= limit else "warn" if (spent >= limit * warn_at or forecast >= limit) else "ok"
    return {"limit": limit, "mode": budget.get("mode") or "warn", "warn_at": warn_at, "spent": round(spent, 4),
            "forecast": round(forecast, 4), "share": round(spent / limit, 4) if limit else 0.0, "state": state}


def current(team_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Status for ``team_id`` now (cached 60 s), or None."""
    if not team_id:
        return None
    with _lock:
        hit = _cache.get(team_id)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1]
    result: Optional[dict] = None
    try:
        from shared.src.lib.database import ai_routing_db
        budget = ai_routing_db.get_budget(team_id)
        if budget:
            result = status_from(budget, ai_routing_db.get_month_spend(team_id, month_start(now)), now)
    except Exception as e:  # noqa: BLE001 - fail open
        print(f"[AI] budget lookup failed for {team_id}: {e}")
    with _lock:
        _cache[team_id] = (time.time(), result)
    return result


def blocked(team_id: Optional[str]) -> bool:
    status = current(team_id) if team_id else None
    return bool(status and status["mode"] == "block" and status["state"] == "over")


def invalidate(team_id: Optional[str] = None) -> None:
    with _lock:
        if team_id:
            _cache.pop(team_id, None)
        else:
            _cache.clear()


def set_for_tests(team_id: str, status: Optional[dict]) -> None:
    with _lock:
        _cache[team_id] = (time.time() + 10 ** 9, status)


BLOCKED_MESSAGE = "The monthly AI budget of this team is used up (Settings → AI → Prices & budget)"
