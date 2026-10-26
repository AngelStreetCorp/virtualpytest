"""Decision points for Jev, cut to the runtime coach and tactician (coach_policy.py): a coach decision every 5 s and a
tactician decision every 3 s.

For each anchor time the state is built from the tables with the runtime keys (KEY_STATUS below says which keys exist in a
replay). The label is the option the elite play fits best over the next window (5 s for the coach, 3 s for the tactician),
by a fixed rule, with a confidence and the rule name. Rewards follow the owner's table (outcomes.REWARDS), per 1 s slice from
the slice's own HP, and are attributed only to the chosen option (the label). Nothing is labelled "unknown": a rule that
cannot be evaluated from the tables does not fire.
"""
import math

COACH_EVERY_S = 5.0
COACH_WINDOW_S = 5.0
TACTICIAN_EVERY_S = 3.0
TACTICIAN_WINDOW_S = 3.0
CHOICE_START_S = 0.0       # the choice is the play from the anchor on; the window is the outcome

# coach_policy.py STRATEGY_FACTS / TACTIC_FACTS, copied verbatim as the option lists
COACH_OPTIONS = [
    ("farm_safe", "Default: the rule bot last-hits everything it can kill and stays out of danger."),
    ("push", "Hit minions early to push the wave: only with high health and no enemy champion near."),
    ("freeze", "Only take sure kills, keep the wave near our side: when health is low, the enemy laner is near or the turret is close."),
    ("fight", "Allow trades when the enemy laner has less health than you."),
    ("avoid", "Stay away from the enemy laner: health is under 50 % or they are stronger."),
    ("recall_now", "Go home and buy: only when no enemy is near and gold covers an item (800+) or health is under 35 %."),
]
TACTICIAN_OPTIONS = [
    ("follow_plan", "Let the rule bot execute the current plan as it is."),
    ("hold_back", "Step back toward the safe point for 3 s: the enemy laner or the turret is a threat right now."),
    ("hold", "Stand still for 3 s."),
    ("e_now", "Spin (E) now: three or more enemy minions are within reach and E is ready."),
]

# runtime key -> status in a replay. available: from the tables; null-in-replays: the replay never has it;
# null-for-now: the tables could have it later (calibration, absolute HP, turret detector).
KEY_STATUS = {
    "time": "available", "level": "available", "hp": "available (fraction; absolute from the detector state)",
    "gold": "null-in-replays", "cs": "available", "ad": "available", "items": "available (Live Client, subject only)",
    "enemies": "null-for-now (absolute HP and map-unit distance need calibration and HP per type; enemy champion identity not built)",
    "ally_minions_near": "available (count of ally minions within 150 screen px of the subject)",
    "ready.q": "null-for-now (rows carry the cooldown seconds, not the ready flag)",
    "ready.e": "null-for-now (rows carry the cooldown seconds, not the ready flag)",
    "ready.r": "null-for-now (rows carry the cooldown seconds, not the ready flag)",
    "turret_d": "null-for-now (no turret detector)", "turret": "null-for-now (no turret detector)",
    "map.x": "null-for-now (no screen-to-world calibration)", "map.y": "null-for-now (no screen-to-world calibration)",
    "map.zone": "null-for-now (no screen-to-world calibration)",
    "next_enemy_turret": "null-for-now (no turret detector)",
    "last10s.cs_gain": "available (CS in the 10 s before the anchor)",
    "last10s.damage_taken": "available (HP lost in the 10 s before the anchor)",
    "plan.mode": "null-for-now (the previous plan label is not recorded yet)",
    "plan.reason": "null-for-now",
}

REWARDS = {"last_hit": 1.0, "last_hit_cannon": 2.0, "champion_kill": 10.0, "assist": 3.0, "turret_kill": 12.0,
           "death": -10.0, "damage_per_hp": -0.01, "missed_last_hit": -0.5, "idle_killable_per_tick": -0.2}
NULL_FOR_NOW_REWARDS = ("turret_kill", "missed_last_hit", "idle_killable_per_tick")


def _rows_by_tick(rows):
    return {r["tick"]: r for r in rows}


def _subject_series(tables):
    return sorted((r for r in tables["champions"] if r.get("is_subject") and r.get("observed")), key=lambda r: r["t_s"])


def _at(series, t, back=0.6):
    """Latest subject row at or before t (within `back` seconds), or None."""
    best = None
    for r in series:
        if r["t_s"] <= t + 1e-9:
            best = r
        else:
            break
    return best if best is not None and t - best["t_s"] <= back else None


def _hp_at_or_after(series, t):
    for r in series:
        if r["t_s"] >= t - 1e-9:
            return r["hp"]
    return None


ENEMY_NEAR_PX = 600.0      # "within about 600 units": screen px proxy (no map units in the tables)
FRONT_NEAR_PX = 250.0      # the wave front within this distance of Garen counts as "with the wave"


def _state(tables, series, t, minions_by_tick, champs_by_tick=None, enemies_by_tick=None):
    """The runtime view keys that the tables can fill at anchor time t. Null where KEY_STATUS says so."""
    row = _at(series, t)
    if row is None:
        return None
    ms = minions_by_tick.get(row["tick"], [])
    champs = (champs_by_tick or {}).get(row["tick"], [])
    enemies = [c for c in champs if c.get("rel") == "enemy" and c.get("dist_to_subject_px") is not None]
    near = [c for c in enemies if c["dist_to_subject_px"] <= ENEMY_NEAR_PX]
    gx, gy = row.get("px"), row.get("py")
    allies_px = [m for m in ms if m["rel"] == "ally" and m.get("px") is not None]
    enemy_px = [m for m in ms if m["rel"] == "enemy" and m.get("px") is not None]
    front = None
    if allies_px and enemy_px and gx is not None:
        ax = sum(m["px"] for m in allies_px) / len(allies_px); ay = sum(m["py"] for m in allies_px) / len(allies_px)
        ex = sum(m["px"] for m in enemy_px) / len(enemy_px); ey = sum(m["py"] for m in enemy_px) / len(enemy_px)
        mx, my = (ax + ex) / 2, (ay + ey) / 2
        front = round(math.hypot(gx - mx, gy - my), 1)
    allies = [m for m in ms if m["rel"] == "ally" and m.get("px") is not None and m.get("dist_to_subject_px") is not None
              and m["dist_to_subject_px"] <= 150]
    cs_hist = [r for r in series if t - 10.0 <= r["t_s"] <= t and r.get("cs") is not None]
    dmg_hist = 0.0
    for a, b in zip(cs_hist, cs_hist[1:]):
        if a["hp"] is not None and b["hp"] is not None:
            dmg_hist += max(0.0, a["hp"] - b["hp"])
    return {
        "time": round(t, 1), "level": row.get("level"),
        "hp": f"{int(row['hp'])}/{int(row['hp_max'])}" if row.get("hp") is not None and row.get("hp_max") else None,
        "hp_frac": row.get("hp_frac"), "gold": None, "cs": row.get("cs"), "ad": row.get("ad"),
        "items": row.get("items"), "enemies": None, "ally_minions_near": len(allies),
        "turret_d": None, "turret": None,
        "map": None, "next_enemy_turret": None,
        "last10s": {"cs_gain": (cs_hist[-1]["cs"] - cs_hist[0]["cs"]) if len(cs_hist) >= 2 else 0,
                    "damage_taken": int(dmg_hist)},
        "plan": None,
        "enemy_champion_near": bool(near),
        "ready": row.get("ready"),
        "enemies": [{"name": e["name"], "px_dist": e["px_dist"]} for e in (enemies_by_tick or {}).get(row["tick"], [])] or None,
        "enemy_champion_hp_frac": min((c["hp_frac"] for c in near if c.get("hp_frac") is not None), default=None),
        "wave_front_px": front,
    }


def _window_facts(tables, series, t, window, minions_by_tick, events_by_tick, enemy_window=None):
    """Facts in (t, t + window]: HP lost (per 1 s slice from the slice's own start), CS gain, kills, recall, E use, and
    the subject's movement. Nothing here looks past t + window."""
    end = t + window
    start_hp = _at(series, t)
    slices = []
    cur = t
    while cur < end - 1e-9:
        nxt = min(cur + 1.0, end)
        a, b = _hp_at_or_after(series, cur), _hp_at_or_after(series, nxt)
        slices.append(max(0.0, a - b) if (a is not None and b is not None) else 0.0)
        cur = nxt
    dmg = sum(slices)
    cs_gain = 0
    cs_now = start_hp.get("cs") if start_hp else None
    for r in series:
        if t < r["t_s"] <= end and r.get("cs") is not None and cs_now is not None and r["cs"] > cs_now:
            cs_gain += r["cs"] - cs_now
            cs_now = r["cs"]
    evs = [e for k, evs_ in events_by_tick.items() if t < k / 10.0 <= end for e in evs_]
    last_hits = [e for e in evs if e["kind"] == "last_hit" and e.get("subject_uid")]
    kills = [e for e in evs if e["kind"] == "champion_kill" and e.get("actor_uid") == (start_hp or {}).get("champion")]
    assists = [e for e in evs if e["kind"] == "assist" and e.get("actor_uid") == (start_hp or {}).get("champion")]
    deaths = any(r.get("alive") is False for r in series if t < r["t_s"] <= end)
    recall = any(e["kind"] == "recall_or_respawn" for e in evs)
    e_cast = False
    if start_hp is not None:
        e_before = start_hp.get("cd_ready_in_s")
        for r in series:
            if t < r["t_s"] <= end and e_before is not None and r.get("cd_ready_in_s") is not None:
                if e_before[2] is None and r["cd_ready_in_s"][2] is not None:
                    e_cast = True
    moved = False
    xs = [r for r in series if t <= r["t_s"] <= end and r.get("est_x") is not None]
    speed = None
    if len(xs) >= 2 and xs[-1]["t_s"] > xs[0]["t_s"]:
        speed = math.hypot(xs[-1]["est_x"] - xs[0]["est_x"], xs[-1]["est_z"] - xs[0]["est_z"]) / (xs[-1]["t_s"] - xs[0]["t_s"])
        moved = speed * 1.0 > 40
    enemy_hp = [c["hp_frac"] for c in enemy_window if c.get("hp_frac") is not None] if enemy_window else []
    enemy_drop = (max(enemy_hp) - min(enemy_hp)) if len(enemy_hp) >= 2 else 0.0
    attack = bool(last_hits or kills or assists)
    return {"damage": dmg, "damage_slices": slices, "cs_gain": cs_gain, "last_hits": last_hits, "kills": kills,
            "assists": assists, "death": deaths, "recall": recall, "e_cast": e_cast, "moved": moved,
            "speed": speed, "attack": attack, "enemy_drop": enemy_drop,
            "max_hp": (start_hp or {}).get("hp_max")}


def _label_coach(start, f, state):
    """Coach label by fixed rules, in precedence order (manager rules, 2026-10-20). Returns (mode, confidence, rule)."""
    max_hp = f["max_hp"] or 1
    hp_frac = state["hp_frac"] if state else None
    near = bool(state and state["enemy_champion_near"])
    if f["recall"]:
        return "recall_now", 0.6, "recall_or_respawn event in window"
    if near and f["damage"] > 0 and f["enemy_drop"] >= 0.05:
        return "fight", 0.6, "enemy champion within 600 px; HP lost by Garen and by the enemy in the window"
    if hp_frac is not None and hp_frac < 0.5 and (f["damage"] >= 0.15 * max_hp or near):
        return "avoid", 0.5, "hp<50% and (>=15% max HP lost or enemy champion near)"
    if hp_frac is not None and hp_frac < 0.5 and f["damage"] > 0:
        return "freeze", 0.5, "hp<50% and damage in window"
    front = state["wave_front_px"] if state else None
    if (hp_frac is not None and hp_frac >= 0.7 and f["cs_gain"] >= 2 and f["damage"] == 0 and not near
            and front is not None and front <= FRONT_NEAR_PX):
        return "push", 0.6, "hp>=70%, >=2 CS, no damage, wave front within 250 px, no enemy champion near"
    return "farm_safe", 0.4, "default: no other rule fired"


def _label_tactician(start, f, state):
    max_hp = f["max_hp"] or 1
    near = bool(state and state["enemy_champion_near"])
    e_ready = bool(state and state.get("ready") and state["ready"].get("E") is True)
    e_minions = (state or {}).get("_n_enemy_near", 0)
    if f["e_cast"] and e_ready and e_minions >= 3:
        return "e_now", 0.6, "E cooldown starts in window; E ready at the anchor; >= 3 enemy minions near"
    if f["damage"] >= 0.10 * max_hp and near:
        return "hold_back", 0.5, ">=10% max HP lost with an enemy champion within 600 px"
    if f["speed"] is not None and f["speed"] < 20 and not f["attack"]:
        return "hold", 0.5, "speed under 20 units/s (estimate) and no attack in window"
    return "follow_plan", 0.4, "default: no other rule fired"


def _reward(f):
    """Owner's reward table over the window, per slice (already in damage_slices, so no double count)."""
    r = 0.0
    parts = {}
    lh = [e for e in f["last_hits"]]
    parts["last_hit"] = len(lh) * REWARDS["last_hit"]
    parts["champion_kill"] = len(f["kills"]) * REWARDS["champion_kill"]
    parts["assist"] = len(f["assists"]) * REWARDS["assist"]
    parts["death"] = REWARDS["death"] if f["death"] else 0.0
    parts["damage"] = REWARDS["damage_per_hp"] * f["damage"]
    r = sum(parts.values())
    return round(r, 3), {k: round(v, 3) for k, v in parts.items()}


def cut(tables, gid, t0, t1, layer):
    """Decision points for one layer ('coach' or 'tactician'). Returns rows in the Jev shape."""
    if layer == "coach":
        every, window, options, label = COACH_EVERY_S, COACH_WINDOW_S, COACH_OPTIONS, _label_coach
    else:
        every, window, options, label = TACTICIAN_EVERY_S, TACTICIAN_WINDOW_S, TACTICIAN_OPTIONS, _label_tactician
    series = _subject_series(tables)
    minions_by_tick = {}
    for m in tables["minions"]:
        minions_by_tick.setdefault(m["tick"], []).append(m)
    events_by_tick = {}
    for e in tables["events"]:
        events_by_tick.setdefault(e["tick"], []).append(e)
    champs_by_tick = {}
    for c in tables["champions"]:
        if c.get("rel") == "enemy" and not c.get("is_subject"):
            champs_by_tick.setdefault(c["tick"], []).append(c)
    rows = []
    n = 0
    t = t0
    while t <= t1 - window + 1e-9:
        state = _state(tables, series, t, minions_by_tick, champs_by_tick)
        if state is not None:
            ew = [c for k, cs_ in champs_by_tick.items() if t < k / 10.0 <= t + window for c in cs_]
            f = _window_facts(tables, series, t, window, minions_by_tick, events_by_tick, enemy_window=ew)
            mode, conf, rule = label(None, f, state)
            r, parts = _reward(f)
            n += 1
            rows.append({"dp_id": f"{gid}-{layer}{n}", "game_id": gid, "layer": layer, "tick": round(t * 10),
                         "t_s": round(t, 2), "window_s": window, "state": state,
                         "options": [{"id": o, "facts": facts} for o, facts in options],
                         "chosen": mode, "chosen_inferred": True, "label_confidence": conf, "label_rule": rule,
                         "outcome": {k: v for k, v in f.items() if k not in ("last_hits", "kills", "assists")} | {
                             "last_hit": len(f["last_hits"]), "champion_kill": len(f["kills"]),
                             "assist": len(f["assists"])},
                         "reward_parts": parts, "reward": r})
        t += every
    return rows


def summary(rows):
    by = {}
    for r in rows:
        by.setdefault(r["chosen"], {"n": 0, "reward_sum": 0.0})
        by[r["chosen"]]["n"] += 1
        by[r["chosen"]]["reward_sum"] += r["reward"]
    return {"points": len(rows), "label_mix": {k: v["n"] for k, v in by.items()},
            "chosen_in_options": all(r["chosen"] in {o["id"] for o in r["options"]} for r in rows),
            "note": "label mix only; mean reward is not reported (it is computed from the same window facts as the label, "
                    "so it is circular) and there is no accuracy here (labels are checked by hand, see hand-labels)"}

HEARTBEAT_MIN_GAP_S = 10.0   # at most one heartbeat point per 10 s (flagged trigger "heartbeat")
CLASH_PX = 120.0             # an ally and an enemy minion this close = the waves are clashing
E_NEAR_PX = 300.0            # E proxy: >= 3 enemy minions this close to Garen (ready flag is not in the tables)
E_NEAR_COUNT = 3
EVENT_TRIGGERS_BUILT = ["enemy_champion_enter_600px", "hp_cross_0.5", "hp_cross_0.3", "wave_clash_proxy",
                        "e_near_proxy_3_minions", "heartbeat_10s"]
EVENT_TRIGGERS_NOT_BUILT = {"wave_enters_turret_range": "no turret positions in the tables",
                            "recall_eligible": "gold is null in replays (spec 9)"}


def _events_on_tick(tick_state, prev, minions, t):
    """Trigger names that fire at this subject tick (rising edges only)."""
    fired = []
    st = tick_state
    if st["enemy_champion_near"] and not (prev and prev["enemy_champion_near"]):
        fired.append("enemy_champion_enter_600px")
    if prev and st.get("hp_frac") is not None and prev.get("hp_frac") is not None:
        for thr, name in ((0.5, "hp_cross_0.5"), (0.3, "hp_cross_0.3")):
            if prev["hp_frac"] > thr >= st["hp_frac"]:
                fired.append(name)
    allies = [m for m in minions if m["rel"] == "ally" and m.get("px") is not None]
    enemies = [m for m in minions if m["rel"] == "enemy" and m.get("px") is not None]
    clash = any(math.hypot(a["px"] - e["px"], a["py"] - e["py"]) <= CLASH_PX for a in allies for e in enemies)
    if clash and not (prev and prev.get("_clash")):
        fired.append("wave_clash_proxy")
    near_e = sum(1 for m in enemies if m.get("dist_to_subject_px") is not None and m["dist_to_subject_px"] <= E_NEAR_PX)
    if near_e >= E_NEAR_COUNT and not (prev and prev.get("_near_e", 0) >= E_NEAR_COUNT):
        fired.append("e_near_proxy_3_minions")
    return fired, clash, near_e


# keys that are null on every replay row (no source in the tables, spec section 9): not written to training rows.
# They remain in the runtime view; DECISIONS.md lists them so the gap is visible (review 3, fix 5).
REPLAY_NULL_KEYS = ("gold", "enemies", "turret_d", "turret", "map", "next_enemy_turret", "plan", "ready")


def _parity_state(state):
    return {k: v for k, v in state.items() if not k.startswith("_") and k not in REPLAY_NULL_KEYS}


def cut_events(tables, gid, t0, t1, enemies_by_tick=None):
    """Event-triggered decision points for both layers. A point opens on a trigger (rising edge), heartbeat fills at most
    one point per 10 s. A point is kept only when a wave or an enemy champion is on screen (else out_of_lane, dropped).
    Returns (rows, stats)."""
    series = _subject_series(tables)
    minions_by_tick, champs_by_tick, events_by_tick = {}, {}, {}
    for m in tables["minions"]:
        minions_by_tick.setdefault(m["tick"], []).append(m)
    for c in tables["champions"]:
        if c.get("rel") == "enemy" and not c.get("is_subject"):
            champs_by_tick.setdefault(c["tick"], []).append(c)
    for e in tables["events"]:
        events_by_tick.setdefault(e["tick"], []).append(e)
    rows, stats = [], {"triggers": {}, "dropped_out_of_lane": 0, "kept": 0, "heartbeats": 0}
    prev = None
    last_point_t = -1e9
    n = 0
    for row in series:
        t = row["t_s"]
        if t < t0 or t > t1:
            continue
        state = _state(tables, series, t, minions_by_tick, champs_by_tick, enemies_by_tick)
        if state is None:
            continue
        minions = minions_by_tick.get(row["tick"], [])
        fired, clash, near_e = _events_on_tick(state, prev, minions, t)
        state["_clash"], state["_near_e"], state["_n_enemy_near"] = clash, near_e, near_e
        prev = state
        if not fired and t - last_point_t >= HEARTBEAT_MIN_GAP_S and t <= t1:
            fired = ["heartbeat_10s"]
        if not fired:
            continue
        on_screen = state["wave_front_px"] is not None or state["enemy_champion_near"] or any(
            c.get("rel") == "enemy" for c in champs_by_tick.get(row["tick"], []))
        if not on_screen:
            stats["dropped_out_of_lane"] += 1
            continue
        for trig in fired:
            stats["triggers"][trig] = stats["triggers"].get(trig, 0) + 1
        if fired == ["heartbeat_10s"]:
            stats["heartbeats"] += 1
        last_point_t = t
        for layer in ("coach", "tactician"):
            if layer == "coach":
                window, options, label = COACH_WINDOW_S, COACH_OPTIONS, _label_coach
            else:
                window, options, label = TACTICIAN_WINDOW_S, TACTICIAN_OPTIONS, _label_tactician
            if t > t1 - window + 1e-9:
                continue
            ew = [c for k, cs_ in champs_by_tick.items() if t < k / 10.0 <= t + window for c in cs_]
            f = _window_facts(tables, series, t, window, minions_by_tick, events_by_tick, enemy_window=ew)
            mode, conf, rule = label(None, f, state)
            r, parts = _reward(f)
            n += 1
            stats["kept"] += 1
            rows.append({"dp_id": f"{gid}-ev-{layer}{n}", "game_id": gid, "layer": layer, "tick": round(t * 10),
                         "t_s": round(t, 2), "window_s": window, "trigger": fired,
                         "state": _parity_state(state),
                         "options": [{"id": o, "facts": facts} for o, facts in options],
                         "chosen": mode, "chosen_inferred": True, "label_confidence": conf, "label_rule": rule,
                         "outcome": {k: v for k, v in f.items() if k not in ("last_hits", "kills", "assists")} | {
                             "last_hit": len(f["last_hits"]), "champion_kill": len(f["kills"]),
                             "assist": len(f["assists"])},
                         "reward_parts": parts, "reward": r})
    stats["triggers_built"] = EVENT_TRIGGERS_BUILT
    stats["triggers_not_built"] = EVENT_TRIGGERS_NOT_BUILT
    return rows, stats
