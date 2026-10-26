"""TASK-131 goal 3: record a League game from the Live Client Data API (read-only).

``https://127.0.0.1:2999/liveclientdata/allgamedata`` is Riot's in-game API (self-signed certificate,
no auth). Only GET is ever sent, to that one path; no input reaches the game, so a human game and a bot
game are recorded the same way. The result is a timeline dict (see :func:`new_timeline`) that
``scorecard.py`` replays offline.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

ALL_GAME_DATA_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
TIMELINE_VERSION = 1


def fetch_all_game_data(url: str = ALL_GAME_DATA_URL, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """GET allgamedata; ``None`` when no game answers (not started, loading, ended)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _me(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``allPlayers`` row of the active player (matched on riotId, then summonerName)."""
    ap = data.get("activePlayer") or {}
    keys = {ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName")} - {None, ""}
    for p in data.get("allPlayers") or []:
        if {p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")} & keys:
            return p
    return {}


def new_timeline(data: Dict[str, Any]) -> Dict[str, Any]:
    ap, me, gd = data.get("activePlayer") or {}, _me(data), data.get("gameData") or {}
    return {
        "version": TIMELINE_VERSION,
        "meta": {
            "player": ap.get("riotId") or ap.get("summonerName") or me.get("summonerName", ""),
            "champion": me.get("championName", ""),
            "team": me.get("team", ""),
            "assigned_position": me.get("position", ""),
            "map": gd.get("mapName", ""),
            "mode": gd.get("gameMode", ""),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "players": [
            {"name": p.get("riotId") or p.get("summonerName", ""), "champion": p.get("championName", ""),
             "team": p.get("team", ""), "position": p.get("position", ""), "is_bot": bool(p.get("isBot"))}
            for p in data.get("allPlayers") or []
        ],
        "samples": [],
        "events": [],
        "zones": [],
    }


def sample_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
    ap, me = data.get("activePlayer") or {}, _me(data)
    cs = ap.get("championStats") or {}
    sc = me.get("scores") or {}
    return {
        "t": round(float((data.get("gameData") or {}).get("gameTime", 0.0)), 1),
        "gold": round(float(ap.get("currentGold", 0.0)), 1),
        "level": int(ap.get("level") or me.get("level") or 0),
        "hp": round(float(cs.get("currentHealth", 0.0)), 1),
        "hp_max": round(float(cs.get("maxHealth", 0.0)), 1),
        "dead": bool(me.get("isDead")),
        "scores": {"kills": sc.get("kills", 0), "deaths": sc.get("deaths", 0), "assists": sc.get("assists", 0),
                   "cs": sc.get("creepScore", 0), "ward": sc.get("wardScore", 0.0)},
        "items": [i.get("displayName", "") for i in me.get("items") or [] for _ in range(max(1, int(i.get("count", 1))))],
    }


def add_poll(timeline: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """Fold one allgamedata poll into the timeline. Returns True once ``GameEnd`` has been seen."""
    s = sample_from_data(data)
    if not timeline["samples"] or s["t"] > timeline["samples"][-1]["t"]:
        timeline["samples"].append(s)
    seen = {e.get("EventID") for e in timeline["events"]}
    for e in (data.get("events") or {}).get("Events") or []:
        if e.get("EventID") not in seen:
            timeline["events"].append(e)
    return any(e.get("EventName") == "GameEnd" for e in timeline["events"])


def save_timeline(timeline: Dict[str, Any], path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=1)
    os.replace(tmp, path)


def load_timeline(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_game(
    out_path: str,
    interval: float = 2.0,
    wait_start_s: float = 600.0,
    fetch: Callable[[], Optional[Dict[str, Any]]] = fetch_all_game_data,
    sleep: Callable[[float], None] = time.sleep,
    max_misses: int = 15,
) -> Dict[str, Any]:
    """Wait for a game, poll every ``interval`` s until GameEnd (or the API stays silent), write ``out_path``."""
    timeline: Optional[Dict[str, Any]] = None
    waited, misses, last_save = 0.0, 0, 0.0
    while True:
        data = fetch()
        if data is None:
            if timeline is None:
                waited += interval
                if waited > wait_start_s:
                    raise TimeoutError("no game answered on the Live Client Data API")
            else:
                misses += 1
                if misses >= max_misses:
                    break
            sleep(interval)
            continue
        misses = 0
        if timeline is None:
            timeline = new_timeline(data)
        if add_poll(timeline, data):
            break
        if timeline["samples"] and timeline["samples"][-1]["t"] - last_save >= 30:
            last_save = timeline["samples"][-1]["t"]
            save_timeline(timeline, out_path)
        sleep(interval)
    if timeline is None:
        raise TimeoutError("no game answered on the Live Client Data API")
    save_timeline(timeline, out_path)
    return timeline


if __name__ == "__main__":  # python -m shared.src.lib.game.leagueoflegends.live_recorder <out.json | run folder>
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "lol-timeline.json"
    if os.path.isdir(target) or not target.endswith(".json"):  # a run folder: record, then score it when the game ends
        os.makedirs(target, exist_ok=True)
        record_game(os.path.join(target, "timeline.json"))
        from .score_run import score_run_dir

        print("overall", score_run_dir(target)["overall"])
    else:
        record_game(target)
