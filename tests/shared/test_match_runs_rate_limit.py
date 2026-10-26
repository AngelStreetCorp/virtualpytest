"""Unit tests for the BUG-0571 rate limiter (match_runs_rate_limit.py).

The limiter is a pure in-process counter, so tests are simple: drive the
limiter with N+1 calls, expect the first N to be allowed and the (N+1)th
to be denied.  No fixtures, no DB, no Redis.
"""
import os
import sys
import time

# Repo root is three levels up from this test file.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# Force a tight budget so the tests do not depend on the default 60 rpm
# (we would have to make 61 calls to assert denial, which is slow).
os.environ['MATCH_RUNS_RATE_BUDGET_SUMMARY'] = '3'

from backend_server.src.lib.utils.match_runs_rate_limit import (  # noqa: E402
    MatchRunsRateLimiter, _budget, get_limiter,
)


def test_budget_reads_env_override(monkeypatch):
    """_budget() picks up the per-endpoint env override."""
    monkeypatch.setenv('MATCH_RUNS_RATE_BUDGET_SUMMARY', '17')
    assert _budget('summary') == 17
    # Other endpoints fall back to the default.
    assert _budget('per_device') > 0


def test_budget_zero_means_unlimited(monkeypatch):
    monkeypatch.setenv('MATCH_RUNS_RATE_BUDGET_SUMMARY', '0')
    assert _budget('summary') == 0


def test_limiter_allows_up_to_budget_then_denies(monkeypatch):
    """First N calls allowed, (N+1)th denied, retry_after sane.

    Uses ``monkeypatch`` to pin the budget to 3 within the test (avoids
    racing the module-level ``os.environ`` set) and a fresh
    ``MatchRunsRateLimiter()`` instance to dodge singleton pollution
    from earlier tests.
    """
    monkeypatch.setenv('MATCH_RUNS_RATE_BUDGET_SUMMARY', '3')
    lim = MatchRunsRateLimiter()
    team = f'team_{int(time.time() * 1000)}_{id(lim)}'
    for i in range(3):
        allowed, info = lim.check(team, 'summary')
        assert allowed is True, f'call {i + 1} of 3 should be allowed'
        assert info['used'] == i + 1
        assert info['remaining'] == 3 - (i + 1)
    # Fourth call denies.
    allowed, info = lim.check(team, 'summary')
    assert allowed is False
    assert info['used'] == 4
    assert info['remaining'] == 0
    assert info['denied'] == 1
    assert 1 <= info['window_started_at'] + 60 - time.time() <= 60


def test_limiter_separate_teams_do_not_starve_each_other():
    """A busy team A does not block a quiet team B."""
    lim = MatchRunsRateLimiter()
    a = f'a_{int(time.time() * 1000)}'
    b = f'b_{int(time.time() * 1000)}'
    # Burn team A's budget.
    for _ in range(4):
        lim.check(a, 'summary')
    # Team B should still be allowed.
    allowed, _ = lim.check(b, 'summary')
    assert allowed is True


def test_limiter_separate_endpoints_have_separate_budgets():
    """summary at 3/3 does not block per_device calls."""
    lim = MatchRunsRateLimiter()
    team = f'c_{int(time.time() * 1000)}'
    for _ in range(4):
        lim.check(team, 'summary')  # burn summary budget
    # per_device has its own counter (default 30).
    allowed, _ = lim.check(team, 'per_device')
    assert allowed is True


def test_limiter_zero_budget_never_denies(monkeypatch):
    """An endpoint with budget=0 (e.g. an env override) is unlimited."""
    monkeypatch.setenv('MATCH_RUNS_RATE_BUDGET_TRANSITIONS', '0')
    lim = MatchRunsRateLimiter()
    team = f'd_{int(time.time() * 1000)}'
    for _ in range(50):
        allowed, info = lim.check(team, 'transitions')
        assert allowed is True
        assert info['remaining'] == 'unlimited'


def test_snapshot_groups_per_endpoint():
    """The metrics snapshot is keyed by endpoint, with per-team filtering."""
    lim = MatchRunsRateLimiter()
    team = f'e_{int(time.time() * 1000)}'
    for _ in range(2):
        lim.check(team, 'summary')
    for _ in range(3):
        lim.check(team, 'per_device')
    # Per-team view.
    snap = lim.snapshot(team_id=team)
    assert snap['by_endpoint'].get('summary', {}).get('this_minute') == 2
    assert snap['by_endpoint'].get('per_device', {}).get('this_minute') == 3
    # Fleet-wide view aggregates all teams.
    fleet = lim.snapshot(team_id=None)
    assert 'by_endpoint' in fleet
    assert fleet['team_id'] == '*'


def test_get_limiter_returns_singleton():
    """get_limiter() is process-singleton (counters survive across calls)."""
    a = get_limiter()
    b = get_limiter()
    assert a is b


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
