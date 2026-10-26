"""TASK-135: per-turn log of the Garen bot (turns.jsonl, zones.jsonl, live overlay file), shape in OVERLAY_CONTRACT.md.

Read-only observer: it never changes what the bot does. Inputs are taken at the :class:`game_input.GameInput` layer
(``gi.on_input = log.add_input``) so every physical input is listed, whoever sent it. A failure here is swallowed: a log must
never stop a game.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import danger_zones
from .perception import MINIMAP_RECT
from .spells import SpellTracker

FRAME = {"w": danger_zones.FRAME_W, "h": danger_zones.FRAME_H}
RECENT_INPUTS = 12
ZONES_EVERY_S = 1.0
ACTION_CHOICE = {"right": "attack", "move": "move", "select": "select", "minimap": "move_minimap", "recall": "recall",
                 "shop": "shop", "levelup": "levelup"}


def _norm(x: float, y: float) -> Tuple[float, float]:
    return round(x / danger_zones.FRAME_W, 4), round(y / danger_zones.FRAME_H, 4)


def _in_minimap(nx: float, ny: float) -> bool:
    return MINIMAP_RECT[0] <= nx <= MINIMAP_RECT[2] and MINIMAP_RECT[1] <= ny <= MINIMAP_RECT[3]


def choice_of(acts: List[Tuple[Any, ...]]) -> str:
    """One word for what the actions of a tick do: the first action decides, ``hold`` when there are none."""
    if not acts:
        return "hold"
    a = acts[0]
    if a[0] == "key":
        return f"cast_{a[1]}" if a[1] in ("Q", "W", "E", "R") else f"key_{a[1]}"
    return ACTION_CHOICE.get(str(a[0]), str(a[0]))


def decision_of(bot: Any, acts: List[Tuple[Any, ...]], game_t: float) -> Dict[str, Any]:
    """The decision block: the bot's own choice and reason, the model's options and probabilities when it is a model contestant."""
    choice = choice_of(acts)
    dec: Dict[str, Any] = {"choice": choice, "options": [{"id": choice, "p": 1.0}], "reason": f"rule bot, mode {bot.mem.mode}"}
    lh = bot.mem.lasthits[-1] if bot.mem.lasthits else None
    if lh and abs(float(lh.get("t", -99)) - game_t) < 1.0:
        dec["reason"] = f"last-hit attempt on a {lh.get('type')} minion (est. health {lh.get('est_hp')}, damage {lh.get('dmg')})"
    recs = getattr(bot, "decisions", None)  # model contestants: LlmBot.decisions, CoachBot jev rows
    if recs:
        rec = recs[-1]
        ch = rec.get("choice")
        if isinstance(ch, dict) and abs(float(rec.get("game_t", -99)) - game_t) < 1.0:
            mid = str(ch.get("a") or ch.get("mode") or ch.get("tactic") or choice)
            probs = ch.get("probabilities") or {}
            dec["options"] = [{"id": k, "p": round(float(v), 3)} for k, v in probs.items()] if probs else [{"id": mid, "p": 1.0}]
            dec["reason"] = str(rec.get("note") or ch.get("reason") or f"model choice {mid}")[:200]
            if rec.get("turret_veto"):
                dec["reason"] = f"turret veto: {rec['turret_veto'].get('why')}"
    jev = getattr(bot, "jev_rows", None)
    if jev and jev[-1].get("probabilities"):
        dec["options"] = [{"id": k, "p": round(float(v), 3)} for k, v in jev[-1]["probabilities"].items()]
        dec["reason"] = f"coach picked {jev[-1].get('choice')} (plan {getattr(bot, 'plan', {}).get('mode')})"
    return dec


def state_of(s: Any, data: Optional[Dict[str, Any]], cs: Optional[int]) -> Dict[str, Any]:
    stats = ((data or {}).get("activePlayer") or {}).get("championStats") or {}
    mini = [round(s.pos[0], 3), round(s.pos[1], 3)] if s.pos else None
    return {"hp": round(s.hp), "hp_max": round(s.max_hp), "mana": round(stats.get("resourceValue", 0) or 0),
            "mana_max": round(stats.get("resourceMax", 0) or 0), "level": s.level, "gold": round(s.gold), "cs": cs,
            "ad": round(s.ad, 1), "armor": round(stats["armor"]) if "armor" in stats else None,
            "mr": round(stats["magicResist"]) if "magicResist" in stats else None, "attack_speed": round(s.attack_speed, 2),
            "move_speed": round(stats["moveSpeed"]) if "moveSpeed" in stats else None, "items": list(s.items),
            "pos_minimap": mini, "mode": None}


ATTACK_RANGE_PX = 210  # Garen: 175 units plus the target's radius (same value as garen_bot.LH_RANGE_PX)
UNITS_PER_PX = 1.0  # camera scale: 175 units of attack range measure about 175..210 px, so about 1 px per unit (as TURRET_RANGE_PX)
NEAR_UNITS = 500  # "within 500 units" of the summary
MAX_UNITS = 40  # nearest units kept per turn
SELF_BOX = (60, 260)  # an allied champion bar this close (dx) and this far above (dy) Garen's feet is Garen's own bar
_KINDS = {("minion", "enemy"): "enemy_minion", ("minion", "ally"): "ally_minion", ("champion", "enemy"): "enemy_champion",
          ("champion", "ally"): "ally_champion", ("turret", "enemy"): "enemy_turret", ("turret", "ally"): "ally_turret"}


def _roster(data: Optional[Dict[str, Any]], my_team: str) -> List[Dict[str, Any]]:
    """Champions of the Live Client Data ``allPlayers``: name, side relative to Garen, level, items, alive."""
    out = []
    for p in (data or {}).get("allPlayers") or []:
        out.append({"name": p.get("championName"), "side": "ally" if p.get("team") == my_team else "enemy", "level": p.get("level"),
                    "dead": bool(p.get("isDead")), "items": [i.get("displayName", "") for i in p.get("items") or []],
                    "self": bool(p.get("_self"))})
    return out


def world_of(bot: Any, s: Any, data: Optional[Dict[str, Any]], prev_hp: Optional[float], tracks: Optional[MinionTracks] = None) -> Dict[str, Any]:
    """Everything perception sees this tick, for the decision log: ``units`` (one per health bar), ``champions`` (roster from the
    Live Client Data), ``self`` and a ``summary``. Ally bars are refreshed every 3rd bot tick, so they can be 2 ticks old."""
    px, py = danger_zones.PLAYER_XY
    ap = (data or {}).get("activePlayer") or {}
    names = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    players = [dict(p, _self=(p.get("riotId") in names or p.get("summonerName") in names)) for p in (data or {}).get("allPlayers") or []]
    roster = _roster({"allPlayers": players}, s.team)
    lone: Dict[str, Optional[Dict[str, Any]]] = {}
    for side in ("ally", "enemy"):
        c = [r for r in roster if r["side"] == side and not r["self"] and not r["dead"]]
        lone[side] = c[0] if len(c) == 1 else None  # a bar carries no name: only a single candidate can be named
    sel = getattr(getattr(bot, "mem", None), "sel", None)
    th = getattr(s, "target_hp", None)
    stats = ap.get("championStats") or {}
    speed = float(stats.get("moveSpeed", 0) or 0) or None
    units: List[Dict[str, Any]] = []
    self_bar = False
    for team, bars in (("enemy", s.enemies), ("ally", s.allies)):
        for b in bars:
            if b.kind == "champion" and team == "ally" and abs(b.x - px) <= SELF_BOX[0] and 0 <= py - b.y <= SELF_BOX[1]:
                self_bar = True
                continue
            if b.kind == "turret":
                x, y = b.x, b.y + danger_zones.TURRET_BAR_DY
            else:
                x, y = b.body
            d = math.hypot(x - px, y - py)
            u: Dict[str, Any] = {"kind": _KINDS[(b.kind, team)], "type": b.minion_type, "hp_frac": b.frac, "hp_exact": None,
                                 "hp_max": None, "x": round(x / danger_zones.FRAME_W, 4), "y": round(y / danger_zones.FRAME_H, 4),
                                 "dist_px": round(d), "dist_units": round(d * UNITS_PER_PX),
                                 "in_attack_range": d <= ATTACK_RANGE_PX and b.kind != "turret",
                                 "walk_eta_s": round(max(0.0, d * UNITS_PER_PX - ATTACK_RANGE_PX * UNITS_PER_PX) / speed, 2) if speed else None,
                                 "kill_mark_frac": getattr(b, "kill_mark_frac", None)}
            if b.kind == "champion":
                c = lone[team]
                if c:
                    u.update(champion=c["name"], level=c["level"], items=c["items"])
            units.append(u)
    units.sort(key=lambda u: u["dist_px"])
    units = units[:MAX_UNITS]
    if tracks is not None:
        tracks.update([u for u in units if u["kind"].endswith("_minion")], danger_zones.FRAME_W, danger_zones.FRAME_H)
    if th and th[1] > 0 and sel:  # the selected minion: the unit whose bar matches the exact health read from the target frame
        cand = [u for u in units if u["kind"] == "enemy_minion"]
        if cand:
            ratio = th[0] / th[1]
            best = min(cand, key=lambda u: abs(u["hp_frac"] - ratio) * 400 + abs(u["x"] * danger_zones.FRAME_W - sel["x"]) + abs(u["y"] * danger_zones.FRAME_H - sel["y"]))
            if abs(best["hp_frac"] - ratio) < 0.12:
                best["hp_exact"], best["hp_max"], best["selected"] = th[0], th[1], True
                MinionTracks.learn(best)
    for i, u in enumerate(units, 1):
        u["id"] = f"u{i}"
        u.pop("_track", None)
    counts = {k: sum(1 for u in units if u["kind"] == k) for k in _KINDS.values()}
    nearest = {}
    for k in _KINDS.values():
        u = next((u for u in units if u["kind"] == k), None)
        if u:
            nearest[k] = {"id": u["id"], "dist_px": u["dist_px"], "dist_units": u["dist_units"]}
    rng = [u for u in units if u["kind"] == "enemy_minion" and u["in_attack_range"]]
    low = min(rng, key=lambda u: u["hp_frac"], default=None)
    # the lowest-health enemy minion on screen (in range or not): can Garen get there before it dies?
    em = [u for u in units if u["kind"] == "enemy_minion"]
    lowest = min(em, key=lambda u: u["hp_frac"], default=None)
    death_s = None
    hist = (sel or {}).get("hist") or []
    if lowest and lowest.get("selected") and len(hist) >= 2 and hist[-1][0] > hist[0][0]:  # exact health history of the selected minion
        rate = (hist[0][1] - hist[-1][1]) / (hist[-1][0] - hist[0][0])  # hp per second lost
        death_s = round(hist[-1][1] / rate, 2) if rate > 0 else None
    reach = None if not lowest else {"id": lowest["id"], "hp_frac": lowest["hp_frac"], "dist_units": lowest["dist_units"],
                                     "walk_eta_s": lowest["walk_eta_s"], "predicted_death_s": death_s,
                                     "reachable_before_death": None if death_s is None or lowest["walk_eta_s"] is None else lowest["walk_eta_s"] < death_s}
    near_u = [u for u in units if u["dist_units"] <= NEAR_UNITS]
    summary = {"counts": counts, "nearest": nearest,
               "within_500_units": {"ally_minion": sum(1 for u in near_u if u["kind"] == "ally_minion"),
                                    "enemy_minion": sum(1 for u in near_u if u["kind"] == "enemy_minion")},
               "lowest_hp_enemy_minion_in_range": {"id": low["id"], "hp_frac": low["hp_frac"], "hp_exact": low["hp_exact"]} if low else None,
               "lowest_hp_enemy_minion_reach": reach,
               "taking_damage": bool(prev_hp is not None and s.hp < prev_hp - 0.5),
               "targeting_garen": None}  # not observable from health bars; the Live Client Data has no target field
    me = {"hp": round(s.hp), "hp_max": round(s.max_hp), "hp_frac": round(s.hp / s.max_hp, 3) if s.max_hp else None,
          "bar_seen": self_bar}
    return {"units": units, "champions": [{k: v for k, v in r.items() if k != "self"} | {"self": r["self"]} for r in roster],
            "self": me, "summary": summary}


def minion_type_from_hp_max(hp_max: float) -> Optional[str]:
    """Minion type from its exact maximum health (garen.yaml measured: caster 284-302, melee 465-570, cannon 835+); None in the gaps."""
    if hp_max < 400:
        return "caster"
    if hp_max < 700:
        return "melee"
    return "cannon" if hp_max >= 800 else None


class MinionTracks:
    """Follows minion bars from tick to tick (nearest bar, health not rising) so a type learned once (the selected minion's exact
    maximum health) stays on that bar. A bar carries no identity, so this is a best-effort match: it fills types in over time."""

    MATCH_PX = 60
    MAX_AGE = 6  # ticks a track survives unseen

    def __init__(self) -> None:
        self.tracks: List[Dict[str, Any]] = []
        self.n = 0

    def update(self, units: List[Dict[str, Any]], fw: int, fh: int) -> None:
        """``units``: minion unit dicts (x, y normalised, hp_frac, kind); sets ``type`` / ``type_source`` where known and ``_track``."""
        self.n += 1
        free = list(self.tracks)
        for u in units:
            ux, uy = u["x"] * fw, u["y"] * fh
            best, bd = None, self.MATCH_PX
            for tr in free:
                if tr["kind"] != u["kind"] or u["hp_frac"] > tr["frac"] + 0.1:
                    continue
                d = math.hypot(tr["x"] - ux, tr["y"] - uy)
                if d < bd:
                    best, bd = tr, d
            if best is None:
                best = {"kind": u["kind"], "type": None}
                self.tracks.append(best)
            else:
                free.remove(best)
            best.update(x=ux, y=uy, frac=u["hp_frac"], seen=self.n)
            u["_track"] = best
            if best["type"] and not u.get("type"):
                u["type"], u["type_source"] = best["type"], "track"
        self.tracks = [tr for tr in self.tracks if self.n - tr["seen"] <= self.MAX_AGE]

    @staticmethod
    def learn(u: Dict[str, Any]) -> None:
        """The selected minion's exact maximum health tells its type."""
        ty = minion_type_from_hp_max(u["hp_max"]) if u.get("hp_max") else None
        if ty:
            u["type"], u["type_source"] = ty, "hp_max"
            if u.get("_track") is not None:
                u["_track"]["type"] = ty


def new_events(data: Optional[Dict[str, Any]], seen: set, names: set) -> List[Dict[str, Any]]:
    """Game events not seen before, reduced to what the reward layer needs: kind (champion_kill / assist / turret_kill / death) for
    Garen, plus the raw name. ``names`` are Garen's summoner names."""
    out: List[Dict[str, Any]] = []
    for e in ((data or {}).get("events") or {}).get("Events") or []:
        eid = e.get("EventID")
        if eid in seen:
            continue
        seen.add(eid)
        name, killer, victim = e.get("EventName"), e.get("KillerName"), e.get("VictimName")
        assisters = e.get("Assisters") or []
        kind = None
        if name == "ChampionKill":
            kind = "death" if victim in names else "champion_kill" if killer in names else "assist" if names & set(assisters) else None
        elif name in ("TurretKilled", "InhibKilled"):
            kind = "turret_kill" if killer in names or names & set(assisters) else None
        if kind:
            out.append({"kind": kind, "name": name, "event_t": e.get("EventTime"), "killer": killer, "victim": victim})
    return out


class TurnLog:
    """Collects the inputs, then writes one turn per bot tick. ``out_dir`` None = live file only."""

    def __init__(self, out_dir: Optional[str] = None, live_path: Optional[str] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.out_dir, self.live_path, self.clock = out_dir, live_path, clock
        self.turn = 0
        self._pending: List[Dict[str, Any]] = []
        self._recent: List[Dict[str, Any]] = []  # (inputs with a wall stamp "_w") of the last RECENT_INPUTS
        self._last_zone_t = -99.0
        self._zones: List[Dict[str, Any]] = []
        self.errors = 0
        self._prev_hp: Optional[float] = None
        self.spells = SpellTracker()
        self.tracks = MinionTracks()
        self._seen_events: set = set()
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            for n in ("turns.jsonl", "zones.jsonl"):
                open(os.path.join(out_dir, n), "w").close()

    # --- GameInput hook ---------------------------------------------------------------------------------------------
    def add_input(self, kind: str, x: Optional[float] = None, y: Optional[float] = None, key: Optional[str] = None,
                  text: Optional[str] = None, ctrl: bool = False) -> None:
        """kind: key | right_click | left_click | move | type_text; x, y in screen pixels (1920x1200)."""
        rec: Dict[str, Any] = {"kind": kind}
        if x is not None and y is not None:
            nx, ny = _norm(x, y)
            rec["x"], rec["y"] = nx, ny
            if kind == "right_click" and _in_minimap(nx, ny):
                rec["kind"] = "minimap"
        if key is not None:
            rec["key"] = key + ("+CTRL" if ctrl else "")
        if text is not None:
            rec["text"] = text
        rec["_w"] = self.clock()
        self._pending.append(rec)

    # --- one bot tick -----------------------------------------------------------------------------------------------
    def tick(self, bot: Any, s: Any, data: Optional[Dict[str, Any]], acts: List[Tuple[Any, ...]]) -> None:
        try:
            self._tick(bot, s, data, acts)
        except Exception:  # noqa: BLE001 - the log never stops the game
            self.errors += 1

    def _retreat_dir(self, s: Any) -> Optional[Tuple[float, float]]:
        """Screen direction towards our base: from the minimap position to the safe point (the map is not rotated)."""
        if not s.pos or not getattr(s, "safe_px", None):
            return None
        sx = (s.safe_px[0] / danger_zones.FRAME_W - MINIMAP_RECT[0]) / (MINIMAP_RECT[2] - MINIMAP_RECT[0])
        sy = (s.safe_px[1] / danger_zones.FRAME_H - MINIMAP_RECT[1]) / (MINIMAP_RECT[3] - MINIMAP_RECT[1])
        dx, dy = sx - s.pos[0], sy - s.pos[1]
        return (dx, dy) if (dx or dy) else None

    def _tick(self, bot: Any, s: Any, data: Optional[Dict[str, Any]], acts: List[Tuple[Any, ...]]) -> None:
        self.turn += 1
        now = self.clock()
        if s.game_t - self._last_zone_t >= ZONES_EVERY_S:
            self._last_zone_t = s.game_t
            self._zones = danger_zones.compute_zones(s.enemies, s.allies, self._retreat_dir(s))
            if self.out_dir:
                self._append("zones.jsonl", {"t": round(s.game_t, 1), "frame": FRAME, "zones": self._zones})
        state = state_of(s, data, getattr(bot, "last_cs", None) if getattr(bot, "last_cs", None) is not None else s.cs)
        state["mode"] = bot.mem.mode
        for i in self._pending:
            if i["kind"] == "key" and i.get("key"):
                self.spells.note_key(i["key"], s.game_t)
        la = getattr(getattr(bot, "mem", None), "last_attack_t", None)
        state["spells"] = self.spells.block(s.game_t, data, s.attack_speed, round(s.t - la, 2) if la is not None and la > -50 else None)
        inputs = [{k: v for k, v in i.items() if k != "_w"} for i in self._pending]
        decision = decision_of(bot, acts, s.game_t)
        in_zone = danger_zones.standing_in(self._zones)
        decision["zones"] = {"standing_in": in_zone, "n_danger": sum(1 for z in self._zones if z["level"] == "danger"),
                             "n_safe": sum(1 for z in self._zones if z["level"] == "safe")}
        world = world_of(bot, s, data, self._prev_hp, self.tracks)
        self._prev_hp = s.hp
        ap = (data or {}).get("activePlayer") or {}
        names = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
        state["dead"] = bool(s.dead)
        line = {"t": round(s.game_t, 1), "turn": self.turn, "state": state, "decision": decision, "inputs": inputs, "world": world}
        evs = new_events(data, self._seen_events, names)
        if evs:
            line["events"] = evs
        if self.out_dir:
            self._append("turns.jsonl", line)
        self._recent = (self._recent + self._pending)[-RECENT_INPUTS:]
        self._pending = []
        if self.live_path:
            recent = [dict({k: v for k, v in i.items() if k != "_w"}, age_s=round(now - i["_w"], 1)) for i in self._recent]
            self._atomic(self.live_path, {"t": round(s.game_t, 1), "frame": FRAME, "zones": self._zones,
                                          "recent_inputs": recent, "state": state, "decision": decision, "world": world})

    def _append(self, name: str, obj: Dict[str, Any]) -> None:
        with open(os.path.join(self.out_dir or "", name), "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")

    @staticmethod
    def _atomic(path: str, obj: Dict[str, Any]) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        os.replace(tmp, path)


def read_turns(path: str) -> List[Dict[str, Any]]:
    """The turns of a run folder (empty when the file is missing)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]
