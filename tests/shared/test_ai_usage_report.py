"""TASK-87: the aggregation behind Monitoring → AI usage (pure, no DB)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import usage_report  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 30, tzinfo=timezone.utc)


def row(hours_ago, usage="vision.banner", team=None, profile="gpu", endpoint="local", **kw):
    base = {"bucket": (NOW - timedelta(hours=hours_ago)).replace(minute=0).isoformat(), "usage_key": usage,
            "team_id": team, "profile": profile, "endpoint": endpoint, "split_arm": "", "calls": 10, "errors": 1,
            "fallbacks": 2, "total_ms": 20000, "tokens_in": 1000, "tokens_out": 400}
    base.update(kw)
    return base


def test_groups_and_totals():
    rows = [row(0), row(1), row(1, usage="text.report", profile="claude", endpoint="anthropic", calls=3, errors=0,
                             fallbacks=0, total_ms=3000, tokens_out=300)]
    report = usage_report.aggregate(rows, "usage", hours=24, now=NOW)
    assert [r["key"] for r in report["rows"]] == ["vision.banner", "text.report"]
    banner = report["rows"][0]
    assert banner["calls"] == 20 and banner["errors"] == 2 and banner["error_rate"] == 0.1
    assert banner["avg_ms"] == 2000 and banner["fallback_rate"] == 0.2
    assert banner["tokens_per_s"] == 20.0  # 800 tokens over 40 s of total time
    assert report["totals"]["calls"] == 23 and report["totals"]["tokens_out"] == 1100
    assert banner["cost"] is None  # no cost column in the rollup yet: never 0


def test_series_is_aligned_to_the_window():
    report = usage_report.aggregate([row(0), row(2)], "usage", hours=24, now=NOW)
    series = report["rows"][0]["series"]
    assert len(series) == report["series_len"] == 24
    assert series[-1] == 10 and series[-3] == 10 and sum(series) == 20


def test_long_windows_use_daily_steps():
    assert usage_report.step_for(24 * 30) == 86400
    report = usage_report.aggregate([row(0), row(5)], "usage", hours=24 * 30, now=NOW)
    assert report["series_len"] == 30 and sum(report["rows"][0]["series"]) == 20


def test_split_arms_show_in_profile_shares_and_missing_team_is_a_key():
    rows = [row(0, team="t1", profile="a", split_arm="b"), row(0, team=None, profile="a")]
    report = usage_report.aggregate(rows, "team", hours=24, now=NOW)
    assert {r["key"] for r in report["rows"]} == {"t1", usage_report.NONE_KEY}
    assert report["rows"][0]["profiles"] in ({"a (b)": 10}, {"a": 10})


def test_filters_and_cost_sum():
    rows = [row(0, cost=0.5), row(0, team="t1", cost=0.25), row(0, team="t1", usage="text.report")]
    report = usage_report.aggregate(rows, "usage", hours=24, filters={"team": "t1"}, now=NOW)
    assert {r["key"]: r["cost"] for r in report["rows"]} == {"vision.banner": 0.25, "text.report": None}
    with pytest.raises(ValueError):
        usage_report.aggregate([], "nope")


def test_forecast_is_linear():
    mid = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)  # 15.5 of 31 days
    assert usage_report.forecast_month(15.5, mid) == pytest.approx(31.0)


def test_error_arm_and_client_groups_and_prompt_size_series():
    rows = [row(0, error_type="timeout", errors=4, calls=4, tokens_in=400), row(0, error_type="", calls=10, tokens_in=2000),
            row(1, split_arm="b", client_hash="ab12", calls=5, tokens_in=500)]
    by_error = usage_report.aggregate(rows, "error", hours=24, now=NOW)
    assert {r["key"]: r["calls"] for r in by_error["rows"]} == {"—": 15, "timeout": 4}
    assert {r["key"] for r in usage_report.aggregate(rows, "arm", hours=24, now=NOW)["rows"]} == {"—", "b"}
    assert usage_report.aggregate(rows, "client", hours=24, now=NOW)["rows"][1]["key"] == "ab12"
    series = usage_report.aggregate(rows, "usage", hours=24, now=NOW)["rows"][0]["tokens_in_series"]
    assert len(series) == 24 and series[-1] == 2400 and series[-2] == 500
    assert "arm" in usage_report.ROLLUP_GROUPS and "error" not in usage_report.ROLLUP_GROUPS


def test_cache_saving_and_avoided_make_saved_cost():
    r = usage_report.aggregate([row(0, cost=1.0, priced_calls=10, avoided=5, cache_saved=0.25)], "usage", hours=24, now=NOW)
    top = r["rows"][0]
    assert top["saved_cost"] == pytest.approx(5 * 1.0 / 10 + 0.25) and top["cache_saved"] == 0.25
