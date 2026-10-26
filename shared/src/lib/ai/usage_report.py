"""
AI usage report (TASK-87): aggregate hourly rollup rows (``ai_usage_stats``) — or per-call rows
(``ai_calls``) mapped to the same fields — into the table behind Monitoring → AI usage.

Pure functions, no DB: the route fetches rows (already filtered by team) and calls ``aggregate``.

A row is a dict with at least ``bucket`` (ISO timestamp), ``usage_key``, ``team_id``, ``profile``,
``endpoint``, ``calls``, ``errors``, ``fallbacks``, ``total_ms``, ``tokens_in``, ``tokens_out``.
Optional: ``origin``, ``host_name``, ``cost`` (USD), ``tokens_cache_read``, ``tokens_cache_write``,
``web_searches`` — absent columns simply stay out of the numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

NONE_KEY = "—"


def _device_key(row: dict) -> str:
    host, device = row.get("host_name") or "", row.get("device_id") or ""
    return f"{host} / {device}" if host and device else (host or device)


def _category_key(row: dict) -> str:
    from .usages import page_category
    return page_category(row.get("usage_key") or "")


def _incident_key(row: dict) -> str:
    """Incident type of an alert-triage call (``ref_kind`` while ``ref_type`` is ``alert``), else empty."""
    return (row.get("ref_kind") or "") if (row.get("ref_type") or "alert") == "alert" else ""


def _caller_key(row: dict) -> str:
    from .usage_caller import caller_of
    return caller_of(row)


def _result_key(row: dict) -> str:
    """``failed`` for a row of failed requests, else ``success`` (per-call rollup rows are one or the other)."""
    return "failed" if int(row.get("errors") or 0) > 0 else "success"


# group_by name -> row field (or a function of the row)
GROUP_FIELDS: dict[str, Any] = {
    "usage": "usage_key",
    "model": "profile",
    "endpoint": "endpoint",
    "team": "team_id",
    "origin": "origin",
    "host": "host_name",
    "device": _device_key,
    "script": "script_name",
    "campaign": "campaign_id",
    "user": "user_id",
    "server": "server",
    "arm": "split_arm",
    "error": "error_type",
    "client": "client_hash",
    "incident": _incident_key,
    "category": _category_key,
    "caller": _caller_key,
    "result": _result_key,
}
# Dimensions the hourly rollup (``ai_usage_stats``, kept forever) can answer: the 30-day view.
ROLLUP_GROUPS = ("usage", "model", "endpoint", "team", "origin", "host", "arm", "category", "caller", "incident")
# Everything else needs the per-call log (``ai_calls``, 90 days): up to 7 days on the page.
CALL_GROUPS = tuple(GROUP_FIELDS)
# The 30-day rollup mixes answered and failed requests in one row, so "result" needs the per-call log.

_SUM_FIELDS = ("calls", "errors", "fallbacks", "total_ms", "tokens_in", "tokens_out", "tokens_cache_read",
               "tokens_cache_write", "tokens_reasoning", "web_searches", "avoided", "priced_calls",
               "parse_total", "parse_ok_n", "truncated", "images", "image_bytes")
# USD sums that are not "cost": what prompt caching saved at write time.
_SUM_USD = ("cache_saved",)


def split_group_by(group_by: str) -> list[str]:
    """The dimensions of ``group_by``: one name, or two joined by a comma ("group by A, then by B")."""
    names = [n for n in str(group_by).split(",") if n]
    if not 1 <= len(names) <= 2 or len(set(names)) != len(names) or any(n not in GROUP_FIELDS for n in names):
        raise ValueError(f"unknown group_by '{group_by}'")
    return names


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))


def step_for(hours: int) -> int:
    """Series resolution in seconds: hourly up to 7 days, daily beyond."""
    return 3600 if hours <= 24 * 7 else 86400


def _new_row(key: str) -> dict:
    row: dict[str, Any] = {"key": key, "profiles": {}, "endpoints": {}, "usages": {}, "cost": None, "_series": {},
                           "_tseries": {}, "_fseries": {}, "_cseries": {}, "error_types": {}, "first_ts": None, "last_ts": None,
                           "last_error_ts": None, "last_ok_ts": None, "profile_errors": {}, "profile_causes": {},
                           "profile_last": {}}
    row.update({f: 0 for f in _SUM_FIELDS})
    row.update({f: 0.0 for f in _SUM_USD})
    return row


def _add(agg: dict, row: dict, step: int) -> None:
    for f in _SUM_FIELDS:
        agg[f] += int(row.get(f) or 0)
    for f in _SUM_USD:
        agg[f] += float(row.get(f) or 0.0)
    calls = int(row.get("calls") or 0)
    # A call without a price is "no price", never 0: cost counts only rows that carry priced calls.
    priced = int(row.get("priced_calls") if "priced_calls" in row else (calls if row.get("cost") is not None else 0))
    if priced > 0 and row.get("cost") is not None:
        agg["cost"] = (agg["cost"] or 0.0) + float(row["cost"])
        slot_c = int(parse_ts(row["bucket"]).timestamp()) // step * step
        agg["_cseries"][slot_c] = agg["_cseries"].get(slot_c, 0.0) + float(row["cost"])
    if "priced_calls" not in row:
        agg["priced_calls"] += priced
    profile = f"{row.get('profile') or '?'}{' (' + row['split_arm'] + ')' if row.get('split_arm') else ''}"
    agg["profiles"][profile] = agg["profiles"].get(profile, 0) + calls
    agg["endpoints"][row.get("endpoint") or "?"] = agg["endpoints"].get(row.get("endpoint") or "?", 0) + calls
    agg["usages"][row.get("usage_key") or "?"] = agg["usages"].get(row.get("usage_key") or "?", 0) + calls
    slot = int(parse_ts(row["bucket"]).timestamp()) // step * step
    agg["_series"][slot] = agg["_series"].get(slot, 0) + calls
    errors = int(row.get("errors") or 0)
    if errors:
        agg["_fseries"][slot] = agg["_fseries"].get(slot, 0) + errors
        if "error_type" in row:  # the hourly rollup (30 d) has no cause
            kind = row.get("error_type") or "other"
            agg["error_types"][kind] = agg["error_types"].get(kind, 0) + errors
    if calls:
        # Exact times when the rollup carries them (first_ts / last_ts), else the hour bucket.
        first = parse_ts(row.get("first_ts") or row["bucket"]).isoformat()
        last = parse_ts(row.get("last_ts") or row["bucket"]).isoformat()
        agg["first_ts"] = first if agg["first_ts"] is None or first < agg["first_ts"] else agg["first_ts"]
        agg["last_ts"] = last if agg["last_ts"] is None or last > agg["last_ts"] else agg["last_ts"]
        if last > agg["profile_last"].get(profile, ""):
            agg["profile_last"][profile] = last
        if errors:
            agg["last_error_ts"] = last if agg["last_error_ts"] is None or last > agg["last_error_ts"] else agg["last_error_ts"]
        if calls > errors:
            agg["last_ok_ts"] = last if agg["last_ok_ts"] is None or last > agg["last_ok_ts"] else agg["last_ok_ts"]
    if errors:
        agg["profile_errors"][profile] = agg["profile_errors"].get(profile, 0) + errors
        if "error_type" in row:
            causes = agg["profile_causes"].setdefault(profile, {})
            kind = row.get("error_type") or "other"
            causes[kind] = causes.get(kind, 0) + errors
    agg["_tseries"][slot] = agg["_tseries"].get(slot, 0) + int(row.get("tokens_in") or 0)


def row_value(row: dict, name: str) -> str:
    spec = GROUP_FIELDS[name]
    return str((spec(row) if callable(spec) else row.get(spec)) or NONE_KEY)


def filter_rows(rows: Iterable[dict], filters: Optional[dict[str, str]]) -> list[dict]:
    """The rows whose group values match every ``filters`` entry (same rule as ``aggregate``)."""
    if not filters:
        return list(rows)
    return [r for r in rows if all(row_value(r, g) == v for g, v in filters.items())]


def calls_of(agg: dict) -> int:
    return agg["calls"] or 1


def _finish(agg: dict, slots: list[int], step: int) -> dict:
    series = agg.pop("_series")
    tokens_series = agg.pop("_tseries")
    failed_series = agg.pop("_fseries")
    # USD per slot, same priced-rows-only definition as "cost" (both sources carry a per-row cost; a slot with no
    # priced call is 0.0).
    cost_series = agg.pop("_cseries")
    agg["cost_series"] = [round(cost_series.get(s, 0.0), 6) for s in slots]
    agg["failed_series"] = [failed_series.get(s, 0) for s in slots]
    agg["main_error"] = max(agg["error_types"].items(), key=lambda kv: kv[1])[0] if agg["error_types"] else None
    agg["tokens_in_series"] = [tokens_series.get(s, 0) for s in slots]
    if agg["cost"] is not None:
        agg["cost"] = round(agg["cost"], 6)
    agg["cost_partial"] = 0 < agg["priced_calls"] < agg["calls"]
    # What the avoided calls would have cost (their number times the average priced call of the same row)
    # plus what prompt caching saved at write time. None when nothing was saved or nothing is priced.
    avoided_saving = (agg["avoided"] * agg["cost"] / agg["priced_calls"]
                      if agg["avoided"] and agg["priced_calls"] and agg["cost"] is not None else 0.0)
    agg["cache_saved"] = round(agg["cache_saved"], 6)
    agg["saved_cost"] = round(avoided_saving + agg["cache_saved"], 6) if (avoided_saving or agg["cache_saved"]) else None
    agg["parse_rate"] = round(agg["parse_ok_n"] / agg["parse_total"], 4) if agg["parse_total"] else None
    agg["truncated_rate"] = round(agg["truncated"] / calls_of(agg), 4) if agg["truncated"] else 0.0
    agg["series"] = [series.get(s, 0) for s in slots]
    calls = agg["calls"]
    agg["avg_ms"] = int(agg["total_ms"] / calls) if calls else 0
    agg["error_rate"] = round(agg["errors"] / calls, 4) if calls else 0.0
    agg["fallback_rate"] = round(agg["fallbacks"] / calls, 4) if calls else 0.0
    # Speed counts the whole call (queue + network + generation): the gateway never streams.
    agg["tokens_per_s"] = round(agg["tokens_out"] * 1000 / agg["total_ms"], 1) if agg["total_ms"] and agg["tokens_out"] else 0.0
    return agg


def aggregate(rows: Iterable[dict], group_by: str = "usage", *, hours: int = 24,
              filters: Optional[dict[str, str]] = None, now: Optional[datetime] = None) -> dict:
    """Group ``rows`` by ``group_by`` and return ``{totals, rows, step_s, series_start, series_len}``.

    ``filters`` maps a group name to a required value (``{"team": "…"}``); ``NONE_KEY`` matches a
    missing value. Rows are sorted by calls, busiest first.
    """
    names = split_group_by(group_by)
    step = step_for(hours)
    end = (now or datetime.now(timezone.utc))
    last_slot = int(end.timestamp()) // step * step
    n = max(1, int(hours * 3600 // step))
    slots = [last_slot - step * (n - 1 - i) for i in range(n)]

    def value_of(row: dict, name: str) -> str:
        spec = GROUP_FIELDS[name]
        return str((spec(row) if callable(spec) else row.get(spec)) or NONE_KEY)

    groups: dict[str, dict] = {}
    total = _new_row("total")
    for row in rows:
        if any(value_of(row, g) != v for g, v in (filters or {}).items()):
            continue
        parts = [value_of(row, n) for n in names]
        key = "|".join(parts)
        if key not in groups:
            groups[key] = _new_row(key)
            groups[key]["parts"] = parts
        _add(groups[key], row, step)
        _add(total, row, step)
    out = sorted((_finish(g, slots, step) for g in groups.values()), key=lambda r: (-r["calls"], r["key"]))
    return {
        "group_by": group_by,
        "totals": _finish(total, slots, step),
        "rows": out,
        "step_s": step,
        "series_start": datetime.fromtimestamp(slots[0], tz=timezone.utc).isoformat(),
        "series_len": n,
    }


def forecast_month(cost_so_far: float, now: Optional[datetime] = None) -> float:
    """Linear month-end projection from the month's spend so far."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    elapsed = max((now - start).total_seconds(), 3600.0)
    return cost_so_far * (nxt - start).total_seconds() / elapsed
