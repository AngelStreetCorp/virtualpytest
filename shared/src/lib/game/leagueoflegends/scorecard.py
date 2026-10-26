"""TASK-131 goal 5/6: score a recorded League game, one function per area, thresholds from the reference.

Input: a timeline from ``live_recorder`` (optionally with ``zones`` from ``minimap``). Reference: the
``reference`` block of ``docs/agent/game/lol/champions/<champion>.yaml`` (every number there carries its sources). Each area
returns ``{"score": 0-100 | None, "measured": bool, "numbers": {...}, "rule": "..."}``; ``None`` means the
data to judge it was not recorded (never a guessed score). Read-only: no game input anywhere.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Dict, List, Optional

# Single source: docs/agent/game/lol/champions/<champion>.yaml (the repo's docs/ tree is rsynced to the
# Windows box with the rest of the repo, so no build-time copy is needed).
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 5, "docs", "agent", "game", "lol", "champions")
ROLE_KEYS = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "bot", "UTILITY": "support"}
AREAS = ["lane", "farm", "deaths", "health", "kills", "objectives", "items", "recalls", "cannons"]
WEIGHTS = {"lane": 1, "farm": 2, "deaths": 2, "health": 2, "kills": 1, "objectives": 1, "items": 1, "recalls": 1, "cannons": 1}


def load_reference(champion: str = "Garen", role: str = "top", path: Optional[str] = None) -> Dict[str, Any]:
    """``reference`` block of ``champions/<champion>.yaml`` for ``role`` (top, jungle, mid, bot, support)."""
    import yaml

    role = ROLE_KEYS.get(role.upper(), role.lower())
    path = path or os.path.join(KNOWLEDGE_DIR, champion.lower() + ".yaml")
    with open(path, encoding="utf-8") as f:
        roles = yaml.safe_load(f)["roles"]
    if role not in roles:
        raise KeyError(f"{champion} has no '{role}' entry in {path}; add it (see docs/agent/game/lol/README.md)")
    return roles[role]["reference"]


def reference_for(tl: Dict[str, Any]) -> Dict[str, Any]:
    m = tl["meta"]
    return load_reference(m.get("champion") or "Garen", m.get("assigned_position") or "top")


def _lin(value: float, bad: float, good: float) -> float:
    """0 at ``bad``, 100 at ``good`` (works for either direction), clamped."""
    if good == bad:
        return 100.0
    return max(0.0, min(100.0, 100.0 * (value - bad) / (good - bad)))


FLOOR_CREDIT = 40.0
TARGET_CREDIT = 80.0


def _banded(value: float, floor: float, target: float, elite: Optional[float] = None) -> float:
    """0 at nothing, FLOOR_CREDIT at the reference floor, 100 at the target (or TARGET_CREDIT at the target and
    100 at ``elite`` when the reference has one: good is not top).

    A plain 0-at-floor scale gave every run below the floor the same 0 (TASK-131 goal 7: three different
    games all scored 57.1), so the part below the floor still ranks games: a bot at 1.5 CS/min and one at
    4.6 CS/min are both under the floor but not equally bad.
    """
    if value <= 0:
        return 0.0
    if value < floor:
        return FLOOR_CREDIT * value / floor
    top = TARGET_CREDIT if elite else 100.0
    v = FLOOR_CREDIT + (top - FLOOR_CREDIT) * _lin(value, floor, target) / 100.0
    if elite and value > target:
        v = TARGET_CREDIT + (100.0 - TARGET_CREDIT) * _lin(value, target, elite) / 100.0
    return v


def _res(score: Optional[float], numbers: Dict[str, Any], rule: str) -> Dict[str, Any]:
    return {"score": None if score is None else round(score, 1), "measured": score is not None,
            "numbers": numbers, "rule": rule}


def _at(samples: List[Dict[str, Any]], t: float) -> Dict[str, Any]:
    prev = samples[0]
    for s in samples:
        if s["t"] > t:
            break
        prev = s
    return prev


def _end_time(tl: Dict[str, Any]) -> float:
    return tl["samples"][-1]["t"] if tl["samples"] else 0.0


# ---------------------------------------------------------------- areas
def cs_at(tl: Dict[str, Any], t: float) -> float:
    """CS at game second ``t``: the exact HUD counter (``tl["cs_exact"]`` = [{"t", "cs"}], read by ``cs_reader``)
    interpolated between readings when present, else the API ``creepScore`` (which only moves in steps of 10)."""
    ex = tl.get("cs_exact")
    if ex:
        if t <= ex[0]["t"]:  # CS is 0 at game second 0
            return float(ex[0]["cs"]) * max(0.0, t) / max(1e-9, ex[0]["t"])
        for a, b in zip(ex, ex[1:]):
            if t <= b["t"]:
                return a["cs"] + (b["cs"] - a["cs"]) * (t - a["t"]) / max(1e-9, b["t"] - a["t"])
        return float(ex[-1]["cs"])
    return float(_at(tl["samples"], t)["scores"]["cs"])


def score_farm(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    """CS/min per phase against the reference; weight = minutes in the phase.

    ``scores.creepScore`` from the Live Client Data API only moves in steps of 10 (seen on every recorded run), so a
    rate is known to +-10 CS over the phase; the CS value is read at the poll where the counter last changed
    and the phase start is not interpolated."""
    r = ref["cs_per_min"]
    end, num, tot_w, tot = _end_time(tl), {}, 0.0, 0.0
    for name, (a, b) in {"early": (1.0, 10), "mid": (10, 20), "late": (20, 40)}.items():
        hi = min(b, end / 60)
        if hi - a < 2 or not tl["samples"]:
            continue
        cs = cs_at(tl, hi * 60) - cs_at(tl, a * 60)
        rate = cs / (hi - a)
        num[f"cs_per_min_{name}"] = round(rate, 2)
        num["cs_source"] = "hud counter (exact)" if tl.get("cs_exact") else "creepScore (steps of 10)"
        w = hi - a
        tot += w * _banded(rate, r[name]["floor"], r[name]["target"], r[name].get("elite"))
        tot_w += w
    if not tot_w:
        return _res(None, {}, "needs >= 2 min of game after 1:00")
    return _res(tot / tot_w, num, f"CS/min per phase: 0 at no CS, {FLOOR_CREDIT:g} at the reference floor, {TARGET_CREDIT:g} at its target, 100 at the elite rate (Garen-top reference); creepScore moves in steps of 10, so the exact HUD counter is used when recorded")


def hp_drops(tl: Dict[str, Any], burst_gap_s: float = 4.0) -> List[Dict[str, Any]]:
    """Damage taken as bursts [{"t0", "t1", "dmg", "hp_before", "hp_after", "source"}] from consecutive HP drops.

    Only drops count (regeneration, potions and max-HP growth are rises, a respawn reset is skipped because either sample
    is dead). Source: ``turret`` when a turret killed us within 6 s of the burst, ``champion`` inside a recorded fight
    (``tl["fights"]``, the bot's trade log) or when ``tl["damage_sources"]`` says so, else ``minions/other`` (no enemy
    champion is needed in the lane, so minion hits and unseen turret shots land here)."""
    ss = tl.get("samples", [])
    bursts: List[Dict[str, Any]] = []
    for a, b in zip(ss, ss[1:]):
        if a["dead"] or b["dead"]:
            continue
        d = a["hp"] - b["hp"]
        if d <= 0:
            continue
        if bursts and b["t"] - bursts[-1]["t1"] <= burst_gap_s:
            bursts[-1].update(t1=b["t"], dmg=bursts[-1]["dmg"] + d, hp_after=b["hp"])
        else:
            bursts.append({"t0": a["t"], "t1": b["t"], "dmg": d, "hp_before": a["hp"], "hp_after": b["hp"], "hp_max": b["hp_max"]})
    deaths = [e for e in tl.get("events", []) if e.get("EventName") == "ChampionKill" and e.get("VictimName") in _my_names(tl)]
    for bu in bursts:
        bu["dmg"] = round(bu["dmg"], 1)
        src = "minions/other"
        if any(0 <= d["EventTime"] - bu["t1"] <= 6 and str(d.get("KillerName", "")).startswith("Turret") for d in deaths):
            src = "turret"
        elif any(f["t"] - 3 <= bu["t1"] and bu["t0"] <= f["t"] + 3 for f in tl.get("fights", [])):
            src = "champion"
        for ds in tl.get("damage_sources", []):
            if ds["t"] - 2 <= bu["t1"] and bu["t0"] <= ds["t"] + 2:
                src = ds["source"]
        bu["source"] = src
    return bursts


def score_health(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    """Health lost while farming. No enemy laner exists in Practice Tool, so the target is close to no damage taken:
    owner rule 2026-10-18 ("if he loses health, the bot did not play well"). Score = 70 % damage per minute (100 at the
    ``good`` rate, 0 at ``bad``) + 30 % time below 50 % health (100 at none, 0 at ``half_share_bad`` of the game)."""
    r = ref.get("health", {})
    ss = tl.get("samples", [])
    minutes = (_end_time(tl) - EVAL_START_S) / 60  # 1:00 onward: the first minute is preparation
    if minutes < 1.5 or len(ss) < 3:
        return _res(None, {}, "needs >= 3 min of game")
    bursts = [b for b in hp_drops(tl) if b["t1"] > EVAL_START_S]
    dmg = sum(b["dmg"] for b in bursts)
    rate = dmg / minutes
    alive = [(a, b) for a, b in zip(ss, ss[1:]) if not a["dead"] and not b["dead"] and a["hp_max"] and a["t"] >= EVAL_START_S]
    span = sum(b["t"] - a["t"] for a, b in alive) or 1.0
    below = sum(b["t"] - a["t"] for a, b in alive if a["hp"] / a["hp_max"] < 0.5)
    mean_frac = sum(a["hp"] / a["hp_max"] * (b["t"] - a["t"]) for a, b in alive) / span
    min_frac = min((s["hp"] / s["hp_max"] for s in ss if not s["dead"] and s["hp_max"] and s["t"] >= EVAL_START_S), default=1.0)
    by_src: Dict[str, float] = {}
    for b in bursts:
        by_src[b["source"]] = round(by_src.get(b["source"], 0.0) + b["dmg"], 1)
    good, bad, half_bad = r.get("dmg_per_min_good", 25.0), r.get("dmg_per_min_bad", 250.0), r.get("half_share_bad", 0.3)
    score = 0.7 * _lin(rate, bad, good) + 0.3 * _lin(below / span, half_bad, 0.0)
    return _res(score, {"damage_taken_per_min": round(rate, 1), "damage_taken": round(dmg), "mean_hp_pct": round(100 * mean_frac, 1),
                        "min_hp_pct": round(100 * min_frac, 1), "seconds_below_50pct": round(below), "damage_by_source": by_src,
                        "bursts": len(bursts)},
                f"damage taken per min from 1:00 (100 at <= {good:g}, 0 at >= {bad:g}) 70 % + time below 50 % health 30 % (provisional thresholds, owner rule: no opponent, so losing health is a mistake)")


def minion_gold(kind: str, t: float) -> float:
    """Gold of one minion killed at game second ``t`` (basics.md "Last-hit priority": wiki wave table + metabot).
    Melee 20, caster 14, cannon 59 until 14:00 rising to 66 at 25:00 and 69 from 30:00."""
    if kind == "melee":
        return 20.0
    if kind == "caster":
        return 14.0
    if kind == "minion":  # melee or caster, not told apart on screen
        return 17.0
    pts = [(840.0, 59.0), (1500.0, 66.0), (1800.0, 69.0)]
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, g0), (t1, g1) in zip(pts, pts[1:]):
        if t <= t1:
            return g0 + (g1 - g0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


MISSED_KINDS = ("cannon", "minion", "melee", "caster")


def score_cannons(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    """Minions that died near the player without the player's CS rising, weighted by their gold (cannon most).

    The Live Client Data API has no minion events, so ``tl["missed_minions"]`` = ``[{"t", "kind"}]`` has to come from
    a screen reader (a minion death beside the champion with no CS step). Without that list the area is
    "not measured", never a guessed score. Scale (provisional, calibrated on the first baseline game): 100 at no
    gold lost, 0 at ``bad_gold_per_10min`` lost per 10 minutes (default 120 = two cannons)."""
    missed = tl.get("missed_minions")
    deaths = tl.get("minion_deaths")  # [{"t", "kind", "ours"}] from minion_events.MinionWatcher
    if deaths is not None:
        missed = [d for d in deaths if not d.get("ours")]
    minutes = _end_time(tl) / 60
    if missed is None or minutes < 5:
        return _res(None, {}, "needs minion deaths from the screen reader (tl['missed_minions']) and >= 5 min of game")
    by_kind = {k: 0 for k in MISSED_KINDS}
    gold = {k: 0.0 for k in MISSED_KINDS}
    for m in missed:
        k = m.get("kind")
        if k in by_kind:
            by_kind[k] += 1
            gold[k] += minion_gold(k, m["t"])
    lost = sum(gold.values())
    bad = ref.get("cannons", {}).get("bad_gold_per_10min", 120.0)
    rate = lost / minutes * 10
    taken = {k: sum(1 for d in deaths or [] if d.get("kind") == k and d.get("ours")) for k in MISSED_KINDS}
    num: Dict[str, Any] = {}
    if deaths is not None:  # last-hit rate per type, gold-weighted overall
        for k in MISSED_KINDS:
            tot = taken[k] + by_kind[k]
            if tot:
                num[f"last_hit_rate_{k}"] = round(taken[k] / tot, 2)
        got = sum(minion_gold(d["kind"], d["t"]) for d in deaths if d.get("ours") and d.get("kind") in by_kind)
        num["last_hit_rate_gold_weighted"] = round(got / (got + lost), 2) if got + lost else None
    return _res(_lin(rate, bad, 0.0), {**num, "missed": by_kind, "gold_lost": {k: round(v) for k, v in gold.items()},
                                         "gold_lost_per_10min": round(rate, 1)},
                f"gold of minions that died near the player without a last hit (cannon ~59-69, melee 20, caster 14); 100 at 0, 0 at {bad:g} per 10 min")


def score_deaths(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    r = ref["deaths_per_10min"]
    minutes = _end_time(tl) / 60
    if minutes < 5:
        return _res(None, {}, "needs >= 5 min of game")
    deaths = [e for e in tl["events"] if e.get("EventName") == "ChampionKill" and e.get("VictimName") in _my_names(tl)]
    early = sum(1 for e in deaths if e["EventTime"] < 600)
    weighted = len(deaths) + (r["early_weight"] - 1) * early
    rate = weighted / minutes * 10
    return _res(_lin(rate, r["bad"], r["good"]),
                {"deaths": len(deaths), "deaths_before_10": early, "weighted_per_10min": round(rate, 2)},
                f"deaths per 10 min (deaths before 10:00 count x{r['early_weight']}); 100 at <= {r['good']}, 0 at >= {r['bad']}")


def _my_names(tl: Dict[str, Any]) -> set:
    p = tl["meta"]["player"]
    return {p, p.split("#")[0]}


def _team_of(tl: Dict[str, Any], name: str) -> str:
    for p in tl["players"]:
        if name in (p["name"], p["name"].split("#")[0]):
            return p["team"]
    m = re.search(r"_T(\d)00", name or "")
    if m:  # minion killers: Minion_T100L0S0
        return "ORDER" if m.group(1) == "1" else "CHAOS"
    return ""


def score_kills(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    r = ref["kills_assists_per_10min"]
    minutes = _end_time(tl) / 60
    if minutes < 5:
        return _res(None, {}, "needs >= 5 min of game")
    sc = tl["samples"][-1]["scores"]
    rate = (sc["kills"] + sc["assists"]) / minutes * 10
    return _res(_banded(rate, r["floor"], r["target"]), {"kills": sc["kills"], "assists": sc["assists"], "k_plus_a_per_10min": round(rate, 2)},
                f"kills + assists per 10 min; 0 at none, {FLOOR_CREDIT:g} at {r['floor']}, 100 at {r['target']}")


# Turret_T1_L_03_A: T1 = ORDER, T2 = CHAOS. Number -> tier is ASSUMED (03 outer, 02 inner, 01 inhibitor,
# 04/05 nexus) and is checked on the first baseline game (TASK-131 goal 7).
def turret_tier(name: str) -> str:
    m = re.match(r"Turret_T(\d)_[A-Z]_(\d\d)_", name or "")
    if not m:
        return "?"
    return {"03": "T1", "02": "T2", "01": "T3"}.get(m.group(2), "nexus")


def score_objectives(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    pts = ref["objective_points"]
    mine = _my_team(tl)
    if not mine or not any(e.get("EventName") in pts_events() for e in tl["events"]):
        return _res(None, {}, "no objective event recorded or team unknown")
    team = enemy = part = total = 0.0
    taken: List[str] = []
    for e in tl["events"]:
        n = e.get("EventName")
        if n == "TurretKilled":
            key = "turret_" + turret_tier(e.get("TurretKilled", ""))
        elif n == "InhibKilled":
            key = "inhibitor"
        elif n == "DragonKill":
            key = "dragon"
        elif n == "HeraldKill":
            key = "herald"
        elif n == "BaronKill":
            key = "baron"
        else:
            continue
        v = pts.get(key, pts["turret_nexus"] if key.startswith("turret_") else 0)
        killer_team = _team_of(tl, e.get("KillerName", ""))
        if killer_team == mine:
            team += v
            taken.append(key)
            total += v
            if _my_names(tl) & ({e.get("KillerName")} | set(e.get("Assisters") or [])):
                part += v
        elif killer_team:
            enemy += v
    score = 50.0 if team + enemy == 0 else 100.0 * team / (team + enemy)
    return _res(score, {"team_points": team, "enemy_points": enemy, "player_involved_points": part, "taken": taken,
                        "scuttle": "not measured (no event; needs minimap)"},
                "team objective points / (team + enemy points); points per type in the reference")


def pts_events() -> set:
    return {"TurretKilled", "InhibKilled", "DragonKill", "HeraldKill", "BaronKill"}


def _my_team(tl: Dict[str, Any]) -> str:
    return tl["meta"].get("team", "")


def score_items(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    r = ref["items"]
    if not tl["samples"]:
        return _res(None, {}, "no samples")
    wanted = [i.lower() for i in r["core"]]
    first: Dict[str, float] = {}
    for s in tl["samples"]:
        have = {i.lower() for i in s["items"]}
        for w in wanted:
            if w in have and w not in first:
                first[w] = s["t"]
    minutes = _end_time(tl) / 60
    due = [w for w, by in zip(wanted, r["core_by_min"]) if by <= minutes]
    if not due:
        return _res(None, {"first_seen_s": first}, "game ended before the first core item was due")
    pts = 0.0
    for w, by in zip(wanted, r["core_by_min"]):
        if by > minutes:
            continue
        if w in first:
            late = max(0.0, first[w] / 60 - by)
            pts += _lin(late, r["late_zero_min"], 0)
    return _res(pts / len(due), {"core_due": due, "first_seen_s": first},
                "each core item due by its minute: 100 on time, 0 when later by the allowed lateness, 0 if never bought")


def detect_recalls(tl: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A recall = gold drops >= 300 between two polls while alive and the item list changes (a shop visit)."""
    out, ss = [], tl["samples"]
    for a, b in zip(ss, ss[1:]):
        if a["dead"] or b["dead"]:
            continue
        if a["gold"] - b["gold"] >= 300 and a["items"] != b["items"]:
            out.append({"t": b["t"], "gold_before": a["gold"], "hp_frac": round(a["hp"] / a["hp_max"], 2) if a["hp_max"] else None})
    return out


def score_recalls(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    r = ref["recalls"]
    if _end_time(tl) < 300:
        return _res(None, {}, "needs >= 5 min of game")
    rec = detect_recalls(tl)
    scores = []
    for i, c in enumerate(rec):
        need = r["first_back_gold"] if i == 0 else r["later_back_gold"]
        s = _lin(c["gold_before"], 0, need)
        if c["hp_frac"] is not None and c["hp_frac"] >= r["full_hp_frac"] and c["gold_before"] < need:
            s *= 0.5
        scores.append(s)
    # dying while holding a lot of gold is a missed recall
    ss, rich = tl["samples"], 0
    for a, b in zip(ss, ss[1:]):
        if not a["dead"] and b["dead"] and a["gold"] >= r["death_gold_limit"]:
            rich += 1
    base = sum(scores) / len(scores) if scores else 0.0
    return _res(max(0.0, base - r["death_gold_penalty"] * rich),
                {"recalls": rec, "deaths_with_unspent_gold": rich, "wave_state": "not measured"},
                f"gold held at each recall vs {r['first_back_gold']} (first) / {r['later_back_gold']} (later); half credit if back at full health; "
                f"-{r['death_gold_penalty']} per death holding >= {r['death_gold_limit']} gold")


def score_lane(tl: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    zones = [z for z in tl.get("zones") or [] if 90 <= z["t"] <= 840]
    if len(zones) < 10:
        return _res(None, {"zone_samples": len(zones)}, "needs minimap zones between 1:30 and 14:00 (goal 4)")
    ok = ref["lane"]["ok_zones"]
    share = sum(1 for z in zones if z["zone"] in ok) / len(zones)
    return _res(_lin(share, ref["lane"]["bad_share"], ref["lane"]["good_share"]), {"share_in_lane_or_river": round(share, 3)},
                f"share of 1:30-14:00 in {ok}")


SCORERS = {"lane": score_lane, "farm": score_farm, "deaths": score_deaths, "kills": score_kills,
           "objectives": score_objectives, "items": score_items, "recalls": score_recalls, "cannons": score_cannons, "health": score_health}


EVAL_START_S = 60.0           # owner correction 2026-10-19: 0:00-1:00 is preparation (buying, walking to lane), not scored; the first wave arrives in the next half minute
LANING_END_S = 480.0          # owner scope 2026-10-19: the laning phase (first 8 minutes) is what matters
HEADLINE_T = (300.0, 480.0)   # headline numbers at 5:00 and 8:00


def window_timeline(tl: Dict[str, Any], end_s: float) -> Dict[str, Any]:
    """A copy of the timeline cut at game second ``end_s`` (samples, events, zones, CS, minion deaths, fights, ...)."""
    out = dict(tl)
    out["samples"] = [s for s in tl.get("samples", []) if s["t"] <= end_s]
    out["events"] = [e for e in tl.get("events", []) if e.get("EventTime", 0) <= end_s]
    for k in ("zones", "cs_exact", "minion_deaths", "fights", "bot_events", "lasthits", "damage_sources"):
        if k in tl:
            out[k] = [x for x in tl[k] if x.get("t", 0) <= end_s]
    return out


def headlines(tl: Dict[str, Any], ref: Dict[str, Any], attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """CS, last-hit rate, damage taken per minute, gold and recall timing at 5:00 and 8:00 (``None`` entry when the game was
    shorter). Elite target bands come from ``ref["laning_targets"]["300"|"480"]`` when the reference has them."""
    end = _end_time(tl)
    done = [a for a in (attempts if attempts is not None else tl.get("lasthits") or []) if a.get("result") is not None]
    bursts = hp_drops(tl)
    recalls = detect_recalls(tl)
    out: Dict[str, Any] = {}
    for T in HEADLINE_T:
        key = f"{int(T) // 60}:00"
        if end < T - 5:
            out[key] = None
            continue
        w = [a for a in done if EVAL_START_S <= a["t"] <= T]
        rc = [r for r in recalls if r["t"] <= T]
        cs = cs_at(tl, T)
        mins = (T - EVAL_START_S) / 60  # per-minute rates run over 1:00-T only
        out[key] = {
            "cs": round(cs, 1), "cs_per_min": round((cs - cs_at(tl, EVAL_START_S)) / mins, 2),
            "lasthit_rate": round(sum(1 for a in w if a["result"] == "hit") / len(w), 2) if w else None, "lasthit_attempts": len(w),
            "damage_per_min": round(sum(b["dmg"] for b in bursts if EVAL_START_S < b["t1"] <= T) / mins, 1),
            "gold": round(_at(tl["samples"], T)["gold"]) if tl.get("samples") else None,
            "recalls": [{"t": round(r["t"]), "gold_before": round(r["gold_before"])} for r in rc],
            "first_recall_s": round(rc[0]["t"]) if rc else None,
            "target": (ref.get("laning_targets") or {}).get(str(int(T))),
        }
    return out


def start_sequence(tl: Dict[str, Any]) -> Dict[str, Any]:
    """Pass/fail checks of the first minute (preparation), kept OUT of the score: starter items bought, camera locked on the
    champion, out of the fountain by 1:00. ``None`` = not recorded (no bot events / zones)."""
    ev = tl.get("bot_events") or []
    def _ok(kind: str) -> Optional[bool]:
        hit = [e for e in ev if e.get("kind") == kind]
        return None if not hit else all(str(e.get("detail", "")).startswith("ok") for e in hit[-1:])
    items = _ok("start_items")
    if items is None and tl.get("samples"):
        items = any(i.startswith("Doran") for s0 in tl["samples"] if s0["t"] <= EVAL_START_S for i in s0["items"])
    zones = [z for z in tl.get("zones") or [] if z["t"] <= EVAL_START_S + 30]
    left = None if not zones else any(z["t"] <= EVAL_START_S and z["zone"] != "base" for z in zones)
    checks = {"starter_items_bought": items, "camera_locked": _ok("camera_locked"), "left_fountain_by_1_00": left}
    timing = next((e["detail"] for e in ev if e.get("kind") == "start_timing"), None)
    known = [v for v in checks.values() if v is not None]
    return {"checks": checks, "pass": (all(known) if known else None), "timing": timing, "scored": False}


def laning_scorecard(tl: Dict[str, Any], ref: Optional[Dict[str, Any]] = None,
                     attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The default view: the 0:00-8:00 window scored, headline numbers at 5:00 / 8:00, the full-game score kept as secondary."""
    ref = ref or reference_for(tl)
    w = window_timeline(tl, LANING_END_S)
    card = scorecard(w, ref)
    full = scorecard(tl, ref)
    card["window"] = "1:00-8:00 (laning; 0:00-1:00 is preparation)"
    card["window_s"] = LANING_END_S
    card["headlines"] = headlines(w, ref, attempts)
    card["start_sequence"] = start_sequence(tl)  # separate pass/fail line, not part of the score
    card["full_game"] = {"overall": full["overall"], "game_minutes": full["game_minutes"],
                         "areas": {a: r["score"] for a, r in full["areas"].items()}}
    return card


def scorecard(tl: Dict[str, Any], ref: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ref = ref or reference_for(tl)
    areas = {a: SCORERS[a](tl, ref) for a in AREAS}
    m = [(WEIGHTS[a], r["score"]) for a, r in areas.items() if r["score"] is not None]
    overall = round(sum(w * s for w, s in m) / sum(w for w, _ in m), 1) if m else None
    return {"meta": tl["meta"], "game_minutes": round(_end_time(tl) / 60, 1), "overall": overall,
            "unmeasured": [a for a, r in areas.items() if r["score"] is None], "areas": areas,
            "reference_sources": ref.get("sources", [])}


def bad_moments(tl: Dict[str, Any], ref: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deaths, recalls made too poor, enemy-team objectives. ``t`` = game seconds."""
    out: List[Dict[str, Any]] = []
    mine, r = _my_team(tl), ref["recalls"]
    for e in tl["events"]:
        if e.get("EventName") == "ChampionKill" and e.get("VictimName") in _my_names(tl):
            out.append({"t": e["EventTime"], "kind": "death", "detail": f"killed by {e.get('KillerName', '?')}"})
        elif e.get("EventName") in pts_events() and mine:
            kt = _team_of(tl, e.get("KillerName", ""))
            if kt and kt != mine:
                out.append({"t": e["EventTime"], "kind": "objective lost", "detail": e["EventName"]})
    for i, c in enumerate(detect_recalls(tl)):
        need = r["first_back_gold"] if i == 0 else r["later_back_gold"]
        if c["gold_before"] < need:
            out.append({"t": c["t"], "kind": "late/poor recall", "detail": f"went home with {int(c['gold_before'])} gold (< {need})"})
    ss = tl["samples"]
    for a, b in zip(ss, ss[1:]):
        if not a["dead"] and b["dead"] and a["gold"] >= r["death_gold_limit"]:
            out.append({"t": b["t"], "kind": "death with unspent gold", "detail": f"{int(a['gold'])} gold"})
    return sorted(out, key=lambda m: m["t"])


def video_link(video_url: Optional[str], t: float, video_offset_s: float = 0.0) -> Optional[str]:
    """Deep link into the game video: ``#t=<seconds>`` (media fragment). ``video_offset_s`` = video time of game 0:00."""
    return None if not video_url else f"{video_url}#t={max(0, int(t + video_offset_s))}"


def compare(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Runs side by side: overall and every area score per run."""
    return {"runs": [c["meta"].get("recorded_at", str(i)) for i, c in enumerate(cards)],
            "overall": [c["overall"] for c in cards],
            "areas": {a: [(c["areas"].get(a) or {}).get("score") for c in cards] for a in AREAS}}


def _fmt_input(i: Dict[str, Any]) -> str:
    where = f" @{i['x']:.2f},{i['y']:.2f}" if "x" in i else ""
    return f"{i['kind']} {i.get('key') or i.get('text') or ''}{where}".replace("  ", " ").strip()


def turns_section(turns: List[Dict[str, Any]], video_url: Optional[str] = None, video_offset_s: float = 0.0) -> str:
    """The per-turn log (turns.jsonl) as a table: state, decision, inputs sent, zone summary. Empty string when there are no turns."""
    if not turns:
        return ""
    rows = []
    for tn in turns:
        s, d = tn["state"], tn["decision"]
        z = d.get("zones") or {}
        link = video_link(video_url, tn["t"], video_offset_s)
        tm = f"{int(tn['t']) // 60}:{tn['t'] % 60:04.1f}"
        opts = ", ".join(f"{o['id']} {o['p']:.2f}" for o in d.get("options", [])[:4])
        tcell = f'<a href="{html.escape(link)}">{tm}</a>' if link else tm
        zcell = ("IN " + html.escape(", ".join(z.get("standing_in") or []))) if z.get("standing_in") else "clear"
        rows.append(
            f'<tr id="turn-{tn["turn"]}"><td>{tn["turn"]}</td><td>{tcell}</td>'
            f"<td>hp {s['hp']}/{s['hp_max']} L{s['level']} {s['gold']}g cs {s['cs']} ad {s['ad']} ar {s['armor']} mr {s['mr']} {html.escape(str(s['mode']))}</td>"
            f"<td><b>{html.escape(d['choice'])}</b> ({html.escape(opts)})<br>{html.escape(d['reason'])}</td>"
            f"<td>{html.escape('; '.join(_fmt_input(i) for i in tn['inputs']))}</td>"
            f"<td>{zcell}; {z.get('n_danger', 0)} danger, {z.get('n_safe', 0)} safe</td></tr>")
    return (f"<h2>Turns ({len(turns)})</h2><p>One row per bot tick: what the bot saw, what it chose, every input it sent, and the "
            f"danger zones at that moment. Raw data: turns.jsonl, zones.jsonl.</p><details><summary>show turns</summary>"
            f"<table><tr><th>#</th><th>time</th><th>state</th><th>decision</th><th>inputs</th><th>zones</th></tr>{''.join(rows)}</table></details>")


def write_report(card: Dict[str, Any], ref: Dict[str, Any], json_path: str, html_path: Optional[str] = None,
                 moments: Optional[List[Dict[str, Any]]] = None, video_url: Optional[str] = None,
                 video_offset_s: float = 0.0, others: Optional[List[Dict[str, Any]]] = None,
                 turns: Optional[List[Dict[str, Any]]] = None, reward_summary: Optional[Dict[str, Any]] = None) -> None:
    card = dict(card, bad_moments=[dict(m, video=video_link(video_url, m["t"], video_offset_s)) for m in moments or []])
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=1)
    if not html_path:
        return
    rows = "".join(
        f"<tr><td>{a}</td><td>{'not measured' if r['score'] is None else r['score']}</td>"
        f"<td><code>{html.escape(json.dumps(r['numbers']))}</code></td><td>{html.escape(r['rule'])}</td></tr>"
        for a, r in card["areas"].items())
    def _clock(t: float) -> str:
        return f"{int(t) // 60}:{int(t) % 60:02d}"

    turn_ts = [t["t"] for t in turns or []]

    def _fmt(v: Any) -> str:
        return "-" if v is None else str(v)

    def _target_text(t: Dict[str, Any]) -> str:
        cs = t.get("cs")
        rng = f"{cs[0]}-{cs[1]}" if isinstance(cs, (list, tuple)) and len(cs) == 2 else str(cs)
        return f"elite {rng}" + (f" (n={t['n']}{', provisional' if t.get('provisional') else ''})" if t.get("n") else "")

    hl_rows = ""
    for key, h in (card.get("headlines") or {}).items():
        if h is None:
            hl_rows += f"<tr><td>{key}</td><td colspan=7>game ended earlier</td></tr>"
            continue
        tgt = h.get("target") or {}
        rc = ", ".join(f"{_clock(r['t'])} ({r['gold_before']} g)" for r in h["recalls"]) or "none"
        hl_rows += (f"<tr><td>{key}</td><td>{h['cs']} ({h['cs_per_min']}/min)" + (f" <small>{html.escape(_target_text(tgt))}</small>" if tgt.get("cs") else "")
                    + f"</td><td>{_fmt(h['lasthit_rate'])} ({h['lasthit_attempts']} tries)</td><td>{h['damage_per_min']}</td><td>{_fmt(h['gold'])}"
                    + (f" <small>elite {tgt['gold'][0]}-{tgt['gold'][1]}</small>" if isinstance(tgt.get("gold"), list) else "") + "</td><td>{html.escape(rc)}</td></tr>")
    hl_html = ("<h2>Laning headlines</h2><table><tr><th>at</th><th>CS</th><th>last-hit rate</th><th>damage taken/min</th><th>gold</th><th>recalls</th></tr>"
               + hl_rows + "</table>") if hl_rows else ""
    ss_ = card.get("start_sequence")
    if ss_:
        mark = lambda v: "n/a" if v is None else ("pass" if v else "FAIL")  # noqa: E731
        hl_html += ("<h2>Start sequence (0:00-1:00, not scored)</h2><p>" + f"<b>{mark(ss_['pass'])}</b> - "
                    + ", ".join(f"{k.replace('_', ' ')}: {mark(v)}" for k, v in ss_["checks"].items())
                    + (f" <small>{html.escape(str(ss_['timing']))}</small>" if ss_.get("timing") else "") + "</p>")
    fg = card.get("full_game")
    fg_html = (f"<p>Full game ({fg['game_minutes']} min), secondary: overall {fg['overall']}</p>") if fg else ""

    def _turn_anchor(t: float) -> str:
        if not turn_ts:
            return ""
        i = min(range(len(turn_ts)), key=lambda k: abs(turn_ts[k] - t))
        return f" <a href=\"#turn-{turns[i]['turn']}\">turn {turns[i]['turn']}</a>"  # type: ignore[index]

    def _bm_row(m: Dict[str, Any]) -> str:
        tcell = f'<a href="{html.escape(m["video"])}">{_clock(m["t"])}</a>' if m["video"] else _clock(m["t"])
        return f"<tr><td>{tcell}</td><td>{html.escape(m['kind'])}</td><td>{html.escape(m['detail'])}{_turn_anchor(m['t'])}</td></tr>"

    bm = "".join(_bm_row(m) for m in card["bad_moments"])
    cmp_html = ""
    if others:
        c = compare(others + [card])
        head = "".join(f"<th>{html.escape(str(r))}</th>" for r in c["runs"])
        body = f"<tr><td>overall</td>{''.join('<td>%s</td>' % v for v in c['overall'])}</tr>" + "".join(
            f"<tr><td>{a}</td>{''.join('<td>%s</td>' % ('-' if v is None else v) for v in vs)}</tr>" for a, vs in c["areas"].items())
        cmp_html = f"<h2>Runs side by side</h2><table><tr><th></th>{head}</tr>{body}</table>"
    turns_html = turns_section(turns or [], video_url, video_offset_s)
    if reward_summary:  # per-action reward table (outcomes.finalize -> reward_summary.json), full game
        from .outcomes import reward_html

        turns_html += reward_html(reward_summary)
    refs = "".join(f"<li>{html.escape(str(s))}</li>" for s in card["reference_sources"])
    doc = (f"<!doctype html><meta charset=utf-8><title>LoL scorecard</title><style>body{{font:14px system-ui;margin:2em}}"
           f"td,th{{border:1px solid #888;padding:4px 8px;vertical-align:top}}table{{border-collapse:collapse}}</style>"
           f"<h1>{html.escape(card['meta'].get('champion', ''))} - {card.get('window') or str(card['game_minutes']) + ' min'} - overall {card['overall']}</h1>"
           f"{hl_html}{fg_html}"
           f"<table><tr><th>area</th><th>score</th><th>numbers</th><th>rule</th></tr>{rows}</table>"
           f"<h2>Bad moments</h2><table><tr><th>time</th><th>what</th><th>detail</th></tr>{bm}</table>{cmp_html}{turns_html}"
           f"<h2>Garen-top reference</h2><pre>{html.escape(json.dumps(ref, indent=1))}</pre><h2>Sources</h2><ul>{refs}</ul>")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(doc)
