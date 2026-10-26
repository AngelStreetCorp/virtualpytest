"""TASK-132: Garen top bot v0. Rules are pure (:func:`decide`), the loop wires perception and input.

State machine: LANE -> (low health or gold covers the next item) RECALL -> SHOP -> RETURN -> LANE.
Items and level order come from ``docs/agent/game/lol/champions/garen.yaml`` (start Doran's Shield, then Berserker's Greaves,
Stridebreaker, Phantom Dancer); the gold prices below are the shop prices of patch 16.20 and only decide *when* to go back.
Never stands still for more than ``IDLE_LIMIT_S`` seconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .minion_track import MinionTracker
from .lane_map import at_base, enemy_top_turrets_down, lane_geometry, too_close
from .perception import PLAYER_XY, Bar, camera_state, hud_calibrated, find_bars, hud_visible, nearest, shop_is_open, shop_search_is_empty, view_box_position

IDLE_LIMIT_S = 4.0  # contract: never stand still for more than 5 s
# Last-hit by computed damage (owner: last-hitting is the most important skill; cannon first, then melee, caster last).
# Max health per minion type = base + per-minute growth. Bases are from the LoL wiki (melee 465, caster 284, siege 835 at the first
# upgrade); the growth per minute is an ESTIMATE (the wiki gives no per-upgrade number) and is corrected live from our own hits.
MINION_HP = {"melee": (465.0, 12.0), "caster": (284.0, 8.0), "cannon": (835.0, 30.0)}
TYPE_RANK = {"cannon": 0, "melee": 1, None: 1, "caster": 2}  # which minion to take first when several can be killed
Q_BONUS = (30, 60, 90, 120, 150)  # Decisive Strike bonus physical damage by rank, + 50 % AD (wiki, V26.14)
Q_SAFETY = 0.6  # measured Q hits did 119 and 149 against 162 predicted (v2o games 1-2): bet on 60 % of the formula until it is calibrated
Q_LEVELS = (2, 8, 10, 12, 13)  # garen.yaml skill order: Q ranks at these levels
LASTHIT_SOURCE = "predictor"  # who decides "one auto kills now": "predictor" = our estimate (the real-game behaviour, default); "marker" = the Practice Tool's
#                               own marker, TRAINING REFERENCE ONLY (owner, 2026-10-19: the marker exists only in training, the bot must not need it)
PREDICT_MARGIN = 1.05  # predictor: predicted health at impact <= our damage x this
FARM_LOOP = "marker"  # "marker" = one-poke/soldiers-first loop of v2w (decides by LASTHIT_SOURCE);  "simple" = 521287b3b attack loop (v2r-v2v); "exact" = the exact-health layer (v2g-v2q)
MARK_SLACK = 0.03  # bar fraction: about two pixels of a 62 px bar, the colour boundary's measurement error
SIMPLE_MARGIN = 1.15
POKE_MAX_FRAC = 0.75  # v2t: poke only a minion already below this fraction of its health (a healthy one is not worth the walk into the wave)
LH_MARGIN = 1.00  # attack when the PREDICTED health at impact <= our damage (research: LASTHIT_PLAYBOOK.md)
WINDUP_PCT = 0.18  # Garen basic attack wind-up share of the attack time (wiki Garen V26.14: 18 %)
LATENCY_S = 0.3  # default decision-to-click latency; replaced by the median of the latencies measured per click (target <= 0.15 s)
MOVE_SPEED_PXS = 345.0  # Garen move speed, px per second (about 1 px per unit)
LH_RANGE_PX = 210  # Garen's attack range (175 units) plus the minion's radius: farther than this an attack click only walks
LH_RESOLVE_S = 3.0  # an attempt counts as a hit when the creep score rose within this many seconds (walk + wind-up)
CROWD_PX = 300  # enemy minions this close count as a crowd around Garen
DRAIN10_FRAC = 0.10  # health lost within 10 s (fraction of max): a slow drain from minions at range (hcoach-1 died to 12 %/10 s)
DRAIN_LOW_HP = 0.60  # ... or health below this while it is still falling
DRAIN_RETREAT_S = 4.0
DRAIN_LOW_DRAIN10 = 0.05  # v2v: under 60 % health the retreat needs 5 % lost in 10 s (v2u game 2: five retreats in 2:50-5:00 and no CS)
CROWD_DROP_FRAC = 0.02  # health lost within 2 s (fraction of max) while in a crowd = minion aggro
BACKSTEP_PX = 240
SELECT_EXTRA_PX = 100  # select only minions this far beyond attack range (v2p waited on minions 450 px away that it never walked to)
LH_SOON = 2.2  # a minion within this many hits of dying is worth waiting for: do not waste an auto on another one
ENGAGE_PX = 330  # E radius (325 game units) is roughly this on screen
MINION_REACH_PX = 380
TURRET_RANGE_PX = 800  # enemy turret range (750 units) plus Garen's size, about 1 px per unit on screen
TURRET_MIN_ALLIES = 3  # allied minions that must be inside the turret's range before Garen enters it
SHOP_MIN_GOLD = 300  # the shop buys the affordable components of an item
RECALL_GOLD = 800  # first trip at 800+ gold when it is safe (reference: first back 800 gold)
LATER_RECALL_GOLD = 1100  # later trips (reference: 1000+)
RECALL_HP_FRAC = 0.35
RECALL_GAP_S = 150.0  # v1 run 1 recalled 5 times in 8 minutes and farmed 20 CS: fewer, bigger trips
HP_DROP_FRAC = 0.06  # health lost within 2 s with no champion near = the turret (or something unseen) is hitting us
R_DMG = ((125, 0.25), (200, 0.30), (275, 0.35))  # (base true damage, share of missing health) per R rank
FAR_PX = 950  # enemy minions farther than reach but on screen: walk toward them
CHAMP_RANGE_PX = 450
R_EXECUTE_FRAC = 0.35

# minimap pixels on a 1920x1200 screen (calibrated 2026-10-18 on a real frame)
_DEFAULT = lane_geometry("ORDER", 0)  # blue side, enemy T1 standing (State defaults; the loop derives them from the game)
MINI_LANE_FARM = _DEFAULT["farm_px"]
MINI_SAFE = _DEFAULT["safe_px"]
RECALL_CHANNEL_S = 9.0  # B channel is 8 s
RETREAT_S = 5.0
# Watchdog: no state may last longer than this; on timeout the bot logs "stuck", resets to LANE and keeps playing.
MODE_LIMIT_S = {"RECALL": 14.0, "SHOP": 20.0, "RETURN": 45.0}
BUY_LIMIT_S = 15.0  # one purchase (open shop, search, buy, close) must finish within this
START_ITEMS = ["Doran's Shield", "Health Potion"]  # garen.yaml start: Shield (500 gold with the potion); Doran's Blade is the alternative
START_AFTER_GAME_S = 1.0  # buy as soon as the clock runs and the HUD shows; while the 'Quest Selection Lock' overlay (~20 s) swallows keys, the shop is retried
START_OPEN_BUDGET_S = 30.0  # how long the first purchase keeps retrying to open the shop
RECALL_DROP_FRAC = 0.03  # health lost during the channel = the recall was interrupted

BUILD: List[Tuple[str, int]] = [  # (item, total gold to have before going back to buy it)
    ("Doran's Shield", 450),
    ("Berserker's Greaves", 1100),
    ("Stridebreaker", 3300),
    ("Phantom Dancer", 2600),
]
SKILL_ORDER = ["R", "E", "Q", "W"]  # level-up presses, R first when available (garen.yaml: max E > Q > W)

Action = Tuple[Any, ...]  # ("key", "Q") | ("right", x, y) = attack click | ("move", x, y) = ground move | ("minimap", x, y) | ("recall",) | ("shop", item) | ("levelup",)


@dataclass
class Mem:
    mode: str = "LANE"  # LANE | RECALL | SHOP | RETURN
    mode_since: float = 0.0
    last_action_t: float = 0.0
    last_levelup_t: float = -99.0
    last_lane_walk_t: float = -99.0
    last_q_t: float = -99.0
    last_e_t: float = -99.0
    last_r_t: float = -99.0
    next_item: int = 0
    actions_sent: int = 0
    last_lock_t: float = -99.0
    retreat_until: float = -99.0
    last_recall_t: float = -999.0
    recalls: int = 0
    last_fight_log_t: float = -99.0
    hp_hist: List[Tuple[float, float]] = field(default_factory=list)
    hp_hist10: List[Tuple[float, float]] = field(default_factory=list)
    drain_until: float = -99.0
    fights: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)  # bot-level events: stuck, recall_*, camera_lock, start_items
    stuck_s: float = 0.0
    latencies: List[float] = field(default_factory=list)  # measured decision-to-click latency per attack click
    q_follow: Optional[Dict[str, Any]] = None  # an auto was clicked: press Q right after it lands if the minion is still alive
    pos_hist: List[Tuple[float, Any]] = field(default_factory=list)  # (time, minimap position) of the last ~1.5 s
    last_dest: Optional[Tuple[int, int]] = None  # destination (minimap units / 0.01) of the last move click
    last_move_t: float = -99.0
    clicks: Dict[str, int] = field(default_factory=lambda: {"attack": 0, "move_screen": 0, "move_minimap": 0, "redundant_avoided": 0, "throttled": 0})
    sel: Optional[Dict[str, Any]] = None  # the minion selected by a left click: position, exact health history
    last_select_t: float = -99.0
    last_attack_t: float = -99.0
    last_backstep_t: float = -99.0
    sel_stats: Dict[str, int] = field(default_factory=lambda: {"selected": 0, "read": 0, "unread": 0, "lost": 0, "mismatch": 0, "died_first": 0, "attack": 0, "setup": 0, "wait": 0})
    exact_enabled: bool = True  # False = estimate-only last-hits (unit tests, or no readable target frame)
    exact_off_until: float = -99.0  # after a selection that never read, the estimate logic runs until this time
    hp_scale: float = 1.0  # live correction of the minion max health estimate (measured from our own hits)
    tracker: MinionTracker = field(default_factory=MinionTracker)
    cal: List[Dict[str, Any]] = field(default_factory=list)  # our attack clicks waiting for the bar drop: calibrates hp_scale
    cal_log: List[Dict[str, Any]] = field(default_factory=list)  # every calibration sample, for the report
    pokes: List[Dict[str, Any]] = field(default_factory=list)  # v2r+ simple loop: autos on minions NOT within one auto of dying (own rows, not in the hit rate)
    lasthits: List[Dict[str, Any]] = field(default_factory=list)  # attempts: t, type, est_hp, dmg, cs0, result


@dataclass
class State:
    t: float  # wall-clock seconds (monotonic)
    game_t: float
    hp: float
    max_hp: float
    gold: float
    level: int
    dead: bool
    items: List[str]
    enemies: List[Bar] = field(default_factory=list)
    allies: List[Bar] = field(default_factory=list)
    fence_turret: Optional[Tuple[float, float]] = _DEFAULT["turret"]  # next standing enemy turret, minimap 0..1
    farm_px: Tuple[int, int] = MINI_LANE_FARM
    safe_px: Tuple[int, int] = MINI_SAFE
    team: str = "ORDER"  # ORDER = blue (bottom-left base), CHAOS = red (top-right base)
    pos: Optional[Tuple[float, float]] = None  # minimap position, 0..1 from the top-left (None when unknown)
    self_visible: bool = True  # the camera is locked on the champion (HUD camera button)
    target_hp: Optional[Tuple[int, int]] = None  # exact (current, max) health of the left-click selected unit, read from the target frame
    ad: float = 70.0  # attack damage (Live Client Data championStats.attackDamage)
    attack_speed: float = 0.625  # championStats.attackSpeed
    cs: int = 0  # creep score


def next_item(items: List[str], mem: Mem) -> Optional[Tuple[str, int]]:
    for name, cost in BUILD:
        if name not in items:
            return name, cost
    return None


def _decide_raw(s: State, m: Mem) -> List[Action]:
    """One tick of rules. Returns the actions to send; mutates ``m`` (mode and timers)."""
    acts: List[Action] = []
    if s.dead:
        m.mode, m.mode_since = "LANE", s.t
        return acts

    # Camera: Y toggles lock; press it only when the HUD camera button shows "unlocked", and not more often than every 10 s.
    if not s.self_visible and s.game_t > 3 and s.t - m.last_lock_t > 10.0 and m.mode in ("LANE", "RETURN"):
        m.last_lock_t = s.t
        acts.append(("key", "Y"))
        return acts
    hp_frac = s.hp / s.max_hp if s.max_hp else 1.0
    want = next_item(s.items, m)
    m.hp_hist = [(t, h) for t, h in m.hp_hist if s.t - t <= 2.0] + [(s.t, s.hp)]
    hp_drop = (max(h for _, h in m.hp_hist) - s.hp) / s.max_hp if s.max_hp else 0.0
    m.hp_hist10 = [(t, h) for t, h in m.hp_hist10 if s.t - t <= 10.0] + [(s.t, s.hp)]
    drain10 = (max(h for _, h in m.hp_hist10) - s.hp) / s.max_hp if s.max_hp else 0.0

    def event(kind: str, detail: str) -> None:
        m.events.append({"t": round(s.game_t, 1), "kind": kind, "detail": detail})

    def timeout(mode: str) -> bool:
        """Watchdog: True (and reset to LANE) when the mode ran past its limit."""
        if s.t - m.mode_since < MODE_LIMIT_S[mode]:
            return False
        m.stuck_s += MODE_LIMIT_S[mode]
        event("stuck", f"{mode} longer than {MODE_LIMIT_S[mode]:.0f} s: reset to LANE")
        m.mode, m.mode_since = "LANE", s.t
        return True

    # --- recall -> (confirm in the fountain) -> shop -> return. The shop is only ever used in the fountain. -----------------
    if m.mode == "RECALL":
        el = s.t - m.mode_since
        if at_base(s.pos, s.team) or (s.pos is None and el >= RECALL_CHANNEL_S):
            event("recall_arrived", f"after {el:.0f} s")
            m.mode, m.mode_since = "SHOP", s.t
            return acts
        if el >= 1.0 and hp_drop >= RECALL_DROP_FRAC:
            event("recall_interrupted", f"health dropped {hp_drop:.0%}")
            m.mode, m.mode_since = "LANE", s.t
            m.last_recall_t = s.t - RECALL_GAP_S + 15.0  # try again in 15 s
            acts.append(("minimap",) + s.safe_px)
            return acts
        timeout("RECALL")
        return acts
    if m.mode == "SHOP":
        if s.pos is not None and not at_base(s.pos, s.team):
            event("shop_refused", "not in the fountain")
            m.mode, m.mode_since = "LANE", s.t
            return acts
        if want is not None and s.gold >= SHOP_MIN_GOLD:
            acts.append(("shop", want[0]))
        m.mode, m.mode_since = "RETURN", s.t
        return acts
    if m.mode == "RETURN":
        if s.t - m.mode_since >= 1.0 and s.t - m.last_lane_walk_t >= 3.0:
            m.last_lane_walk_t = s.t
            acts.append(("minimap",) + s.farm_px)
        farm = ((s.farm_px[0] - 1612) / 300.0, (s.farm_px[1] - 893) / 297.0)
        if s.pos is not None and abs(s.pos[0] - farm[0]) + abs(s.pos[1] - farm[1]) < 0.16:
            m.mode, m.mode_since = "LANE", s.t  # normal end: back on the farm spot
        elif s.pos is None and s.t - m.mode_since >= 25.0:
            m.mode, m.mode_since = "LANE", s.t  # position unknown: assume the walk is done
        else:
            timeout("RETURN")
        return acts

    # --- level up skills (cheap, every few seconds) -----------------------------------------------------------------
    if s.t - m.last_levelup_t >= 6.0:
        m.last_levelup_t = s.t
        acts.append(("levelup",))

    champs = nearest(s.enemies, "champion", CHAMP_RANGE_PX)
    minions = nearest(s.enemies, "minion", MINION_REACH_PX)
    px, py = PLAYER_XY
    turrets = [b for b in s.enemies if b.kind == "turret" and ((b.x - px) ** 2 + (b.y + 90 - py) ** 2) ** 0.5 <= TURRET_RANGE_PX]
    allies_in_turret = 0
    if turrets:
        tx, ty = turrets[0].x, turrets[0].y + 90
        allies_in_turret = sum(1 for b in s.allies if b.kind == "minion" and ((b.x - tx) ** 2 + (b.body[1] - ty) ** 2) ** 0.5 <= TURRET_RANGE_PX)

    # a health drop with no champion near while a turret is on screen = the turret targets Garen
    turret_on_us = bool(turrets) and not champs and hp_drop >= HP_DROP_FRAC

    # --- 1. turret: never inside its range without >= 3 allied minions; leave when it hits us or the wave dies ---------
    if turrets and (allies_in_turret < TURRET_MIN_ALLIES or turret_on_us):
        m.retreat_until = s.t + RETREAT_S
    if s.t < m.retreat_until:
        if s.t - m.last_lane_walk_t >= 1.0:
            m.last_lane_walk_t = s.t
            acts.append(("minimap",) + s.safe_px)
        return acts

    # --- 2. recall: below 35 % health, or 800+ gold when it is safe (no champion near, wave pushed or lane quiet) -------
    wave_pushed = len(nearest(s.allies, "minion", 700)) >= 3 and not minions
    safe = not champs and not turrets and hp_drop < RECALL_DROP_FRAC  # also: not taking turret or minion damage
    gold_ok = want is not None and s.gold >= (RECALL_GOLD if m.recalls == 0 else LATER_RECALL_GOLD)
    if s.game_t > 45 and s.t - m.last_recall_t >= RECALL_GAP_S and (
        hp_frac < RECALL_HP_FRAC or (gold_ok and safe and (wave_pushed or not any(
            b.kind == "minion" and ((b.x - PLAYER_XY[0]) ** 2 + (b.body[1] - PLAYER_XY[1]) ** 2) ** 0.5 <= 450 for b in s.enemies)))
    ):
        m.mode, m.mode_since, m.last_recall_t = "RECALL", s.t, s.t
        m.recalls += 1
        acts.append(("recall",))
        return acts

    # --- never go past the middle of the lane: beyond it the enemy turret kills a bot that follows a pushing wave ----------
    past_mid = too_close(s.pos, s.fence_turret)  # backstop; the 3-minion rule above is the main gate
    if past_mid and s.t - m.last_lane_walk_t >= 1.0:
        m.last_lane_walk_t = s.t
        acts.append(("minimap",) + s.safe_px)
        return acts

    # --- 3. fight the enemy laner only when their health is lower than ours --------------------------------------------
    if champs:
        c = champs[0]
        edge = c.frac <= hp_frac + 0.05 and hp_frac >= 0.40
        rank = 3 if s.level >= 16 else 2 if s.level >= 11 else 1 if s.level >= 6 else 0
        r_kills = False
        if rank:
            base, share = R_DMG[rank - 1]
            est_max = 700 + 100 * s.level
            r_kills = c.frac * est_max < base + share * (1 - c.frac) * est_max
        action = "avoid"
        if edge or r_kills:
            action = "R" if (r_kills and s.t - m.last_r_t > 3) else "engage"
            if action == "R":
                m.last_r_t = s.t
                acts += [("right", *c.body), ("key", "R")]
            else:
                if s.t - m.last_q_t > 6.0:
                    m.last_q_t = s.t
                    acts.append(("key", "Q"))
                if s.t - m.last_e_t > 1.0:
                    m.last_e_t = s.t
                    acts.append(("key", "E"))
                acts.append(("right", *c.body))
        elif s.t - m.last_lane_walk_t >= 1.5:
            m.last_lane_walk_t = s.t
            acts.append(("minimap",) + s.safe_px)
        if s.t - m.last_fight_log_t >= 2.0:
            m.last_fight_log_t = s.t
            m.fights.append({"t": round(s.game_t, 1), "action": action, "enemy_frac": c.frac, "my_frac": round(hp_frac, 2)})
        return acts

    # --- 4. last-hit by computed damage (LASTHIT_PLAYBOOK.md): auto only when the predicted health at impact <= our damage; Q is a
    #        reset AFTER the auto, never first; the minion that dies to allies soonest goes first (cannon > melee > caster on ties);
    #        no E while farming (it blocks autos for 3 s); no auto on healthy minions (it pushes the wave) ----------------------------
    for h in m.lasthits:
        if h["result"] is None and s.t - h["t_wall"] >= LH_RESOLVE_S:
            h["result"] = "hit" if s.cs > h["cs0"] else "miss"
            if h["result"] == "miss" and h.get("cause") is None:
                h["cause"] = ("q_short" if h.get("action") == "q" else "over_margin" if h["est_hp"] > h["dmg"] else "gone_or_late")
            event("lasthit", f"{h['type'] or 'melee'}: {h['result']} (est {h['est_hp']:.0f} hp, dmg {h['dmg']:.0f}, "
                  f"pred {h['pred_hp']:.0f} hp at impact, drop {h['rate']:.2f}/s)")
    for h in m.pokes:
        if h["result"] is None and s.t - h["t_wall"] >= LH_RESOLVE_S:
            h["result"] = "hit" if s.cs > h["cs0"] else "miss"
    m.tracker.update(s.t, [b for b in s.enemies if b.kind == "minion"])
    if minions:
        game_min = s.game_t / 60.0
        latency = sorted(m.latencies)[len(m.latencies) // 2] if m.latencies else LATENCY_S

        def max_hp(b: Bar) -> float:
            base, growth = MINION_HP[b.minion_type or "melee"]
            return (base + growth * game_min) * m.hp_scale

        def dist(b: Bar) -> float:
            return ((b.x - PLAYER_XY[0]) ** 2 + (b.body[1] - PLAYER_XY[1]) ** 2) ** 0.5

        def time_to_impact(b: Bar) -> float:
            """Decision-to-click latency + wind-up (18 % of the attack time) + the walk to attack range."""
            windup = WINDUP_PCT / max(s.attack_speed, 0.3)
            return latency + windup + max(0.0, dist(b) - LH_RANGE_PX) / MOVE_SPEED_PXS

        def pred_hp(b: Bar) -> float:
            """Health at the moment our hit would land: now minus what allied minions and turrets take off meanwhile."""
            rate = m.tracker.drop_rate(b)
            return max(0.0, b.frac - rate * time_to_impact(b)) * max_hp(b)

        def secs_to_die(b: Bar) -> float:
            rate = m.tracker.drop_rate(b) * max_hp(b)
            return pred_hp(b) / rate if rate > 1.0 else 99.0

        # calibration: our attack click from a moment ago, the same minion's bar now. The drop beyond what the allies were already
        # taking is our hit: implied max health = our damage / that drop.
        for c in list(m.cal):
            if s.t - c["t"] < c["wait"]:
                continue
            m.cal.remove(c)
            same = [b for b in minions if abs(b.x - c["x"]) <= 60 and abs(b.body[1] - c["y"]) <= 60]
            if same:
                excess = c["f0"] - same[0].frac - c["rate"] * (s.t - c["t"])
                if 0.03 <= excess <= 0.6:
                    base, growth = MINION_HP[same[0].minion_type or "melee"]
                    implied = c["dmg"] / excess
                    m.hp_scale = max(0.5, min(2.0, 0.7 * m.hp_scale + 0.3 * (implied / (base + growth * game_min))))
                    m.cal_log.append({"t": round(s.game_t, 1), "excess": round(excess, 3), "implied_max_hp": round(implied),
                                      "hp_scale": round(m.hp_scale, 2)})
        dmg = s.ad  # armor 0 early; Garen's auto is physical
        px_, py_ = PLAYER_XY
        q_rank = sum(1 for lv in Q_LEVELS if s.level >= lv)
        q_bonus = (Q_BONUS[q_rank - 1] + 0.5 * s.ad) if q_rank else 0.0
        q_ready = q_rank > 0 and s.t - m.last_q_t > 8.0
        cannon_near = any(b.minion_type == "cannon" for b in minions)
        # --- keep out of the enemy wave: minions that are not tanked by allies aggro Garen (v2l: 117 hp/min; frame 3:25 of v2m shows
        #     him inside four enemy minions). While health is falling and two or more enemy minions are close, step away from them.
        crowd = [b for b in s.enemies if b.kind == "minion" and dist(b) <= CROWD_PX]
        # --- slow drain: 10 %+ of health in 10 s (or below 60 % and still falling) with enemy minions near = walk back behind our wave until
        #     it stops (the 2 %/2 s backstep below misses one or two casters chipping at range)
        if (drain10 >= DRAIN10_FRAC or (hp_frac < DRAIN_LOW_HP and drain10 >= DRAIN_LOW_DRAIN10)) and any(dist(b) <= 600 for b in s.enemies if b.kind == "minion"):
            if s.t >= m.drain_until:
                event("drain_retreat", f"lost {drain10:.0%} in 10 s at {hp_frac:.0%} health with enemy minions near: back behind our wave")
            m.drain_until = s.t + DRAIN_RETREAT_S
        if s.t < m.drain_until:
            m.sel = None
            near = [b for b in s.enemies if b.kind == "minion" and dist(b) <= 600]
            if near and s.t - m.last_backstep_t >= 1.5:  # on-screen step away from the enemy minions (v2r used the minimap: 28 clicks in 8 min)
                m.last_backstep_t = s.t
                cx_, cy_ = sum(b.x for b in near) / len(near), sum(b.body[1] for b in near) / len(near)
                dx_, dy_ = PLAYER_XY[0] - cx_, PLAYER_XY[1] - cy_
                norm_ = max((dx_ ** 2 + dy_ ** 2) ** 0.5, 1.0)
                acts.append(("move", int(PLAYER_XY[0] + dx_ / norm_ * 1.5 * BACKSTEP_PX), int(PLAYER_XY[1] + dy_ / norm_ * 1.5 * BACKSTEP_PX)))
            return acts
        if hp_drop >= CROWD_DROP_FRAC and len(crowd) >= 2 and s.t - m.last_backstep_t >= 1.2:
            cx_ = sum(b.x for b in crowd) / len(crowd)
            cy_ = sum(b.body[1] for b in crowd) / len(crowd)
            dx_, dy_ = px_ - cx_, py_ - cy_
            norm_ = max((dx_ ** 2 + dy_ ** 2) ** 0.5, 1.0)
            m.last_backstep_t = s.t
            m.sel = None
            acts.append(("move", int(px_ + dx_ / norm_ * BACKSTEP_PX), int(py_ + dy_ / norm_ * BACKSTEP_PX)))
            event("backstep", f"{len(crowd)} enemy minions close and health falling {hp_drop:.0%}: stepped away")
            return acts
        if FARM_LOOP == "marker":
            # v2w: the Practice Tool draws the health one of our autos removes as a darker red segment at the left end of an enemy bar
            # (Bar.kill_mark). Pink left of it is health beyond one auto: the minion is killable when no pink is left, allowing for what
            # the allies take off during our wind-up. One set-up auto per minion (bar identity from the tracker), then we wait for the marker.
            def pink_frac(b: Bar) -> float:
                return max(0.0, b.frac - b.kill_mark)

            def rank(b: Bar) -> Tuple[int, float]:
                """Soldiers (melee) first, lowest health first. The type comes from max health at this minute: melee > caster, cannon > both."""
                mx = max_hp(b)
                kind = 0 if mx >= 700 * m.hp_scale else 1 if mx >= 380 * m.hp_scale else 2
                return kind, b.frac

            def marker_killable(b: Bar) -> bool:
                return b.kill_mark > 0.0 and pink_frac(b) <= MARK_SLACK + m.tracker.drop_rate(b) * time_to_impact(b)

            def predictor_killable(b: Bar, with_q: bool) -> bool:
                """Our own estimate: predicted health at impact (bar fraction x max health by type and minute, minus the allied drop) against our damage."""
                pred = max(0.0, b.frac - m.tracker.drop_rate(b) * time_to_impact(b)) * max_hp(b)
                return pred <= (dmg + (q_bonus * Q_SAFETY if with_q else 0.0)) * PREDICT_MARGIN

            def killable(b: Bar, with_q: bool) -> bool:
                if LASTHIT_SOURCE == "marker" and b.kill_mark > 0.0:
                    extra = b.kill_mark * Q_SAFETY * q_bonus / max(dmg, 1.0) if with_q else 0.0
                    return pink_frac(b) <= MARK_SLACK + m.tracker.drop_rate(b) * time_to_impact(b) + extra
                return predictor_killable(b, with_q)

            # training signal: every tick, our predictor against the marker (ground truth for "one auto kills now")
            for b_ in minions:
                if b_.kill_mark > 0.0:
                    p_, k_ = predictor_killable(b_, False), marker_killable(b_)
                    key = "agree_kill" if p_ and k_ else "agree_wait" if not p_ and not k_ else "false_early" if p_ else "false_late"
                    m.sel_stats[key] = m.sel_stats.get(key, 0) + 1

            cand = sorted(minions, key=rank)
            auto_now = [b for b in cand if killable(b, False)]
            q_now = [b for b in cand if q_ready and b not in auto_now and killable(b, True)]
            target = auto_now[0] if auto_now else (q_now[0] if q_now else None)
            if target is not None:
                if target in q_now:
                    m.last_q_t = s.t
                    acts.append(("key", "Q"))
                acts.append(("right", *target.body))
                m.sel_stats["marker_hit"] = m.sel_stats.get("marker_hit", 0) + 1
                m.lasthits.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": target.minion_type, "est_hp": target.frac * max_hp(target),
                                   "pred_hp": target.frac * max_hp(target), "rate": m.tracker.drop_rate(target), "dmg": dmg + (q_bonus if target in q_now else 0.0),
                                   "cs0": s.cs, "result": None, "x": target.x, "y": target.body[1], "bar_frac": target.frac, "ad": s.ad,
                                   "action": "q" if target in q_now else "auto", "wait": 0.0, "t_click": round(s.game_t, 2), "latency": None,
                                   "kill_mark": target.kill_mark, "pink_frac": round(pink_frac(target), 3),
                                   "implied_max_hp": round(s.ad / target.kill_mark) if target.kill_mark > 0 else None, "source": LASTHIT_SOURCE})
            elif s.t - m.last_attack_t >= 1.0 / max(s.attack_speed, 0.3):
                fresh = [b for b in cand if (m.tracker.track_of(b) is not None and not m.tracker.track_of(b).poked)]
                if fresh:
                    t_ = fresh[0]
                    m.tracker.track_of(t_).poked = True
                    m.last_attack_t = s.t
                    m.pokes.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": t_.minion_type, "est_hp": t_.frac * max_hp(t_), "dmg": dmg,
                                    "cs0": s.cs, "result": None, "x": t_.x, "y": t_.body[1], "bar_frac": t_.frac, "ad": s.ad, "action": "poke",
                                    "t_click": round(s.game_t, 2), "kill_mark": t_.kill_mark})
                    acts.append(("right", *t_.body))
                    m.sel_stats["marker_poke"] = m.sel_stats.get("marker_poke", 0) + 1
            return acts
        if FARM_LOOP == "simple":
            # v2r: the attack loop of 521287b3b (3.41 CS/min in the TASK-134 benchmark) -- attack whatever is within one auto (+15 %)
            # or one auto + Q, cannon first, and never stand idle; backstep above is the only extra kept from the exact-layer versions.
            def est_hp(b: Bar) -> float:
                return b.frac * max_hp(b)

            cand = sorted(minions, key=lambda b: (TYPE_RANK[b.minion_type], est_hp(b)))
            auto_now = [b for b in cand if est_hp(b) <= dmg * SIMPLE_MARGIN]
            q_now = [b for b in cand if q_ready and est_hp(b) <= (dmg + q_bonus) * SIMPLE_MARGIN and b not in auto_now]
            target = auto_now[0] if auto_now else (q_now[0] if q_now else None)
            if target is not None:
                if target in q_now:
                    m.last_q_t = s.t
                    acts.append(("key", "Q"))
                acts.append(("right", *target.body))
                m.sel_stats["simple_hit"] = m.sel_stats.get("simple_hit", 0) + 1
                m.lasthits.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": target.minion_type, "est_hp": est_hp(target),
                                   "pred_hp": est_hp(target), "rate": m.tracker.drop_rate(target), "dmg": dmg + (q_bonus if target in q_now else 0.0),
                                   "cs0": s.cs, "result": None, "x": target.x, "y": target.body[1], "bar_frac": target.frac, "ad": s.ad,
                                   "action": "q" if target in q_now else "auto", "wait": 0.0, "t_click": round(s.game_t, 2), "latency": None})
            elif s.t - m.last_attack_t >= 1.0 / max(s.attack_speed, 0.3) and cand[0].frac <= POKE_MAX_FRAC:
                m.last_attack_t = s.t
                m.pokes.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": cand[0].minion_type, "est_hp": est_hp(cand[0]), "dmg": dmg,
                                "cs0": s.cs, "result": None, "x": cand[0].x, "y": cand[0].body[1], "bar_frac": cand[0].frac, "ad": s.ad,
                                "action": "poke", "t_click": round(s.game_t, 2)})
                acts.append(("right", *cand[0].body))  # nothing close to dying: a safe auto on the weakest, never idle
                m.sel_stats["simple_poke"] = m.sel_stats.get("simple_poke", 0) + 1
            return acts
        # --- exact layer: left-click selects a minion (no attack) and the target frame shows its exact health ----------------------
        sel = m.sel if m.exact_enabled else None
        if sel is not None:
            near_sel = [b for b in s.enemies if b.kind == "minion" and abs(b.x - sel["x"]) <= 110 and abs(b.body[1] - sel["y"]) <= 110]  # the scene scrolls with Garen
            unread = sel["seen"] is None and s.t - sel["t"] > 1.5
            if not near_sel or s.t - sel["t"] > 8.0 or unread:
                m.sel_stats["unread" if unread else "lost"] += 1
                if unread:
                    m.exact_off_until = s.t + 3.0  # the click did not select it / the frame is unreadable: estimates for a while
                m.sel = sel = None  # it died, left the screen, or the click did not select it
            else:
                th = s.target_hp
                if th and th[1] > 0:
                    # bars cluster in a wave and swap identity from tick to tick: the exact health read from the target frame says
                    # which bar is the selected one (the fill fraction must match), nearest position breaks ties
                    ratio = th[0] / th[1]
                    cand_b = min(near_sel, key=lambda b: abs(b.frac - ratio) * 400 + abs(b.x - sel["x"]) + abs(b.body[1] - sel["y"]))
                else:
                    cand_b = min(near_sel, key=lambda b: abs(b.x - sel["x"]) + abs(b.body[1] - sel["y"]))
                sel["x"], sel["y"], sel["frac"] = cand_b.x, cand_b.body[1], cand_b.frac
                if th and th[1] > 0 and abs(th[0] / th[1] - cand_b.frac) >= 0.12:
                    m.sel_stats["mismatch"] += 1  # the target frame shows another unit than the bar we followed
                if th and th[1] > 0 and abs(th[0] / th[1] - cand_b.frac) < 0.12:
                    sel["hist"] = [(t_, c_) for t_, c_ in sel["hist"] if s.t - t_ <= 2.5] + [(s.t, th[0])]
                    sel["max"], sel["seen"] = th[1], s.t
                    m.sel_stats["read"] += 1
                    if 400 <= th[1] < 700:  # a melee minion (a cannon has 835+ and must not move the melee estimate): its real max health corrects the estimate used for the other bars
                        base, growth = MINION_HP["melee"]
                        m.hp_scale = max(0.5, min(2.0, 0.6 * m.hp_scale + 0.4 * th[1] / (base + growth * game_min)))
        # measured damage of our last exact attempt: the drop right after the hit, beyond what the allies were already doing
        for h in m.lasthits:
            if h.get("hp_exact") is not None and h.get("measured_dmg") is None and sel is not None and sel["hist"]:
                after = [(t_, c_) for t_, c_ in sel["hist"] if t_ >= h["t_wall"]]
                if len(after) >= 3 and s.t - h["t_wall"] >= h["wait"] + 0.6 and abs(sel["x"] - h["x"]) <= 70 and abs(sel["y"] - h["y"]) <= 70:
                    # our hit is the biggest single drop of the exact health after the click (allied hits are small)
                    drops = [after[i][1] - after[i + 1][1] for i in range(len(after) - 1)]
                    h["measured_dmg"] = float(max(max(drops), 0.0))
                    if abs(h["measured_dmg"] - h["dmg"]) > 2.0:
                        event("dmg_check", f"predicted {h['dmg']:.0f}, measured {h['measured_dmg']:.0f}: differ by more than 2")
        if sel is not None and sel["seen"] is not None and s.t - sel["seen"] <= 0.8 and sel["hist"]:
            cur, mx = sel["hist"][-1][1], sel["max"]
            old = [(t_, c_) for t_, c_ in sel["hist"] if 0.3 <= sel["hist"][-1][0] - t_ <= 1.2]
            rate_abs = max(0.0, (old[0][1] - cur) / (sel["hist"][-1][0] - old[0][0])) if old else 0.0  # hp per second taken by allies
            d_sel = ((sel["x"] - px_) ** 2 + (sel["y"] - py_) ** 2) ** 0.5
            windup = WINDUP_PCT / max(s.attack_speed, 0.3)
            tti = latency + windup + max(0.0, d_sel - LH_RANGE_PX) / MOVE_SPEED_PXS
            pred_exact = cur - rate_abs * tti
            if pred_exact <= 0.02 * mx:
                m.sel_stats["died_first"] += 1
                m.sel = None  # it dies to the allies before our hit lands: not ours, pick another
            elif cur <= (dmg + (Q_SAFETY * q_bonus if q_ready else 0.0)) * LH_MARGIN:  # exact health already within one auto (or one Q-empowered auto)
                use_q = q_ready and cur > dmg * LH_MARGIN  # Q first only when the plain auto cannot kill: the Q bonus widens the window
                if d_sel > LH_RANGE_PX:
                    if s.t - m.last_lane_walk_t >= 0.5:
                        m.last_lane_walk_t = s.t
                        acts.append(("move", int(px_ + 0.7 * (sel["x"] - px_)), int(py_ + 0.7 * (sel["y"] - py_))))
                    return acts
                if use_q:
                    m.last_q_t = s.t
                    acts.append(("key", "Q"))
                    m.sel_stats["q"] = m.sel_stats.get("q", 0) + 1
                    m.sel_stats["q_" + str(type_from_max_hp(mx))] = m.sel_stats.get("q_" + str(type_from_max_hp(mx)), 0) + 1  # Q uses by minion type
                acts.append(("right", int(sel["x"]), int(sel["y"])))
                m.sel_stats["attack"] += 1
                m.last_attack_t = s.t
                pending = [h for h in m.lasthits if h["result"] is None and s.t - h["t_wall"] < LH_RESOLVE_S
                           and abs(h["x"] - sel["x"]) <= 45 and abs(h["y"] - sel["y"]) <= 45]
                if not pending:
                    m.lasthits.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": type_from_max_hp(mx), "est_hp": float(cur), "pred_hp": float(pred_exact),
                                       "rate": rate_abs / max(mx, 1), "dmg": dmg + (q_bonus if use_q else 0.0), "cs0": s.cs, "result": None, "x": sel["x"], "y": sel["y"],
                                       "bar_frac": sel["frac"], "ad": s.ad, "action": "q" if use_q else "auto", "wait": round(tti, 3),
                                       "t_click": round(s.game_t, 2), "latency": None, "hp_exact": cur, "hp_max": mx,
                                       "predicted_dmg": dmg + (q_bonus if use_q else 0.0), "measured_dmg": None, "rate_abs": rate_abs})
                return acts
            else:
                # exact health says: not yet. Wait on it (standing still is correct) unless a minion that dies much sooner is on screen
                better = [b for b in minions if b.frac <= 0.5 and abs(b.x - sel["x"]) > 70 and secs_to_die(b) + 1.0 < (cur - dmg) / max(rate_abs, 1.0)]
                # set-up hit: one hit that leaves it above 1.1 x our damage cannot kill it by mistake and brings the next last-hit sooner
                attack_ready = s.t - m.last_attack_t >= 1.0 / max(s.attack_speed, 0.3)
                if not better and attack_ready and d_sel <= LH_RANGE_PX and cur - dmg >= dmg * 1.1 and rate_abs * tti < cur - 2 * dmg:
                    m.last_attack_t = s.t
                    acts.append(("right", int(sel["x"]), int(sel["y"])))
                    m.clicks["setup"] = m.clicks.get("setup", 0) + 1
                    m.sel_stats["setup"] += 1
                    return acts
                if not better and d_sel > LH_RANGE_PX and cur <= 2.5 * dmg:
                    # it is about to become killable but out of reach: step into attack range (a ground click relative to Garen)
                    if s.t - m.last_lane_walk_t >= 0.5:
                        m.last_lane_walk_t = s.t
                        acts.append(("move", int(px_ + 0.75 * (sel["x"] - px_)), int(py_ + 0.75 * (sel["y"] - py_))))
                        m.sel_stats["step_in"] = m.sel_stats.get("step_in", 0) + 1
                    return acts
                if not better:
                    m.sel_stats["wait"] += 1
                    return acts
                m.sel = None
        if m.exact_enabled and m.sel is None and s.t >= m.exact_off_until and s.t - m.last_select_t >= 1.5:
            # select the minion that will be killable soonest (a left click: it selects, it does not attack)
            pick = sorted((b for b in minions if b.frac <= 0.45 and dist(b) <= LH_RANGE_PX + SELECT_EXTRA_PX), key=lambda b: (secs_to_die(b), b.frac))
            if pick:
                m.last_select_t = s.t
                b0 = pick[0]
                m.sel = {"x": b0.x, "y": b0.body[1], "frac": b0.frac, "t": s.t, "seen": None, "hist": [], "max": None}
                m.sel_stats["selected"] += 1
                acts.append(("select", int(b0.x), int(b0.body[1])))
                return acts

        # Q as a reset: the auto landed, the minion is still alive and now within AD + Q bonus: Q and click it at once
        if m.q_follow is not None:
            qf = m.q_follow
            if s.t - qf["t"] > 3.0:
                m.q_follow = None
            elif s.t - qf["t"] >= qf["wait"]:
                same = [b for b in minions if abs(b.x - qf["x"]) <= 60 and abs(b.body[1] - qf["y"]) <= 60]
                m.q_follow = None
                if same and q_ready and same[0].frac * max_hp(same[0]) <= dmg + q_bonus:
                    m.last_q_t = s.t
                    acts += [("key", "Q"), ("right", *same[0].body)]
                    return acts

        alive = [b for b in minions if pred_hp(b) > 0.04 * max_hp(b)]  # one that dies before our hit lands is not ours any more
        auto_now = sorted((b for b in alive if pred_hp(b) <= dmg * LH_MARGIN),
                          key=lambda b: (round(secs_to_die(b) / 0.3), TYPE_RANK[b.minion_type], pred_hp(b)))
        # a cannon that auto + Q-reset secures (health <= AD + Q bonus + AD): auto first, Q follows; Q is held for the cannon
        cannon_two = [b for b in alive if b.minion_type == "cannon" and dmg * LH_MARGIN < pred_hp(b) <= dmg + q_bonus + dmg and q_ready]
        soon = [b for b in alive if b not in auto_now and pred_hp(b) <= dmg * LH_SOON]
        target = cannon_two[0] if cannon_two else (auto_now[0] if auto_now else None)  # a securable cannon beats a caster or melee
        if target is not None and dist(target) > LH_RANGE_PX:
            # killable but out of reach: close the distance first (an attack click now would only walk, and the wave kills it)
            if s.t - m.last_lane_walk_t >= 0.8:
                m.last_lane_walk_t = s.t
                acts.append(("move", int(PLAYER_XY[0] + 0.7 * (target.x - PLAYER_XY[0])), int(PLAYER_XY[1] + 0.7 * (target.body[1] - PLAYER_XY[1]))))
            return acts
        if target is not None:
            acts.append(("right", *target.body))
            rate = m.tracker.drop_rate(target)
            wait = time_to_impact(target)
            if q_ready and not (cannon_near and target.minion_type != "cannon"):  # Q is held for the cannon on cannon waves
                m.q_follow = {"t": s.t, "wait": wait + 0.05, "x": target.x, "y": target.body[1]}
            pending = [h for h in m.lasthits if h["result"] is None and s.t - h["t_wall"] < LH_RESOLVE_S
                       and abs(h["x"] - target.x) <= 45 and abs(h["y"] - target.body[1]) <= 45]
            if not pending:  # one attempt per minion: re-issuing the click is not a new attempt
                m.lasthits.append({"t": round(s.game_t, 1), "t_wall": s.t, "type": target.minion_type, "est_hp": target.frac * max_hp(target),
                                   "pred_hp": pred_hp(target), "rate": rate, "dmg": dmg, "cs0": s.cs, "result": None,
                                   "x": target.x, "y": target.body[1], "bar_frac": target.frac, "ad": s.ad, "action": "auto",
                                   "wait": round(wait, 3), "t_click": round(s.game_t, 2), "latency": None})
                m.cal.append({"t": s.t, "wait": wait + 0.5, "x": target.x, "y": target.body[1], "f0": target.frac, "rate": rate, "dmg": dmg})
        else:
            # Practice Tool, no enemy laner: pushing the wave costs nothing, and not hitting costs the CS (v2p: 8-10 attack clicks in 8 minutes,
            # 33-39 minions died near Garen). Hit the lowest-health enemy minion in range whenever the attack timer is ready.
            def awkward_after_hit(b: Bar) -> bool:
                """Health just above one auto after our hit (between 1 and 2 autos) invites an ally to take the kill: avoid it."""
                left = b.frac * max_hp(b) - dmg
                return dmg * LH_MARGIN < left < dmg * 2.0

            in_range = sorted((b for b in minions if dist(b) <= LH_RANGE_PX and not awkward_after_hit(b)), key=lambda b: b.frac)
            attack_ready = s.t - m.last_attack_t >= 1.0 / max(s.attack_speed, 0.3)
            if in_range and attack_ready:
                m.last_attack_t = s.t
                acts.append(("right", *in_range[0].body))
                m.sel_stats["farm_hit"] = m.sel_stats.get("farm_hit", 0) + 1
            elif not in_range and s.t - m.last_action_t >= IDLE_LIMIT_S - 1.0:
                nxt = (soon or alive or minions)[0]  # nothing in range: walk toward the next one
                acts.append(("move", int(PLAYER_XY[0] + 0.25 * (nxt.x - PLAYER_XY[0])), int(PLAYER_XY[1] + 0.25 * (nxt.body[1] - PLAYER_XY[1]))))
        return acts

    # --- minions visible but out of reach: walk toward the nearest one -------------------------------------------------
    far = nearest(s.enemies, "minion", FAR_PX)
    if far and not too_close(s.pos, s.fence_turret) and s.t - m.last_lane_walk_t >= 1.5:
        m.last_lane_walk_t = s.t
        t = far[0]
        acts.append(("move", int(PLAYER_XY[0] + 0.7 * (t.x - PLAYER_XY[0])), int(PLAYER_XY[1] + 0.7 * (t.body[1] - PLAYER_XY[1]))))
        return acts

    # --- no minions in view: walk to the lane ------------------------------------------------------------------------
    if s.t - m.last_lane_walk_t >= 3.0:
        m.last_lane_walk_t = s.t
        acts.append(("minimap",) + s.farm_px)
    return acts


# --- movement layer (owner rules, 2026-10-18): the minimap only for far moves, no click when already there, one click per destination --

FAR_MINIMAP_UNITS = 0.15  # a minimap right-click is only for destinations farther than this (base <-> lane); in lane the game screen is used
ARRIVED_MINIMAP = 0.02  # within this of the destination (minimap units) Garen has arrived: no click
ARRIVED_SCREEN_PX = 60  # same, for a ground click relative to Garen on the screen
MOVE_GAP_S = 0.5  # at most one move click per this many seconds unless the destination changes
STOPPED_S = 1.0  # a re-click to the same destination is allowed once Garen has been standing still this long, short of it
UNITS_PER_NORM = 14800.0  # game units across the map = one minimap unit; about 1 screen px per game unit
SCREEN_BOX = (140, 140, 1540, 980)  # where a ground click is safe (inside the game view, clear of the HUD and the minimap)


def type_from_max_hp(mx: int) -> Optional[str]:
    """Minion type from the max health shown in the target frame (wiki bases: caster 284, melee 465, siege 835; growth per upgrade)."""
    if mx >= 700:
        return "cannon"
    if mx >= 400:
        return "melee"
    return "caster" if mx >= 250 else None


def _norm(x: float, y: float) -> Tuple[float, float]:
    return (x - 1612) / 300.0, (y - 893) / 297.0


def filter_moves(acts: List[Action], s: State, m: Mem) -> List[Action]:
    """Apply the movement rules to the move clicks of ``acts`` (attack clicks, keys, recall, shop pass through untouched)."""
    out: List[Action] = []
    pos = s.pos
    hist = m.pos_hist = [(t, p) for t, p in m.pos_hist if s.t - t <= STOPPED_S + 0.5] + ([(s.t, pos)] if pos else [])
    stopped = len(hist) >= 2 and s.t - hist[0][0] >= STOPPED_S and all(abs(p[0] - pos[0]) + abs(p[1] - pos[1]) < 0.003 for _, p in hist) if pos else False
    for a in acts:
        if a[0] not in ("move", "minimap"):
            if a[0] == "right":
                m.clicks["attack"] += 1
            elif a[0] == "select":
                m.clicks["select"] = m.clicks.get("select", 0) + 1
            out.append(a)
            continue
        # destination in minimap units (None = unknown position: pass the click through as it is)
        if a[0] == "minimap":
            dest = _norm(a[1], a[2])
        elif pos is not None:
            dest = (pos[0] + (a[1] - PLAYER_XY[0]) / UNITS_PER_NORM, pos[1] + (a[2] - PLAYER_XY[1]) / UNITS_PER_NORM)
        else:
            dest = None
        key = None if dest is None else (round(dest[0] / 0.01), round(dest[1] / 0.01))
        # arrival: already there = no click (idle is a valid action)
        if pos is not None and dest is not None and abs(pos[0] - dest[0]) + abs(pos[1] - dest[1]) <= ARRIVED_MINIMAP and m.mode == "LANE":
            m.clicks["redundant_avoided"] += 1
            continue
        if a[0] == "move" and pos is None and abs(a[1] - PLAYER_XY[0]) + abs(a[2] - PLAYER_XY[1]) <= ARRIVED_SCREEN_PX:
            m.clicks["redundant_avoided"] += 1
            continue
        same = m.last_dest is not None and key is not None and abs(m.last_dest[0] - key[0]) <= 3 and abs(m.last_dest[1] - key[1]) <= 3
        if same and not stopped:
            m.clicks["redundant_avoided"] += 1  # one click per destination
            continue
        if not same and s.t - m.last_move_t < MOVE_GAP_S and m.last_dest is not None and key is not None and m.mode == "LANE":
            m.clicks["throttled"] += 1
            continue
        if a[0] == "minimap":
            far = pos is None or dest is None or abs(pos[0] - dest[0]) + abs(pos[1] - dest[1]) > FAR_MINIMAP_UNITS or m.mode != "LANE"
            if not far:  # in lane: a ground click relative to Garen instead of the minimap
                x = int(PLAYER_XY[0] + (dest[0] - pos[0]) * UNITS_PER_NORM)
                y = int(PLAYER_XY[1] + (dest[1] - pos[1]) * UNITS_PER_NORM)
                a = ("move", max(SCREEN_BOX[0], min(SCREEN_BOX[2], x)), max(SCREEN_BOX[1], min(SCREEN_BOX[3], y)))
        m.clicks["move_minimap" if a[0] == "minimap" else "move_screen"] += 1
        m.last_dest, m.last_move_t = key, s.t
        out.append(a)
    return out


def decide(s: State, m: Mem) -> List[Action]:
    """One tick of rules, then the movement rules. Returns the actions to send; mutates ``m``."""
    return filter_moves(_decide_raw(s, m), s, m)


def anti_idle(s: State, m: Mem) -> List[Action]:
    """If nothing was sent for IDLE_LIMIT_S, step toward the lane."""
    if s.t - m.last_action_t >= IDLE_LIMIT_S and m.mode == "LANE":
        return [("minimap",) + s.farm_px]
    return []


# --- the loop ---------------------------------------------------------------------------------------------------------

SELF_BAR = (876, 448)  # own health bar with the camera locked on the champion
SHOP_FIRST_RESULT = (498, 296)  # first search result of the shop, 1920x1200 (calibrated 2026-10-18)
SHOP_SEARCH_BOX = (700, 201)
SHOP_PURCHASE = (1375, 600)  # the PURCHASE button of the selected item


def state_from_api(data: Dict[str, Any], enemies: List[Bar], allies: List[Bar], now: float) -> Optional[State]:
    """Build a :class:`State` from ``allgamedata`` plus the bars found on screen."""
    ap = data.get("activePlayer") or {}
    stats = ap.get("championStats") or {}
    if not stats:
        return None
    names = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    me = next((p for p in data.get("allPlayers") or [] if p.get("riotId") in names or p.get("summonerName") in names), {})
    items = [i.get("displayName", "") for i in me.get("items") or []]
    return State(
        t=now,
        game_t=float((data.get("gameData") or {}).get("gameTime", 0.0)),
        hp=float(stats.get("currentHealth", 0.0)),
        max_hp=float(stats.get("maxHealth", 1.0)),
        gold=float(ap.get("currentGold", 0.0)),
        level=int(ap.get("level", 1)),
        dead=bool(me.get("isDead", False)),
        items=items,
        team=me.get("team") or "ORDER",
        ad=float(stats.get("attackDamage", 70.0)),
        attack_speed=float(stats.get("attackSpeed", 0.625)),
        cs=int((me.get("scores") or {}).get("creepScore", 0)),
        enemies=enemies,
        allies=allies,
    )


class GarenBot:
    """Runs :func:`decide` against the live game. Input goes through :class:`game_input.GameInput` (guarded)."""

    def __init__(
        self,
        gi: Any,
        fetch: Callable[[], Optional[Dict[str, Any]]],
        screenshot: Callable[[], Any],
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        tick_s: float = 0.0,  # no sleep between ticks: the last-hit needs >= 2 Hz (v2i measured 0.88 Hz with a 0.5 s sleep)
        on_tick: Optional[Callable[[Dict[str, Any], Optional[Any]], None]] = None,
        camera_mode: str = "locked",
    ) -> None:
        self.gi, self.fetch, self.screenshot = gi, fetch, screenshot
        self.sleep, self.clock, self.tick_s, self.on_tick = sleep, clock, tick_s, on_tick
        self.mem = Mem()
        self._last_shop_close = -99.0
        self.last_enemies: List[Bar] = []  # enemy bars of the latest tick (for the minion-death watcher)
        self.camera_mode = camera_mode  # "locked" (Y) or "free": unlocked, SPACE taps recentre on Garen while he moves
        self._last_move_click = -99.0
        self._last_space = -99.0
        self._tick_n = 0
        self.last_cs: Optional[int] = None  # exact CS from the HUD counter (the MinionWatcher and the hit/miss log use it)
        self.calib_dir: Optional[Any] = None  # pathlib.Path: when set, left-click enemy minions (select, no attack) and save the frames
        self._calib_n = 0
        self._calib_pending: Optional[float] = None
        self._allies: List[Bar] = []
        self._cam_checked = -99.0
        self._cam_ok = True
        self.shot_dir: Optional[Any] = None  # pathlib.Path: where the shop screenshots of each buy attempt go
        self.log: List[Tuple[float, Action]] = []
        self.turn_log: Optional[Any] = None  # turn_log.TurnLog: read-only observer (turns.jsonl, zones.jsonl, live overlay file)

    # one action -> input calls
    def execute(self, a: Action, level: int) -> None:
        kind = a[0]
        if kind == "key":
            self.gi.key(a[1])
        elif kind in ("right", "move"):
            self.gi.right_click(int(a[1]), int(a[2]))
            if kind == "move":
                self._last_move_click = self.clock()
        elif kind == "select":
            self.gi.left_click(int(a[1]), int(a[2]))  # selects the unit (target frame shows its exact health); never attacks
        elif kind == "minimap":
            self.gi.right_click(int(a[1]), int(a[2]))
            self._last_move_click = self.clock()
        elif kind == "recall":
            self.gi.key("B")
        elif kind == "levelup":
            order = ["R"] if level in (6, 11, 16) else []
            for k in order + ["E", "Q", "W"]:
                self.gi.key(k, ctrl=True)
        elif kind == "shop":
            self.buy(a[1])

    def event(self, kind: str, detail: str, game_t: float = 0.0) -> None:
        self.mem.events.append({"t": round(game_t, 1), "kind": kind, "detail": detail})
        print(f"[bot] {kind}: {detail}", flush=True)

    def _shop_open(self) -> bool:
        img = self.screenshot()
        return img is not None and shop_is_open(img)

    def close_shop(self) -> None:
        if self._shop_open():
            self.gi.key("P")
            self.sleep(0.8)

    def _save_shot(self, name: str) -> None:
        if self.shot_dir is None:
            return
        try:
            from PIL import Image

            img = self.screenshot()
            if img is not None:
                self.shot_dir.mkdir(parents=True, exist_ok=True)
                Image.fromarray(img).resize((960, 600)).save(self.shot_dir / f"{name}.png")
        except Exception:  # noqa: BLE001
            pass

    def _gold_items(self) -> Tuple[float, List[str]]:
        data = self.fetch() or {}
        return float((data.get("activePlayer") or {}).get("currentGold", 0.0)), self._owned()

    def _type_name(self, item: str) -> bool:
        """Get the item name into the shop search box and see it there (the placeholder is gone). Two ways to focus it."""
        for focus in ("ctrl+L", "click"):
            if focus == "ctrl+L":
                self.gi.key("L", ctrl=True)
            else:
                self.gi.left_click(*SHOP_SEARCH_BOX)
            self.sleep(0.3)
            self.gi.type_text(item, delay_s=0.03)
            self.sleep(0.7)
            img = self.screenshot()
            if img is not None and not shop_search_is_empty(img):
                return True
            self.event("shop_search", f"typing {item!r} did not land after {focus}")
        return False

    def buy(self, item: str, open_budget_s: float = 2.0) -> bool:
        """Open the shop (only when the screen says it is closed), find the item, buy it, close the shop. Max BUY_LIMIT_S.

        Methods, in order: cursor on the icon + right-click, double-click, select + PURCHASE. A method counts only when
        the Live Client Data shows the purchase (a changed item list or at least 20 gold spent). The method used is logged.
        """
        t0 = self.clock()
        tag = item.replace(" ", "_").replace("'", "")
        try:
            if not self._shop_open():
                self.gi.focus_game()
                while not self._shop_open():
                    if self.clock() - t0 > open_budget_s:
                        self.event("shop_not_open", f"could not open the shop for {item} within {open_budget_s:.0f} s")
                        self._save_shot(f"shop_{tag}_not_open")
                        return False
                    self.gi.key("P")
                    self.sleep(0.8)
            self._save_shot(f"shop_{tag}_1_open")
            if not self._type_name(item):
                self.event("shop_search", f"FAILED to type {item!r}")
                self._save_shot(f"shop_{tag}_2_search_failed")
                return False
            self._save_shot(f"shop_{tag}_2_typed")
            gold0, items0 = self._gold_items()
            x, y = SHOP_FIRST_RESULT
            methods = [
                ("right-click", lambda: (self.gi.move_to(x, y), self.sleep(0.1), self.gi.right_click(x, y))),
                ("double-click", lambda: (self.gi.left_click(x, y), self.sleep(0.15), self.gi.left_click(x, y))),
                ("purchase-button", lambda: (self.gi.left_click(x, y), self.sleep(0.4), self.gi.left_click(*SHOP_PURCHASE))),
            ]
            for name, act in methods:
                if self.clock() - t0 > BUY_LIMIT_S:
                    self.event("stuck", f"buying {item} took longer than {BUY_LIMIT_S:.0f} s: shop closed")
                    self.mem.stuck_s += BUY_LIMIT_S
                    return False
                act()
                self.sleep(0.6)
                gold1, items1 = self._gold_items()
                self._save_shot(f"shop_{tag}_3_{name}")
                if set(items1) != set(items0) or len(items1) != len(items0) or gold1 < gold0 - 20.0:
                    self.event("bought", f"{item} by {name} (gold {gold0:.0f} -> {gold1:.0f})")
                    return True
            self.event("shop_buy", f"FAILED to buy {item}: no method changed the items or the gold")
            return False
        finally:
            self.close_shop()  # outside the fountain the shop must never stay open

    def _owned(self) -> List[str]:
        data = self.fetch()
        if not data:
            return []
        ap = data.get("activePlayer") or {}
        names = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
        me = next((p for p in data.get("allPlayers") or [] if p.get("riotId") in names or p.get("summonerName") in names), {})
        return [i.get("displayName", "") for i in me.get("items") or []]

    def buy_start_items(self) -> bool:
        """First thing in the game, in the fountain: Doran's Shield + Health Potion, verified through the Live Client Data items."""
        for attempt in (1, 2):
            owned = self._owned()
            missing = [i for i in START_ITEMS if i not in owned]
            if not missing:
                self.event("start_items", f"ok {START_ITEMS}")
                return True
            for item in missing:
                self.buy(item)
        owned = self._owned()
        missing = [i for i in START_ITEMS if i not in owned]
        self.event("start_items", f"FAILED, missing {missing}, owned {owned}" if missing else f"ok {START_ITEMS}")
        return not missing

    def _camera_locked(self) -> bool:
        img = self.screenshot()
        return True if img is None else camera_state(img) is True

    def lock_camera(self) -> bool:
        """Y locks the camera on the champion (owner rule). Y TOGGLES, so it is pressed only when the HUD camera button shows the
        camera UNLOCKED (never when the button cannot be read), and the button is read again after each press: at most 3 tries,
        and a loud event when it fails."""
        for attempt in range(1, 4):
            img = self.screenshot()
            state = camera_state(img) if img is not None else True
            if state is True:
                self.event("camera_locked", f"ok (try {attempt})")
                return True
            if state is None:
                self.event("camera_locked", "FAILED: the HUD camera button cannot be read (HUD scale changed?); Y not pressed")
                return False
            self.gi.key("Y")
            self.sleep(0.6)
        img = self.screenshot()
        ok = img is None or camera_state(img) is True
        self.event("camera_locked", "ok" if ok else "FAILED after 3 tries")
        return ok

    def unlock_camera(self) -> bool:
        """Free-camera variant: make sure the camera is NOT locked (the pinned setting starts locked), then recentre once with SPACE."""
        for attempt in range(1, 4):
            img = self.screenshot()
            state = camera_state(img) if img is not None else False
            if state is False:
                self.event("camera_free", f"ok (try {attempt})")
                self.gi.key("SPACE")
                return True
            if state is None:
                self.event("camera_free", "FAILED: the HUD camera button cannot be read; Y not pressed")
                return False
            self.gi.key("Y")  # locked -> unlocked
            self.sleep(0.6)
        self.event("camera_free", "FAILED after 3 tries")
        return False

    def _game_time(self) -> float:
        data = self.fetch()
        return float(((data or {}).get("gameData") or {}).get("gameTime", 0.0)) if data else 0.0

    def wait_in_game(self, timeout_s: float = 90.0) -> bool:
        """Wait until the game can take input: game clock past START_AFTER_GAME_S and rising, in-game HUD on screen."""
        t0 = self.clock()
        last = -1.0
        while self.clock() - t0 < timeout_s:
            g = self._game_time()
            try:
                self.gi.focus_game()  # the taskbar covers the HUD when the game is not the foreground window
            except Exception:  # noqa: BLE001
                pass
            img = self.screenshot()
            if g >= START_AFTER_GAME_S and g > last and img is not None and hud_visible(img):
                self.event("in_game", f"clock {g:.0f} s, HUD visible", g)
                return True
            last = g
            self.sleep(1.5)
        self.event("in_game", "FAILED: clock or HUD never ready")
        return False

    def start_sequence(self) -> bool:
        """In the fountain, before the first step out: wait for the game, buy the start items, lock the camera.

        Target: out of the fountain by game time 15 s. Each step's game time is logged (``start_timing``). Returns False when the
        start items could not be bought (the run must stop: no playing without items)."""
        t0 = self.clock()
        marks: Dict[str, float] = {}
        if not self.wait_in_game():
            return False
        marks["ready"] = round(self.clock() - t0, 1)
        img = self.screenshot()
        if img is not None and not hud_calibrated(img):
            self.event("hud_calibration", "INVALID RUN: the HUD is not laid out as calibrated (minimap scale / resolution): stopping, "
                       "not playing blind")
            return False
        owned = self._owned()
        for item in START_ITEMS:
            if item not in owned:
                self.buy(item, open_budget_s=START_OPEN_BUDGET_S)
        marks["bought"] = round(self.clock() - t0, 1)
        ok = self.buy_start_items()  # verifies through the API; retries what is still missing
        marks["verified"] = round(self.clock() - t0, 1)
        (self.unlock_camera if self.camera_mode == "free" else self.lock_camera)()
        marks["camera"] = round(self.clock() - t0, 1)
        self.event("start_timing", f"seconds since the start steps began: {marks}; game time now {self._game_time():.0f} s",
                   self._game_time())
        return ok

    def step(self) -> Optional[State]:
        if self.camera_mode == "free" and self.clock() - self._last_move_click < 1.5 and self.clock() - self._last_space >= 0.4:
            self._last_space = self.clock()
            self.gi.key("SPACE")  # recentre on Garen while he walks; standing still the free camera does not scroll
            self.sleep(0.12)
        data = self.fetch()
        if data is None:
            return None
        img = self.screenshot()
        if img is not None and self.mem.mode != "SHOP" and shop_is_open(img) and self.clock() - self._last_shop_close >= 2.0:
            self._last_shop_close = self.clock()
            self.mem.stuck_s += 2.0
            self.event("stuck", "shop open outside the buy step: closed it")
            self.gi.key("P")  # a shop left open hides the game: close it
            self.log.append((0.0, ("key", "P")))
            return None
        enemies = find_bars(img, "enemy") if img is not None else []
        self.last_enemies = enemies
        self._tick_n += 1
        if img is not None and self._tick_n % 3 == 1:  # ally bars only feed the turret rule and the wave-pushed test: every 3rd tick
            self._allies = find_bars(img, "ally")
        allies = self._allies
        now = self.clock()
        s = state_from_api(data, enemies, allies, now)
        if s is None:
            return None
        self._calibrate_target_frame(img, s, enemies)
        s.pos = view_box_position(img) if img is not None else None
        if img is not None:
            try:
                from .target_hp import read_target_health

                s.target_hp = read_target_health(img)
            except Exception:  # noqa: BLE001
                s.target_hp = None
        if img is not None:  # exact HUD CS: the API creepScore moves in steps of 10, useless for hit/miss
            try:
                from .cs_reader import read_cs

                exact = read_cs(img[..., ::-1])
                if exact is not None:
                    s.cs = exact
                    self.last_cs = exact
            except Exception:  # noqa: BLE001
                pass
        down = enemy_top_turrets_down(((data.get("events") or {}).get("Events")) or [], s.team)
        g = lane_geometry(s.team, down)
        s.fence_turret, s.farm_px, s.safe_px = g["turret"], g["farm_px"], g["safe_px"]
        if img is not None and self.clock() - self._cam_checked >= 2.0:  # the HUD button changes rarely: read it every 2 s
            self._cam_checked = self.clock()
            self._cam_ok = camera_state(img) is not False  # unlocked -> press Y; unreadable -> never press
        s.self_visible = img is None or self._cam_ok or self.camera_mode == "free"  # "camera locked" (kept under the old field name)
        acts = decide(s, self.mem)
        if self.mem.mode == "LANE":
            acts += filter_moves(anti_idle(s, self.mem), s, self.mem)  # standing still is valid: it only moves when not at the spot
        for a in acts:
            self.execute(a, s.level)
            self.mem.last_action_t = self.clock()
            self.mem.actions_sent += 1
            self.log.append((s.game_t, a))
            if a[0] == "right" and self.mem.lasthits and self.mem.lasthits[-1].get("latency") is None and self.mem.lasthits[-1]["t_wall"] == s.t:
                lat = self.clock() - s.t  # decision-to-click: the screenshot is older than s.t, so this is a lower bound
                self.mem.lasthits[-1]["latency"] = round(lat, 3)
                self.mem.latencies = (self.mem.latencies + [lat])[-20:]
        if self.turn_log is not None:
            self.turn_log.tick(self, s, data, acts)
        if self.on_tick:
            self.on_tick(data, img)
        return s

    def _calibrate_target_frame(self, img: Any, s: State, enemies: List[Bar]) -> None:
        """Calibration capture for the exact-health reader: LEFT-click (select, never attack) an enemy minion in reach, then save
        the next full frame, where the target frame at the top left shows its exact health. Early game only, at most 40 frames."""
        if self.calib_dir is None or img is None or s.dead:
            return
        if self._calib_pending is not None and s.t - self._calib_pending >= 0.35:
            try:
                from PIL import Image

                self.calib_dir.mkdir(parents=True, exist_ok=True)
                Image.fromarray(img).save(self.calib_dir / f"target_{self._calib_n:02d}_t{s.game_t:07.2f}.png")
            except Exception:  # noqa: BLE001
                pass
            self._calib_pending = None
            self._calib_n += 1
            return
        near = nearest(enemies, "minion", 260)
        if near and self._calib_n < 40 and self._calib_pending is None and self._tick_n % 8 == 0 and 60.0 < s.game_t < 420.0:
            self.gi.left_click(*near[0].body)
            self._calib_pending = s.t

    def run(self, max_s: float, is_over: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
        """Tick until ``max_s`` wall-clock seconds, the game ends (API silent), or ``is_over``."""
        start, misses = self.clock(), 0
        while self.clock() - start < max_s and not is_over():
            s = self.step()
            misses = 0 if s is not None else misses + 1
            if misses >= 20:
                break
            self.sleep(self.tick_s)
        return {"seconds": round(self.clock() - start, 1), "actions": self.mem.actions_sent}
