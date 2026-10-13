"""
Provider and period views of Monitoring → AI usage (TASK-87 review round 1). Pure functions over rollup rows.

``provider_label`` turns an ``ai_endpoints`` row into the name a person reads and a type (cloud / local PC);
``provider_view`` is the one-row-per-provider list of the Providers section: status, answered / failed bars per
time bucket of the page period, the active cause with its start, and the calls held back by a no-credit pause.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from . import usage_report
from .config import PRESETS

TOTAL_FIELDS = ("calls", "errors", "cost", "priced_calls", "tokens_in", "tokens_out")


def provider_label(ep: dict) -> dict:
    """``{name, type}``: the endpoint's name (the preset label when the name is just the preset id) and
    ``cloud`` or ``local`` (a host-reach endpoint, a keyless OpenAI-compatible server, or a private-network URL)."""
    preset = PRESETS.get((ep.get("preset") or "").lower())
    name = ep.get("name") or "?"
    if preset and name.lower() in (preset.name, preset.name.replace("_", "-")):
        name = preset.label
    base = (ep.get("base_url") or (preset.base_url if preset else "") or "").lower()
    private = any(f"//{h}" in base for h in ("localhost", "127.", "10.", "192.168.", "172.16.", "172.17.", "172.18."))
    local = ep.get("reach") == "host" or (preset is not None and not preset.needs_key) or private
    return {"name": name, "type": "local" if local else "cloud"}


def preset_of(ep: dict):
    return PRESETS.get((ep.get("preset") or "").lower())


def bucket_floor(moment: datetime, step: int) -> datetime:
    return datetime.fromtimestamp(int(moment.timestamp()) // step * step, tz=timezone.utc)


def split_periods(wide_rows: Iterable[dict], hours: int, now: datetime) -> tuple[list[dict], list[dict]]:
    """``(chart_rows, previous_rows)`` of a wide fetch: the rows of the chart window (at least 24 h) and the rows of
    the period of the same length before the page period."""
    step = usage_report.step_for(hours)
    chart_hours = max(hours, 24)
    chart_from = bucket_floor(now - timedelta(hours=chart_hours), step)
    prev_from, prev_to = bucket_floor(now - timedelta(hours=2 * hours), step), bucket_floor(now - timedelta(hours=hours), step)
    chart, previous = [], []
    for r in wide_rows:
        bucket = usage_report.parse_ts(r["bucket"])
        if bucket >= chart_from:
            chart.append(r)
        if prev_from <= bucket < prev_to:
            previous.append(r)
    return chart, previous


def previous_totals(previous_rows: list[dict], group_by: str, hours: int, filters: Optional[dict], now: datetime) -> dict:
    totals = usage_report.aggregate(previous_rows, group_by, hours=hours, filters=filters, now=now)["totals"]
    return {f: totals[f] for f in TOTAL_FIELDS}


def apply_chart(report: dict, chart: dict) -> None:
    """Replace the per-row series of ``report`` by those of ``chart`` (a wider window) and say how wide it is."""
    by_key = {r["key"]: r for r in chart["rows"]}
    empty = [0] * chart["series_len"]
    for row in [*report["rows"], report["totals"]]:
        src = chart["totals"] if row is report["totals"] else by_key.get(row["key"])
        for f in ("series", "failed_series", "tokens_in_series"):
            row[f] = list(src[f]) if src else list(empty)
    report.update(step_s=chart["step_s"], series_start=chart["series_start"], series_len=chart["series_len"])


def provider_view(endpoints: list[dict], period_rows: list[dict], chart_report: dict, causes: list[dict],
                  down_for: dict[str, int]) -> list[dict]:
    """One entry per endpoint: label, status (down | degraded | ok | unused), counts of the page period, answered /
    failed series of the chart window, active cause (reason, since, last, skipped calls)."""
    period = {r["key"]: r for r in usage_report.aggregate(period_rows, "endpoint", hours=24)["rows"]}
    chart = {r["key"]: r for r in chart_report["rows"]}
    cause_of: dict[str, dict] = {}
    for c in causes:  # worst first: keep the first cause per endpoint
        cause_of.setdefault(c["endpoint"], c)
    out = []
    for ep in endpoints:
        p, c, cause = period.get(ep["name"]), chart.get(ep["name"]), cause_of.get(ep["name"])
        calls, errors = (p["calls"], p["errors"]) if p else (0, 0)
        series = c["series"] if c else [0] * chart_report["series_len"]
        failed = c["failed_series"] if c else [0] * chart_report["series_len"]
        down = down_for.get(str(ep["id"]), 0)
        if cause and cause["severity"] == "error" or down:
            status = "down"
        elif cause or (calls and errors / calls >= 0.05):
            status = "degraded"
        else:
            status = "ok" if calls else "unused"
        label = provider_label(ep)
        out.append({"endpoint": ep["name"], "name": label["name"], "type": label["type"], "preset": ep["preset"],
                    "plan": bool(preset_of(ep) and preset_of(ep).flat_plan),
                    "region": ep.get("region"), "reach": ep.get("reach"), "enabled": ep.get("enabled", True),
                    "status": status, "down_for_s": down, "calls": calls, "errors": errors,
                    "answered": calls - errors, "error_rate": round(errors / calls, 4) if calls else 0.0,
                    "failed_series": failed, "answered_series": [max(0, a - f) for a, f in zip(series, failed)],
                    "reason": cause["reason"] if cause else (p or {}).get("main_error"),
                    "since": cause["since"] if cause else None, "last": cause["last"] if cause else (p or {}).get("last_ts"),
                    "skipped": cause["skipped"] if cause else 0})
    order = {"down": 0, "degraded": 1, "ok": 2, "unused": 3}
    out.sort(key=lambda e: (order[e["status"]], -e["calls"], e["name"]))
    return out


# --- Overview: where the AI goes and whether it is worth it (TASK-87 round 2) ---------------------------------
def _bucket() -> dict:
    return {"calls": 0, "useful": 0, "wasted": 0, "saved": 0, "tokens": 0.0, "tokens_useful": 0.0,
            "tokens_wasted": 0.0, "cost": 0.0, "cost_wasted": 0.0, "priced": 0, "cache_saved": 0.0}


def _accumulate(b: dict, row: dict) -> None:
    calls, errors = int(row.get("calls") or 0), int(row.get("errors") or 0)
    wasted_share = errors / calls if calls else 0.0  # exact per call row (one outcome per row), pro rata in the 30 d rollup
    tokens = int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
    b["calls"] += calls
    b["wasted"] += errors
    b["useful"] += calls - errors
    b["saved"] += int(row.get("avoided") or 0)
    b["tokens"] += tokens
    b["tokens_wasted"] += tokens * wasted_share
    b["tokens_useful"] += tokens * (1 - wasted_share)
    priced = int(row["priced_calls"]) if "priced_calls" in row else (calls if row.get("cost") is not None else 0)
    if priced and row.get("cost") is not None:
        cost = float(row["cost"])
        b["cost"] += cost
        b["cost_wasted"] += cost * wasted_share
        b["priced"] += priced
    b["cache_saved"] += float(row.get("cache_saved") or 0.0)


def _finish(b: dict) -> dict:
    """Round the sums and derive what the avoided requests would have used (their number times the average
    answered request of the same group). Costs are None when nothing in the group is priced."""
    useful = b["useful"]
    avg_tokens = b["tokens_useful"] / useful if useful else 0.0
    avg_cost = (b["cost"] - b["cost_wasted"]) / useful if useful and b["priced"] else None
    saved_cost = (b["saved"] * avg_cost if avg_cost is not None else 0.0) + b["cache_saved"]
    priced = b["priced"] > 0
    return {
        "calls": b["calls"], "useful": b["useful"], "wasted": b["wasted"], "saved": b["saved"],
        "tokens": round(b["tokens"]), "tokens_useful": round(b["tokens_useful"]),
        "tokens_wasted": round(b["tokens_wasted"]), "tokens_saved": round(b["saved"] * avg_tokens),
        "cost": round(b["cost"], 6) if priced else None,
        "cost_wasted": round(b["cost_wasted"], 6) if priced else None,
        "cost_useful": round(b["cost"] - b["cost_wasted"], 6) if priced else None,
        "cost_saved": round(saved_cost, 6) if saved_cost else None,
    }


def overview(rows: Iterable[dict], limit_callers: int = 12) -> dict:
    """``{totals, categories, callers}``: every category and the busiest callers split into useful (answered) /
    wasted (failed or empty) / saved (avoided by memory or a rule), in requests, tokens and cost. A caller also
    lists the categories it drives (requests per category)."""
    from .usage_caller import caller_of
    from .usages import category_of
    total, by_cat, by_caller, caller_cats = _bucket(), {}, {}, {}
    for r in rows:
        category, caller = category_of(r.get("usage_key") or ""), caller_of(r)
        for bucket in (total, by_cat.setdefault(category, _bucket()), by_caller.setdefault(caller, _bucket())):
            _accumulate(bucket, r)
        cats = caller_cats.setdefault(caller, {})
        cats[category] = cats.get(category, 0) + int(r.get("calls") or 0) + int(r.get("avoided") or 0)
    categories = sorted(({"key": k, **_finish(b)} for k, b in by_cat.items()), key=lambda c: -(c["calls"] + c["saved"]))
    callers = sorted(({"key": k, **_finish(b), "categories": caller_cats[k]} for k, b in by_caller.items()),
                     key=lambda c: -(c["calls"] + c["saved"]))[:limit_callers]
    return {"totals": _finish(total), "categories": categories, "callers": callers}
