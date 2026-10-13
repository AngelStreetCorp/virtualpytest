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
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

CACHE_TTL_S = 60
WILDCARD = "*"
_PER = 1_000_000

_lock = threading.Lock()
_cache: dict[str, Any] = {"rows": None, "at": 0.0}


def set_for_tests(rows: Optional[list[dict]]) -> None:
    with _lock:
        _cache["rows"], _cache["at"] = rows, time.time() + 10 ** 9 if rows is not None else 0.0


def invalidate() -> None:
    with _lock:
        _cache["rows"], _cache["at"] = None, 0.0


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


def _ts(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def price_for(endpoint: str, model: str, at: Optional[datetime] = None, rows: Optional[list[dict]] = None) -> Optional[dict]:
    """The price row valid at ``at`` for ``model`` on ``endpoint`` (exact model first, then ``*``), or None."""
    at = at or datetime.now(timezone.utc)
    rows = _load() if rows is None else rows
    for wanted in (model, WILDCARD):
        valid = [r for r in rows if r.get("endpoint") == endpoint and r.get("model") == wanted
                 and _ts(r["valid_from"]) <= at]
        if valid:
            return max(valid, key=lambda r: _ts(r["valid_from"]))
    return None


def _num(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def compute(price: dict, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0,
            web_searches: int = 0, input_includes_cache: bool = False) -> tuple[float, float]:
    """``(cost, cache_saved)`` in USD for one call.

    ``input_includes_cache``: OpenAI-shaped providers count cached tokens inside ``prompt_tokens``;
    Anthropic reports them separately. Cache prices default to the plain input price."""
    p_in = _num(price.get("price_in"), 0.0)
    p_out = _num(price.get("price_out"), 0.0)
    p_read = _num(price.get("price_cache_read"), p_in)
    p_write = _num(price.get("price_cache_write"), p_in)
    plain_in = max(tokens_in - cache_read - cache_write, 0) if input_includes_cache else tokens_in
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


def cost_for(hop: Any, tokens_in: int, tokens_out: int, usage: Any = None,
             at: Optional[datetime] = None) -> Optional[tuple[float, float]]:
    """``(cost, cache_saved)`` for a call on ``hop`` from the price table, or None when no price is known."""
    price = price_for(hop.endpoint_name, hop.model, at)
    if price is None:
        from .usage_view import provider_label
        if is_flat_plan(hop.endpoint):
            return (0.0, 0.0)  # included in the subscription
        # A local endpoint (your own GPU / PC) costs nothing per call: free, not "no price".
        return (0.0, 0.0) if provider_label(hop.endpoint)["type"] == "local" else None
    from .config import get_preset
    return compute(price, tokens_in, tokens_out,
                   getattr(usage, "cache_read", 0), getattr(usage, "cache_write", 0), getattr(usage, "web_searches", 0),
                   input_includes_cache=get_preset(hop.preset).client != "anthropic")


def resolve(hop: Any, tokens_in: int, tokens_out: int, usage: Any = None) -> tuple[Optional[float], str]:
    """``(cost, cost_source)`` of one call, the same figure the call log stores and Langfuse shows:
    the provider's own cost, else the price table / flat plan / local, else ``(None, 'none')``."""
    provider = getattr(usage, "cost", None)
    if isinstance(provider, (int, float)) and not isinstance(provider, bool):
        return round(float(provider), 8), "provider"
    priced = cost_for(hop, int(tokens_in or 0), int(tokens_out or 0), usage)
    return (priced[0], "price_table") if priced is not None else (None, "none")
