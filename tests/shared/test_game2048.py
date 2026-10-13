"""2048 showcase library (TASK-33): board rules, player parsing, and the runner + pixel reader
against a simulated device.

The simulated device plays real 2048 and renders each frame in the classic colours with the
HDMI colour shift, and it keeps showing the pre-move board for a few frames (capture lag).
No device, no network.

Run: pytest tests/shared/test_game2048.py -v
"""
import os
import random
import sys
import tempfile

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

import shared.src.lib.game2048.runner as runner_mod  # noqa: E402
from shared.src.lib.game2048.board import apply_move, first_legal, legal_moves, merge_gain  # noqa: E402
from shared.src.lib.game2048.player import heuristic_decide, parse_llm_move  # noqa: E402
from shared.src.lib.game2048.reader import BOARD_BG, CANONICAL, CELL, GAP, locate_board  # noqa: E402

HDMI_SHIFT = np.array([18, 15, 8])  # RGB brightening measured on the S21 HDMI capture


def test_board_rules():
    assert apply_move([[2, 2, 2, 2]] + [[0] * 4] * 3, "LEFT")[0] == [4, 4, 0, 0]
    assert apply_move([[2, 0, 2, 4]] + [[0] * 4] * 3, "RIGHT")[0] == [0, 0, 4, 4]
    assert merge_gain([[2, 2, 4, 4]] + [[0] * 4] * 3, "LEFT") == 12
    stuck = [[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]]
    assert legal_moves(stuck) == [] and first_legal(stuck) is None


def test_parse_llm_move():
    assert parse_llm_move('{"reasoning": "merge", "move": "down"}', ["LEFT", "DOWN"]) == ("DOWN", "merge")
    assert parse_llm_move('{"reasoning": "x", "move": "UP"}', ["LEFT", "DOWN"])[0] is None
    assert parse_llm_move('noise "move": "LEFT" noise', ["LEFT"])[0] == "LEFT"


class _Game:
    def __init__(self, seed, lag_frames):
        self.rng = random.Random(seed)
        self.rows = [[0] * 4 for _ in range(4)]
        self.lag_frames = lag_frames
        self.lag, self.shown = 0, None
        self._spawn()
        self._spawn()

    def _spawn(self):
        r, c = self.rng.choice([(r, c) for r in range(4) for c in range(4) if not self.rows[r][c]])
        self.rows[r][c] = 2 if self.rng.random() < 0.9 else 4

    def move(self, direction):
        after = apply_move(self.rows, direction)
        if after != self.rows:
            self.shown, self.lag = [row[:] for row in self.rows], self.lag_frames
            self.rows = after
            self._spawn()


def _play(monkeypatch, seed, lag_frames, start_over=False):
    game = _Game(seed, lag_frames)
    if start_over:  # the previous game's final board is still on screen
        game.rows = [[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]]
    tmp = tempfile.mkdtemp()
    count = {"n": 0}

    def render(*_a, **_k):
        rows = game.rows
        if game.lag > 0:
            game.lag -= 1
            rows = game.shown
        img = np.full((720, 1280, 3), 250, np.uint8)
        x, y, w = 511, 310, 258
        bg = np.clip(np.array(BOARD_BG) + HDMI_SHIFT, 0, 255)[::-1]
        cv2.rectangle(img, (x, y), (x + w, y + w), tuple(int(v) for v in bg), -1)
        for r in range(4):
            for c in range(4):
                col = np.clip(np.array(CANONICAL[rows[r][c]]) + HDMI_SHIFT, 0, 255)[::-1]
                x0, y0 = int(x + w * (GAP + (CELL + GAP) * c)), int(y + w * (GAP + (CELL + GAP) * r))
                cv2.rectangle(img, (x0, y0), (x0 + int(w * CELL), y0 + int(w * CELL)), tuple(int(v) for v in col), -1)
                if rows[r][c]:
                    cv2.putText(img, str(rows[r][c]), (x0 + 8, y0 + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 60, 60), 2)
        count["n"] += 1
        path = os.path.join(tmp, f"f{count['n']}.png")
        cv2.imwrite(path, img)
        return path

    class Nav:
        async def execute_navigation(self, target_node_label, context, **_k):
            if target_node_label.startswith("move_"):
                game.move(target_node_label[5:].upper())
            ok = True
            if target_node_label == "new_game":
                # The tap starts a new game; after a finished game the confirm "OK" is not
                # there, so the phone's new_game edge reports a failure.
                game.rows = [[0] * 4 for _ in range(4)]
                game._spawn()
                game._spawn()
                ok = not start_over
            context.record_step_immediately({"success": ok, "message": f"game -> {target_node_label}",
                                             "actions": [], "verifications": []})
            return {"success": ok}

    class Device:
        device_model = "android_mobile"
        navigation_executor = Nav()

    class Ctx:
        team_id = "t"

        def __init__(self):
            self.step_results, self.screenshot_paths = [], []

        def record_step_immediately(self, step):
            self.step_results.append(step)

        def add_screenshot(self, path):
            self.screenshot_paths.append(path)

    def evidence(_device, context, _name):
        context.add_screenshot(render())
        return _name

    monkeypatch.setattr(runner_mod, "capture_screenshot", render)
    monkeypatch.setattr(runner_mod, "capture_screenshot_for_script", evidence)
    monkeypatch.setattr(runner_mod, "FRAME_POLL_S", 0)
    monkeypatch.setattr(runner_mod, "BOARD_READ_TIMEOUT_S", 1)
    ctx = Ctx()
    data = runner_mod.GameRunner(Device(), ctx, "game2048-android-mobile", "tree", heuristic_decide,
                                 "heuristic", 3000, 600, 500, 64).run()
    return game, data, ctx


@pytest.mark.parametrize("lag_frames", [0, 4])
def test_runner_tracks_a_full_game(monkeypatch, lag_frames):
    game, data, ctx = _play(monkeypatch, seed=7, lag_frames=lag_frames)
    assert data["stop_reason"] == "game_over" and data["success"]
    assert data["board_resyncs"] == 0
    assert data["final_board"] == game.rows
    assert data["move_count"] > 100
    # one enriched step per move, carrying the decision and the board
    moves = [s for s in ctx.step_results if str(s.get("message", "")).startswith("Move ")]
    assert len(moves) == data["move_count"]
    assert moves[0]["verifications"][-1]["details"]["board_after"] is not None


def test_locate_board_ignores_a_square_piece_of_the_grid():
    """S21 HDMI: the capture shift sits near the strictest threshold, so only part of the grid
    passed it and that square piece was taken for the board (misreads, then input_not_applied)."""
    img = np.full((720, 1280, 3), 250, np.uint8)
    x, y, w = 511, 310, 258
    far = np.clip(np.array(BOARD_BG) + [27, 11, -6], 0, 255)[::-1]  # distance 44: fails 40
    near = np.clip(np.array(BOARD_BG) + [17, 17, 1], 0, 255)[::-1]  # distance 35: passes 40
    cv2.rectangle(img, (x, y), (x + w, y + w), tuple(int(v) for v in far), -1)
    cv2.rectangle(img, (x + 70, y + 70), (x + w, y + w), tuple(int(v) for v in near), -1)
    assert locate_board(img) == (x, y, w + 1, w + 1)


def test_runner_starts_after_a_finished_game(monkeypatch):
    """The last game's board is on screen and new_game "fails" (no confirm dialog to click
    "OK" on after game over) although the tap started a new game: the run must still play."""
    game, data, _ctx = _play(monkeypatch, seed=3, lag_frames=0, start_over=True)
    assert data["stop_reason"] == "game_over" and data["success"]
    assert data["move_count"] > 50
