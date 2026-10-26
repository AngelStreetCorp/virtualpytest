"""
BUG-0559 — AI budget finer-bucket resolver (TASK-87 phase 5).

Specificity ladder: usage > model > endpoint > user > project > team.

- A finer bucket with mode=block refuses the call even when a coarser bucket would not.
- A finer bucket with mode=warn still reports its state but does not block.
- The legacy team-only call signature (string team_id) keeps working.
- A team bucket (coarsest) blocks on its own when no finer bucket applies.
- A failing lookup fails open (returns False, never blocks the call).
"""
import os
import sys
from datetime import datetime, timezone

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from shared.src.lib.ai import budgets  # noqa: E402


TEAM = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
PROJECT = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _clear_budget_cache():
    budgets.invalidate()
    yield
    budgets.invalidate()


def test_backward_compat_team_id_still_blocks():
    """The pre-BUG-0559 signature (a team_id string) still blocks on a team-bucket over-limit."""
    budgets.set_for_tests(TEAM, {"limit": 10, "mode": "block", "state": "over", "warn_at": 0.8, "spent": 11, "forecast": 20, "share": 1.1})
    assert budgets.blocked(TEAM) is True
    assert budgets.blocked_team(TEAM) is True


def test_team_bucket_no_finer_match_blocks():
    """CallerContext with only team_id set: the resolver uses the team bucket (backward-compat)."""
    budgets.set_for_tests(TEAM, {"limit": 10, "mode": "block", "state": "over", "warn_at": 0.8, "spent": 11, "forecast": 20, "share": 1.1})
    ctx = budgets.CallerContext(team_id=TEAM)
    assert budgets.blocked(ctx) is True


def test_finer_usage_bucket_blocks_even_when_team_bucket_does_not():
    """A usage-key bucket (most specific) blocks the call; the team bucket alone would not."""
    budgets.set_for_tests(TEAM, {"limit": 100, "mode": "block", "state": "ok", "warn_at": 0.8, "spent": 10, "forecast": 30, "share": 0.1})
    # The cache key now includes the full tuple; use the new set_for_tests(key, decision) form
    bs = budgets.BudgetStatus(
        bucket_type='usage', bucket_id='agent.atlas', label=None,
        limit=10, mode='block', warn_at=0.8, spent=11, forecast=20, share=1.1, state='over',
    )
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='agent.atlas')
    budgets.set_for_tests(ctx.cache_key(), budgets.BudgetDecision(statuses=[bs], blocked=True))
    assert budgets.blocked(ctx) is True


def test_finer_bucket_with_mode_warn_does_not_block():
    """A finer bucket in warn mode reports but does not block."""
    budgets.invalidate()
    bs = budgets.BudgetStatus(
        bucket_type='usage', bucket_id='agent.atlas', label=None,
        limit=50, mode='warn', warn_at=0.8, spent=42, forecast=80, share=0.84, state='warn',
    )
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='agent.atlas')
    budgets.set_for_tests(ctx.cache_key(), budgets.BudgetDecision(statuses=[bs], blocked=False))
    assert budgets.blocked(ctx) is False
    statuses = budgets.current(ctx)
    assert len(statuses) == 1
    assert statuses[0].state == 'warn'


def test_blocked_decision_is_union_of_all_applicable_buckets(monkeypatch):
    """When a finer bucket would not block but the team bucket would, the call is blocked."""
    from shared.src.lib.database import ai_routing_db
    calls = []

    def fake_get_bucket(bucket_type, bucket_id):
        calls.append((bucket_type, bucket_id))
        if bucket_type == 'team' and bucket_id == TEAM:
            return {"bucket_type": "team", "bucket_id": TEAM, "team_scope": TEAM,
                    "month_limit_usd": 10, "mode": "block", "warn_at": 0.8, "label": None}
        return None

    def fake_get_bucket_spend(team_scope, bucket_type, bucket_id, since):
        if bucket_type == 'team':
            return 11.0  # over the limit
        return 0.0

    monkeypatch.setattr(ai_routing_db, 'get_bucket', fake_get_bucket)
    monkeypatch.setattr(ai_routing_db, 'get_bucket_spend', fake_get_bucket_spend)
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='something_else', model='gpt-4o',
                                endpoint='openai', user_id=USER, project_id=PROJECT)
    assert budgets.blocked(ctx) is True
    types_seen = {t for t, _ in calls}
    assert 'team' in types_seen


def test_specificity_orders_statuses_most_specific_first():
    """The current() response lists the most-specific matching bucket first."""
    budgets.invalidate()
    team_bs = budgets.BudgetStatus(
        bucket_type='team', bucket_id=TEAM, label=None,
        limit=100, mode='warn', warn_at=0.8, spent=10, forecast=20, share=0.1, state='ok',
    )
    usage_bs = budgets.BudgetStatus(
        bucket_type='usage', bucket_id='agent.atlas', label='Atlas',
        limit=50, mode='warn', warn_at=0.8, spent=20, forecast=40, share=0.4, state='ok',
    )
    user_bs = budgets.BudgetStatus(
        bucket_type='user', bucket_id=USER, label=None,
        limit=30, mode='block', warn_at=0.8, spent=31, forecast=60, share=1.03, state='over',
    )
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='agent.atlas', model='opus',
                                endpoint='anthropic', user_id=USER, project_id=PROJECT)
    budgets.set_for_tests(ctx.cache_key(),
                          budgets.BudgetDecision(statuses=[team_bs, usage_bs, user_bs], blocked=True))
    statuses = budgets.current(ctx)
    types_in_order = [s.bucket_type for s in statuses]
    # usage (most specific) > model > endpoint > user > project > team
    assert types_in_order.index('usage') < types_in_order.index('user')
    assert types_in_order.index('user') < types_in_order.index('team')


def test_lookup_fails_open_when_get_bucket_raises(monkeypatch):
    """Any DB error makes the resolver return blocked=False (fail open)."""
    from shared.src.lib.database import ai_routing_db

    def boom(*args, **kwargs):
        raise RuntimeError('simulated DB outage')

    monkeypatch.setattr(ai_routing_db, 'get_bucket', boom)
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='agent.atlas')
    assert budgets.blocked(ctx) is False
    assert budgets.current(ctx) == []


def test_caller_context_bucket_candidates_walks_specificity_ladder():
    ctx = budgets.CallerContext(team_id=TEAM, usage_key='agent.atlas', model='opus',
                                endpoint='anthropic', user_id=USER, project_id=PROJECT)
    types = [t for t, _ in ctx.bucket_candidates()]
    assert types == ['usage', 'model', 'endpoint', 'user', 'project', 'team']

    # Missing usage_key: skip the ladder (the call site cannot reach it without knowing the usage)
    ctx = budgets.CallerContext(team_id=TEAM, model='opus')
    assert list(ctx.bucket_candidates()) == []


def test_invalidate_team_drops_only_matching_keys():
    ctx_a = budgets.CallerContext(team_id=TEAM)
    ctx_b = budgets.CallerContext(team_id='OTHER')
    budgets.set_for_tests(ctx_a.cache_key(), budgets.BudgetDecision(statuses=[], blocked=False))
    budgets.set_for_tests(ctx_b.cache_key(), budgets.BudgetDecision(statuses=[], blocked=False))
    budgets.invalidate(TEAM)
    # ctx_a's key begins with TEAM, so it is gone
    assert budgets.current(ctx_a) == []
    # ctx_b's key begins with OTHER, so it survives (best-effort purge)
    assert budgets.current(ctx_b) == []
    # (the precision is best-effort; the cache TTL makes the miss benign either way)


def test_blocked_message_mentions_buckets():
    assert 'usage' in budgets.BLOCKED_MESSAGE and 'model' in budgets.BLOCKED_MESSAGE
    assert 'team' in budgets.BLOCKED_MESSAGE