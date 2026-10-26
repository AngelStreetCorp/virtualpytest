"""
Provider and period views of Monitoring → AI usage (TASK-87 review round 1). Pure functions over rollup rows.

``provider_label`` turns an ``ai_endpoints`` row into the name a person reads and a type (cloud / local PC);
``provider_view`` is the one-row-per-provider list of the Providers section: status, answered / failed bars per
time bucket of the page period, the active cause with its start, and the calls held back by a no-credit pause.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
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
        for f in ("series", "failed_series", "tokens_in_series", "cost_series"):
            row[f] = list(src[f]) if src else list(empty)
    report.update(step_s=chart["step_s"], series_start=chart["series_start"], series_len=chart["series_len"])


def provider_models(endpoint_id: str, profiles: Iterable[dict]) -> list[dict]:
    """The models an endpoint serves: one entry per distinct model of its enabled profiles, with what each can do."""
    seen: dict[str, dict] = {}
    for pr in profiles:
        if str(pr.get("endpoint_id")) == str(endpoint_id) and pr.get("enabled", True) and pr.get("model"):
            entry = seen.setdefault(pr["model"], {"model": pr["model"], "capabilities": []})
            entry["capabilities"] = sorted({*entry["capabilities"], *(pr.get("capabilities") or [])})
    return sorted(seen.values(), key=lambda m: m["model"])


def provider_view(endpoints: list[dict], period_rows: list[dict], chart_report: dict, causes: list[dict],
                  down_for: dict[str, int], profiles: Iterable[dict] = (),
                  now_rows: Optional[list[dict]] = None) -> list[dict]:
    """One entry per endpoint: label, status (down | degraded | ok | unused), counts of the page period, answered /
    failed series of the chart window, active cause (reason, since, last, skipped calls).

    Status, reason and since are a NOW signal: they come from ``now_rows`` (the last 24 h) and the causes
    (also 24 h), never from the page period. Calls, errors and series follow the page period."""
    period = {r["key"]: r for r in usage_report.aggregate(period_rows, "endpoint", hours=24)["rows"]}
    recent = period if now_rows is None else {r["key"]: r for r in usage_report.aggregate(now_rows, "endpoint", hours=24)["rows"]}
    chart = {r["key"]: r for r in chart_report["rows"]}
    cause_of: dict[str, dict] = {}
    for c in causes:  # worst first: keep the first cause per endpoint
        cause_of.setdefault(c["endpoint"], c)
    out = []
    profiles = list(profiles)
    for ep in endpoints:
        p, c, cause = period.get(ep["name"]), chart.get(ep["name"]), cause_of.get(ep["name"])
        n = recent.get(ep["name"])
        calls_now, errors_now = (n["calls"], n["errors"]) if n else (0, 0)
        calls, errors = (p["calls"], p["errors"]) if p else (0, 0)
        series = c["series"] if c else [0] * chart_report["series_len"]
        failed = c["failed_series"] if c else [0] * chart_report["series_len"]
        down = down_for.get(str(ep["id"]), 0)
        if cause and cause["severity"] == "error" or down:
            status = "down"
        elif cause or (calls_now and errors_now / calls_now >= 0.05):
            status = "degraded"
        else:
            status = "ok" if calls or calls_now else "unused"
        label = provider_label(ep)
        out.append({"endpoint": ep["name"], "name": label["name"], "type": label["type"], "preset": ep["preset"],
                    "plan": bool(preset_of(ep) and preset_of(ep).flat_plan),
                    "region": ep.get("region"), "reach": ep.get("reach"), "enabled": ep.get("enabled", True),
                    "models": provider_models(ep["id"], profiles),
                    # answered calls but no token count: the provider does not report tokens (never shown as 0)
                    "tokens_unreported": bool(p and calls > errors and not (p.get("tokens_in") or 0) + (p.get("tokens_out") or 0)),
                    "status": status, "down_for_s": down, "calls": calls, "errors": errors,
                    "answered": calls - errors, "error_rate": round(errors / calls, 4) if calls else 0.0,
                    "failed_series": failed, "answered_series": [max(0, a - f) for a, f in zip(series, failed)],
                    "reason": cause["reason"] if cause else (n or {}).get("main_error"),
                    "since": cause["since"] if cause else None, "last": cause["last"] if cause else (n or p or {}).get("last_ts"),
                    "skipped": cause["skipped"] if cause else 0})
    order = {"down": 0, "degraded": 1, "ok": 2, "unused": 3}
    out.sort(key=lambda e: (order[e["status"]], -e["calls"], e["name"]))
    return out


# --- Overview: where the AI goes and whether it is worth it (TASK-87 round 2) ---------------------------------
def _bucket() -> dict:
    return {"calls": 0, "useful": 0, "wasted": 0, "saved": 0, "tokens": 0.0, "tokens_useful": 0.0,
            "tokens_wasted": 0.0, "cost": 0.0, "cost_wasted": 0.0, "priced": 0, "cache_saved": 0.0}


# A call refused before it was billed (no credit, bad key): it is a failure, but it cost nothing.
UNBILLED_ERRORS = ("no_credit", "auth")


def wasted_calls(row: dict) -> int:
    """Calls of ``row`` that gave nothing usable (TASK-87 O5): failed (incl. empty answer) + unparseable
    (``parse_ok = false``) + cut off (``stop_reason = max_tokens``). The rollup has the counts, not the
    overlap between them, so the sum is capped at the row's calls."""
    calls, errors = int(row.get("calls") or 0), int(row.get("errors") or 0)
    unparsed = max(int(row.get("parse_total") or 0) - int(row.get("parse_ok_n") or 0), 0)
    return min(calls, errors + unparsed + int(row.get("truncated") or 0))


def _accumulate(b: dict, row: dict) -> None:
    calls = int(row.get("calls") or 0)
    errors = wasted_calls(row)
    wasted_share = errors / calls if calls else 0.0  # exact per call row (one outcome per row), pro rata in the 30 d rollup
    unbilled = row.get("error_type") in UNBILLED_ERRORS and errors >= calls
    tokens = int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
    b["calls"] += calls
    b["wasted"] += errors
    b["useful"] += calls - errors
    b["saved"] += int(row.get("avoided") or 0)
    b["tokens"] += tokens
    b["tokens_wasted"] += tokens * wasted_share
    b["tokens_useful"] += tokens * (1 - wasted_share)
    priced = int(row["priced_calls"]) if "priced_calls" in row else (calls if row.get("cost") is not None else 0)
    if priced and row.get("cost") is not None and not unbilled:  # a refused call is not money wasted
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


def overview(rows: Iterable[dict], limit_callers: int = 100) -> dict:
    """``{totals, categories, callers}``: every category and the busiest callers split into useful (answered) /
    wasted (failed or empty) / saved (avoided by memory or a rule), in requests, tokens and cost. A caller also
    lists the categories it drives (requests per category)."""
    from .usage_caller import caller_of, category_label
    from .usages import page_category
    total, by_cat, by_caller, caller_cats, by_pair, by_incident = _bucket(), {}, {}, {}, {}, {}
    for r in rows:
        category, caller = page_category(r.get("usage_key") or ""), caller_of(r)
        for bucket in (total, by_cat.setdefault(category, _bucket()), by_caller.setdefault(caller, _bucket()),
                       by_pair.setdefault((category, caller), _bucket())):
            _accumulate(bucket, r)
        if category == "discard_incident":  # which incident the triage calls judged: host · device · incident type
            _accumulate(by_incident.setdefault((r.get("host_name") or "", r.get("device_id") or "", r.get("ref_kind") or ""), _bucket()), r)
        cats = caller_cats.setdefault(caller, {})
        cats[category] = cats.get(category, 0) + int(r.get("calls") or 0) + int(r.get("avoided") or 0)
    categories = sorted(({"key": k, **_finish(b)} for k, b in by_cat.items()), key=lambda c: -(c["calls"] + c["saved"]))
    for c in categories:  # the sources of each category, busiest first (the page opens a row to show them)
        c["sources"] = sorted(({"key": caller, **_finish(b)} for (cat, caller), b in by_pair.items() if cat == c["key"]),
                              key=lambda x: -(x["calls"] + x["saved"]))
    for c in categories:
        if c["key"] == "discard_incident":
            c["incidents"] = sorted(({"host": h, "device": d, "kind": k, **_finish(b)} for (h, d, k), b in by_incident.items()),
                                    key=lambda x: -(x["calls"] + x["saved"]))
    labels = {k: category_label(k) for k in by_cat if category_label(k)}  # only the "usage:<key>" ones: named categories are translated by the page
    for c in categories:
        if c["key"] in labels:
            c["label"] = labels[c["key"]]
    callers = sorted(({"key": k, **_finish(b), "categories": caller_cats[k]} for k, b in by_caller.items()),
                     key=lambda c: -(c["calls"] + c["saved"]))[:limit_callers]
    labels.update({k: category_label(k) for c in callers for k in c["categories"] if category_label(k)})
    return {"totals": _finish(total), "categories": categories, "callers": callers, "category_labels": labels}


_MODEL_WORDS = {"minimax": "MiniMax", "vlm": "VLM", "gpt": "GPT", "llm": "LLM", "ai": "AI", "glm": "GLM", "qwen": "Qwen",
                "gemini": "Gemini", "claude": "Claude", "jev": "Jev", "highspeed": "Highspeed", "openrouter": "OpenRouter",
                "vl": "VL"}


def model_label(model: Optional[str], profile: str = "") -> str:
    """A person's name for a model: ``minimax-vlm`` -> "MiniMax VLM", ``jev-1.13`` -> "Jev 1.13". Falls back to the
    profile name when the profile has no model (never a doubled id like ``minimax-vlm-minimax-vlm``)."""
    raw = (model or profile or "?").split("/")[-1]
    words = [w for w in raw.replace("_", "-").split("-") if w]
    out: list[str] = []
    for w in words:
        head = re.match(r"([a-z]+)(\d.*)", w.lower())  # qwen3 -> Qwen3: a known name glued to its version
        pretty = _MODEL_WORDS.get(w.lower()) or (_MODEL_WORDS[head.group(1)] + head.group(2) if head and head.group(1) in _MODEL_WORDS else None) \
            or (w if any(ch.isdigit() for ch in w) else w.capitalize())
        if not out or out[-1].lower() != pretty.lower():
            out.append(pretty)
    half = len(out) // 2
    if len(out) % 2 == 0 and out[:half] == out[half:]:
        out = out[:half]
    return " ".join(out) or raw
