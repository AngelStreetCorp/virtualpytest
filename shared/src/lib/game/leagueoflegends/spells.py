"""TASK-135: spell state for the turn log: rank, cast time, cooldown and time until ready for Garen's Q W E R, the summoners and the
auto-attack. Pure (no I/O); the clock is the game time. Numbers and sources: ``docs/agent/game/lol/champions/garen.yaml`` (kit, farming).

``ready_in_s`` is tracked from our own casts (the key presses of the input log), not read from the HUD. A cast that the game rejected
(no rank, silenced) still starts our timer: the HUD digit reader is the open check (see OVERLAY_CONTRACT.md).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# cooldown in seconds by rank 1..5 (R 1..3): Data Dragon 16.20.1 champion/Garen.json ``cooldown`` arrays (authoritative for the patch,
# fetched 2026-10-19); the wiki end points agree.
COOLDOWNS: Dict[str, List[float]] = {
    "Q": [8, 8, 8, 8, 8],
    "W": [22, 19.5, 17, 14.5, 12],
    "E": [9, 8.25, 7.5, 6.75, 6],
    "R": [120, 100, 80],
}
# time the cast locks Garen, seconds. Q and W are instant (Q empowers the next auto for 4.5 s); E spins up to 3 s (wiki, 7 spins);
# R is a short cast (0.435 s PROVISIONAL, single source: Data Dragon has no cast times).
CAST_S = {"Q": 0.0, "W": 0.0, "E": 3.0, "R": 0.435}
SUMMONER_KEY = {"summonerSpellOne": "D", "summonerSpellTwo": "F"}
# summoner cooldowns: Data Dragon 16.20.1 summoner.json, the CLASSIC (Summoner's Rift) entries, fetched 2026-10-19
SUMMONER_CD = {"Flash": 300.0, "Ignite": 180.0, "Teleport": 300.0, "Heal": 240.0, "Barrier": 180.0, "Ghost": 240.0, "Exhaust": 240.0,
               "Cleanse": 240.0, "Smite": 15.0}
WINDUP_FRAC = 0.18  # of the attack time (wiki, single source)


def cooldown_s(key: str, rank: int, haste: float = 0.0) -> Optional[float]:
    """Cooldown after haste: cd x 100 / (100 + haste). None when the rank is 0 or unknown."""
    cds = COOLDOWNS.get(key)
    if not cds or rank < 1:
        return None
    return round(cds[min(rank, len(cds)) - 1] * 100.0 / (100.0 + max(haste, 0.0)), 2)


class SpellTracker:
    """Remembers when we last cast each key (game time) and answers the spell block for a tick."""

    def __init__(self) -> None:
        self.cast_at: Dict[str, float] = {}

    def note_key(self, key: str, game_t: float) -> None:
        k = key.split("+")[0].upper()
        if k in ("Q", "W", "E", "R", "D", "F"):
            self.cast_at[k] = game_t

    def block(self, game_t: float, data: Optional[Dict[str, Any]], attack_speed: float, since_last_auto_s: Optional[float]) -> Dict[str, Any]:
        ap = (data or {}).get("activePlayer") or {}
        haste = float((ap.get("championStats") or {}).get("abilityHaste", 0.0) or 0.0)
        abil = ap.get("abilities") or {}
        out: Dict[str, Any] = {}
        for k in ("Q", "W", "E", "R"):
            rank = int((abil.get(k) or {}).get("abilityLevel", 0) or 0)
            cd = cooldown_s(k, rank, haste)
            out[k] = self._entry(k, rank, cd, CAST_S[k], game_t)
        me = next((p for p in (data or {}).get("allPlayers") or [] if p.get("riotId") in {ap.get("riotId")} - {None}
                   or p.get("summonerName") in {ap.get("summonerName")} - {None}), {})
        for slot, key in SUMMONER_KEY.items():
            name = (((me.get("summonerSpells") or {}).get(slot)) or {}).get("displayName")
            if name:
                base = next((v for n, v in SUMMONER_CD.items() if n in name), None)
                cd = round(base * 100.0 / (100.0 + float((ap.get("championStats") or {}).get("summonerHaste", 0.0) or 0.0)), 1) if base else None
                e = self._entry(key, 1, cd, 0.0, game_t)
                e["name"] = name
                out[key] = e
        period = round(1.0 / attack_speed, 3) if attack_speed > 0 else None
        nxt = None if period is None or since_last_auto_s is None else round(max(0.0, period - since_last_auto_s), 2)
        out["auto"] = {"attack_period_s": period, "cast_time_s": round(period * WINDUP_FRAC, 3) if period else None,
                       "next_auto_in_s": nxt}
        return out

    def _entry(self, key: str, rank: int, cd: Optional[float], cast: float, game_t: float) -> Dict[str, Any]:
        t0 = self.cast_at.get(key)
        ready: Optional[float]
        if rank < 1 or cd is None:
            ready = None  # not learned
        elif t0 is None:
            ready = 0.0
        else:
            ready = round(max(0.0, t0 + cd - game_t), 2)
        return {"rank": rank, "cast_time_s": cast, "cooldown_s": cd, "ready_in_s": ready,
                "casting_for_s": round(max(0.0, t0 + cast - game_t), 2) if t0 is not None and cast else 0.0,
                "last_cast_ago_s": round(game_t - t0, 1) if t0 is not None else None, "source": "own_casts"}
