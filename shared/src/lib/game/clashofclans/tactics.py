"""
Tactics for the Clash of Clans farm bot (TASK-81 §81.1.2).

The priority chain comes straight from §81.1.2:

    collect_ready_collectors -> train_donations_needed -> donate_pending ->
    clan_capital_collect -> daily_collect -> idle

The chain is checked top-down. The **first** true condition decides; ties
(in every signal ready at once) resolve toward the earlier priority. The
chain never returns ``attack`` (TASK-81 §81.1 out-of-scope). ``idle`` is
fine and expected -- a farm bot spends most of its time waiting on
collector timers.

Tactics stays a pure function: ``decide_next(obs) -> Action``. The runner
maps the priority name to the matching user-interface tree node (e.g.
``collect_ready_collectors`` -> ``collect_resources``) and dispatches the
navigation. Tactics does not know about the runner, the device, or the UI
tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .vision import VillageObservation


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

# Action verb names in the priority chain. The runner's UI-tree node names
# are different (``collect_resources``, ``train_troops``, ...); the mapping
# lives in ``runner.py`` so tactics stays decoupled from the tree.
COLLECT_READY_COLLECTORS = "collect_ready_collectors"
TRAIN_DONATIONS_NEEDED = "train_donations_needed"
DONATE_PENDING = "donate_pending"
CLAN_CAPITAL_COLLECT = "clan_capital_collect"
DAILY_COLLECT = "daily_collect"
CLEAR_DISCONNECT_MODAL = "clear_disconnect_modal"
IDLE = "idle"

# Tree node names per §81.1.1. Surface this here so tactics callers have
# one place to look.
TREE_ACTIONS = {
    COLLECT_READY_COLLECTORS: "collect_resources",
    TRAIN_DONATIONS_NEEDED: "train_troops",
    DONATE_PENDING: "donate_troops",
    CLAN_CAPITAL_COLLECT: "collect_clan_capital",
    DAILY_COLLECT: "collect_daily_reward",
    CLEAR_DISCONNECT_MODAL: None,      # menus.cross_to handles this — no tree node
    IDLE: None,                       # no tree node
}

# Tree of banned / "real-money" surfaces. The runner refuses any tap that
# would land in one of these, full stop (rule 6, GAME_BOTS §2).
BANNED_ACTION_SUBSTRINGS: Tuple[str, ...] = (
    "buy", "purchase", "subscribe", "gem", "offer", "pass", "ship",
    "trader", "builder_base", "magic_item", "progression", "supercell_store",
    "gold_pass", "boost", "deal",
)


@dataclass(frozen=True)
class Action:
    """One tactical decision: which priority is firing.

    ``name`` is one of the priority constants. ``target`` is the screen
    the action needs (so the runner can call ``menus.cross_to(obs,
    action.target)``). ``params`` is an opaque bag for the runner /
    tree node (e.g. a collector name, a troop to request).
    """

    name: str
    target: str = "home"
    params: dict = field(default_factory=dict)
    reason: str = ""

    @property
    def is_idle(self) -> bool:
        return self.name == IDLE

    def is_blocked_by_guard(self) -> bool:
        """A guard trip (``obs.account_warning_present``) blocks every action;
        tactics returns ``idle`` with ``reason='guard'`` to make it visible."""
        return False  # set by decide_next; see below

    def to_dict(self) -> dict:
        return {"name": self.name, "target": self.target, "params": dict(self.params), "reason": self.reason}


# ---------------------------------------------------------------------------
# Heuristics for the per-priority booleans
# ---------------------------------------------------------------------------

def _has_ready_collectors(obs: VillageObservation) -> bool:
    return bool(obs.collector_ready)


def _training_needed(obs: VillageObservation) -> bool:
    """The clan requests troops we can train only when the queue isn't full
    AND a donation dot is up (someone has asked for a troop we own). When
    training_queue_full is unknown, assume "not full" (be conservative --
    the worst case is a redundant train tap)."""
    if obs.training_queue_full is True:
        return False
    return obs.donation_dot_present is True


def _donate_pending(obs: VillageObservation) -> bool:
    return obs.donation_dot_present is True


def _capital_ready(obs: VillageObservation) -> bool:
    return obs.clan_capital_ready is True


def _daily_ready(obs: VillageObservation) -> bool:
    return obs.daily_present is True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide_next(obs: Optional[VillageObservation]) -> Action:
    """The §81.1.2 priority chain.

    Returns an ``Action`` with one of the priority constants. ``None`` /
    unknown observations collapse to ``idle`` -- the runner waits one
    frame, then re-reads. The chain never returns ``attack`` even when
    every signal is True at once; the priority chain ends at ``idle``.
    """
    if obs is None:
        return Action(name=IDLE, reason="no_observation")

    # §R5 guard. The vision layer's red-strip check is the structural pre-
    # filter; the runner also runs the OCR-substring scan on the real
    # capture. Tactics must never argue with a guard trip: it returns
    # ``idle`` with ``reason='guard'`` so the runner sees the trip in its
    # step logs.
    if obs.account_warning_present:
        return Action(name=IDLE, reason="guard")

    # Disconnect-modal short-circuit. CoC drops a "Anyone there?" dialog
    # whenever the device idles for ~3 minutes; the modal blocks the
    # resource bar and grass silhouette, so without an explicit cross the
    # runner spins on the transition frame forever. This priority is
    # strictly above the collect/train/donate chain: we always clear the
    # modal before doing anything else.
    if getattr(obs, "screen", None) == "disconnect":
        return Action(
            name=CLEAR_DISCONNECT_MODAL,
            target="home",
            params={},
            reason="disconnect_modal_open",
        )

    # Top-down priority. The first match wins; ties resolve to the earlier
    # priority by construction. ``None``/unknown signals collapse to False
    # so the chain doesn't skip ahead on incomplete reads.
    if _has_ready_collectors(obs):
        return Action(
            name=COLLECT_READY_COLLECTORS,
            target="home",
            params={"collectors": list(obs.collector_ready)},
            reason="collector_ready",
        )
    if _training_needed(obs):
        return Action(
            name=TRAIN_DONATIONS_NEEDED,
            target="home",       # training lives on the home screen too
            params={"queue_full": obs.training_queue_full},
            reason="donation_request_open",
        )
    if _donate_pending(obs):
        return Action(
            name=DONATE_PENDING,
            target="clan",
            params={},
            reason="donation_dot",
        )
    if _capital_ready(obs):
        return Action(
            name=CLAN_CAPITAL_COLLECT,
            target="clan_capital",
            params={},
            reason="capital_chest_ready",
        )
    if _daily_ready(obs):
        return Action(
            name=DAILY_COLLECT,
            target="daily",
            params={},
            reason="daily_reward_present",
        )
    return Action(name=IDLE, reason="nothing_ready")


def priority_chain_description() -> List[str]:
    """The §81.1.2 chain as a list, for the report."""
    return [
        COLLECT_READY_COLLECTORS,
        TRAIN_DONATIONS_NEEDED,
        DONATE_PENDING,
        CLAN_CAPITAL_COLLECT,
        DAILY_COLLECT,
        IDLE,
    ]
