"""TASK-135: outcome and reward layer over the per-turn log (turns.jsonl). Pure: it reads turn dicts and returns them annotated.

Each action of a turn is linked to what happened after it (last-hit, kills, death, damage taken, a missed last-hit, idling next to a
killable minion) with an attribution window; every outcome is ``{event, value, t, cause_turn, cause_action, confidence}``. Every turn
gets ``reward`` (the outcomes it caused) and ``return_8s`` (discounted sum over the next 8 s). Also the per-action table, Jev-ready
decision rows (``decisions.jsonl``, the ``ai_decisions`` shape: state, options with facts, chosen, outcome) and empirical priors per
(situation bucket, action). Works on bot turns and, with the same dict shape, on elite replay rows. Shape: OVERLAY_CONTRACT.md.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

# Owner values (2026-10-19), the one place to change them.
REWARDS: Dict[str, float] = {
    "last_hit": 1.0, "last_hit_cannon": 2.0, "champion_kill": 10.0, "assist": 3.0, "turret_kill": 12.0, "death": -10.0,
    "damage_per_hp": -0.01, "missed_last_hit": -0.5, "idle_killable_per_tick": -0.2,
}
LAST_HIT_WINDOW_S = 0.6  # our auto / Q to the exact CS +1
LAST_HIT_WIDE_S = 1.5  # a longer window, lower confidence
KILL_WINDOW_S = 10.0  # our damage to a champion to its death
DEATH_WINDOW_S = 5.0
RETURN_LOOKAHEAD_S = 8.0
GAMMA_PER_S = 0.9
MISS_HP_FRAC = 0.25  # a minion this low that vanishes while we did not hit counts as a missed last-hit
EST_MINION_HP = 500.0  # melee estimate when no exact health is read
CHAMP_REACH_PX = 600
ACTION_CLASS = {"attack": "auto", "select": "select", "cast_Q": "Q", "cast_W": "W", "cast_E": "E", "cast_R": "R", "move": "move",
                "move_minimap": "move", "hold": "idle", "recall": "recall", "shop": "shop", "levelup": "levelup"}
HIT_ACTIONS = ("auto", "Q")


def action_of(turn: Dict[str, Any]) -> str:
    """Action class of a turn. A right click on an enemy unit is an auto even when the bot labelled it a move."""
    ch = str((turn.get("decision") or {}).get("choice") or "hold")
    cls = ACTION_CLASS.get(ch, "other")
    if cls == "move":
        foes = [u for u in (turn.get("world") or {}).get("units") or [] if str(u.get("kind", "")).startswith("enemy_") and u.get("kind") != "enemy_turret"]
        for i in turn.get("inputs") or []:
            if i.get("kind") == "right_click" and any(abs(i["x"] - u["x"]) <= 0.03 and abs(i["y"] - u["y"]) <= 0.05 for u in foes):
                return "auto"
    return cls


def _world(t: Dict[str, Any]) -> Dict[str, Any]:
    return t.get("world") or {}


def _units(t: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [u for u in _world(t).get("units") or [] if u.get("kind") == kind]


def _minion_hp(u: Dict[str, Any]) -> float:
    return float(u["hp_exact"]) if u.get("hp_exact") else float(u.get("hp_frac") or 0) * float(u.get("hp_max") or EST_MINION_HP)


def hits_to_kill(t: Dict[str, Any]) -> Optional[int]:
    """Autos needed for the weakest enemy minion in attack range (None = none in range)."""
    ad = float((t.get("state") or {}).get("ad") or 0)
    inr = [u for u in _units(t, "enemy_minion") if u.get("in_attack_range")]
    if not inr or ad <= 0:
        return None
    low = min(inr, key=_minion_hp)
    return max(1, int(-(-_minion_hp(low) // ad)))


def _out(event: str, value: float, t: float, cause: int, action: str, conf: float, **extra: Any) -> Dict[str, Any]:
    return dict({"event": event, "value": round(value, 3), "t": round(t, 1), "cause_turn": cause, "cause_action": action,
                 "confidence": round(conf, 2)}, **extra)


def attribute(turns: List[Dict[str, Any]], rewards: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Return all outcomes of the run, each pointing at the turn that caused it. Does not modify ``turns``."""
    R = rewards or REWARDS
    outs: List[Dict[str, Any]] = []
    n = len(turns)
    acts = [action_of(t) for t in turns]
    idx_by_turn = {t["turn"]: i for i, t in enumerate(turns)}
    for i, t in enumerate(turns):
        nxt = turns[i + 1] if i + 1 < n else None
        st = t.get("state") or {}
        # last-hit: exact CS rose since the previous turn
        if i and st.get("cs") is not None and (turns[i - 1].get("state") or {}).get("cs") is not None:
            gained = st["cs"] - turns[i - 1]["state"]["cs"]
            if 0 < gained < 10:  # API-step jumps of 10 are not last-hits
                k = next((k for k in range(i, -1, -1) if t["t"] - turns[k]["t"] <= LAST_HIT_WIDE_S and acts[k] in HIT_ACTIONS), -1)
                prev = turns[i - 1]
                low = min(_units(prev, "enemy_minion"), key=lambda u: u.get("hp_frac", 1), default=None)
                cannon = bool(low and low.get("type") == "cannon")
                val = (R["last_hit_cannon"] if cannon else R["last_hit"]) * gained
                if k >= 0:
                    conf = 0.9 if t["t"] - turns[k]["t"] <= LAST_HIT_WINDOW_S else 0.5
                    outs.append(_out("last_hit", val, t["t"], turns[k]["turn"], acts[k], conf, cs=gained))
                else:
                    outs.append(_out("last_hit", val, t["t"], t["turn"], "unknown", 0.2, cs=gained))
        # kills, assists, turret kills, death from the Live Client events logged on the turn
        for ev in t.get("events") or []:
            kind = ev.get("kind")
            if kind in ("champion_kill", "assist"):
                dmg = [k for k in range(i, -1, -1) if t["t"] - turns[k]["t"] <= KILL_WINDOW_S and acts[k] in HIT_ACTIONS + ("E", "W", "R")
                       and any(u.get("dist_px", 9999) <= CHAMP_REACH_PX for u in _units(turns[k], "enemy_champion"))]
                val = R["champion_kill" if kind == "champion_kill" else "assist"]
                if dmg:
                    outs.append(_out(kind, val * 0.7, t["t"], turns[dmg[0]]["turn"], acts[dmg[0]], 0.8))  # the last damaging action
                    rest = dmg[1:]
                    for k in rest:
                        outs.append(_out(kind, val * 0.3 / len(rest), t["t"], turns[k]["turn"], acts[k], 0.5))
                else:
                    outs.append(_out(kind, val, t["t"], t["turn"], acts[i], 0.2))
            elif kind == "turret_kill":
                hit = next((k for k in range(i, -1, -1) if t["t"] - turns[k]["t"] <= KILL_WINDOW_S and acts[k] in HIT_ACTIONS), i)
                outs.append(_out("turret_kill", R["turret_kill"], t["t"], turns[hit]["turn"], acts[hit], 0.6 if hit != i else 0.3))
            elif kind == "death":
                zone = [k for k in range(i, -1, -1) if t["t"] - turns[k]["t"] <= DEATH_WINDOW_S
                        and ((turns[k].get("decision") or {}).get("zones") or {}).get("standing_in")]
                cause = zone or [i]
                for k in cause:
                    outs.append(_out("death", R["death"] / len(cause), t["t"], turns[k]["turn"], acts[k], 0.7 if zone else 0.2,
                                     zones=((turns[k].get("decision") or {}).get("zones") or {}).get("standing_in")))
        # damage taken after this turn's action, against the zone we stood in
        if nxt is not None and st.get("hp") is not None and (nxt.get("state") or {}).get("hp") is not None:
            drop = st["hp"] - nxt["state"]["hp"]
            if drop > 0 and not any(e.get("kind") == "death" for e in nxt.get("events") or []):
                outs.append(_out("damage_taken", drop * R["damage_per_hp"], nxt["t"], t["turn"], acts[i], 0.6, hp=drop,
                                 zones=((t.get("decision") or {}).get("zones") or {}).get("standing_in")))
            # a weak minion in range that vanished while we did not hit it (and CS did not rise)
            if (nxt.get("state") or {}).get("cs") == st.get("cs") and acts[i] not in HIT_ACTIONS:
                gone = [u for u in _units(t, "enemy_minion") if u.get("in_attack_range") and u.get("hp_frac", 1) <= MISS_HP_FRAC
                        and not any(abs(v.get("x", 9) - u["x"]) < 0.04 and abs(v.get("y", 9) - u["y"]) < 0.06 for v in _units(nxt, "enemy_minion"))]
                if gone:
                    outs.append(_out("missed_last_hit", R["missed_last_hit"], t["t"], t["turn"], acts[i], 0.5))
        htk = hits_to_kill(t)
        if acts[i] == "idle" and htk == 1:
            outs.append(_out("idle_killable", R["idle_killable_per_tick"], t["t"], t["turn"], "idle", 0.9))
    for o in outs:
        o["_i"] = idx_by_turn.get(o["cause_turn"], 0)
    return outs


def annotate(turns: List[Dict[str, Any]], rewards: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """New turn dicts with ``outcomes``, ``reward`` and ``return_8s`` added (previous values replaced)."""
    outs = attribute(turns, rewards)
    res: List[Dict[str, Any]] = []
    by_i: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for o in outs:
        by_i[o["_i"]].append({k: v for k, v in o.items() if k != "_i"})
    for i, t in enumerate(turns):
        o = dict(t)
        o["outcomes"] = by_i.get(i, [])
        o["reward"] = round(sum(x["value"] for x in o["outcomes"]), 3)
        res.append(o)
    for i, t in enumerate(res):
        ret, j = 0.0, i
        while j < len(res) and res[j]["t"] - t["t"] <= RETURN_LOOKAHEAD_S:
            ret += res[j]["reward"] * (GAMMA_PER_S ** (res[j]["t"] - t["t"]))
            j += 1
        t["return_8s"] = round(ret, 3)
    return res


def action_table(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Annotated turns -> per action class: count, total / mean reward, useless rate (no outcome at all); plus totals."""
    rows: Dict[str, Dict[str, Any]] = {}
    for t in turns:
        r = rows.setdefault(action_of(t), {"n": 0, "reward": 0.0, "useless": 0, "return_8s": 0.0})
        r["n"] += 1
        r["reward"] += t.get("reward", 0.0)
        r["return_8s"] += t.get("return_8s", 0.0)
        r["useless"] += 0 if t.get("outcomes") else 1
    for r in rows.values():
        r["mean_reward"] = round(r["reward"] / r["n"], 4)
        r["mean_return_8s"] = round(r["return_8s"] / r["n"], 4)
        r["useless_rate"] = round(r["useless"] / r["n"], 3)
        r["reward"] = round(r["reward"], 2)
        del r["return_8s"]
    events: Dict[str, Dict[str, float]] = defaultdict(lambda: {"n": 0, "value": 0.0})
    for t in turns:
        for o in t.get("outcomes") or []:
            e = events[o["event"]]
            e["n"] += 1
            e["value"] = round(e["value"] + o["value"], 3)
    acted = [t for t in turns if action_of(t) != "idle"]
    return {"actions": rows, "events": dict(events), "total_reward": round(sum(t.get("reward", 0.0) for t in turns), 2),
            "turns": len(turns), "useless_action_rate": round(sum(1 for t in acted if not t.get("outcomes")) / len(acted), 3) if acted else None}


# --- Jev-ready decision rows -------------------------------------------------------------------------------------------------
def options_of(t: Dict[str, Any]) -> List[Dict[str, str]]:
    """The legal actions at this moment, each ``{"id", "facts"}`` (the ``decisions.choose`` option format)."""
    st, w = t.get("state") or {}, _world(t)
    sp = st.get("spells") or {}
    auto = sp.get("auto") or {}
    ready = (auto.get("next_auto_in_s") or 0) <= 0.05
    opts: List[Dict[str, str]] = []
    inr = [u for u in _units(t, "enemy_minion") if u.get("in_attack_range")]
    if inr:
        low = min(inr, key=_minion_hp)
        htk = hits_to_kill(t)
        hp = f"{round(low['hp_exact'])} hp" if low.get("hp_exact") else f"{round(low['hp_frac'] * 100)} % hp"
        opts.append({"id": "auto", "facts": f"last-hit {low.get('type') or ''} minion, {hp}, in range, {htk} auto(s) to kill, auto {'ready' if ready else 'in %.1f s' % (auto.get('next_auto_in_s') or 0)}".replace("  ", " ")})
    champ = [u for u in _units(t, "enemy_champion") if u.get("in_attack_range")]
    if champ and "auto" not in {o["id"] for o in opts}:
        opts.append({"id": "auto", "facts": f"attack enemy champion at {round(champ[0]['hp_frac'] * 100)} % hp, in range"})
    for k in ("Q", "W", "E", "R"):
        e = sp.get(k) or {}
        if e.get("rank", 0) >= 1 and e.get("ready_in_s") == 0.0:
            opts.append({"id": k, "facts": f"{k} ready, cooldown {e.get('cooldown_s')} s"})
    zones = ((t.get("decision") or {}).get("zones") or {}).get("standing_in") or []
    opts.append({"id": "move", "facts": f"move; standing in {len(zones)} zone(s)" + (": " + ",".join(zones) if zones else "")})
    opts.append({"id": "idle", "facts": "hold position"})
    return opts


def state_summary(t: Dict[str, Any]) -> Dict[str, Any]:
    st = t.get("state") or {}
    sm = _world(t).get("summary") or {}
    return {"t": t.get("t"), "hp": st.get("hp"), "hp_max": st.get("hp_max"), "level": st.get("level"), "cs": st.get("cs"), "mode": st.get("mode"),
            "counts": sm.get("counts"), "within_500_units": sm.get("within_500_units"), "reach": sm.get("lowest_hp_enemy_minion_reach"),
            "standing_in": ((t.get("decision") or {}).get("zones") or {}).get("standing_in"),
            "spells": {k: {"ready_in_s": v.get("ready_in_s")} for k, v in (st.get("spells") or {}).items() if k != "auto"},
            "next_auto_in_s": ((st.get("spells") or {}).get("auto") or {}).get("next_auto_in_s")}


def decision_rows(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One ``ai_decisions``-shaped row per turn (annotated turns in): state, options, chosen, outcome."""
    rows = []
    for t in turns:
        rows.append({"turn": t.get("turn"), "t": t.get("t"), "state": state_summary(t), "options": options_of(t), "chosen": action_of(t),
                     "outcome": {"reward": t.get("reward"), "return_8s": t.get("return_8s"),
                                 "events": [o["event"] for o in t.get("outcomes") or []]}})
    return rows


# --- priors ------------------------------------------------------------------------------------------------------------------
def bucket_of(t: Dict[str, Any]) -> str:
    htk = hits_to_kill(t)
    h = "none_in_range" if htk is None else "1_hit" if htk == 1 else "2_3_hits" if htk <= 3 else "4plus_hits"
    auto = ((t.get("state") or {}).get("spells") or {}).get("auto") or {}
    ready = "auto_ready" if (auto.get("next_auto_in_s") or 0) <= 0.05 else "auto_wait"
    zone = "in_zone" if (((t.get("decision") or {}).get("zones") or {}).get("standing_in")) else "no_zone"
    return f"minion={h}|{ready}|{zone}"


def priors(runs: Iterable[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Empirical priors from annotated runs: per bucket and action the count, mean reward, mean 8 s return and P(success) (the share
    of those turns with a positive outcome)."""
    acc: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "reward": 0.0, "ret": 0.0, "ok": 0}))
    for turns in runs:
        for t in turns:
            a = acc[bucket_of(t)][action_of(t)]
            a["n"] += 1
            a["reward"] += t.get("reward", 0.0)
            a["ret"] += t.get("return_8s", 0.0)
            a["ok"] += 1 if any(o["value"] > 0 for o in t.get("outcomes") or []) else 0
    return {b: {act: {"n": int(v["n"]), "mean_reward": round(v["reward"] / v["n"], 4), "mean_return_8s": round(v["ret"] / v["n"], 4),
                      "p_success": round(v["ok"] / v["n"], 3)} for act, v in sorted(acts.items())} for b, acts in sorted(acc.items())}


# --- run folder ---------------------------------------------------------------------------------------------------------------
def finalize(run_dir: str) -> Optional[Dict[str, Any]]:
    """Annotate ``turns.jsonl`` of a run folder in place and write ``outcomes.jsonl``, ``decisions.jsonl`` and ``reward_summary.json``.
    Safe to run again. Returns the summary (None when there are no turns)."""
    path = os.path.join(run_dir, "turns.jsonl")
    if not os.path.exists(path):
        return None
    turns: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            try:
                turns.append(json.loads(ln))
            except ValueError:
                pass  # a truncated last line
    if not turns:
        return None
    ann = annotate(turns)
    summary = action_table(ann)
    summary["rewards"] = REWARDS
    for name, rows in (("turns.jsonl", ann), ("decisions.jsonl", decision_rows(ann)),
                       ("outcomes.jsonl", [dict(o, ) for t in ann for o in t["outcomes"]])):
        tmp = os.path.join(run_dir, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        os.replace(tmp, os.path.join(run_dir, name))
    with open(os.path.join(run_dir, "reward_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary


def reward_html(summary: Dict[str, Any]) -> str:
    """A small HTML block for the scorecard: totals, the per-action table, the event table."""
    rows = "".join(f"<tr><td>{a}</td><td>{r['n']}</td><td>{r['reward']}</td><td>{r['mean_reward']}</td><td>{r['mean_return_8s']}</td>"
                   f"<td>{round(r['useless_rate'] * 100)} %</td></tr>" for a, r in sorted(summary["actions"].items()))
    ev = "".join(f"<tr><td>{e}</td><td>{v['n']}</td><td>{v['value']}</td></tr>" for e, v in sorted(summary["events"].items()))
    return (f"<section id=\"reward\"><h2>Reward</h2><p>Total {summary['total_reward']} over {summary['turns']} turns; useless action rate "
            f"{summary['useless_action_rate']}.</p><table><tr><th>action</th><th>n</th><th>reward</th><th>mean</th><th>mean 8 s return</th>"
            f"<th>useless</th></tr>{rows}</table><table><tr><th>event</th><th>n</th><th>value</th></tr>{ev}</table></section>")
