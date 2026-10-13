"""
The Kirby fight's tactic list and the per-frame bot step.

``TACTICS`` is the ordered option list Jev sees (each ``id`` paired with a one-sentence fact).
``bot_step`` is the deterministic part of the loop: given the last frame's observation and the
current tactic, return the Switch actions for this frame. The list of legal commands lives in
``backend_host/src/controllers/switch/bluetooth_procon.py`` (``press:<b>``, ``sequence:[b1,b2,...]``,
``stick:<left|right>,<direction>[,<ms>]``, ``hold:<b>[,<b>]``, ``release``).
"""

from __future__ import annotations

import statistics
import time
from typing import Dict, List, Optional

from .vision import KIRBY_BAR, MATE_BAR, boss_x, hp, kirby_x

TACTICS: Dict[str, str] = {
    "rush": "close in on the boss and mash attack; the safest pressure when Kirby is healthy.",
    "charged": "close in, hold attack about 0.8 s, release; trades rhythm for raw damage.",
    "jump_attack": "jump then attack; avoids ground charges from the boss.",
    "guard_counter": "guard about 0.4 s then two attacks; best right after a telegraphed hit.",
    "keep_distance": "stay around 350 px away, step in only to land a hit; a safe neutral.",
    "retreat": "move away and guard; use when both Kirbys are low on HP.",
}

NEAR_PX = 180
SAFETY_HP = 0.30       # below this Kirby HP ...
SAFETY_DIST_PX = 350   # ... and closer than this to the boss, the safety retreat overrides every tactic
HP_LOSS_EPS = 0.02     # smaller frame-to-frame HP drops are bar noise, not damage

# Button constants used by the controller.
_B = "b"
_A = "a"
_R = "r"


def _action(command: str, **params) -> dict:
    """One Switch action in the executor's shape. ``wait_time`` is the per-action settle (0)."""
    body: dict = {"command": command, "action_type": "switch"}
    body["params"] = {"wait_time": 0, **params}
    return body


def safety_active(obs: dict) -> bool:
    """True when Kirby is low on HP and close to the boss: retreat whatever the tactic says."""
    kx, bx, khp = obs.get("kirby_x"), obs.get("boss_x"), obs.get("kirby_hp")
    return (khp is not None and khp < SAFETY_HP and kx is not None and bx is not None
            and abs(bx - kx) < SAFETY_DIST_PX)


def bot_step(tactic: str, obs: dict, prev_obs: Optional[dict]) -> List[dict]:
    """Switch actions for this frame, given the current observation and the current tactic.

    ``dx = boss_x - kirby_x``; ``toward`` = the side that closes the gap; ``away`` the opposite.
    Near is ``abs(dx) <= NEAR_PX``. If either x is missing (the boss moved off-screen), fall back
    to mashing attack — better than standing still.
    """
    kx, bx = obs.get("kirby_x"), obs.get("boss_x")
    if kx is None or bx is None:
        return [_action(f"press:{_B}")]

    dx = bx - kx
    toward = "right" if dx > 0 else "left"
    away = "left" if toward == "right" else "right"
    near = abs(dx) <= NEAR_PX

    if safety_active(obs):
        return [_action(f"stick:left,{away},300"), _action(f"press:{_R}", hold_ms=300)]

    if tactic == "rush":
        if not near:
            return [_action(f"stick:left,{toward},200")]
        return [_action(f"sequence:[{toward},{_B},{_B},{_B}]", hold_ms=50, gap_ms=40)]

    if tactic == "charged":
        if not near:
            return [_action(f"stick:left,{toward},200")]
        # Hold attack ~0.8 s, then release. Two actions so the runner can honour pre_wait_ms.
        return [
            _action(f"hold:{_B}"),
            {**_action("release"), "pre_wait_ms": 800},
        ]

    if tactic == "jump_attack":
        if not near:
            return [_action(f"stick:left,{toward},200")]
        return [_action(f"sequence:[{_A},{toward},{_B},{_B}]", hold_ms=50, gap_ms=40)]

    if tactic == "guard_counter":
        # Guard ~0.4 s, release, two attacks stepping toward the boss.
        return [
            _action(f"hold:{_R}"),
            {**_action("release"), "pre_wait_ms": 400},
            _action(f"sequence:[{toward},{_B},{_B}]", hold_ms=50, gap_ms=40),
        ]

    if tactic == "keep_distance":
        dist = abs(dx)
        if dist < 300:
            return [_action(f"stick:left,{away},200")]
        if dist > 420:
            return [_action(f"stick:left,{toward},150")]
        return [_action(f"sequence:[{toward},{_B}]", hold_ms=50, gap_ms=40)]

    if tactic == "retreat":
        return [
            _action(f"stick:left,{away},300"),
            _action(f"press:{_R}"),
        ]

    # Unknown tactic: never stand still, mash attack.
    return [_action(f"press:{_B}")]


def boss_speed(history: list, now: Optional[float] = None) -> Optional[float]:
    """Boss speed in px/s, median of the last 5 boss_x deltas over their timestamps."""
    if len(history) < 2:
        return None
    recent = history[-6:]  # 5 deltas
    deltas_px = []
    deltas_t = []
    for i in range(1, len(recent)):
        a, b = recent[i - 1], recent[i]
        if a["boss_x"] is None or b["boss_x"] is None:
            continue
        if b["t"] <= a["t"]:
            continue
        deltas_px.append(abs(b["boss_x"] - a["boss_x"]))
        deltas_t.append(b["t"] - a["t"])
    if not deltas_t:
        return None
    speeds = [px / dt for px, dt in zip(deltas_px, deltas_t) if dt > 0]
    if not speeds:
        return None
    return round(statistics.median(speeds), 1)


def seconds_since_last_hp_loss(history: list, now: float) -> Optional[float]:
    """Seconds since Kirby last lost HP. None if Kirby has never lost HP in this fight."""
    last = None
    prev_hp = None
    for h in history:
        cur = h.get("kirby_hp")
        if cur is None:
            continue
        if prev_hp is not None and prev_hp - cur >= HP_LOSS_EPS:
            last = h["t"]
        prev_hp = cur
    if last is None:
        return None
    return round(now - last, 1)


def state_text(obs: dict, history: list, current_tactic: str, hp_lost_this_tactic: float,
               fight_start: float, now: Optional[float] = None) -> str:
    """The text Jev reads: Kirby HP, teammate HP, distance to the boss, boss speed, HP loss timing."""
    now = now if now is not None else time.time()
    kx, bx = obs.get("kirby_x"), obs.get("boss_x")
    if kx is not None and bx is not None:
        side = "right" if bx >= kx else "left"
        dist = abs(bx - kx)
        distance_str = f"{dist} px to the {side}"
    else:
        distance_str = "unknown (boss or Kirby off-screen)"
    kirby_hp = obs.get("kirby_hp")
    mate_hp = obs.get("mate_hp")
    kirby_hp_pct = f"{int(round((kirby_hp or 0) * 100))}%" if kirby_hp is not None else "unknown"
    mate_hp_pct = f"{int(round((mate_hp or 0) * 100))}%" if mate_hp is not None else "unknown"
    speed = boss_speed(history)
    since_loss = seconds_since_last_hp_loss(history, now)
    fight_s = round(now - fight_start, 1)
    safety = " Kirby HP is low and the boss is close: safety retreat active, it overrides the tactic." \
        if safety_active(obs) else ""
    return (
        f"Super Kirby Clash boss fight, {fight_s} s in. "
        f"Kirby HP {kirby_hp_pct}, teammate HP {mate_hp_pct}. "
        f"Distance: {distance_str}. "
        f"Boss speed: {speed if speed is not None else 'unknown'} px/s. "
        f"Seconds since Kirby lost HP: {since_loss if since_loss is not None else 'never'}. "
        f"Current tactic: {current_tactic}, Kirby HP lost during it: {int(round(hp_lost_this_tactic * 100))} %."
        f"{safety}"
    )


def fixed_choose(state: str, options: list, instructions: str) -> dict:
    """The baseline chooser: always rush. Same return shape as the Jev chooser."""
    return {
        "choice": "rush",
        "confidence": 1.0,
        "probabilities": {"rush": 1.0},
        "cost": 0.0,
        "ms": 0,
        "decision_id": None,
    }

