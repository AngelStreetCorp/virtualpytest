"""TASK-130: practice_runner allowlist + happy path against a fake client API."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.src.lib.game.leagueoflegends.practice_runner import (
    LcuClient,
    LcuRefused,
    PracticeConfig,
    PracticeRunner,
    PRACTICE_LOBBY_BODY,
)

pytestmark = pytest.mark.unit


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.phase = "None"
        self.bots = 0

    def __call__(self, method, path, body):
        self.calls.append((method, path))
        if path == "/lol-gameflow/v1/gameflow-phase":
            return 200, self.phase
        if path == "/lol-lobby/v2/lobby" and method == "POST":
            return 200, {}
        if path.endswith("available-bots"):
            return 200, [{"id": 1}, {"id": 2}]
        if path.endswith("/custom/bots"):
            self.bots += 1
            return 204, None
        if path.endswith("start-champ-select"):
            self.phase = "ChampSelect"
            return 204, None
        if path == "/lol-champ-select/v1/session":
            return 200, {"localPlayerCellId": 0, "actions": [[{"id": 7, "actorCellId": 0, "type": "pick", "completed": False}]]}
        if path.endswith("pickable-champion-ids"):
            return 200, [22, 51]
        if path.startswith("/lol-champ-select/v1/session/actions/"):
            self.phase = "InProgress"
            return 204, None
        return 404, "nope"


def _cfg(**kw):
    return PracticeConfig(poll_s=0.0, game_running_fn=kw.pop("running", lambda: True), live_client_fn=lambda: True, **kw)


def test_refuses_non_practice_lobby_and_unknown_paths() -> None:
    client = LcuClient(http=FakeApi())
    with pytest.raises(LcuRefused):
        client.call("POST", "/lol-lobby/v2/lobby", {"queueId": 3140, "customGameLobby": {"configuration": {"gameMode": "CLASSIC"}}})
    with pytest.raises(LcuRefused):
        client.call("POST", "/lol-matchmaking/v1/search")
    with pytest.raises(LcuRefused):
        client.call("DELETE", "/lol-lobby/v2/lobby/members")
    with pytest.raises(LcuRefused):
        client.call("POST", "/lol-lobby/v2/lobby", {"queueId": 420, "customGameLobby": {"configuration": {"gameMode": "PRACTICETOOL"}}})
    assert client.call("POST", "/lol-lobby/v2/lobby", PRACTICE_LOBBY_BODY)[0] == 200


def test_happy_path_full_team(tmp_path: Path) -> None:
    api = FakeApi()
    shots: list[Path] = []
    cfg = _cfg(screenshot_fn=shots.append, screenshot_dir=tmp_path)
    # game_running_fn must be False at the start guard, True afterwards.
    state = {"started": False}
    cfg.game_running_fn = lambda: state["started"]
    runner = PracticeRunner(cfg, LcuClient(http=lambda m, p, b: _flip(api, state, m, p, b)))
    result = runner.run()
    assert result.ok, result
    assert api.bots == 9
    assert [s.name for s in result.steps][-1] == "see_game"
    assert shots and shots[0].name == "practice_in_game.png"


def _flip(api, state, m, p, b):
    out = api(m, p, b)
    if p.startswith("/lol-champ-select/v1/session/actions/"):
        state["started"] = True
    return out


def test_refuses_when_game_already_running() -> None:
    runner = PracticeRunner(_cfg(running=lambda: True), LcuClient(http=FakeApi()))
    result = runner.run()
    assert not result.ok and "already running" in result.final_message


def test_red_side_joins_team_two_and_puts_allied_bots_on_it() -> None:
    api = FakeApi()
    bots_teams: list = []
    state = {"started": False, "clicked": False}

    def http(m, p, b):
        if p == "/lol-lobby/v2/lobby" and m == "GET":
            return 200, {"gameConfig": {"customTeam200": [{"x": 1}] if state["clicked"] else []}}
        if p.endswith("/custom/bots"):
            bots_teams.append(b["teamId"])
        return _flip(api, state, m, p, b)

    cfg = _cfg(player_team="200", join_red_fn=lambda: state.__setitem__("clicked", True), screenshot_fn=lambda p: None)
    cfg.game_running_fn = lambda: state["started"]
    result = PracticeRunner(cfg, LcuClient(http=http)).run()
    assert result.ok, result
    assert state["clicked"] and bots_teams.count("200") == 4 and bots_teams.count("100") == 5


def test_red_side_without_a_join_click_is_refused() -> None:
    cfg = _cfg(player_team="200")
    cfg.game_running_fn = lambda: False
    result = PracticeRunner(cfg, LcuClient(http=FakeApi())).run()
    assert not result.ok and "join_red_fn" in result.final_message
