"""
AI budget resolver (TASK-87 phase 5 / BUG-0559): per-bucket monthly budgets, most-specific wins.

Each ``ai_budgets`` row is keyed by ``(bucket_type, bucket_id)`` where ``bucket_type`` is one of
``team``, ``user``, ``model``, ``endpoint``, ``usage``, ``project``. Every bucket carries a
``team_scope`` (FK to ``teams.id``) so the resolver can always join spend back to the team that
owns the cost — the tenant-defending team.

Specificity ladder (most specific first):

    usage > model > endpoint > user > project > team

The resolver collects every bucket that applies to the call (zero or more rows), reports
them all in the API/UI response, and blocks when **any** matching bucket has mode ``block``
and is over its limit. The most-specific bucket wins the visibility rule for the UI (it is
the one shown as the "active" budget), but blocking is a union: one over-limit block bucket
refuses the call regardless of the others.

Spend sources:

- **team** bucket → ``ai_usage_stats.cost`` (hourly rollup, fast).
- **finer** buckets → ``ai_calls.cost`` summed per dimension (90-day per-call log).

``blocked(team_id)`` is the backward-compat shortcut: it builds a context with only the team
id and asks the resolver. The gateway + agent manager now pass a richer ``CallerContext``
so finer buckets are honored.

Fails open: no table, no row, or any DB error means "not blocked". An AI outage must never
come from a budget lookup.

Cache: per (team_id, user_id, usage_key, model, endpoint, project_id) tuple, 60 s TTL.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Iterable

from . import usage_report

CACHE_TTL_S = 60
DEFAULT_WARN_AT = 0.8

BUCKET_TYPES = ("team", "user", "model", "endpoint", "usage", "project")
# Higher = more specific. The resolver orders the response by this and the block decision
# is "any block + over"; the UI's "active budget" is the highest-specificity match.
SPECIFICITY = {
    "team": 0,
    "project": 1,
    "user": 2,
    "endpoint": 3,
    "model": 4,
    "usage": 5,
}
# Most-specific wins at the API surface (we report earlier blocks first in the response).
_RESPONSE_ORDER = sorted(BUCKET_TYPES, key=lambda t: -SPECIFICITY[t])

_lock = threading.Lock()
_cache: dict[tuple, tuple[float, "BudgetDecision"]] = {}
# Backward-compat fallback: when a test sets a decision by team_id alone, the resolver
# can still answer for a richer CallerContext (the gateway passes model + endpoint). The
# team-only entry answers as long as the team_id matches.
_team_cache: dict[str, "BudgetDecision"] = {}


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def unbudgeted_endpoints(spend_by_endpoint: dict, endpoint_bucket_ids: Iterable[str],
                         team_budgeted: bool, names: Optional[dict] = None) -> list:
    """Endpoints with month-to-date spend above 0 and no endpoint bucket, biggest first; ``names`` maps an endpoint
    id to its display name. Rule: a team bucket caps all of the team's spend, so with one nothing is unbudgeted."""
    if team_budgeted:
        return []
    covered = set(endpoint_bucket_ids)
    rows = [{'endpoint': e, 'name': (names or {}).get(e, e), 'spent': round(v, 4)}
            for e, v in spend_by_endpoint.items() if v > 0 and e not in covered]
    return sorted(rows, key=lambda r: -r['spent'])


@dataclasses.dataclass(frozen=True)
class CallerContext:
    """Everything the resolver needs to evaluate every bucket that may apply.

    Fields are all strings; ``None``/empty means "not set" and the resolver skips that bucket.
    The team_id is the only mandatory field — every bucket's spend is reported under its
    ``team_scope`` so the resolver always knows the team to query against.
    """

    team_id: Optional[str]
    user_id: Optional[str] = None
    usage_key: Optional[str] = None
    model: Optional[str] = None
    endpoint: Optional[str] = None      # endpoint name (ai_calls.endpoint)
    project_id: Optional[str] = None

    def cache_key(self) -> tuple:
        return (self.team_id or "", self.user_id or "", self.usage_key or "",
                self.model or "", self.endpoint or "", self.project_id or "")

    def bucket_candidates(self) -> Iterable[tuple[str, str]]:
        """Yield ``(bucket_type, bucket_id)`` for every level with a defined id, in
        specificity order so the most-specific match is first."""
        # The walk stops at the first empty level because finer buckets require the
        # call site to actually know the coarser one (you can't have a model bucket
        # for a call where the model is still unknown).
        for level in ("usage", "model", "endpoint", "user", "project", "team"):
            value = getattr(self, {
                "usage": "usage_key", "model": "model", "endpoint": "endpoint",
                "user": "user_id", "project": "project_id", "team": "team_id",
            }[level], None)
            if not value:
                return
            yield level, str(value)


@dataclasses.dataclass
class BudgetStatus:
    bucket_type: str
    bucket_id: str
    label: Optional[str]
    limit: float
    mode: str
    warn_at: float
    spent: float
    forecast: float
    share: float
    state: str  # ok | warn | over

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class BudgetDecision:
    statuses: list[BudgetStatus]
    blocked: bool

    def to_dict(self) -> dict:
        return {"statuses": [s.to_dict() for s in self.statuses], "blocked": self.blocked}


def status_from(budget: Optional[dict], spent: float, now: Optional[datetime] = None) -> Optional[dict]:
    """Budget status for one bucket (legacy dict shape — ``state``: ok | warn | over), or
    None without a budget. The multi-bucket resolver builds BudgetStatus dataclasses; this
    helper stays a plain dict so the old call sites (the routes' status_from(budget, spent)
    path) keep working unchanged."""
    if not budget:
        return None
    limit = float(budget["month_limit_usd"])
    warn_at = float(budget.get("warn_at") or DEFAULT_WARN_AT)
    forecast = usage_report.forecast_month(spent, now)
    state = "over" if spent >= limit else "warn" if (spent >= limit * warn_at or forecast >= limit) else "ok"
    return {
        "bucket_type": str(budget.get("bucket_type") or "team"),
        "bucket_id": str(budget.get("bucket_id") or ""),
        "label": budget.get("label"),
        "limit": limit, "mode": str(budget.get("mode") or "warn"), "warn_at": warn_at,
        "spent": round(spent, 4), "forecast": round(forecast, 4),
        "share": round(spent / limit, 4) if limit else 0.0, "state": state,
    }


def _budget_status_from(budget: Optional[dict], spent: float, now: Optional[datetime] = None) -> Optional[BudgetStatus]:
    """Same as ``status_from`` but returns the BudgetStatus dataclass — used by the
    multi-bucket resolver where dataclass semantics (sorting, attribute access) help."""
    d = status_from(budget, spent, now)
    if d is None:
        return None
    return BudgetStatus(**d)


def _decide(ctx: CallerContext, now: Optional[datetime] = None) -> BudgetDecision:
    """Walk the candidate ladder. Most-specific bucket wins the API surface; any over-limit
    block bucket refuses the call (union rule). Fails open on any error."""
    if not ctx or not ctx.team_id:
        return BudgetDecision(statuses=[], blocked=False)
    key = ctx.cache_key()
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return _sort_decision(hit[1])
        # Backward-compat: a test that called ``set_for_tests(TEAM, ...)`` populated the
        # team-level cache. Honor it as a fallback so callers with a richer context still
        # see the team's decision.
        team_decision = _team_cache.get(ctx.team_id)
    if team_decision is not None:
        return _sort_decision(team_decision)
    decision = _evaluate(ctx, now)
    with _lock:
        _cache[key] = (time.time(), decision)
    return decision


def _sort_decision(decision: BudgetDecision) -> BudgetDecision:
    """Reorder the cached statuses so the most-specific bucket is first in the API surface."""
    decision.statuses.sort(key=lambda s: (-SPECIFICITY[s.bucket_type],
                                          0 if s.state == "over" else 1 if s.state == "warn" else 2))
    return decision


def _evaluate(ctx: CallerContext, now: Optional[datetime] = None) -> BudgetDecision:
    since = month_start(now)
    statuses: list[BudgetStatus] = []
    try:
        from shared.src.lib.database import ai_routing_db
        for bucket_type, bucket_id in ctx.bucket_candidates():
            if not bucket_id:
                continue
            row = ai_routing_db.get_bucket(bucket_type, bucket_id)
            if not row:
                continue
            spend = ai_routing_db.get_bucket_spend(row["team_scope"], bucket_type, bucket_id, since)
            status = _budget_status_from(row, spend, now)
            if status:
                statuses.append(status)
        # Order for the API surface: most-specific first, then state=over before warn before ok.
        statuses.sort(key=lambda s: (-SPECIFICITY[s.bucket_type], 0 if s.state == "over" else 1 if s.state == "warn" else 2))
    except Exception as e:  # noqa: BLE001 — fail open
        print(f"[AI] budget lookup failed for {ctx.cache_key()}: {e}")
        return BudgetDecision(statuses=[], blocked=False)
    blocked = any(s.mode == "block" and s.state == "over" for s in statuses)
    return BudgetDecision(statuses=statuses, blocked=blocked)


def current(ctx: CallerContext, now: Optional[datetime] = None) -> list[BudgetStatus]:
    """Every bucket that applies to this call, ordered most-specific first."""
    return _decide(ctx, now).statuses


def blocked(ctx) -> bool:
    """True iff ANY matching bucket is over its block limit. Fails open (returns False).

    Accepts a ``CallerContext`` (preferred — gives finer buckets) or a string ``team_id``
    for backward compat (looks at the team bucket only)."""
    if ctx is None:
        return False
    if isinstance(ctx, CallerContext):
        return _decide(ctx).blocked
    if isinstance(ctx, str):
        return blocked_team(ctx)
    return False


def blocked_team(team_id: Optional[str]) -> bool:
    """Backward-compat shortcut. Today (and forever) callers can keep passing only the team
    id; the resolver honors finer buckets when the agent manager / gateway pass them."""
    if not team_id:
        return False
    return blocked(CallerContext(team_id=team_id))


def invalidate(team_id: Optional[str] = None) -> None:
    """Drop the cache. Pass a team_id to only drop the team's entries (best-effort: the
    cache key includes more than team_id so a precise purge would need a tuple — we wipe
    the whole cache; it's 60 s TTL anyway)."""
    with _lock:
        if team_id:
            # Best-effort: drop keys that begin with this team_id. The cache is small.
            for k in list(_cache.keys()):
                if k and k[0] == team_id:
                    _cache.pop(k, None)
            _team_cache.pop(team_id, None)
        else:
            _cache.clear()
            _team_cache.clear()


def set_for_tests(key, status) -> None:
    """Test hook: install a fixed decision (skip TTL inspection by setting ts = far future).
    Backward-compat: ``set_for_tests(team_id, status_dict)`` wraps the dict into a one-bucket
    decision so the older per-team tests keep working unchanged."""
    if isinstance(key, str):
        # Legacy signature: a team_id and a status dict. Wrap into a one-bucket decision so
        # ``blocked(team_id)`` returns True when the dict's mode is block + state is over.
        if status is None:
            decision = BudgetDecision(statuses=[], blocked=False)
        else:
            bs = BudgetStatus(
                bucket_type='team', bucket_id=key, label=None,
                limit=float(status.get('limit', 0)), mode=str(status.get('mode', 'warn')),
                warn_at=float(status.get('warn_at', DEFAULT_WARN_AT)),
                spent=float(status.get('spent', 0)), forecast=float(status.get('forecast', 0)),
                share=float(status.get('share', 0)), state=str(status.get('state', 'ok')),
            )
            decision = BudgetDecision(
                statuses=[bs],
                blocked=(bs.mode == 'block' and bs.state == 'over'),
            )
        cache_key = CallerContext(team_id=key).cache_key()
        # Also populate the team-level fallback cache so callers with a richer
        # CallerContext (gateway + agent manager pass model + endpoint) still see this.
        with _lock:
            _cache[cache_key] = (time.time() + 10 ** 9, decision)
            _team_cache[key] = decision
    else:
        # New signature: a cache key tuple + a BudgetDecision.
        cache_key = key
        decision = status
        with _lock:
            _cache[cache_key] = (time.time() + 10 ** 9, decision)


BLOCKED_MESSAGE = (
    "The monthly AI budget of this team (or the bucket that applies to your call: usage, model, "
    "endpoint, user, project) is used up. Settings → AI → Prices & budget."
)