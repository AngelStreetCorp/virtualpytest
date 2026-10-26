"""TASK-87 review round 1: provider rows, previous period, failure causes and times in the aggregate (pure)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import usage_report, usage_view  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


def row(hours_ago, **kw):
    bucket = (NOW - timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0)
    base = {"bucket": bucket.isoformat(), "usage_key": "vision.banner", "endpoint": "or", "profile": "p", "calls": 10,
            "errors": 0, "fallbacks": 0, "total_ms": 1000, "tokens_in": 10, "tokens_out": 5, "error_type": ""}
    base.update(kw)
    return base


def test_aggregate_keeps_causes_times_and_a_failed_series():
    rows = [row(2, calls=10, first_ts=(NOW - timedelta(hours=2, minutes=20)).isoformat(),
                last_ts=(NOW - timedelta(hours=2)).isoformat()),
            row(1, calls=4, errors=4, error_type="no_credit", last_ts=(NOW - timedelta(minutes=50)).isoformat())]
    agg = usage_report.aggregate(rows, "usage", hours=24, now=NOW)
    r = agg["rows"][0]
    assert r["error_types"] == {"no_credit": 4} and r["main_error"] == "no_credit"
    assert sum(r["failed_series"]) == 4 and r["failed_series"][-2] == 4
    assert r["last_error_ts"].startswith("2026-10-16T11:40") and r["first_ts"].startswith("2026-10-16T10:10")
    rollup = usage_report.aggregate([{k: v for k, v in x.items() if k != "error_type"} for x in rows], "usage", hours=24, now=NOW)
    assert rollup["rows"][0]["main_error"] is None  # the hourly rollup (30 d) has no cause


def test_previous_period_and_chart_window_come_from_one_wide_fetch():
    wide = [row(0, calls=5), row(3, calls=7), row(30, calls=11), row(50, calls=99)]
    chart, previous = usage_view.split_periods(wide, 24, NOW)
    assert sorted(r["calls"] for r in chart) == [5, 7]          # the last 24 h
    assert [r["calls"] for r in previous] == [11]                # 24 h before that
    assert usage_view.previous_totals(previous, "usage", 24, None, NOW)["calls"] == 11
    # a 1 h page still charts 24 h
    chart, _ = usage_view.split_periods(wide, 1, NOW)
    assert len(chart) == 2


def test_provider_view_status_series_and_labels():
    eps = [{"id": "1", "name": "openrouter", "preset": "openrouter", "reach": "server"},
           {"id": "2", "name": "pc", "preset": "openai_compatible", "reach": "host", "base_url": "http://10.0.0.5:1234/v1"},
           {"id": "3", "name": "Idle", "preset": "anthropic", "reach": "server"}]
    rows = [row(1, endpoint="openrouter", calls=6, errors=6, error_type="no_credit"), row(1, endpoint="pc", calls=20)]
    chart = usage_report.aggregate(rows, "endpoint", hours=24, now=NOW)
    cause = {"endpoint": "openrouter", "reason": "no_credit", "severity": "error", "since": "s", "last": "l", "skipped": 3}
    profiles = [{"endpoint_id": "2", "model": "qwen", "capabilities": ["vision"], "enabled": True},
                {"endpoint_id": "2", "model": "qwen", "capabilities": ["text"], "enabled": True},
                {"endpoint_id": "3", "model": "off", "enabled": False}]
    out = usage_view.provider_view(eps, rows, chart, [cause], {}, profiles)
    by = {p["endpoint"]: p for p in out}
    assert by["openrouter"]["name"] == "OpenRouter" and by["openrouter"]["type"] == "cloud"
    assert by["openrouter"]["status"] == "down" and by["openrouter"]["skipped"] == 3
    assert by["pc"]["type"] == "local" and by["pc"]["status"] == "ok" and by["Idle"]["status"] == "unused"
    assert sum(by["openrouter"]["failed_series"]) == 6 and sum(by["openrouter"]["answered_series"]) == 0
    assert by["pc"]["models"] == [{"model": "qwen", "capabilities": ["text", "vision"]}] and by["Idle"]["models"] == []
    assert by["pc"]["tokens_unreported"] is False
    silent = usage_view.provider_view(eps, [row(1, endpoint="pc", tokens_in=0, tokens_out=0)], chart, [], {})
    assert {p["endpoint"]: p["tokens_unreported"] for p in silent}["pc"] is True
    assert [p["status"] for p in out] == ["down", "ok", "unused"]


def test_provider_status_is_a_now_signal_whatever_the_period():
    eps = [{"id": "1", "name": "or", "preset": "openrouter", "reach": "server"}]
    # 30 d: a no-credit storm 20 days ago; the last 24 h are clean
    old = [row(480, calls=50, errors=50, error_type="no_credit"), row(2, calls=10)]
    chart = usage_report.aggregate([row(2, calls=10)], "endpoint", hours=24, now=NOW)
    out = usage_view.provider_view(eps, old, chart, [], {}, now_rows=[row(2, calls=10)])[0]
    assert out["status"] == "ok" and out["reason"] is None and out["calls"] == 60 and out["errors"] == 50
    # the other way round: failing now, healthy over the period
    now_bad = [row(1, calls=10, errors=6, error_type="timeout")]
    out = usage_view.provider_view(eps, [row(100, calls=500)] + now_bad, chart, [], {}, now_rows=now_bad)[0]
    assert out["status"] == "degraded" and out["reason"] == "timeout" and out["calls"] == 510
