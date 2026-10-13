"""
Model prices from OpenRouter's public list and Langfuse's model price list (TASK-87 round 2 R3, cost pipeline).

Cost of a call is, in this order: what the provider reported (OpenRouter ``usage.cost``, Jev ``cost``), the
price valid for that endpoint + model in ``ai_prices``, a flat plan or a local endpoint (0), nothing ("—").
This module fills ``ai_prices`` once a day so a cloud model needs no hand-typed price: one row per (endpoint, model),

- endpoint on the OpenRouter preset: ``GET https://openrouter.ai/api/v1/models`` (public, no key; USD per token), note ``source:openrouter``
- any other cloud endpoint: ``GET <LANGFUSE_HOST>/api/public/models``, note ``source:langfuse``

written only when

- the endpoint is a cloud one (a local endpoint is free, a flat-plan endpoint is included in its subscription),
- nobody typed a price for that model or for the whole endpoint (a manual row always wins),
- the price differs from the latest synced row (history is never rewritten: a change is a new row).

A source that is unreachable or has no such API is not an error: nothing is written for it. Models Langfuse does not
know are pushed to it (``POST /api/public/models``) so its own dashboards agree; its built-ins are never touched.
The sync runs once a day from the server (``start``).
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Optional

import requests

from . import prices, tracing

SOURCE_NOTE = "source:langfuse"
OPENROUTER_NOTE = "source:openrouter"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
AUTO_SOURCES = ("openrouter", "langfuse")
INTERVAL_S = 24 * 3600
_PER = 1_000_000
_started = False


def fetch_models(timeout: float = 15.0) -> Optional[list[dict]]:
    """Every model of the Langfuse price list, or None when Langfuse is off, unreachable or has no such API."""
    host = (os.getenv("LANGFUSE_HOST") or "").strip().rstrip("/")
    key, secret = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    if not (tracing.enabled() and key and secret):
        return None
    models: list[dict] = []
    page = 1
    while page <= 50:
        try:
            resp = requests.get(f"{host}/api/public/models", params={"page": page, "limit": 100},
                                auth=(key, secret), timeout=timeout)
        except requests.RequestException as e:
            print(f"[AI] Langfuse price list unreachable: {e}")
            return None
        if resp.status_code != 200:
            print(f"[AI] Langfuse price list not available (HTTP {resp.status_code}): manual prices only")
            return None
        body = resp.json() if resp.content else {}
        models.extend(body.get("data") or [])
        if page >= int((body.get("meta") or {}).get("totalPages") or 1):
            return models
        page += 1
    return models


def _per_million(model: dict) -> Optional[dict]:
    """``{price_in, price_out, price_cache_read?}`` per 1M tokens of a Langfuse model entry, or None."""
    prices_map = model.get("prices") or {}

    def one(*names: str, flat: Optional[str] = None) -> Optional[float]:
        for name in names:
            entry = prices_map.get(name)
            value = entry.get("price") if isinstance(entry, dict) else entry
            if isinstance(value, (int, float)):
                return float(value)
        value = model.get(flat) if flat else None
        return float(value) if isinstance(value, (int, float)) else None

    p_in, p_out = one("input", flat="inputPrice"), one("output", flat="outputPrice")
    if p_in is None or p_out is None:
        return None
    out = {"price_in": round(p_in * _PER, 6), "price_out": round(p_out * _PER, 6)}
    cached = one("input_cache_read", "cache_read_input_tokens")
    if cached is not None:
        out["price_cache_read"] = round(cached * _PER, 6)
    return out


def match_model(model_name: str, models: list[dict]) -> Optional[dict]:
    """The Langfuse entry whose ``matchPattern`` (or exact name) fits ``model_name``, tried with and without the
    provider prefix of an OpenRouter-style id (``anthropic/claude-…``)."""
    candidates = [model_name]
    if "/" in model_name:
        candidates.append(model_name.split("/", 1)[1])
    for entry in models:
        if _per_million(entry) is None:
            continue
        for name in candidates:
            if entry.get("modelName") == name:
                return entry
            pattern = entry.get("matchPattern")
            try:
                if pattern and re.search(pattern, name):
                    return entry
            except re.error:
                continue
    return None


def fetch_openrouter_models(timeout: float = 20.0) -> Optional[list[dict]]:
    """OpenRouter's public model list, or None when unreachable."""
    try:
        resp = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
        if resp.status_code != 200:
            print(f"[AI] OpenRouter model list not available (HTTP {resp.status_code})")
            return None
        return (resp.json() or {}).get("data") or []
    except (requests.RequestException, ValueError) as e:
        print(f"[AI] OpenRouter model list unreachable: {e}")
        return None


def openrouter_per_million(entry: dict) -> Optional[dict]:
    """``{price_in, price_out, price_cache_read?}`` per 1M tokens of an OpenRouter ``pricing`` block (strings, USD per
    token), or None when the model has no usable price (``-1`` marks the variable-price routers)."""
    pricing = entry.get("pricing") or {}

    def one(name: str) -> Optional[float]:
        try:
            value = float(pricing.get(name))
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    p_in, p_out = one("prompt"), one("completion")
    if p_in is None or p_out is None:
        return None
    out = {"price_in": round(p_in * _PER, 6), "price_out": round(p_out * _PER, 6)}
    cached = one("input_cache_read")
    if cached is not None:
        out["price_cache_read"] = round(cached * _PER, 6)
    write = one("input_cache_write")
    if write is not None:
        out["price_cache_write"] = round(write * _PER, 6)
    return out


def match_openrouter(model_name: str, models: list[dict]) -> Optional[dict]:
    """The OpenRouter entry for ``model_name`` (exact id, then without a ``:variant`` suffix such as ``:online``)."""
    wanted = {model_name, model_name.split(":", 1)[0]}
    for entry in models:
        if entry.get("id") in wanted or entry.get("canonical_slug") in wanted:
            return entry
    return None


def plan(models: list[dict], endpoints: list[dict], profiles: list[dict], existing: list[dict],
         openrouter_models: Optional[list[dict]] = None) -> list[dict]:
    """The new ``ai_prices`` rows a sync should write (pure; see the module doc for the rules)."""
    from .usage_view import provider_label
    by_id = {e["id"]: e for e in endpoints}
    rows: list[dict] = []
    done: set[tuple[str, str]] = set()
    for profile in profiles:
        endpoint = by_id.get(profile.get("endpoint_id"))
        model = profile.get("model")
        if (not endpoint or not model or provider_label(endpoint)["type"] == "local" or prices.is_flat_plan(endpoint)
                or (endpoint["name"], model) in done):
            continue
        done.add((endpoint["name"], model))
        mine = [r for r in existing if r["endpoint"] == endpoint["name"]]
        if any(r["model"] in (model, prices.WILDCARD) and prices.source_of(r.get("note")) not in AUTO_SOURCES for r in mine):
            continue  # a typed price (for the model or the endpoint) always wins
        if endpoint.get("preset") == "openrouter":
            entry = match_openrouter(model, openrouter_models or [])
            found, note = (openrouter_per_million(entry) if entry else None), OPENROUTER_NOTE
        else:
            entry = match_model(model, models)
            found, note = (_per_million(entry) if entry else None), SOURCE_NOTE
        if not found:
            continue
        latest = max((r for r in mine if r["model"] == model and prices.source_of(r.get("note")) in AUTO_SOURCES),
                     key=lambda r: str(r["valid_from"]), default=None)
        if latest and all(float(latest.get(k) or 0) == v for k, v in found.items()):
            continue
        rows.append({"endpoint": endpoint["name"], "model": model, "note": note, **found})
    return rows


def missing_in_langfuse(rows: list[dict], langfuse_models: list[dict]) -> list[dict]:
    """The synced rows whose model Langfuse does not price itself (pure): candidates to push into its model list."""
    seen: set[str] = set()
    out = []
    for r in rows:
        if r["model"] in seen or match_model(r["model"], langfuse_models):
            continue
        seen.add(r["model"])
        out.append(r)
    return out


def push_to_langfuse(rows: list[dict], timeout: float = 15.0) -> int:
    """``POST /api/public/models`` for each row (USD per token). Existing Langfuse models are never overwritten:
    the caller passes only models the list lacks. Returns how many were created."""
    host = (os.getenv("LANGFUSE_HOST") or "").strip().rstrip("/")
    key, secret = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    if not (host and key and secret):
        return 0
    created = 0
    for r in rows:
        body = {"modelName": r["model"], "matchPattern": f"(?i)^{re.escape(r['model'])}$", "unit": "TOKENS",
                "inputPrice": r["price_in"] / _PER, "outputPrice": r["price_out"] / _PER}
        try:
            resp = requests.post(f"{host}/api/public/models", json=body, auth=(key, secret), timeout=timeout)
            created += resp.status_code in (200, 201)
        except requests.RequestException as e:
            print(f"[AI] Langfuse model push failed for {r['model']}: {e}")
            break
    return created


def sync_once() -> int:
    """One sync pass; returns the number of price rows written."""
    from shared.src.lib.database import ai_routing_db
    langfuse_models = fetch_models()
    endpoints, profiles = ai_routing_db.list_endpoints(), ai_routing_db.list_profiles()
    openrouter_models = fetch_openrouter_models() if any(e.get("preset") == "openrouter" for e in endpoints) else None
    if not langfuse_models and not openrouter_models:
        return 0
    rows = plan(langfuse_models or [], endpoints, profiles, ai_routing_db.list_prices(), openrouter_models)
    for row in rows:
        ai_routing_db.create_price(row)
    if rows:
        prices.invalidate()
        print(f"[AI] {len(rows)} model price(s) synced (OpenRouter list / Langfuse)")
    if langfuse_models is not None:
        pushed = push_to_langfuse(missing_in_langfuse(rows, langfuse_models))
        if pushed:
            print(f"[AI] {pushed} model price(s) pushed to Langfuse")
    return len(rows)


def start() -> None:
    """Start the daily sync thread once per process (the server calls this after it is up)."""
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        time.sleep(60)
        while True:
            try:
                sync_once()
            except Exception as e:  # noqa: BLE001 - a failed sync must never touch serving
                print(f"[AI] Langfuse price sync failed: {e}")
            time.sleep(INTERVAL_S)

    threading.Thread(target=loop, name="ai-price-sync", daemon=True).start()
