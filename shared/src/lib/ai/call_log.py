"""
The AI call log (TASK-87): ``router.record`` builds one row per billed request and hands it to the
sink here; a daemon thread writes rows in batches through ``ai_calls_ingest`` (one round trip inserts
the rows and bumps the hourly rollup). The row has no prompt and no answer text.

Never raises, never blocks a call: a full queue drops the row (counted in ``dropped()``), a failed
batch is retried once and then dropped with a log line.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import caller as ai_caller
from . import prices, usages
from .provider_client import ERROR_TYPES

MAX_QUEUE = 5000
BATCH_SIZE = 100
FLUSH_INTERVAL_S = 1.0
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

# Columns of ai_calls the writer fills (ts defaults to now in SQL).
ROW_FIELDS = (
    "ts", "server", "request_id", "usage_key", "team_id", "user_id", "origin", "route", "script_name",
    "script_result_id", "campaign_id", "host_name", "device_id", "device_model", "userinterface_name",
    "session_id", "client_hash", "turn_index", "tool_calls", "stop_reason", "split_arm", "profile", "endpoint",
    "model", "effort_sent", "fallback_used", "attempt_index", "hop_index", "ok", "outcome", "error_type", "tokens_in",
    "tokens_out", "tokens_cache_read", "tokens_cache_write", "tokens_reasoning", "web_searches", "images",
    "image_bytes", "parse_ok", "latency_ms", "cost", "cost_source", "cache_saved", "ref_type", "ref_id", "ref_kind",
    "project_id",
)
# Fields a call site may add through ``extra``.
EXTRA_FIELDS = ("turn_index", "tool_calls", "stop_reason", "images", "image_bytes", "parse_ok", "effort_sent")

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=MAX_QUEUE)
_dropped = 0
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_writer = None  # test hook: callable(rows) replacing the DB write


def effective_origin(label: str, fields: dict) -> str:
    """``test:*`` and ``eval:*`` stats labels are their own origin whatever the context says."""
    if label.startswith("test:"):
        return "settings_test"
    if label.startswith("eval:"):
        return "eval"
    origin = fields.get("origin")
    if not origin:
        logging.getLogger(__name__).warning("AI call %s has no caller origin; recorded as background", label)
        origin = "background"
    return origin


def looks_like_json(text: str) -> bool:
    """True when ``text`` holds a parseable JSON object / array (code fences and chatter around it tolerated)."""
    if not text:
        return False
    body = text.strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = body.find(opener), body.rfind(closer)
        if start != -1 and end > start:
            try:
                json.loads(body[start:end + 1])
                return True
            except ValueError:
                continue
    return False


def parse_ok_for(usage_key: str, text: Optional[str], ok: bool) -> Optional[bool]:
    """parse_ok for JSON usages (None for text usages and unanswered calls)."""
    if not ok or text is None:
        return None
    try:
        if usages.effective(usage_key, "output") != "json":
            return None
    except usages.UnknownUsageError:
        return None
    return looks_like_json(text)


def build_row(resolution: Any, hop: Any, *, ok: bool, ms: int, tokens_in: int = 0, tokens_out: int = 0,
              fallback: bool = False, usage: Any = None, error_type: Optional[str] = None,
              attempt_index: int = 0, outcome: str = "served", extra: Optional[dict] = None,
              caller: Optional[dict] = None, server: Optional[str] = None) -> dict:
    """One ``ai_calls`` row. ``caller`` overrides the bound context field by field."""
    fields = {**ai_caller.current(), **ai_caller.from_wire(caller)}
    context = getattr(resolution, "context", None) or {}
    label = getattr(resolution, "stats_label", None) or resolution.usage
    team_id = resolution.team_id if resolution.team_id and _UUID_RE.match(str(resolution.team_id)) else None
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "request_id": resolution.request_id or None,
        "usage_key": label,
        "team_id": team_id,
        "origin": effective_origin(label, fields),
        "host_name": fields.get("host_name") or context.get("host_name"),
        "device_model": fields.get("device_model") or context.get("device_model"),
        "userinterface_name": fields.get("userinterface_name") or context.get("userinterface_name"),
        "split_arm": resolution.split_arm or "",
        "profile": hop.profile_name,
        "endpoint": hop.endpoint_name,
        "model": hop.model,
        "effort_sent": hop.effort(resolution.usage),
        "fallback_used": bool(fallback),
        "attempt_index": int(attempt_index),
        "hop_index": resolution.hop_index(hop) if hasattr(resolution, "hop_index") else 0,
        "ok": bool(ok),
        "outcome": outcome,
        # A value outside the CHECK list would fail the whole 100-row batch: never send one.
        "error_type": (error_type if error_type in ERROR_TYPES else "other") if error_type else None,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "latency_ms": max(int(ms or 0), 0),
        "cost": None,
        "cost_source": "none",
    }
    for key in ("user_id", "route", "script_name", "script_result_id", "campaign_id", "device_id", "session_id",
                "client_hash", "ref_type", "ref_id", "ref_kind", "project_id"):
        row[key] = fields.get(key)
    if usage is not None:
        row.update(tokens_cache_read=usage.cache_read, tokens_cache_write=usage.cache_write,
                   tokens_reasoning=usage.reasoning, web_searches=usage.web_searches)
        if usage.cost is not None:
            row["cost"], row["cost_source"] = round(float(usage.cost), 8), "provider"
    if outcome == "served":
        # No provider figure: price it now from the dated price table (never rewritten later).
        # A call with no tokens (the provider reports none) is priced 0 only when the endpoint is free — the
        # coding plan, a local machine; a metered endpoint keeps "no price" instead of claiming a wrong 0.
        priced = prices.cost_for(hop, int(tokens_in or 0), int(tokens_out or 0), usage)
        if priced is not None:
            if row["cost"] is None:
                row["cost"], row["cost_source"] = priced[0], "price_table"
            if priced[1]:
                row["cache_saved"] = priced[1]
    for key, value in (extra or {}).items():
        if key in EXTRA_FIELDS and value is not None:
            row[key] = value
    return {k: v for k, v in row.items() if v is not None}


def reported_row(data: dict, server: Optional[str] = None) -> dict:
    """The row for a call a host made straight to a host-reach endpoint (``POST /server/ai/stats``)."""
    fields = ai_caller.current()  # the host's forwarded X-VPT-Caller, bound by the server request
    team_id = data.get("team_id") if data.get("team_id") and _UUID_RE.match(str(data["team_id"])) else None
    label = str(data.get("usage") or "unknown")
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(), "server": server, "request_id": data.get("request_id") or None,
        "usage_key": label, "team_id": team_id, "origin": effective_origin(label, fields),
        "split_arm": data.get("split_arm") or "", "profile": data.get("profile") or "?",
        "endpoint": data.get("endpoint") or "?", "model": data.get("model"),
        "fallback_used": bool(data.get("fallback")), "attempt_index": 0, "hop_index": int(data.get("hop_index") or 0),
        "ok": bool(data.get("ok")),
        "outcome": "served", "error_type": data.get("error_type") if data.get("error_type") in ERROR_TYPES else None,
        "tokens_in": int(data.get("tokens_in") or 0), "tokens_out": int(data.get("tokens_out") or 0),
        "tokens_cache_read": int(data.get("tokens_cache_read") or 0),
        "tokens_cache_write": int(data.get("tokens_cache_write") or 0),
        "tokens_reasoning": int(data.get("tokens_reasoning") or 0), "web_searches": int(data.get("web_searches") or 0),
        "latency_ms": max(int(data.get("ms") or 0), 0), "cost_source": "none",
    }
    row.update({k: fields.get(k) for k in ("user_id", "route", "script_name", "script_result_id", "campaign_id",
                                           "host_name", "device_id", "device_model", "userinterface_name",
                                           "session_id", "client_hash", "project_id")})
    if isinstance(data.get("cost"), (int, float)):
        row["cost"], row["cost_source"] = round(float(data["cost"]), 8), "provider"
    else:
        priced = prices.cost_for_endpoint(row["endpoint"], row.get("model") or "", row["tokens_in"], row["tokens_out"],
                                          row["tokens_cache_read"], row["tokens_cache_write"], row["web_searches"])
        if priced is not None:
            row["cost"], row["cost_source"] = priced[0], "price_table"
            if priced[1]:
                row["cache_saved"] = priced[1]
        elif row["tokens_in"] or row["tokens_out"]:
            # only host-reach endpoints (a PC on the user's LAN) report here: no per-call cost
            row["cost"], row["cost_source"] = 0.0, "price_table"
    for key, value in (data.get("extra") or {}).items():
        if key in EXTRA_FIELDS and value is not None:
            row[key] = value
    return {k: v for k, v in row.items() if v is not None}


def new_request_id() -> str:
    return uuid.uuid4().hex


# ------------------------------------------------------------------------------- sink
def submit(row: dict) -> None:
    """Queue ``row`` for the next batch. Never raises."""
    global _dropped
    try:
        _queue.put_nowait(row)
    except queue.Full:
        with _lock:
            _dropped += 1
        return
    _ensure_thread()
    _audit(row)


def _audit(row: dict) -> None:
    """TASK-154: one audit_events row per AI call (``ai_calls`` stays the AI system of record). Never raises."""
    try:
        from shared.src.lib.database import audit_events_db
        user_id = row.get("user_id")
        kind = audit_events_db.actor_for(user_id) if user_id else "agent"
        audit_events_db.record(
            category="ai", action="ai.call", actor_kind=kind,
            actor_id=user_id or row.get("origin"), team_id=row.get("team_id"), target=row.get("usage_key"),
            outcome="ok" if row.get("ok", True) else "error", request_id=row.get("request_id"),
            meta={"origin": row.get("origin"), "route": row.get("route"), "model": row.get("model"),
                  "cost": row.get("cost")})
    except Exception:
        pass


def dropped() -> int:
    return _dropped


def _ensure_thread() -> None:
    global _thread, _atexit_set
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="ai-call-log", daemon=True)
            _thread.start()
        if not _atexit_set:
            # A script (jev_*, score_eval, a bench) can exit before the daemon thread writes its last rows.
            atexit.register(_flush_at_exit)
            _atexit_set = True


_atexit_set = False


def _flush_at_exit() -> None:
    flush()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=FLUSH_INTERVAL_S * 3)  # the batch the thread already holds


def _write(rows: list[dict]) -> None:
    if _writer is not None:
        _writer(rows)
        return
    from shared.src.lib.database import ai_routing_db
    ai_routing_db.ingest_calls(rows)


def _drain(limit: int = BATCH_SIZE) -> list[dict]:
    rows: list[dict] = []
    while len(rows) < limit:
        try:
            rows.append(_queue.get_nowait())
        except queue.Empty:
            break
    return rows


def _flush_rows(rows: list[dict]) -> None:
    for attempt in (1, 2):
        try:
            _write(rows)
            return
        except Exception as e:  # noqa: BLE001 - the call log must never break a call
            if attempt == 2:
                print(f"[AI] call log: dropped {len(rows)} rows after retry: {e}")
            else:
                time.sleep(0.5)


def _run() -> None:
    while True:
        try:
            first = _queue.get(timeout=FLUSH_INTERVAL_S * 30)
        except queue.Empty:
            return  # idle: the next submit starts a new thread
        time.sleep(FLUSH_INTERVAL_S)  # let a burst accumulate into one batch
        _flush_rows([first, *_drain(BATCH_SIZE - 1)])


def flush() -> None:
    """Write everything queued now (shutdown, tests)."""
    while True:
        rows = _drain()
        if not rows:
            return
        _flush_rows(rows)
