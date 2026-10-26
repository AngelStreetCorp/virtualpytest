"""TASK-130: start a full Practice Tool game through the League Client's local API.

The League Client writes ``<install>\\lockfile`` (``name:pid:port:password:protocol``) and serves
HTTPS on ``127.0.0.1:<port>`` with basic auth ``riot:<password>`` (self-signed certificate).
This module drives only the Practice Tool path:

    wait_loaded -> create_lobby -> add_bots -> start_champ_select -> lock_champion
    -> wait_game -> see_game

Safety: every call goes through :class:`LcuClient`, which only allows the endpoints in
``_ALLOWED`` and refuses to create any lobby that is not ``PRACTICETOOL``. No credentials are
read or sent, and no queue is joined.
"""

from __future__ import annotations

import base64
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

DEFAULT_LOCKFILE = r"C:\Riot Games\League of Legends\lockfile"
LIVE_CLIENT_URL = "https://127.0.0.1:2999/liveclientdata/gamestats"

# (method, path regex). Anything else is refused before a request is made.
_ALLOWED: List[Tuple[str, "re.Pattern[str]"]] = [
    (m, re.compile(p))
    for m, p in [
        ("GET", r"^/lol-gameflow/v1/gameflow-phase$"),
        ("GET", r"^/lol-lobby/v2/lobby$"),
        ("POST", r"^/lol-lobby/v2/lobby$"),
        ("DELETE", r"^/lol-lobby/v2/lobby$"),
        ("GET", r"^/lol-lobby/v2/lobby/custom/available-bots$"),
        ("POST", r"^/lol-lobby/v1/lobby/custom/bots$"),
        ("POST", r"^/lol-lobby/v1/lobby/custom/start-champ-select$"),
        ("GET", r"^/lol-champ-select/v1/session$"),
        ("GET", r"^/lol-champ-select/v1/pickable-champion-ids$"),
        ("PATCH", r"^/lol-champ-select/v1/session/actions/\d+$"),
        ("POST", r"^/lol-champ-select/v1/session/actions/\d+/complete$"),
    ]
]

PRACTICE_LOBBY_BODY = {
    "queueId": 3140,  # required together with customGameLobby, else INVALID_LOBBY
    "customGameLobby": {
        "configuration": {
            "gameMode": "PRACTICETOOL",
            "gameMutator": "",
            "gameServerRegion": "",
            "mapId": 11,
            "mutators": {"id": 1},
            "spectatorPolicy": "AllAllowed",
            "teamSize": 5,
        },
        "lobbyName": "vpt practice",
        "lobbyPassword": "",
    },
    "isCustom": True,
}


class LcuRefused(Exception):
    """The call is outside the Practice Tool allowlist."""


class LcuUnavailable(Exception):
    """No lockfile, or the client API does not answer."""


HttpFn = Callable[[str, str, Optional[Any]], Tuple[int, Any]]


class LcuClient:
    """Allowlisted client for the local League Client API."""

    def __init__(self, lockfile: str = DEFAULT_LOCKFILE, http: Optional[HttpFn] = None) -> None:
        self._lockfile = lockfile
        self._http = http or self._real_http

    def _real_http(self, method: str, path: str, body: Optional[Any]) -> Tuple[int, Any]:
        try:
            name, _pid, port, password, _proto = Path(self._lockfile).read_text().strip().split(":")
        except (OSError, ValueError) as e:
            raise LcuUnavailable(f"lockfile unreadable: {e}") from e
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        )
        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]
        except (urllib.error.URLError, OSError) as e:
            raise LcuUnavailable(f"client API unreachable: {e}") from e

    def call(self, method: str, path: str, body: Optional[Any] = None) -> Tuple[int, Any]:
        if not any(m == method and rx.match(path) for m, rx in _ALLOWED):
            raise LcuRefused(f"{method} {path} is not on the Practice Tool allowlist")
        if method == "POST" and path == "/lol-lobby/v2/lobby":
            if (body or {}).get("queueId") != 3140:
                raise LcuRefused(f"queue {(body or {}).get('queueId')!r} refused: Practice Tool queue 3140 only")
            mode = (((body or {}).get("customGameLobby") or {}).get("configuration") or {}).get("gameMode")
            if mode != "PRACTICETOOL":
                raise LcuRefused(f"lobby game mode {mode!r} refused: Practice Tool only")
        return self._http(method, path, body)


@dataclass
class PracticeStep:
    name: str
    ok: bool
    detail: str
    duration_s: float


@dataclass
class PracticeConfig:
    lockfile: str = DEFAULT_LOCKFILE
    loaded_timeout_s: float = 120.0
    champ_select_timeout_s: float = 120.0
    game_timeout_s: float = 180.0
    champion_id: int = 0  # 0 = first pickable; Garen = 86
    player_team: str = "100"  # "100" = blue / ORDER, "200" = red / CHAOS
    join_red_fn: Optional[Callable[[], None]] = None  # clicks the Team 2 "Join" button (the client API cannot switch teams)
    allied_bots: int = 4
    enemy_bots: int = 5
    bot_difficulty: str = "RSINTERMEDIATE"  # this client offers RSINTRO / RSBEGINNER / RSINTERMEDIATE
    enemy_top_bot: bool = False  # TASK-134: the first enemy bot gets position TOP (a top-lane champion), so Garen has a laner; every bot is MIDDLE otherwise
    poll_s: float = 2.0
    game_executable: str = "League of Legends.exe"
    screenshot_fn: Optional[Callable[[Path], None]] = None
    screenshot_dir: Path = field(default_factory=lambda: Path("practice-shots"))
    game_running_fn: Optional[Callable[[], bool]] = None
    live_client_fn: Optional[Callable[[], bool]] = None


@dataclass
class PracticeResult:
    ok: bool
    steps: List[PracticeStep]
    final_message: str


def _process_running(exe: str) -> bool:
    if sys.platform != "win32":
        return False
    from .process_utils import is_running

    return is_running(exe)


def _live_client_answers() -> bool:
    try:
        with urllib.request.urlopen(LIVE_CLIENT_URL, context=ssl._create_unverified_context(), timeout=5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


class PracticeRunner:
    def __init__(self, config: PracticeConfig, client: Optional[LcuClient] = None) -> None:
        self._cfg = config
        self._lcu = client or LcuClient(config.lockfile)
        self._steps: List[PracticeStep] = []
        self._game_running = config.game_running_fn or (lambda: _process_running(config.game_executable))
        self._live_client = config.live_client_fn or _live_client_answers

    # -- helpers -----------------------------------------------------------------------
    def _phase(self) -> Optional[str]:
        status, body = self._lcu.call("GET", "/lol-gameflow/v1/gameflow-phase")
        return body if status == 200 and isinstance(body, str) else None

    def _poll(self, timeout_s: float, check: Callable[[], Optional[str]]) -> Optional[str]:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                value = check()
            except LcuUnavailable:
                value = None
            if value is not None or time.monotonic() >= deadline:
                return value
            time.sleep(self._cfg.poll_s)

    def _record(self, name: str, ok: bool, detail: str, start: float) -> bool:
        step = PracticeStep(name, ok, detail, round(time.monotonic() - start, 2))
        self._steps.append(step)
        print(f"[practice] {name}: {'ok' if ok else 'FAILED'} ({step.duration_s}s) {detail}", flush=True)
        return ok

    def _fail(self, msg: str) -> PracticeResult:
        return PracticeResult(False, self._steps, msg)

    # -- run ---------------------------------------------------------------------------
    def run(self) -> PracticeResult:
        cfg = self._cfg

        if self._game_running():
            return self._fail(f"{cfg.game_executable} is already running: not starting a second game")

        # 1. Loaded: lockfile + API answers + phase is None (idle, logged in).
        t = time.monotonic()
        phase = self._poll(cfg.loaded_timeout_s, lambda: self._phase() if self._phase() in ("None", "Lobby") else None)
        if not self._record("wait_loaded", phase is not None, f"gameflow-phase={phase!r}", t):
            return self._fail("League Client API did not report an idle client within the timeout")

        # 2. Practice Tool lobby.
        t = time.monotonic()
        if self._lcu.call("GET", "/lol-lobby/v2/lobby")[0] == 200:
            self._lcu.call("DELETE", "/lol-lobby/v2/lobby")  # leave a stale lobby of our own
        status, body = self._lcu.call("POST", "/lol-lobby/v2/lobby", PRACTICE_LOBBY_BODY)
        if not self._record("create_lobby", status in (200, 201), f"HTTP {status}", t):
            return self._fail(f"create lobby refused: HTTP {status} {str(body)[:200]}")

        if cfg.player_team == "200":
            t = time.monotonic()
            if cfg.join_red_fn is None:
                return self._fail("red side needs join_red_fn (a click on the lobby's Team 2 Join button)")
            time.sleep(2.0)
            cfg.join_red_fn()
            time.sleep(2.0)
            st, lobby = self._lcu.call("GET", "/lol-lobby/v2/lobby")
            on_red = st == 200 and bool((lobby.get("gameConfig") or {}).get("customTeam200"))
            if not self._record("join_red", on_red, "player on team 200" if on_red else "player not on team 200", t):
                return self._fail("could not join the red team")

        # 3. Bots: a full 5v5.
        t = time.monotonic()
        status, bots = self._lcu.call("GET", "/lol-lobby/v2/lobby/custom/available-bots")
        if status != 200 or not bots:
            self._record("add_bots", False, f"available-bots HTTP {status}", t)
            return self._fail("no bots available")
        bots = [b for b in bots if b.get("active", True)]
        other = "200" if cfg.player_team == "100" else "100"
        wanted = [(cfg.player_team, cfg.allied_bots), (other, cfg.enemy_bots)]
        added = 0
        for team, count in wanted:
            for i in range(count):
                bot = bots[added % len(bots)]
                top = cfg.enemy_top_bot and team == other and i == 0
                if top:  # prefer a champion that lanes top (Malphite, Sion, Darius, Nasus, Garen's usual opponents)
                    bot = next((b for b in bots if b.get("id") in (54, 14, 122, 75)), bot)
                levels = bot.get("botDifficulties") or [cfg.bot_difficulty]
                difficulty = cfg.bot_difficulty if cfg.bot_difficulty in levels else levels[-1]
                s, b = self._lcu.call(
                    "POST", "/lol-lobby/v1/lobby/custom/bots",
                    {"championId": bot["id"], "botDifficulty": difficulty,
                     "teamId": team, "position": "TOP" if top else "MIDDLE", "botUuid": str(uuid.uuid4())},
                )
                if s not in (200, 201, 204):
                    self._record("add_bots", False, f"bot {added + 1} team {team}: HTTP {s} {str(b)[:120]}", t)
                    return self._fail("could not add a bot")
                added += 1
        self._record("add_bots", True, f"{added} bots added", t)

        # 4. Champion select.
        t = time.monotonic()
        status, body = self._lcu.call("POST", "/lol-lobby/v1/lobby/custom/start-champ-select")
        if not self._record("start_champ_select", status in (200, 204), f"HTTP {status}", t):
            return self._fail(f"start champ select refused: HTTP {status} {str(body)[:200]}")

        t = time.monotonic()
        locked = self._poll(cfg.champ_select_timeout_s, self._lock_champion)
        if not self._record("lock_champion", locked is not None, f"{locked}", t):
            return self._fail("could not lock a champion")

        # 5. Game starts.
        t = time.monotonic()
        phase = self._poll(cfg.game_timeout_s, lambda: self._phase() if self._phase() in ("InProgress", "GameStart") else None)
        running = self._poll(cfg.game_timeout_s, lambda: "yes" if self._game_running() else None)
        if not self._record("wait_game", phase is not None and running is not None,
                            f"phase={phase!r} {cfg.game_executable} running={running is not None}", t):
            return self._fail("game did not start")

        # 6. In-game screen seen: Live Client Data API answers, screenshot saved.
        t = time.monotonic()
        live = self._poll(cfg.game_timeout_s, lambda: "yes" if self._live_client() else None)
        shot = ""
        if cfg.screenshot_fn is not None:
            cfg.screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = cfg.screenshot_dir / "practice_in_game.png"
            cfg.screenshot_fn(path)
            shot = str(path)
        if not self._record("see_game", live is not None, f"live client data answers={live is not None} shot={shot}", t):
            return self._fail("in-game screen not seen")

        return PracticeResult(True, self._steps, "practice game running: in-game screen seen")

    def _lock_champion(self) -> Optional[str]:
        """Pick the first pickable champion for the local player's pick action and lock it in."""
        status, session = self._lcu.call("GET", "/lol-champ-select/v1/session")
        if status != 200 or not isinstance(session, dict):
            return None
        phase = self._phase()
        if phase in ("GameStart", "InProgress"):
            return "already past champion select"
        cell = session.get("localPlayerCellId")
        for group in session.get("actions", []):
            for action in group:
                if action.get("actorCellId") == cell and action.get("type") == "pick" and not action.get("completed"):
                    s, ids = self._lcu.call("GET", "/lol-champ-select/v1/pickable-champion-ids")
                    if s != 200 or not ids:
                        return None
                    pick = self._cfg.champion_id if self._cfg.champion_id in ids else ids[0]
                    s, _ = self._lcu.call(
                        "PATCH", f"/lol-champ-select/v1/session/actions/{action['id']}",
                        {"championId": pick, "completed": True},
                    )
                    return f"locked champion {pick} (HTTP {s})" if s in (200, 204) else None
        return None
