"""Tetris showcase library (TASK-33 phase 3): court rules, placement, the pixel court reader and
the real-time runner against a simulated page. No browser, no device.

Run: pytest tests/shared/test_tetris.py -v
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

import shared.src.lib.game.tetris.runner as runner_mod  # noqa: E402
from shared.src.lib.game.tetris.board import (  # noqa: E402
    NX, NY, SHAPES, best_placement, cells, empty_court, fits, landing_y, place, placement_keys)
from shared.src.lib.game.tetris.reader import diff_cells, read_court  # noqa: E402
from shared.src.lib.game.tetris.ui import build_manifest  # noqa: E402

COLOURS = {"cyan": (0, 255, 255), "blue": (0, 0, 255), "orange": (255, 165, 0), "yellow": (255, 255, 0),
           "green": (0, 128, 0), "purple": (128, 0, 128), "red": (255, 0, 0)}


def test_place_clears_full_rows_like_the_page():
    court = empty_court()
    for x in range(NX - 1):          # bottom row full except the last column
        court[x][NY - 1] = 1
    court[0][NY - 2] = 1             # one block above it
    # a vertical I in the last column fills the bottom row
    y = landing_y(court, "cyan", 1, NX - 3)  # mask 0x2222: column 2 of the 4x4 box
    after, placed, lines = place(court, "cyan", 1, NX - 3, y)
    assert lines == 1
    assert after[0][NY - 1] == 1 and after[0][NY - 2] == 0  # the block above moved down
    assert sum(after[NX - 1]) == 3                           # the I's 3 other cells, shifted down


def test_best_placement_and_keys():
    court = empty_court()
    target = best_placement(court, "yellow", 0, 4, 0)
    assert target and target["y"] == NY - 2
    keys = placement_keys(0, 4, 0, target)
    assert keys.count("down") == target["y"] + 1  # + the DOWN that locks it
    assert keys.count("left") + keys.count("right") == abs(target["x"] - 4)
    assert "rotate" not in keys


def _frame(court, path, piece=None):
    """A frame like the page: dark 2 px border, pale texture, flat colour blocks with outlines."""
    img = np.full((720, 1280, 3), 248, np.uint8)
    x0, y0, cell = 617, 62, 30
    cv2.rectangle(img, (x0 - 2, y0 - 2), (x0 + cell * NX + 1, y0 + cell * NY + 1), (51, 51, 51), -1)
    rng = np.random.default_rng(1)
    tex = np.clip(np.array([245, 205, 200]) + rng.integers(-15, 15, (cell * NY, cell * NX, 3)), 0, 255)
    img[y0:y0 + cell * NY, x0:x0 + cell * NX] = tex.astype(np.uint8)
    names = list(COLOURS)
    for x in range(NX):
        for y in range(NY):
            if court[x][y]:
                r, g, b = COLOURS[names[(x + y) % len(names)]]
                p0, p1 = (x0 + x * cell, y0 + y * cell), (x0 + (x + 1) * cell - 1, y0 + (y + 1) * cell - 1)
                cv2.rectangle(img, p0, p1, (b, g, r), -1)
                cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return path


def test_reader_reads_a_jpeg_frame():
    rng = random.Random(4)
    court = [[1 if y > 10 and rng.random() < 0.6 else 0 for y in range(NY)] for x in range(NX)]
    path = _frame(court, os.path.join(tempfile.mkdtemp(), "f.jpg"))
    read = read_court(path)
    assert read is not None and diff_cells(read, court) == 0


class _Page:
    """The page's rules: one key per frame is not modelled, keys apply at once."""

    def __init__(self, seed, top_out_after=None):
        self.rng = random.Random(seed)
        self.court = empty_court()
        self.playing, self.rows, self.score, self.ids = False, 0, 0, 0
        self.top_out_after = top_out_after
        self.piece = None

    def spawn(self):
        t = self.rng.choice(list(SHAPES))
        self.ids += 1
        self.piece = {"id": self.ids, "t": t, "x": self.rng.randint(0, NX - 4), "y": 0, "d": 0}
        if not fits(self.court, t, 0, self.piece["x"], 0) or (self.top_out_after and self.ids > self.top_out_after):
            self.playing = False

    def key(self, k):
        if k == "SPACE" and not self.playing:
            self.court, self.rows, self.playing = empty_court(), 0, True
            self.spawn()
            return
        if not self.playing:
            return
        p = self.piece
        if k == "ESCAPE":
            self.playing = False
        elif k == "UP" and fits(self.court, p["t"], (p["d"] + 1) % 4, p["x"], p["y"]):
            p["d"] = (p["d"] + 1) % 4
        elif k in ("LEFT", "RIGHT") and fits(self.court, p["t"], p["d"], p["x"] + (1 if k == "RIGHT" else -1), p["y"]):
            p["x"] += 1 if k == "RIGHT" else -1
        elif k == "DOWN":
            if fits(self.court, p["t"], p["d"], p["x"], p["y"] + 1):
                p["y"] += 1
            else:  # lands: lock, clear rows, next piece
                self.court, _, lines = place(self.court, p["t"], p["d"], p["x"], p["y"])
                self.rows += lines
                self.score += 10 + 100 * lines
                self.spawn()

    def state(self):
        court = "".join("1" if self.court[x][y] else "0" for x in range(NX) for y in range(NY))
        return {"playing": self.playing, "score": self.score, "rows": self.rows, "step": 0.5,
                "piece": dict(self.piece) if self.piece else None, "next": "cyan", "court": court}


class _IO:
    def __init__(self, page, tmp):
        self.page, self.tmp, self.n = page, tmp, 0
        tree = build_manifest()["trees"][0]
        self.edges = {(e["source_node_id"], e["target_node_id"]): e["action_sets"][0]["actions"] for e in tree["edges"]}

    def edge_actions(self, source, target):
        return list(self.edges.get((source, target), []))

    def run_actions(self, actions):
        results = []
        for a in actions:
            out = {}
            if a["command"] == "press_key":
                self.page.key(a["params"]["key"])
            elif a["command"] == "execute_javascript":
                out = {"result": self.page.state()}
            results.append({"success": True, "output_data": out})
        return {"success": True, "results": results}

    def navigate(self, target):
        for a in self.edges.get(("game", target), []):
            if a["command"] == "press_key":
                self.page.key(a["params"]["key"])
        if target == "game_over":
            return {"success": not self.page.playing}
        return {"success": True}

    def frame(self):
        self.n += 1
        court = [col[:] for col in self.page.court]
        p = self.page.piece
        if p:  # the page also draws the current piece
            for cx, cy in cells(p["t"], p["d"], p["x"], p["y"]):
                if 0 <= cx < NX and 0 <= cy < NY:
                    court[cx][cy] = 1
        return _frame(court, os.path.join(self.tmp, f"f{self.n}.jpg"))

    def evidence(self, name):
        return self.frame()


class _Ctx:
    team_id = "t"

    def __init__(self):
        self.step_results, self.screenshot_paths = [], []

    def record_step_immediately(self, step):
        self.step_results.append(step)


def _run(monkeypatch, page, max_pieces):
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    ctx = _Ctx()
    data = runner_mod.TetrisRunner(_IO(page, tempfile.mkdtemp()), ctx, max_pieces, 600, 10).run()
    return data, ctx


def test_runner_plays_to_the_piece_limit(monkeypatch):
    data, ctx = _run(monkeypatch, _Page(seed=2), max_pieces=150)
    assert data["stop_reason"] == "piece_limit" and data["success"], data.get("error")
    assert data["pieces"] == 150 and data["missed_pieces"] == 0
    assert data["rows"] >= 50                     # ~2.5 pieces per row with this heuristic
    assert data["reader_match"] is True           # pixels vs page, current piece included
    assert any(s["message"].startswith("Pieces 1-25") for s in ctx.step_results)


def test_runner_ends_on_game_over(monkeypatch):
    data, _ = _run(monkeypatch, _Page(seed=5, top_out_after=40), max_pieces=1000)
    assert data["stop_reason"] == "game_over"
    assert data["pieces"] == 40
    assert data["success"] == (data["rows"] >= 10)
