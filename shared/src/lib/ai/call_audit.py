"""Audit of the AI call log (BUG-0721): rows that say a billed model answered but carry no tokens.

An ``ai_calls`` row with ``ok = true``, ``outcome = 'served'`` and 0 tokens in and out on an endpoint that bills by
the token (OpenRouter, Anthropic, OpenAI, Google) means the call site read the usage block wrong, or not at all:
the provider charged for it and the page shows nothing. Flat plans (MiniMax coding plan, MiniMax VLM) and keyless
local servers (LM Studio) are left out: a zero there costs nothing.

``scripts/ai_calls_audit.py`` runs it against the live DB and exits 1 when it finds any.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .config import get_preset


def bills_tokens(preset: Optional[str]) -> bool:
    """True for a preset whose provider charges per token (needs a key, no flat plan)."""
    try:
        spec = get_preset(preset)
    except ValueError:
        return False
    return spec.needs_key and not spec.flat_plan


def billing_endpoints(endpoints: Iterable[dict]) -> set[str]:
    return {e["name"] for e in endpoints if bills_tokens(e.get("preset"))}


def zero_token_suspects(rows: Iterable[dict], endpoints: Iterable[dict]) -> list[dict]:
    """Served, ok rows with no tokens on an endpoint that bills tokens."""
    billed = billing_endpoints(endpoints)
    return [r for r in rows
            if r.get("ok") and (r.get("outcome") or "served") == "served"
            and not r.get("tokens_in") and not r.get("tokens_out")
            and r.get("endpoint") in billed]


def fetch_suspects(hours: int = 24) -> list[dict]:
    """Zero-token suspects of the last ``hours`` from the DB (server-side: service role)."""
    from shared.src.lib.database import ai_routing_db
    db = ai_routing_db.get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = (db.table("ai_calls")
            .select("ts,usage_key,endpoint,profile,model,origin,host_name,script_name,ok,outcome,tokens_in,tokens_out,cost")
            .gte("ts", since).eq("ok", True).eq("outcome", "served").eq("tokens_in", 0).eq("tokens_out", 0)
            .limit(5000).execute().data or [])
    return zero_token_suspects(rows, ai_routing_db.list_endpoints())
