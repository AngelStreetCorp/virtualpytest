"""
TASK-81 §81.1.4 — synthetic tests for the Clash of Clans tactics layer.

The tactics module decides what the runner should tap next. The contract is the
§81.1.2 priority chain from TASK-81 §81.1, locked in priority order:

    COLLECT        (collectors are ready)
    TRAIN          (queue empty AND clan requests troops)
    DONATE         (queue full AND a donation request is pending)
    CLAN_CAPITAL   (a ready clan-capital chest)
    DAILY          (a ready daily-reward badge)
    IDLE           (fallback, "wait one frame")

``ATTACK`` MUST NEVER be returned by v1 of the bot (TASK-81 §81.1 Out of scope).

The companion implementation lives at ``shared/src/lib/game/clashofclans/tactics.py``
under another owner's lane; this file pins the contract.

Run: ``pytest tests/shared/test_clashofclans_tactics.py -v``
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterable, Optional, Tuple

import pytest

# --- the test root bootstrap ----------------------------------------------------
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


# ============================================================================
# Contract spec — the public surface the §81.1.2 tactics layer must implement.
#
# The helpers below mirror the priority chain in TASK-81 §81.1.2 exactly. When
# the real tactics module lands, replace the inline helpers with
# ``from shared.src.lib.game.clashofclans.tactics import decide_next, Action``.
# ============================================================================


class Action:
    """The runner's action vocabulary, mirrored as string constants.

    String constants (vs an enum) keep the data model JSON-serializable for
    metadata (``"action": "COLLECT"``) and make parametrized test failures
    human-readable. ``ATTACK`` exists as a sentinel only so the "never returns
    ATTACK" invariant has a value to assert against.
    """

    COLLECT = "COLLECT"
    TRAIN = "TRAIN"
    DONATE = "DONATE"
    CLAN_CAPITAL = "CLAN_CAPITAL"
    DAILY = "DAILY"
    IDLE = "IDLE"
    ATTACK = "ATTACK"  # sentinel only — never returned in v1.


class VillageState:
    """The minimal state the tactics layer reads.

    Every flag is optional / permissive: an empty-state village (no collectors,
    no requests, no chests, no dailies, no donations) maps to ``IDLE``. The
    runner's tactic chain is exhaustive on ``None``/``False`` defaults — every
    "unknown" defaults to "no input this frame".
    """

    __slots__ = (
        "collectors_ready", "training_queue_count", "training_queue_cap",
        "clan_requests_pending", "donation_request_pending",
        "clan_capital_ready", "daily_reward_ready", "screen",
    )

    def __init__(self, *,
                 collectors_ready: Tuple[str, ...] = (),
                 training_queue_count: int = 0,
                 training_queue_cap: int = 30,
                 clan_requests_pending: bool = False,
                 donation_request_pending: bool = False,
                 clan_capital_ready: bool = False,
                 daily_reward_ready: bool = False,
                 screen: str = "home") -> None:
        self.collectors_ready = collectors_ready
        self.training_queue_count = training_queue_count
        self.training_queue_cap = training_queue_cap
        self.clan_requests_pending = clan_requests_pending
        self.donation_request_pending = donation_request_pending
        self.clan_capital_ready = clan_capital_ready
        self.daily_reward_ready = daily_reward_ready
        self.screen = screen

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collectors_ready": list(self.collectors_ready),
            "training_queue_count": self.training_queue_count,
            "training_queue_cap": self.training_queue_cap,
            "clan_requests_pending": self.clan_requests_pending,
            "donation_request_pending": self.donation_request_pending,
            "clan_capital_ready": self.clan_capital_ready,
            "daily_reward_ready": self.daily_reward_ready,
            "screen": self.screen,
        }


def _training_full(s: VillageState) -> bool:
    cap = max(1, s.training_queue_cap)
    return s.training_queue_count >= cap


def _training_empty(s: VillageState) -> bool:
    return s.training_queue_count == 0


def decide_next(state: VillageState) -> str:
    """The TASK-81 §81.1.2 priority chain.

    Order is locked (TASK-81 §81.1 R2 + Out of scope):

      1. collectors ready   → COLLECT         (collect_ready_collectors)
      2. queue empty + clan requests → TRAIN (train_donations_needed)
      3. queue full + donation pending → DONATE (donate_pending)
      4. clan-capital chest ready → CLAN_CAPITAL (clan_capital_collect)
      5. daily reward ready → DAILY (daily_collect)
      6. otherwise          → IDLE            (idle)

    The function never returns ``ATTACK`` — the §R1/R2 surface the brief locks
    out of v1. That invariant is tested below.
    """
    # 1. Collectors ready — fires first whenever any collector has finished.
    if state.collectors_ready:
        return Action.COLLECT
    # 2. Train when there is something to train AND the queue is empty.
    # "Empty" + "clan requests pending" is the textual form in the brief; we
    # accept zero-current AND zero-cap (no barracks yet) the same way.
    if state.clan_requests_pending and _training_empty(state):
        return Action.TRAIN
    # 3. Donate when the queue is full and somebody asked for a troop.
    if _training_full(state) and state.donation_request_pending:
        return Action.DONATE
    # 4. Clan-capital chest ready.
    if state.clan_capital_ready:
        return Action.CLAN_CAPITAL
    # 5. Daily reward badge visible.
    if state.daily_reward_ready:
        return Action.DAILY
    # 6. Nothing actionable — let the runner wait one frame.
    return Action.IDLE


# ============================================================================
# Tests — one scenario per priority-chain node, plus the no-Attack invariant.
# ============================================================================


# --- (1) collectors ready wins first ----------------------------------------

def test_collectors_ready_wins_over_train_chain():
    """Even with training queue empty AND clan requests pending AND a clan-capital
    chest AND dailies — collectors_ready MUST win the priority chain."""
    s = VillageState(
        collectors_ready=("gold_mine", "elixir_collector"),
        training_queue_count=0,
        clan_requests_pending=True,
        donation_request_pending=True,
        clan_capital_ready=True,
        daily_reward_ready=True,
    )
    assert decide_next(s) == Action.COLLECT


def test_single_collector_ready_still_wins():
    s = VillageState(collectors_ready=("gold_mine",))
    assert decide_next(s) == Action.COLLECT


# --- (2) train_donations_needed ---------------------------------------------

def test_train_when_queue_empty_and_clan_requests():
    s = VillageState(
        training_queue_count=0,
        clan_requests_pending=True,
    )
    assert decide_next(s) == Action.TRAIN


def test_train_skipped_when_queue_has_partial_progress():
    """The brief says "training queue is empty AND clan requests" — partial
    progress means there are still troops cooking, so TRAIN is not yet the
    priority (the queue will finish on its own). Donation, if pending, can
    fire instead."""
    s = VillageState(
        training_queue_count=10,
        clan_requests_pending=True,
    )
    # No collectors, no donation_request, no clan capital, no daily → IDLE.
    assert decide_next(s) == Action.IDLE


# --- (3) donate_pending ------------------------------------------------------

def test_donate_when_queue_full_and_request_pending():
    s = VillageState(
        training_queue_count=30,
        training_queue_cap=30,
        donation_request_pending=True,
    )
    assert decide_next(s) == Action.DONATE


def test_donate_skipped_when_no_request():
    s = VillageState(training_queue_count=30, training_queue_cap=30)
    assert decide_next(s) == Action.IDLE


# --- (4) clan_capital -------------------------------------------------------

def test_clan_capital_when_chest_ready():
    s = VillageState(clan_capital_ready=True)
    assert decide_next(s) == Action.CLAN_CAPITAL


# --- (5) daily_reward -------------------------------------------------------

def test_daily_when_reward_ready():
    s = VillageState(daily_reward_ready=True)
    assert decide_next(s) == Action.DAILY


# --- (6) idle fallback ------------------------------------------------------

def test_idle_when_nothing_actionable():
    s = VillageState()
    assert decide_next(s) == Action.IDLE


# --- priority chain ordering, exhaustively -----------------------------------

def test_priority_chain_ordering_exhaustive():
    """Walk the chain end-to-end. At each level, lower-numbered priorities must
    win over higher ones. The "exhaust all five then IDLE" sweep below proves
    the order is COLLECT → TRAIN → DONATE → CLAN_CAPITAL → DAILY → IDLE."""
    for action, kwargs in (
        # COLLECT wins on its own.
        (Action.COLLECT, dict(collectors_ready=("gold_mine",))),
        # TRAIN wins when queue empty + clan requests, even with capital+daily.
        (Action.TRAIN, dict(clan_requests_pending=True, clan_capital_ready=True,
                            daily_reward_ready=True)),
        # DONATE when queue full + donation requested, alongside capital+daily.
        (Action.DONATE, dict(training_queue_count=30, donation_request_pending=True,
                             clan_capital_ready=True, daily_reward_ready=True)),
        # CLAN_CAPITAL when only capital is ready.
        (Action.CLAN_CAPITAL, dict(clan_capital_ready=True, daily_reward_ready=True)),
        # DAILY when only daily is ready.
        (Action.DAILY, dict(daily_reward_ready=True)),
        # IDLE when nothing matches.
        (Action.IDLE, dict()),
    ):
        s = VillageState(**kwargs)
        assert decide_next(s) == action, f"expected {action}, got {decide_next(s)} for {kwargs}"


# --- the no-Attack invariant (TASK-81 §81.1 Out of scope) -------------------

@pytest.mark.parametrize("kwargs", [
    {},
    dict(collectors_ready=("gold_mine",)),
    dict(training_queue_count=0, clan_requests_pending=True),
    dict(training_queue_count=30, donation_request_pending=True),
    dict(clan_capital_ready=True),
    dict(daily_reward_ready=True),
    dict(collectors_ready=("gold_mine",), clan_requests_pending=True,
         donation_request_pending=True, clan_capital_ready=True,
         daily_reward_ready=True),
])
def test_decide_next_never_returns_attack(kwargs):
    """§R1/R2 forbids Attack in v1; this parametrised test asserts the rule
    across every priority state we recognise."""
    s = VillageState(**kwargs)
    assert decide_next(s) != Action.ATTACK


def test_attack_is_known_constant_but_unused():
    """``Action.ATTACK`` exists as a sentinel so the assertion above has a value
    to check against, but it MUST NOT be in the decided-action vocabulary."""
    allowed = {Action.COLLECT, Action.TRAIN, Action.DONATE,
               Action.CLAN_CAPITAL, Action.DAILY, Action.IDLE}
    decided_actions = {decide_next(VillageState(**kw)) for kw in [
        {}, dict(collectors_ready=("gold_mine",)),
        dict(training_queue_count=0, clan_requests_pending=True),
        dict(training_queue_count=30, donation_request_pending=True),
        dict(clan_capital_ready=True),
        dict(daily_reward_ready=True),
    ]}
    assert decided_actions.issubset(allowed)
    assert Action.ATTACK not in decided_actions
    assert Action.ATTACK not in allowed


# --- runtime guards: the contract is pure ------------------------------------

def test_decide_next_is_pure_no_global_mutation():
    """State in, action out — never mutates the state object or hides side
    effects across calls."""
    s = VillageState(collectors_ready=("gold_mine",))
    snapshot = s.to_dict()
    for _ in range(5):
        decide_next(s)
    assert s.to_dict() == snapshot


def test_priority_overrides_safety_check_chain():
    """The chain MUST NOT silently swallow a lower-priority action when a
    higher-priority one is met (e.g. donation request must not pop COLLECT
    when a collector is ready). One sanity row for every higher node."""
    # Training empty + clan requests + donation pending + capital + daily +
    # 0/30 training -> COLLECT because collectors ready (rule 1 wins).
    s = VillageState(
        collectors_ready=("dark_elixir_drill",),
        training_queue_count=0,
        clan_requests_pending=True,
        donation_request_pending=True,
        clan_capital_ready=True,
        daily_reward_ready=True,
    )
    assert decide_next(s) == Action.COLLECT
