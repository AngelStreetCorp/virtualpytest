"""TASK-134 round 2: the rule bot plays, a model (or Jev, or both) coaches.

Round 1 gave the model the 1-second reflexes and it lost to the rule bot. Here the rule bot (:mod:`garen_bot`, newest main) does every
tick: last-hits, moves, turret safety, the recall -> shop -> return trip. The coach only sets a *strategy*, asynchronously (a slow call never
stalls a tick; the last plan stays until a new one arrives):

* ``haiku-coach``: ``claude-haiku-5-5`` answers a schema-constrained strategy every ``STRATEGIST_EVERY_S`` or on an event.
* ``jev-coach``: Jev (``typesafe/jev-1.13``) picks the strategy from typed options every ``JEV_COACH_EVERY_S`` (state, options with facts,
  calibrated probabilities).
* ``duo``: Haiku = strategist (plan + one sentence of intent), Jev = tactician every ``TACTICIAN_EVERY_S`` choosing among the tactics the
  plan allows; the rule bot = hands.

How a strategy reaches the hands without editing ``garen_bot``: ``avoid`` opens the rule bot's own retreat window, ``recall_now`` starts its
own recall state, ``push`` / ``freeze`` move its last-hit margin (``LH_MARGIN``) for that tick, the tactician can hold, step back or cast E.
The turret safety, the camera lock, the shop trip and the input guard stay the rule bot's. Every decision of every layer is logged
(``decisions.jsonl``; Jev rows also to ``jev_decisions.jsonl`` in the shape of ``ai_decisions`` rows with the outcome: HP lost and CS gained in the next 3 s).
"""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.request
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from . import garen_bot
from .garen_bot import Action, Mem, State
from .llm_policy import LlmBot, _RULE_DECIDE, build_view

STRATEGIST_EVERY_S = 10.0
JEV_COACH_EVERY_S = 5.0
TACTICIAN_EVERY_S = 3.0
OUTCOME_WINDOW_S = 3.0
PUSH_MARGIN, FREEZE_MARGIN = 1.35, 0.90  # LH_MARGIN while the plan is push / freeze (the rule bot's default is 1.0)
HOLD_S = 1.5
STEP_BACK_S = 3.0

STRATEGY_FACTS = {
    "farm_safe": "Default: the rule bot last-hits everything it can kill and stays out of danger.",
    "push": "Hit minions earlier than the exact kill so the wave pushes toward the enemy: when no enemy champion is near and health is high.",
    "freeze": "Only take sure kills, keep the wave near our side: when health is low, the enemy laner is near or the turret is close.",
    "fight": "Allow trades with the enemy laner when their health is below ours; the rule bot's engage rule.",
    "avoid": "Stay out of reach of the enemy laner for a few seconds: when health is under 50 % or the enemy is stronger.",
    "recall_now": "Go home and buy: only when no enemy is near and gold covers an item (800+) or health is under 35 %.",
}
TACTIC_FACTS = {
    "follow_plan": "Let the rule bot execute the current plan as it is.",
    "hold_back": "Step back toward the safe point for 3 s: the enemy laner or the turret is a threat right now.",
    "hold": "Do nothing for 1.5 s: wait for a minion to come into last-hit range instead of chasing it.",
    "e_now": "Spin (E) now: three or more enemy minions are within reach and E is ready.",
}
ITEMS = [n for n, _ in garen_bot.BUILD]

COACH_SYSTEM = """You coach a Garen top-lane bot in League of Legends (Practice Tool, bots as opponents, 5 game minutes). A rule bot already does every reflex: it last-hits with exact damage math, takes the cannon first, avoids the enemy turret, recalls and shops. You only choose the strategy for the next ~10 seconds. Answer with one JSON object: {"mode": ..., "recall_now": bool, "buy": <item or null>, "reason": <at most 12 words>}.
Modes: farm_safe (default), push (hit minions early to push the wave; only with high health and no enemy champion near), freeze (only sure kills; when health is low, the enemy laner is near or the turret is close), fight (allow trades when the enemy laner has less health than you), avoid (stay away from the enemy laner when your health is under 50 % or they are stronger).
recall_now = true only when no enemy is near and gold is 800+ or health is under 35 %. buy = the next item to buy from """ + ", ".join(ITEMS) + """, or null.
The view has your health, gold, CS, the enemy rows (health fraction, distance), allied minions near, the turret facts, and the last 10 s (cs_gain, damage_taken). Health lost with no opponent means you played badly: prefer safety when damage_taken is high."""


def _post(url: str, payload: Dict[str, Any], timeout: float = 25.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - local relay
        out = json.loads(r.read())
    out["wall_ms"] = int((time.monotonic() - t0) * 1000)
    return out


class CoachBot(LlmBot):
    """``kind``: ``haiku-coach`` | ``jev-coach`` | ``duo``. The rule bot is the hands in every case."""

    def __init__(self, *args: Any, kind: str = "haiku-coach", relay: Optional[str] = None, model_id: str = "claude-haiku-5-5", **kw: Any) -> None:
        super().__init__(*args, model=kind, client=object(), **kw)  # LlmBot's loop, watcher, logs and camera lock; its lane policy is not used
        import os

        self.kind, self.model_id = kind, model_id
        self.relay = relay or os.environ.get("LLM_RELAY_URL") or "http://127.0.0.1:8787"
        self._lane_reached = True  # the rule bot walks and plays the lane in every round-2 contestant
        self.plan: Dict[str, Any] = {"mode": "farm_safe", "recall_now": False, "buy": None, "reason": "start", "set_t": 0.0}
        self.tactic: Dict[str, Any] = {"id": "follow_plan", "until": 0.0}
        self.lock = threading.Lock()
        self.inflight: Dict[str, bool] = {"strategist": False, "tactician": False}
        self.last_call: Dict[str, float] = {"strategist": -99.0, "tactician": -99.0}
        self.hist: Deque[Tuple[float, Optional[int], float]] = deque(maxlen=64)  # (t, cs, hp)
        self.pending_outcomes: List[Dict[str, Any]] = []
        self.jev_rows: List[Dict[str, Any]] = []
        self.plan_changes = 0
        self._was_dead = False
        self._last_hp_frac = 1.0

    # --- the tick ---------------------------------------------------------------------------------------------------
    def _recent(self, now: float) -> Dict[str, Any]:
        old = next(((t, cs, hp) for t, cs, hp in self.hist if now - t <= 10.0), None)
        cur = self.hist[-1] if self.hist else None
        if not old or not cur:
            return {"cs_gain": 0, "damage_taken": 0}
        dmg = sum(max(0.0, a[2] - b[2]) for a, b in zip(self.hist, list(self.hist)[1:]) if now - a[0] <= 10.0)
        return {"cs_gain": (cur[1] or 0) - (old[1] or 0), "damage_taken": int(dmg)}

    def _state_view(self, s: State) -> Dict[str, Any]:
        cs, ad = self._facts()
        view, _ = build_view(s, cs, ad, {})
        view["enemies"] = view["enemies"][:6]
        view["last10s"] = self._recent(s.t)
        view["plan"] = {k: self.plan.get(k) for k in ("mode", "reason")}
        return view

    def _coach_decide(self, s: State, m: Mem) -> List[Action]:
        cs, _ = self._facts()
        self.hist.append((s.t, cs, s.hp))
        if hasattr(m, "hp_hist"):
            m.hp_hist = [(t, h) for t, h in m.hp_hist if s.t - t <= 2.0] + [(s.t, s.hp)]
        self._close_outcomes(s, cs)
        if not s.dead:
            self._maybe_ask(s)
        self._was_dead = s.dead
        acts: List[Action] = []
        with self.lock:
            plan, tactic = dict(self.plan), dict(self.tactic)
        # tactician: hold = do nothing for a moment (the rule bot's state is untouched)
        if tactic["id"] == "hold" and s.t < tactic["until"] and m.mode == "LANE" and not s.dead:
            return []
        if tactic["id"] == "hold_back" and s.t < tactic["until"] and m.mode == "LANE" and not s.dead:
            m.retreat_until = max(getattr(m, "retreat_until", -99.0), tactic["until"])
        if plan["mode"] == "avoid" and m.mode == "LANE" and not s.dead:
            champ_near = any(b.kind == "champion" for b in s.enemies)
            if champ_near:
                m.retreat_until = max(getattr(m, "retreat_until", -99.0), s.t + garen_bot.RETREAT_S)
        # stance -> hands: freeze and avoid mean "get out of the exchange": when health is draining (12 % of max in the last 10 s) or under 60 %,
        # the rule bot's own retreat window opens (hcoach-1 died to minions while Haiku had already said freeze; freeze alone only moved the last-hit margin)
        if plan["mode"] in ("freeze", "avoid") and m.mode == "LANE" and not s.dead:
            drain = self._recent(s.t)["damage_taken"] / max(s.max_hp, 1)
            if drain >= 0.12 or s.hp / max(s.max_hp, 1) < 0.6:
                m.retreat_until = max(getattr(m, "retreat_until", -99.0), s.t + garen_bot.RETREAT_S)
        if plan["recall_now"] and m.mode == "LANE" and not s.dead:
            champs = any(b.kind == "champion" for b in s.enemies)
            gap_ok = s.t - getattr(m, "last_recall_t", -999.0) >= 60.0
            if s.game_t > 45 and gap_ok and not champs and (s.gold >= getattr(garen_bot, "SHOP_MIN_GOLD", 300) or s.hp / max(s.max_hp, 1) < 0.35):
                with self.lock:
                    self.plan["recall_now"] = False
                m.mode, m.mode_since = "RECALL", s.t
                if hasattr(m, "last_recall_t"):
                    m.last_recall_t = s.t
                if hasattr(m, "recalls"):
                    m.recalls += 1
                return [("recall",)]
        margin = {"push": PUSH_MARGIN, "freeze": FREEZE_MARGIN}.get(plan["mode"])
        old_margin = garen_bot.LH_MARGIN
        if margin is not None and m.mode == "LANE":
            garen_bot.LH_MARGIN = margin
        try:
            acts = _RULE_DECIDE(s, m)
        finally:
            garen_bot.LH_MARGIN = old_margin
        if tactic["id"] == "e_now" and s.t < tactic["until"] and m.mode == "LANE" and not s.dead and s.t - self.cd.get("e", -99.0) >= 6.0:
            self.cd["e"] = s.t
            acts = acts + [("key", "E")]
        return acts

    # --- asking the coach ---------------------------------------------------------------------------------------------
    def _events(self, s: State) -> bool:
        hp_frac = s.hp / max(s.max_hp, 1)
        hit = hp_frac < 0.5 <= self._last_hp_frac or self._last_hp_frac - hp_frac >= 0.05
        died = s.dead and not self._was_dead
        self._last_hp_frac = hp_frac
        return bool(hit or died)

    def _maybe_ask(self, s: State) -> None:
        event = self._events(s)
        every = {"haiku-coach": STRATEGIST_EVERY_S, "duo": 12.0, "jev-coach": JEV_COACH_EVERY_S}[self.kind]
        layer = "tactician" if self.kind == "jev-coach" else "strategist"  # jev-coach's single layer is Jev choosing the strategy
        if not self.inflight[layer] and (s.t - self.last_call[layer] >= every or (event and s.t - self.last_call[layer] >= 3.0)):
            self.inflight[layer] = True
            self.last_call[layer] = s.t
            view = self._state_view(s)
            threading.Thread(target=self._ask, args=(layer, view, s.game_t, s.t), daemon=True).start()
        if self.kind == "duo" and not self.inflight["tactician"] and s.t - self.last_call["tactician"] >= TACTICIAN_EVERY_S:
            self.inflight["tactician"] = True
            self.last_call["tactician"] = s.t
            threading.Thread(target=self._ask, args=("tactician", self._state_view(s), s.game_t, s.t), daemon=True).start()

    def _ask(self, layer: str, view: Dict[str, Any], game_t: float, t_wall: float) -> None:
        rec: Dict[str, Any] = {"game_t": round(game_t, 1), "layer": layer, "view": view}
        try:
            if self.kind == "haiku-coach" or (self.kind == "duo" and layer == "strategist"):
                out = _post(self.relay + "/decide", {"model": self.model_id, "schema": "coach", "system": COACH_SYSTEM,
                                                     "user": json.dumps(view, separators=(",", ":"))})
                text = out.get("text", "")
                from .llm_policy import pick_json

                obj = pick_json(text)
                rec.update({k: out.get(k) for k in ("wall_ms", "api_ms", "in_tokens", "out_tokens", "cost_usd")})
                if obj is None or obj.get("mode") not in STRATEGY_FACTS:
                    rec["note"] = "unparseable reply"
                else:
                    rec["choice"] = obj
                    self._set_plan(obj, game_t)
            elif self.kind == "jev-coach":
                options = [{"id": k, "facts": v} for k, v in STRATEGY_FACTS.items()]
                out = _post(self.relay + "/jev", {"state": view, "options": options, "instructions": "Which strategy should the rule bot follow for the next few seconds?"})
                rec.update({k: out.get(k) for k in ("wall_ms", "api_ms", "in_tokens", "out_tokens", "cost_usd")})
                ch = out.get("choice")
                if ch not in STRATEGY_FACTS:
                    rec["note"] = "no valid choice"
                else:
                    rec["choice"] = {"mode": ch, "confidence": out.get("confidence"), "probabilities": out.get("probabilities")}
                    self._set_plan({"mode": "farm_safe" if ch == "recall_now" else ch, "recall_now": ch == "recall_now", "buy": None, "reason": "jev"}, game_t)
                self._jev_row(view, options, out, t_wall)
            else:  # duo tactician: Jev picks among the tactics the plan allows
                mode = self.plan.get("mode")
                ids = ["follow_plan", "hold_back", "hold"] + (["e_now"] if mode != "freeze" else [])
                options = [{"id": i, "facts": TACTIC_FACTS[i]} for i in ids]
                out = _post(self.relay + "/jev", {"state": view, "options": options, "instructions": "Which tactic for the next 1-3 seconds, given the plan?"})
                rec.update({k: out.get(k) for k in ("wall_ms", "api_ms", "in_tokens", "out_tokens", "cost_usd")})
                ch = out.get("choice")
                if ch in ids:
                    hold = {"hold_back": STEP_BACK_S, "hold": HOLD_S, "e_now": 1.0, "follow_plan": 0.0}[ch]
                    with self.lock:
                        self.tactic = {"id": ch, "until": t_wall + hold}
                    rec["choice"] = {"tactic": ch, "confidence": out.get("confidence")}
                else:
                    rec["note"] = "no valid choice"
                self._jev_row(view, options, out, t_wall)
        except Exception as e:  # noqa: BLE001 - a failed call leaves the last plan in place
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            self.decisions.append(rec)
            self.inflight[layer] = False

    def _set_plan(self, obj: Dict[str, Any], game_t: float) -> None:
        with self.lock:
            changed = obj.get("mode") != self.plan.get("mode")
            self.plan = {"mode": obj["mode"], "recall_now": bool(obj.get("recall_now")), "buy": obj.get("buy"),
                         "reason": str(obj.get("reason", ""))[:80], "set_t": game_t}
            self.plan_changes += int(changed)

    # --- Jev rows with outcomes (ai_decisions shape) ------------------------------------------------------------------
    def _jev_row(self, view: Dict[str, Any], options: List[Dict[str, Any]], out: Dict[str, Any], t_wall: float) -> None:
        cs, _ = self._facts()
        hp = self.hist[-1][2] if self.hist else 0.0
        row = {"usage": "text.decision", "model": out.get("model") or "typesafe/jev-1.13", "state": view, "options": options,
               "choice": out.get("choice"), "confidence": out.get("confidence"), "probabilities": out.get("probabilities"),
               "cost": out.get("cost_usd"), "ms": out.get("api_ms"), "tokens": [out.get("in_tokens"), out.get("out_tokens")],
               "refs": {"game": "lol", "layer": "tactician" if self.kind == "duo" else "coach", "contestant": self.kind}, "outcome": None}
        self.jev_rows.append(row)
        self.pending_outcomes.append({"row": row, "t": t_wall, "cs": cs or 0, "hp": hp, "dmg": 0.0, "last_hp": hp})

    def _close_outcomes(self, s: State, cs: Optional[int]) -> None:
        keep = []
        for p in self.pending_outcomes:
            p["dmg"] += max(0.0, p["last_hp"] - s.hp)
            p["last_hp"] = s.hp
            if s.t - p["t"] >= OUTCOME_WINDOW_S:
                p["row"]["outcome"] = {"window_s": OUTCOME_WINDOW_S, "hp_lost": round(p["dmg"], 1), "cs_gained": (cs or 0) - p["cs"]}
            else:
                keep.append(p)
        self.pending_outcomes = keep

    # --- loop hooks ---------------------------------------------------------------------------------------------------
    def step(self) -> Optional[State]:
        real = garen_bot.decide
        garen_bot.decide = self._coach_decide
        try:
            s = super(LlmBot, self).step()  # GarenBot.step with the coach's decide
        finally:
            garen_bot.decide = real
        if s is not None:
            self._gt, self._gt_wall = s.game_t, time.monotonic()
        return s

    def summary(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"model": self.kind, "harness": "r2b",  # r2 = stance map v1 (freeze only moved the last-hit margin); r2b = freeze / avoid also open the retreat window when health drains
                            "plan_changes": self.plan_changes}
        for layer in ("strategist", "tactician"):
            ds = [d for d in self.decisions if d.get("layer") == layer and d.get("wall_ms") is not None]
            lat = sorted(d["wall_ms"] for d in ds)
            out[f"{layer}_calls"] = len([d for d in self.decisions if d.get("layer") == layer])
            out[f"{layer}_errors"] = len([d for d in self.decisions if d.get("layer") == layer and d.get("error")])
            out[f"{layer}_p50_ms"] = lat[len(lat) // 2] if lat else None
            out[f"{layer}_cost_usd"] = round(sum(d.get("cost_usd") or 0.0 for d in ds), 5)
        out["cost_usd"] = round(out["strategist_cost_usd"] + out["tactician_cost_usd"], 5)
        out["parse_failures"] = sum(1 for d in self.decisions if d.get("note") in ("unparseable reply", "no valid choice"))
        out["turret_vetoes"] = 0  # the rule bot's own safety is the turret guard in every round-2 contestant
        calls = [d for d in self.decisions if d.get("wall_ms") is not None]
        lat = sorted(d["wall_ms"] for d in calls)
        out["latency_p50_ms"] = lat[len(lat) // 2] if lat else None
        out["latency_p95_ms"] = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None
        out["decisions"] = len(self.decisions)
        return out

    def save(self) -> None:
        super().save()
        if self.log_dir and self.jev_rows:
            import os

            with open(os.path.join(self.log_dir, "jev_decisions.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(r) for r in self.jev_rows))
