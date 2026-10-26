"""TASK-134: a model-driven Garen controller that plugs into the same loop as the rule bot (:mod:`garen_bot`).

Only the *lane decision* is the model's. Everything else stays scripted and identical for every contestant: the game start
(items, camera lock, walk to lane), the recall -> shop -> return state machine (``garen_bot.decide`` for any mode but LANE),
skill level-ups, the camera re-lock, the input guard, cooldown guards and the stop time.

Every ~1-2 s the model gets one compact JSON view (health, gold, level, items, CS, game time, nearby minion / champion /
turret bars from :mod:`perception`, minimap zone, ability readiness) and replies with ONE JSON action from ``ACTIONS``.
The call goes to ``llm_relay.py`` (``LLM_RELAY_URL``): the API key never leaves the machine that runs the relay.
"""

from __future__ import annotations

import copy
import io
import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

import math

from . import garen_bot
from .lane_map import FENCE, too_close
from .garen_bot import Action, GarenBot, Mem, State
from .perception import PLAYER_XY, Bar

_RULE_DECIDE = garen_bot.decide  # the rule bot's own decide; garen_bot.decide is swapped while a model plays
ACTIONS = ("last_hit", "attack", "q", "e", "r", "move_lane", "retreat", "recall", "wait")
HARNESS = "h3"  # h3 = schema-constrained reply (no unparseable replies) + turret veto with the minimap fence; earlier games are "old harness"
STOP_AT_S = 300.0  # 5 game minutes
SELF_RANGE_PX = 210  # Garen auto-attack range on screen
Q_CD, E_CD, R_CD = 8.0, 6.0, 3.0  # cooldown guards (a cast inside them is dropped and logged)
RECALL_MIN_GAP_S = 60.0
MAX_MINIONS = 8
LANE_RADIUS = 0.10  # minimap distance (0..1) from the lane farm spot at which the scripted walk ends
LANE_BY_S = 110.0  # game second after which the model plays regardless (first wave meets at ~1:30)

SYSTEM_PROMPT = """You play Garen (top lane, melee) in a League of Legends Practice Tool game against bots. Your goal for the next 5 game minutes: maximise CS (last-hit enemy minions), earn gold, stay alive, buy items.
Each turn you get a JSON view of the game and answer with ONE JSON object, nothing else: {"a": <action>, "t": <target id or null>}.
Actions:
- last_hit: auto-attack target t (an enemy minion id like "m2") now. Do it when its hp (fraction of ~480 max health early on, ~300 for casters) times that is at or below your attack damage "ad": only the killing blow gives CS.
- attack: auto-attack target t (minion, champion "c1" or turret "t1").
- q: cast Q (empty-minion-kill boost, 8 s cooldown) then attack t if given. e: spin (radius ~325 px, 6 s cooldown). r: Demacian Justice on champion t (level 6+; executes when low).
- move_lane: walk to the lane farm spot. retreat: walk to the safe spot by your inner turret.
- recall: go home and buy items (takes ~9 s; only when safe, gold >= 300 or health < 35%).
- wait: do nothing this turn.
Minion "type" is "cannon" (60 gold) or "other" (melee or caster: the bar cannot tell them apart). Owner rule when several minions can be last-hit: take the cannon first, then melee (soldier) minions, then casters, because of the gold each gives (each minion row has "type" and "gold"). A cannon is worth three casters: do not skip it for a nearer caster.\nHow to play each turn, in this order:
1. Enemy champion near and your health under 40%: retreat. "next_enemy_turret.map_dist" under "unsafe_below" (minimap units) means you are too close to the next enemy turret even when its bar is not on screen: retreat. If "turret" is not null you are inside an enemy turret's range ("range" px): unless "allied_minions_inside" >= "min_allies" (3) retreat now. A hard safety rule overrides any other action there and walks you out, so diving only wastes time.
2. Enemy minions in view: NEVER move_lane. A minion is killable when its hp (fraction) times ~480 (cannon ~900, casters ~300) is at or below "ad". If a killable one has d <= 210: last_hit it (cannon first, then melee, then casters). If a killable one is farther: attack it (you walk to it and hit it). If none is killable yet: attack the lowest-hp minion within d <= 210 to bring it down, or wait for the wave to come to you; if all minions are farther than 210, attack the nearest one to close in.
3. Cast e when 3+ minions are within d <= 210 and ready.e is true; q right before a last_hit on a cannon or a nearly killed target t (it boosts damage), r on a champion t at level 6+ when its hp is low.
4. No enemies in view at all: move_lane. Gold >= 800 and nothing near: recall (it also buys items).
Do not let more than ~4 s pass without acting. Never explain."""


def pick_json(text: str) -> Optional[Dict[str, Any]]:
    """First JSON object in the model's reply, or None."""
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(text[i : j + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _clock(gt: float) -> str:
    return f"{int(gt) // 60}:{int(gt) % 60:02d}"


# Gold per minion kill comes from the cited table in docs/agent/game/lol/basics.md ("Last-hit priority and minion gold"), the one
# source (owner rule 2026-10-18: cannon first, then melee, then casters). Perception contract: a minion Bar may carry
# ``minion_type`` in MINION_GOLD; without it the type is "other" (melee or caster, no gold shown).
BASICS_MD = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "docs", "agent", "game", "lol", "basics.md")


def load_minion_gold(path: str = BASICS_MD) -> Dict[str, int]:
    """cannon / melee / caster gold read from the table in basics.md (first number of the Gold cell; a range takes its top)."""
    import re

    text = open(path, encoding="utf-8").read()
    start = text.index("## Last-hit priority and minion gold")  # other tables in the doc have Melee / Caster rows too
    text = text[start : text.find("\n## ", start + 5) if text.find("\n## ", start + 5) > 0 else len(text)]
    out: Dict[str, int] = {}
    for key, label in (("cannon", "Cannon"), ("melee", "Melee"), ("caster", "Caster")):
        m = re.search(rf"^\|\s*{label}[^|]*\|\s*(?:about\s*)?(\d+)(?:-(\d+))?", text, re.M)
        if not m:
            raise ValueError(f"{label} gold row not found in {path}")
        out[key] = int(m.group(2) or m.group(1))
    return out


MINION_GOLD = load_minion_gold()


def _target_row(b: Bar, tid: str) -> Dict[str, Any]:
    bx, by = b.body
    dx, dy = bx - PLAYER_XY[0], by - PLAYER_XY[1]
    row: Dict[str, Any] = {"id": tid, "kind": b.kind, "hp": round(b.frac, 2), "dx": int(dx), "dy": int(dy), "d": int((dx * dx + dy * dy) ** 0.5)}
    if b.kind == "minion":
        mt = getattr(b, "minion_type", None)
        row["type"], row["gold"] = (mt, MINION_GOLD[mt]) if mt in MINION_GOLD else ("other", None)  # perception only tells a cannon (wider bar); melee and caster look alike
    return row


def turret_facts(s: State) -> Optional[Dict[str, Any]]:
    """The nearest enemy turret in range of Garen, its range in px and the allied minions inside it (None when none is in range)."""
    px, py = PLAYER_XY
    rng = getattr(garen_bot, "TURRET_RANGE_PX", 800)
    near = [b for b in s.enemies if b.kind == "turret" and ((b.x - px) ** 2 + (b.y + 90 - py) ** 2) ** 0.5 <= rng]
    if not near:
        return None
    t = near[0]
    tx, ty = t.x, t.y + 90
    inside = sum(1 for b in s.allies if b.kind == "minion" and ((b.x - tx) ** 2 + (b.body[1] - ty) ** 2) ** 0.5 <= rng)
    return {"d": int(((tx - px) ** 2 + (ty - py) ** 2) ** 0.5), "range": rng, "allied_minions_inside": inside,
            "min_allies": getattr(garen_bot, "TURRET_MIN_ALLIES", 3)}


def build_view(s: State, cs: Optional[int], ad: float, cds: Dict[str, float], zone: str = "") -> Tuple[Dict[str, Any], Dict[str, Bar]]:
    """The compact state the model sees plus the id -> bar table used to resolve its target."""
    targets: Dict[str, Bar] = {}
    rows: List[Dict[str, Any]] = []
    minions = sorted((b for b in s.enemies if b.kind == "minion"), key=lambda b: _target_row(b, "")["d"])[:MAX_MINIONS]
    for n, b in enumerate(minions, 1):
        targets[f"m{n}"] = b
        rows.append(_target_row(b, f"m{n}"))
    for n, b in enumerate((b for b in s.enemies if b.kind == "champion"), 1):
        targets[f"c{n}"] = b
        rows.append(_target_row(b, f"c{n}"))
    turret_d = None
    for n, b in enumerate((b for b in s.enemies if b.kind == "turret"), 1):
        targets[f"t{n}"] = b
        r = _target_row(b, f"t{n}")
        rows.append(r)
        turret_d = r["d"] if turret_d is None else min(turret_d, r["d"])
    ally_min = [b for b in s.allies if b.kind == "minion"]
    fence = turret_facts(s)
    view: Dict[str, Any] = {
        "time": _clock(s.game_t), "level": s.level, "hp": f"{int(s.hp)}/{int(s.max_hp)}", "gold": int(s.gold), "cs": cs,
        "ad": round(ad), "items": s.items, "enemies": rows, "ally_minions_near": len(ally_min),
        "ready": {k: (cds.get(k, -99.0) <= 0.0) for k in ("q", "e")} | {"r": s.level >= 6 and cds.get("r", -99.0) <= 0.0},
        "turret_d": turret_d, "turret": fence,
        "map": {"x": round(s.pos[0], 2), "y": round(s.pos[1], 2), "zone": zone} if s.pos else None,
        "next_enemy_turret": ({"map_dist": round(math.dist(s.pos, s.fence_turret), 3), "unsafe_below": FENCE}
                              if s.pos and getattr(s, "fence_turret", None) else None),
    }
    return view, targets


def choice_to_actions(choice: Dict[str, Any], targets: Dict[str, Bar], s: State, m: Mem, now: float, cd: Dict[str, float]) -> Tuple[List[Action], str]:
    """Map the model's choice to input actions. Returns (actions, note); the note is "" when accepted, else why not."""
    a = str(choice.get("a", "")).lower()
    bar = targets.get(str(choice.get("t"))) if choice.get("t") else None
    if a not in ACTIONS:
        return [], f"unknown action {a!r}"
    if a == "wait":
        return [], ""
    if a == "move_lane":
        return [("minimap",) + tuple(getattr(s, "farm_px", garen_bot.MINI_LANE_FARM))], ""
    if a == "retreat":
        return [("minimap",) + tuple(getattr(s, "safe_px", garen_bot.MINI_SAFE))], ""
    if a == "recall":
        gap_ok = now - getattr(m, "last_recall_t", -999.0) >= RECALL_MIN_GAP_S
        if s.game_t > 45 and gap_ok and (s.gold >= getattr(garen_bot, "SHOP_MIN_GOLD", 300) or s.hp / max(s.max_hp, 1) < 0.35):
            m.mode, m.mode_since = "RECALL", s.t
            if hasattr(m, "last_recall_t"):
                m.last_recall_t = now
            if hasattr(m, "recalls"):
                m.recalls += 1
            return [("recall",)], ""
        return [], "recall rejected (too early, too soon, or nothing to buy)"
    acts: List[Action] = []
    if a in ("q", "e", "r"):
        key = a.upper()
        if a == "r" and s.level < 6:
            return [], "R before level 6"
        limit = {"q": Q_CD, "e": E_CD, "r": R_CD}[a]
        if now - cd.get(a, -99.0) < limit:
            return [], f"{key} on cooldown"
        cd[a] = now
        if a == "r" and bar is not None:
            acts.append(("right", *bar.body))
        acts.append(("key", key))
        if a == "q" and bar is not None:
            acts.append(("right", *bar.body))
        return acts, ""
    if bar is None:
        return [], f"{a} needs a valid target id"
    return [("right", *bar.body)], ""


class LlmClient:
    """POSTs one decision to the relay (``llm_relay.py``) and returns (text, meta)."""

    def __init__(self, model: str, url: Optional[str] = None, timeout: float = 20.0) -> None:
        self.model, self.timeout = model, timeout
        self.url = (url or os.environ.get("LLM_RELAY_URL") or "http://127.0.0.1:8787") + "/decide"

    def decide(self, system: str, user: str, image_b64: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        body = json.dumps({"model": self.model, "system": system, "user": user, "image_b64": image_b64}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"content-type": "application/json"})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - local relay
            out = json.loads(r.read())
        out["wall_ms"] = int((time.monotonic() - t0) * 1000)
        return out.get("text", ""), out


class LlmBot(GarenBot):
    """:class:`GarenBot` whose lane decision comes from a model. ``model == "rule"`` keeps the rule bot (baseline contestant)."""

    def __init__(self, *args: Any, model: Optional[str] = None, client: Optional[Any] = None, log_dir: Optional[str] = None,
                 stop_at_s: float = STOP_AT_S, image: Optional[bool] = None, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.model = model or os.environ.get("LLM_MODEL", "rule")
        self.client = client or (None if self.model == "rule" else LlmClient(self.model))
        self.stop_at_s = stop_at_s
        self.image = bool(int(os.environ.get("LLM_IMAGE", "0"))) if image is None else image
        self.log_dir = log_dir or os.environ.get("LLM_LOG_DIR")
        self.decisions: List[Dict[str, Any]] = []
        self.vetoes = 0
        self.inputs: List[Dict[str, Any]] = []
        self._pos: Any = None
        self.cd: Dict[str, float] = {}
        self._gt = 0.0
        self._data: Optional[Dict[str, Any]] = None
        self._img: Any = None
        self._lane_reached, self.lane_reached_t = self.model == "rule", None  # the rule contestant is the rule bot throughout
        self.watcher: Any = None  # MinionWatcher: minion deaths for the scorecard, sampled by its own thread (>= 2 Hz) for every contestant
        self._gt_wall = time.monotonic()
        self._orig_fetch, self._orig_shot = self.fetch, self.screenshot
        self.fetch = self._fetch
        self.screenshot = self._shot

    def _fetch(self) -> Optional[Dict[str, Any]]:
        self._data = self._orig_fetch()
        return self._data

    def _shot(self) -> Any:
        self._img = self._orig_shot()
        try:  # our minimap position at the time of the next input, for the click log (passive)
            from .perception import view_box_position

            self._pos = view_box_position(self._img) if self._img is not None else None
        except Exception:  # noqa: BLE001
            pass
        return self._img

    def execute(self, a: Action, level: int) -> None:
        """Passive input log (inputs.jsonl): every action with the game time and our minimap position, same for every contestant."""
        self.inputs.append({"t": round(self._gt + (time.monotonic() - self._gt_wall), 1), "a": list(a[:3]), "pos": self._pos})
        super().execute(a, level)

    # --- the decision -------------------------------------------------------------------------------------------
    def _facts(self) -> Tuple[Optional[int], float]:
        d = self._data or {}
        ap = d.get("activePlayer") or {}
        ad = float((ap.get("championStats") or {}).get("attackDamage", 0.0))
        names = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
        me = next((p for p in d.get("allPlayers") or [] if p.get("riotId") in names or p.get("summonerName") in names), {})
        cs = (me.get("scores") or {}).get("creepScore")
        return (int(cs) if cs is not None else None), ad

    def _image_b64(self) -> Optional[str]:
        if not self.image or self._img is None:
            return None
        import base64

        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(self._img).resize((768, 480)).save(buf, "JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()

    def _in_lane(self, s: State) -> bool:
        """True once Garen is at the lane farm spot on the minimap (or the game is old enough that the wave has met)."""
        if s.game_t >= LANE_BY_S:
            return True
        if s.pos is None:
            return False
        from .perception import MINIMAP_RECT

        fx, fy = getattr(s, "farm_px", garen_bot.MINI_LANE_FARM)
        tx, ty = (fx / 1920 - MINIMAP_RECT[0]) / (MINIMAP_RECT[2] - MINIMAP_RECT[0]), (fy / 1200 - MINIMAP_RECT[1]) / (MINIMAP_RECT[3] - MINIMAP_RECT[1])
        return ((s.pos[0] - tx) ** 2 + (s.pos[1] - ty) ** 2) ** 0.5 <= LANE_RADIUS

    def _turret_veto(self, s: State, m: Mem, view: Dict[str, Any], intended: str) -> Optional[str]:
        """Shared hard veto (manager 2026-10-18), the rule bot's own fence: inside an enemy turret's range with fewer than 3 allied
        minions there, or being hit by it, Garen walks to the safe point for 5 s whatever the model wants. Only a retreat/wait passes."""
        f = view.get("turret")
        hist = getattr(m, "hp_hist", [])
        hp_drop = (max(h for _, h in hist) - s.hp) / s.max_hp if hist and s.max_hp else 0.0
        champs_near = any(r["kind"] == "champion" and r["d"] <= garen_bot.CHAMP_RANGE_PX for r in view.get("enemies", []))
        on_us = bool(f) and not champs_near and hp_drop >= getattr(garen_bot, "HP_DROP_FRAC", 0.06)
        past_fence = too_close(s.pos, getattr(s, "fence_turret", None))  # the rule bot's minimap backstop: the turret bar is often not on screen
        if (f and (f["allied_minions_inside"] < f["min_allies"] or on_us)) or past_fence:
            m.retreat_until = s.t + getattr(garen_bot, "RETREAT_S", 5.0)
        if s.t >= getattr(m, "retreat_until", -99.0):
            return None
        if intended in ("retreat", "wait", "recall"):
            return None
        return "turret hit us" if on_us else "inside turret range without 3 allied minions" if f else "past the lane fence" if past_fence else "retreat window"

    def _scripted(self, s: State, m: Mem) -> Optional[List[Action]]:
        """Anything the rule bot's own state machine owns: the walk to lane, dead, shop trip, camera re-lock. None = the model decides."""
        if not self._lane_reached and not s.dead and m.mode == "LANE":
            if self._in_lane(s):
                self._lane_reached = True
                self.lane_reached_t = round(s.game_t, 1)
            else:
                return _RULE_DECIDE(s, m)  # the rule bot walks to lane (identical for every contestant)
        if s.dead or m.mode != "LANE":
            return _RULE_DECIDE(s, m)
        probe = _RULE_DECIDE(s, copy.deepcopy(m))  # a copy: the rule bot's lane choice is thrown away
        if probe == [("key", "Y")]:
            return _RULE_DECIDE(s, m)
        return None

    def _llm_decide(self, s: State, m: Mem) -> List[Action]:
        if hasattr(m, "hp_hist"):  # the rule bot's recall watchdog reads it; its decide only updates it when it runs for real
            m.hp_hist = [(t, h) for t, h in m.hp_hist if s.t - t <= 2.0] + [(s.t, s.hp)]
        scripted = self._scripted(s, m)
        if scripted is not None:
            return scripted
        acts: List[Action] = []
        if s.t - m.last_levelup_t >= 6.0:
            m.last_levelup_t = s.t
            acts.append(("levelup",))
        cs, ad = self._facts()
        cds = {k: self.cd.get(k, -99.0) + {"q": Q_CD, "e": E_CD, "r": R_CD}[k] - s.t for k in ("q", "e", "r")}
        view, targets = build_view(s, cs, ad, cds)
        rec: Dict[str, Any] = {"game_t": round(s.game_t, 1), "gold": int(s.gold), "cs": cs, "view": view}
        try:
            text, meta = self.client.decide(SYSTEM_PROMPT, json.dumps(view, separators=(",", ":")), self._image_b64())
            rec.update({k: meta.get(k) for k in ("wall_ms", "api_ms", "in_tokens", "out_tokens", "cache_read", "cost_usd", "stop")})
            choice = pick_json(text)
            rec["reply"] = text[:200]
            if choice is None:
                rec["note"] = "unparseable reply"
            else:
                new, note = choice_to_actions(choice, targets, s, m, s.t, self.cd)
                rec["choice"], rec["note"] = choice, note
                veto = self._turret_veto(s, m, view, str(choice.get("a")))
                if veto is not None:
                    rec["turret_veto"] = {"intended": choice, "why": veto}
                    self.vetoes += 1
                    new = [("minimap",) + tuple(getattr(s, "safe_px", garen_bot.MINI_SAFE))]
                acts += new
        except Exception as e:  # noqa: BLE001 - a failed call is a wait; the anti-idle rule keeps the bot moving
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        if "choice" not in rec:  # no usable reply: the veto still holds Garen out of the turret
            if self._turret_veto(s, m, view, "none") is not None:
                acts.append(("minimap",) + tuple(getattr(s, "safe_px", garen_bot.MINI_SAFE)))
        self.decisions.append(rec)
        return acts

    def lock_camera(self) -> bool:
        """The shared lock sometimes fails (Y toggles; 2 of 9 recent starts). Retry with focus; if it still fails the game is invalid."""
        if super().lock_camera():
            return True
        for _ in range(3):
            try:
                self.gi.focus_game()
            except Exception:  # noqa: BLE001
                pass
            if super().lock_camera():
                return True
        raise RuntimeError("camera lock failed after retries: invalid benchmark game, restart it")

    # --- loop hooks ---------------------------------------------------------------------------------------------
    def step(self) -> Optional[State]:
        if self.model == "rule":
            s = super().step()
        else:
            real = garen_bot.decide
            garen_bot.decide = self._llm_decide
            try:
                s = super().step()
            finally:
                garen_bot.decide = real
        if s is not None:
            self._gt, self._gt_wall = s.game_t, time.monotonic()
        return s

    def _watch_loop(self, stop: Any, period_s: float = 0.4) -> None:
        from . import cs_reader, perception

        while not stop.is_set():
            try:
                img = self._orig_shot()
                if img is not None and self._gt > 0:
                    gt = self._gt + (time.monotonic() - self._gt_wall)
                    self.watcher.update(gt, perception.find_bars(img, "enemy"), cs_reader.read_cs(img[..., ::-1]))
            except Exception:  # noqa: BLE001 - the watcher must never stop the game loop
                pass
            stop.wait(period_s)

    def minion_deaths(self) -> List[Dict[str, Any]]:
        return self.watcher.finish(self._gt + (time.monotonic() - self._gt_wall)) if self.watcher else []

    def run(self, max_s: float, is_over: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
        import threading

        stop = threading.Event()
        try:
            from .minion_events import MinionWatcher

            self.watcher = MinionWatcher()
            threading.Thread(target=self._watch_loop, args=(stop,), daemon=True).start()
        except ImportError:
            self.watcher = None
        try:
            out = super().run(max_s, lambda: is_over() or self._gt >= self.stop_at_s)
        finally:
            stop.set()
        self.deaths = self.minion_deaths()
        out.update(self.summary())
        self.save()
        return out

    def summary(self) -> Dict[str, Any]:
        ds = [d for d in self.decisions if d.get("wall_ms") is not None]
        lat = sorted(d["wall_ms"] for d in ds)

        def pct(p: float) -> Optional[int]:
            return lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None

        return {
            "model": self.model, "harness": HARNESS, "decisions": len(self.decisions), "errors": sum(1 for d in self.decisions if d.get("error")),
            "rejected": sum(1 for d in self.decisions if d.get("note")), "turret_vetoes": self.vetoes,
            "parse_failures": sum(1 for d in self.decisions if d.get("note") == "unparseable reply"),
            "latency_p50_ms": pct(0.5), "latency_p95_ms": pct(0.95),
            "in_tokens": sum(d.get("in_tokens") or 0 for d in ds), "out_tokens": sum(d.get("out_tokens") or 0 for d in ds),
            "cost_usd": round(sum(d.get("cost_usd") or 0.0 for d in ds), 5),
        }

    def save(self) -> None:
        if self.log_dir:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(os.path.join(self.log_dir, "decisions.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(d) for d in self.decisions))
            with open(os.path.join(self.log_dir, "inputs.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(i) for i in self.inputs))
            with open(os.path.join(self.log_dir, "llm_summary.json"), "w") as f:
                json.dump(self.summary(), f, indent=1)
