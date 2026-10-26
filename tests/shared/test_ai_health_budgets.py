"""TASK-87 phase 4: AI health alerts and team budgets."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, install_routing  # noqa: E402
from shared.src.lib.ai import budgets, gateway, health, router  # noqa: E402

TEAM = "11111111-1111-1111-1111-111111111111"
LIMITS = {"error_rate": 0.05, "backup_share": 0.10, "min_requests": 20}


HOUR = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def r(usage="vision.banner", calls=100, errors=0, fallbacks=0, endpoint="lab", error_type="", first=-50, last=-10):
    """A rollup row; first / last are minutes before HOUR (the 'now' of these tests)."""
    from datetime import timedelta
    return {"usage_key": usage, "calls": calls, "errors": errors, "fallbacks": fallbacks, "endpoint": endpoint,
            "error_type": error_type, "bucket": (HOUR - timedelta(hours=1)).isoformat(),
            "first_ts": (HOUR + timedelta(minutes=first)).isoformat(), "last_ts": (HOUR + timedelta(minutes=last)).isoformat()}


def test_one_line_per_cause_lists_every_feature_even_a_few_requests():
    rows = [r("agent.browser", calls=3, errors=3, endpoint="or", error_type="no_credit", first=-50, last=-5),
            r("text.decision.localize", calls=40, errors=40, endpoint="or", error_type="no_credit", first=-45, last=-2),
            r("vision.banner", calls=90, errors=0, endpoint="lab", last=-1)]
    out = health.evaluate(rows, HOUR, skipped={"or": [(HOUR - timedelta(minutes=m)).isoformat() for m in range(1, 31)] + ["2026-10-15T01:00:00+00:00"]}, limits=LIMITS)
    assert len(out["causes"]) == 1
    cause = out["causes"][0]
    assert (cause["endpoint"], cause["reason"], cause["severity"]) == ("or", "no_credit", "error")
    assert [f["usage"] for f in cause["features"]] == ["text.decision.localize", "agent.browser"]
    assert cause["errors"] == 43 and cause["skipped"] == 30  # held back since the cause began; older ones not counted
    assert cause["since"].startswith("2026-10-16T11:10") and cause["last"].startswith("2026-10-16T11:58")


def test_a_provider_cause_ends_when_the_endpoint_answers_again():
    rows = [r(calls=10, errors=10, endpoint="or", error_type="no_credit", last=-30),
            r("text.translation", calls=5, errors=0, endpoint="or", last=-3)]
    assert health.evaluate(rows, HOUR, limits=LIMITS)["causes"] == []


def test_a_partial_failure_is_a_warning_and_feature_causes_need_the_error_rate():
    # Rollup rows are per error type: a failed row has calls == errors, answered calls sit in the '' row.
    rows = [r("vision.menu", calls=30, errors=30, endpoint="or", error_type="timeout", first=-55, last=-1),
            r("vision.menu", calls=70, errors=0, endpoint="or", first=-55, last=-30),
            r("vision.banner", calls=97, errors=0, endpoint="lab", last=-1),
            r("vision.banner", calls=3, errors=3, endpoint="lab", error_type="parse", last=-1),     # 3 %: below limit
            r("vision.quality", calls=80, errors=0, endpoint="lab", last=-20),
            r("vision.quality", calls=20, errors=20, endpoint="lab", error_type="parse", last=-1)]  # 20 %
    out = {(c["endpoint"], c["reason"]): c for c in health.evaluate(rows, HOUR, limits=LIMITS)["causes"]}
    assert set(out) == {("lab", "parse"), ("or", "timeout")}
    assert out[("or", "timeout")]["severity"] == "warning"  # it still answered 30 min ago, then failed again
    assert out[("lab", "parse")]["features"] == [{"usage": "vision.quality", "errors": 20, "last": "2026-10-16T11:59:00+00:00"}]


def test_backup_share_needs_volume_in_the_last_hour_and_thresholds_read_the_environment(monkeypatch):
    rows = [r("vision.menu", fallbacks=15), r("vision.banner", calls=10, fallbacks=10), r("text.report", fallbacks=10)]
    backup = health.evaluate(rows, HOUR, limits=LIMITS)["backup"]
    assert [(b["usage"], b["share"]) for b in backup] == [("vision.menu", 0.15)]  # 10 of 100 is not above the limit
    monkeypatch.setenv("AI_ALERT_ERROR_RATE", "0.5")
    monkeypatch.setenv("AI_ALERT_MIN_REQUESTS", "x")
    assert health.thresholds() == {"error_rate": 0.5, "backup_share": 0.10, "min_requests": 20}


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)  # half way through a 31-day month


def test_budget_state_warn_over_and_forecast():
    budget = {"month_limit_usd": 100, "mode": "warn", "warn_at": 0.8}
    ok = budgets.status_from(budget, 20.0, NOW)
    assert ok["state"] == "ok" and ok["forecast"] == pytest.approx(40.0) and ok["share"] == 0.2
    assert budgets.status_from(budget, 45.0, NOW)["state"] == "ok"        # forecast 90: still inside the limit
    assert budgets.status_from(budget, 55.0, NOW)["state"] == "warn"      # forecast 110: the month will overshoot
    assert budgets.status_from(budget, 85.0, NOW)["state"] == "warn"      # past the 80 % warning line
    assert budgets.status_from(budget, 100.0, NOW)["state"] == "over"
    assert budgets.status_from(None, 5.0, NOW) is None


def test_only_a_blocking_budget_that_is_used_up_blocks(monkeypatch):
    base = {"limit": 10, "warn_at": 0.8, "spent": 10, "forecast": 20, "share": 1.0}
    budgets.set_for_tests("t-warn", {**base, "mode": "warn", "state": "over"})
    budgets.set_for_tests("t-block-ok", {**base, "mode": "block", "state": "warn"})
    budgets.set_for_tests("t-block", {**base, "mode": "block", "state": "over"})
    assert [budgets.blocked(t) for t in ("t-warn", "t-block-ok", "t-block", "none", None)] == [False, False, True, False, False]
    budgets.invalidate()


def test_lookup_failure_fails_open(monkeypatch):
    budgets.invalidate()
    from shared.src.lib.database import ai_routing_db
    monkeypatch.setattr(ai_routing_db, "get_budget", lambda team: (_ for _ in ()).throw(RuntimeError("db down")))
    assert budgets.blocked("some-team") is False


def test_gateway_refuses_a_blocked_team_without_calling_a_model(monkeypatch):
    calls = install_routing(monkeypatch, "ok")
    budgets.set_for_tests(TEAM, {"limit": 10, "mode": "block", "state": "over", "warn_at": 0.8, "spent": 10,
                                 "forecast": 10, "share": 1.0})
    result = gateway.complete("text", "hi", team_id=TEAM)
    assert result["success"] is False and result["budget_blocked"] is True and "budget" in result["error"]
    assert calls == []
    assert gateway.complete("text", "hi", team_id=None)["success"] is True   # no team: server default, never blocked
    budgets.invalidate()
    clear_routing()
