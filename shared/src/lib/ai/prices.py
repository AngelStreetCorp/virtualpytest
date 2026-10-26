"""
Prices and cost at write time (TASK-87).

``ai_prices`` holds per-1M-token prices per (endpoint, model) with a ``valid_from`` date. The call log
stores the cost **when the call is made**: the provider's own figure when it gives one (OpenRouter
``usage.cost``, Jev ``cost``), else the price valid at that moment. Changing a price never rewrites
history; a call with no known price keeps ``cost = NULL`` and shows "no price" — never 0. A price of 0
is a real price (a local GPU) and gives cost 0. A local endpoint with no price row is free (cost 0). Cloud prices
can come from OpenRouter's public model list (rows noted ``source:openrouter``, for OpenRouter endpoints) or Langfuse's
model price list (``source:langfuse``) via ``price_sync``. A flat-plan endpoint (``ProviderPreset.flat_plan``: the MiniMax
coding plan) costs 0 per call and is stored as ``price_table`` with cost 0; the page reads "included in plan" from the preset.
A typed price (any note that is not a ``source:`` tag) always wins over all of these.

An endpoint-wide price uses ``model = '*'`` and applies to every model without its own row.

An endpoint that bills per token but has no price row of its own takes the price of **another endpoint with the same
preset** (a second Anthropic key prices like the first one), so a new endpoint never logs cost NULL.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

CACHE_TTL_S = 60
WILDCARD = "*"
_PER = 1_000_000

_lock = threading.Lock()
_cache: dict[str, Any] = {"rows": None, "at": 0.0, "endpoints": None, "endpoints_at": 0.0}


def set_for_tests(rows: Optional[list[dict]], endpoints: Optional[list[dict]] = None) -> None:
    """Pin the price rows (and the endpoint list) for a test; ``None`` restores the DB."""
    with _lock:
        _cache["rows"], _cache["at"] = rows, time.time() + 10 ** 9 if rows is not None else 0.0
        _cache["endpoints"], _cache["endpoints_at"] = endpoints, time.time() + 10 ** 9 if endpoints is not None else 0.0


def invalidate() -> None:
    with _lock:
        _cache["rows"], _cache["at"] = None, 0.0
        _cache["endpoints"], _cache["endpoints_at"] = None, 0.0


def _load() -> list[dict]:
    with _lock:
        if _cache["rows"] is not None and time.time() - _cache["at"] < CACHE_TTL_S:
            return _cache["rows"]
    rows: list[dict] = []
    try:
        from shared.src.lib.database import ai_routing_db
        rows = ai_routing_db.list_prices()
    except Exception as e:  # noqa: BLE001 - no table / no DB: calls are simply unpriced
        print(f"[AI] price table unavailable: {e}")
    with _lock:
        _cache["rows"], _cache["at"] = rows, time.time()
    return rows


def _load_endpoints() -> list[dict]:
    """The endpoint list (name + preset), cached like the price rows."""
    with _lock:
        if _cache["endpoints"] is not None and time.time() - _cache["endpoints_at"] < CACHE_TTL_S:
            return _cache["endpoints"]
    endpoints: list[dict] = []
    try:
        from shared.src.lib.database import ai_routing_db
        endpoints = ai_routing_db.list_endpoints()
    except Exception as e:  # noqa: BLE001 - no table / no DB: calls are simply unpriced
        print(f"[AI] endpoint list unavailable: {e}")
    with _lock:
        _cache["endpoints"], _cache["endpoints_at"] = endpoints, time.time()
    return endpoints


def _ts(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row_at(rows: list[dict], endpoint: str, model: str, at: datetime) -> Optional[dict]:
    """The price row of ``endpoint`` / ``model`` valid at ``at`` (the latest one), or None."""
    valid = [r for r in rows if r.get("endpoint") == endpoint and r.get("model") == model
             and _ts(r["valid_from"]) <= at]
    return max(valid, key=lambda r: _ts(r["valid_from"])) if valid else None


def _same_preset_price(endpoint: str, model: str, at: datetime, rows: list[dict],
                       endpoints: Optional[list[dict]] = None) -> Optional[dict]:
    """The price of the same model on **another endpoint with the same preset**, or None.

    Only for an endpoint that bills per token: a local endpoint is free and a flat plan is included in its
    subscription, so neither needs a price.
    """
    from .call_audit import bills_tokens
    endpoints = _load_endpoints() if endpoints is None else endpoints
    mine = next((e for e in endpoints if e.get("name") == endpoint), None)
    if not mine or not bills_tokens(mine.get("preset")):
        return None
    preset = (mine.get("preset") or "").lower()
    siblings = [e.get("name") for e in endpoints
                if e.get("name") and e.get("name") != endpoint and (e.get("preset") or "").lower() == preset]
    for wanted in (model, WILDCARD):   # the exact model first, the endpoint-wide price second
        best = None
        for name in siblings:
            found = _row_at(rows, name, wanted, at)
            if found and (best is None or _ts(found["valid_from"]) > _ts(best["valid_from"])):
                best = found
        if best:
            return best
    return None


def price_for(endpoint: str, model: str, at: Optional[datetime] = None, rows: Optional[list[dict]] = None,
              endpoints: Optional[list[dict]] = None) -> Optional[dict]:
    """The price row valid at ``at`` for ``model`` on ``endpoint`` (exact model first, then ``*``), or None.

    An endpoint that bills per token but has no price row of its own takes the price of another endpoint with the
    same preset (a second Anthropic key prices like the first one): a new endpoint never logs cost NULL.
    """
    at = at or datetime.now(timezone.utc)
    rows = _load() if rows is None else rows
    for wanted in (model, WILDCARD):
        found = _row_at(rows, endpoint, wanted, at)
        if found:
            return found
    return _same_preset_price(endpoint, model, at, rows, endpoints)


def _num(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def compute(price: dict, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0,
            web_searches: int = 0) -> tuple[float, float]:
    """``(cost, cache_saved)`` in USD for one call.

    ``tokens_in`` is the whole prompt, cached tokens included (``CallUsage.tokens_in``).
    Cache prices default to the plain input price."""
    p_in = _num(price.get("price_in"), 0.0)
    p_out = _num(price.get("price_out"), 0.0)
    p_read = _num(price.get("price_cache_read"), p_in)
    p_write = _num(price.get("price_cache_write"), p_in)
    plain_in = max(tokens_in - cache_read - cache_write, 0)
    cost = (plain_in * p_in + cache_read * p_read + cache_write * p_write + tokens_out * p_out) / _PER
    cost += web_searches * _num(price.get("price_web_search"), 0.0)
    saved = max(cache_read * (p_in - p_read), 0.0) / _PER
    return round(cost, 8), round(saved, 8)


SOURCE_PREFIX = "source:"


def source_of(note: Optional[str]) -> str:
    """Where a price row came from: ``openrouter`` | ``langfuse`` | ``plan`` | ``manual`` (any other note, or none)."""
    text = (note or "").strip()
    if text.startswith(SOURCE_PREFIX):
        tag = text[len(SOURCE_PREFIX):].split()[0] if text[len(SOURCE_PREFIX):].strip() else ""
        if tag in ("openrouter", "langfuse", "plan"):
            return tag
    return "manual"


def is_flat_plan(endpoint: dict) -> bool:
    """True when the endpoint's preset is a flat subscription (no per-call price)."""
    from .config import PRESETS
    preset = PRESETS.get((endpoint.get("preset") or "").lower())
    return bool(preset and preset.flat_plan)


def is_free(hop: Any) -> bool:
    """True when a call on ``hop`` costs nothing: a flat plan (the coding plan), a local endpoint, or a price row
    of zeros.

    A free model is worth waiting for: the provider refused the request (HTTP 429), so nothing was billed and the
    next attempt is free too. A metered model is never waited for: its caller moves on to the fallback chain.
    """
    endpoint = hop.endpoint or {}
    price = price_for(hop.endpoint_name, hop.model)
    if price is None:
        if is_flat_plan(endpoint):
            return True
        from .usage_view import provider_label
        return provider_label(endpoint)["type"] == "local"
    return not any(_num(price.get(key), 0.0) for key in
                   ("price_in", "price_out", "price_cache_read", "price_cache_write", "price_web_search"))


def cost_for(hop: Any, tokens_in: int, tokens_out: int, usage: Any = None,
             at: Optional[datetime] = None) -> Optional[tuple[float, float]]:
    """``(cost, cache_saved)`` for a call on ``hop`` from the price table, or None when no price is known.

    A flat-plan endpoint (the coding plan) costs 0 whatever the call: a synced price row (``source:...``) does
    not bill it — only a typed one does. A metered endpoint whose provider reported no tokens has an unknown
    cost: never 0.
    """
    endpoint = hop.endpoint or {}
    price = price_for(hop.endpoint_name, hop.model, at)
    if price is not None and is_flat_plan(endpoint) and source_of(price.get("note")) != "manual":
        price = None  # the plan covers the call: a synced price does not bill it
    if price is None:
        from .usage_view import provider_label
        if is_flat_plan(endpoint):
            return (0.0, 0.0)  # included in the subscription
        # A local endpoint (your own GPU / PC) costs nothing per call: free, not "no price".
        return (0.0, 0.0) if provider_label(endpoint)["type"] == "local" else None
    if not (tokens_in or tokens_out):
        return None  # the provider reported no tokens: the cost is unknown, never 0
    return compute(price, tokens_in, tokens_out,
                   getattr(usage, "cache_read", 0), getattr(usage, "cache_write", 0), getattr(usage, "web_searches", 0))


def endpoint_by_name(name: str) -> dict:
    """The endpoint row with this name (its preset decides the flat plan), or {} when it is unknown."""
    for e in _load_endpoints():
        if e.get("name") == name:
            return e
    return {}


def cost_for_endpoint(endpoint_name: str, model: str, tokens_in: int, tokens_out: int, cache_read: int = 0,
                       cache_write: int = 0, web_searches: int = 0,
                       at: Optional[datetime] = None) -> Optional[tuple[float, float]]:
    """The cost of a call reported by endpoint NAME (a caller that hit the provider itself): the same rules
    as a routed call — the price row, then the flat plan, then a local endpoint."""
    hop = SimpleNamespace(endpoint_name=endpoint_name, model=model, endpoint=endpoint_by_name(endpoint_name))
    usage = SimpleNamespace(cache_read=cache_read, cache_write=cache_write, web_searches=web_searches)
    return cost_for(hop, tokens_in, tokens_out, usage, at)


def resolve(hop: Any, tokens_in: int, tokens_out: int, usage: Any = None) -> tuple[Optional[float], str]:
    """``(cost, cost_source)`` of one call, the same figure the call log stores and Langfuse shows:
    the provider's own cost, else the price table / flat plan / local, else ``(None, 'none')``."""
    provider = getattr(usage, "cost", None)
    if isinstance(provider, (int, float)) and not isinstance(provider, bool):
        return round(float(provider), 8), "provider"
    priced = cost_for(hop, int(tokens_in or 0), int(tokens_out or 0), usage)
    return (priced[0], "price_table") if priced is not None else (None, "none")
