"""
AI health alerts (TASK-87 phase 4): is a feature failing or leaning on its backup right now?

Pure over the ``ai_calls`` rollup rows of the last 24 h. Failures are grouped by *cause* (provider + reason), not
by feature; see ``evaluate``. A backup alert needs at least ``MIN_REQUESTS`` requests in the last hour with a backup
share above ``BACKUP_SHARE``; a feature-level cause needs an error rate above ``ERROR_RATE``. Thresholds: 5 % and 10 % (env ``AI_ALERT_ERROR_RATE``,
``AI_ALERT_BACKUP_SHARE``, ``AI_ALERT_MIN_REQUESTS``, read at call time).

These are not rows of the ``alerts`` table: that table holds device AV incidents (host + device, a fixed list of
five types) and the triage worker sends every one to a model, so an AI-health row there would be triaged by the
AI that is failing. The alerts show on Monitoring → AI usage and come from ``GET /server/ai/usage/alerts``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

DEFAULT_ERROR_RATE = 0.05
DEFAULT_BACKUP_SHARE = 0.10
DEFAULT_MIN_REQUESTS = 20


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def thresholds() -> dict:
    return {
        "error_rate": _env_float("AI_ALERT_ERROR_RATE", DEFAULT_ERROR_RATE),
        "backup_share": _env_float("AI_ALERT_BACKUP_SHARE", DEFAULT_BACKUP_SHARE),
        "min_requests": int(_env_float("AI_ALERT_MIN_REQUESTS", DEFAULT_MIN_REQUESTS)),
    }


# Causes that belong to the provider account or link: one success on the endpoint (by any feature) ends them.
PROVIDER_CAUSES = ("no_credit", "auth", "connection", "server", "rate_limit", "timeout")
# Everything else belongs to one feature's request or answer (empty_answer, parse, bad_request, refusal, busy,
# other) and is judged by that feature's error rate over the last hour.


def _ts(row: dict, key: str) -> datetime:
    from .usage_report import parse_ts
    return parse_ts(row.get(key) or row["bucket"])


def evaluate(rows: Iterable[dict], now: Optional[datetime] = None, skipped: Optional[dict] = None,
             limits: Optional[dict] = None) -> dict:
    """``{causes, backup}`` for the banner of Monitoring → AI usage, from ``ai_calls_rollup`` rows (last 24 h).

    One *cause* = a provider (endpoint) and a reason (``error_type``), listing every feature it hit, however few
    requests, with when it started and when it was last seen. A provider cause is *active* until the endpoint
    answers a request again; a feature cause only while that feature's last-hour error rate is above the
    threshold. ``skipped`` maps endpoint name -> timestamps of calls held back by a no-credit pause.
    Worst first.
    """
    limits = limits or thresholds()
    now = now or datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    rows = list(rows)
    last_ok: dict[tuple, datetime] = {}
    for r in rows:
        if int(r.get("calls") or 0) > int(r.get("errors") or 0):
            t = _ts(r, "last_ts")
            for scope in ((r.get("endpoint"),), (r.get("endpoint"), r.get("usage_key"))):
                if scope not in last_ok or t > last_ok[scope]:
                    last_ok[scope] = t
    hourly: dict[str, dict] = {}
    for r in rows:
        if _ts(r, "last_ts") >= hour_ago:
            h = hourly.setdefault(r.get("usage_key") or "?", {"calls": 0, "errors": 0, "fallbacks": 0})
            for f in h:
                h[f] += int(r.get(f) or 0)
    causes: dict[tuple, dict] = {}
    for r in rows:
        errors = int(r.get("errors") or 0)
        if not errors:
            continue
        endpoint, usage = r.get("endpoint") or "?", r.get("usage_key") or "?"
        reason = r.get("error_type") or "other"
        provider_level = reason in PROVIDER_CAUSES
        ended = last_ok.get((endpoint,) if provider_level else (endpoint, usage))
        last, first = _ts(r, "last_ts"), _ts(r, "first_ts")
        if ended and last <= ended:
            continue  # answered since: fixed
        if not provider_level:
            h = hourly.get(usage)
            if not h or h["calls"] < limits["min_requests"] or h["errors"] / h["calls"] <= limits["error_rate"] \
                    or last < hour_ago:
                continue
        c = causes.setdefault((endpoint, reason), {"errors": 0, "first_ts": first, "last_ts": last, "features": {}})
        c["errors"] += errors
        c["first_ts"], c["last_ts"] = min(c["first_ts"], first), max(c["last_ts"], last)
        f = c["features"].setdefault(usage, {"usage": usage, "errors": 0})
        f["errors"] += errors
    out = []
    for (endpoint, reason), c in causes.items():
        ended = last_ok.get((endpoint,))
        # No answer since the first failure -> error (since = first failure); an answer in between -> warning.
        all_failed = ended is None or ended <= c["first_ts"]
        started = c["first_ts"]
        from .usage_report import parse_ts
        held = [t for t in (skipped or {}).get(endpoint, []) if parse_ts(t) >= started] if reason == "no_credit" else []
        out.append({"endpoint": endpoint, "reason": reason, "severity": "error" if all_failed else "warning",
                    "errors": c["errors"], "since": started.isoformat(), "last": c["last_ts"].isoformat(),
                    "features": sorted(c["features"].values(), key=lambda f: -f["errors"]),
                    "skipped": len(held)})
    out.sort(key=lambda c: (c["severity"] != "error", -c["errors"]))
    backup = [{"usage": u, "calls": h["calls"], "fallbacks": h["fallbacks"],
               "share": round(h["fallbacks"] / h["calls"], 4)}
              for u, h in hourly.items()
              if h["calls"] >= limits["min_requests"] and h["fallbacks"] / h["calls"] > limits["backup_share"]]
    backup.sort(key=lambda b: -b["share"])
    return {"causes": out, "backup": backup}
