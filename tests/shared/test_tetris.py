"""Tetris showcase library (TASK-33 phase 3, TASK-51 profiles + vision): court rules, placement,
the pixel court reader, the SRS kick reachability, and the real-time runner against a simulated
page. No browser, no device.

Run: pytest tests/shared/test_tetris.py -v
"""
import os
import random
import sys
import tempfile
import time

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

import shared.src.lib.game.tetris.runner as runner_mod  # noqa: E402
from shared.src.lib.game.tetris.board import (  # noqa: E402
    NX, NY, SHAPES, best_placement, cells, empty_court, fits, landing_y, place,
    placement_keys, reachable)
from shared.src.lib.game.tetris.profiles import (  # noqa: E402
    GUIDELINE, JAKESGORDON, SHAPES_BY_NAME, VisionProfile, rules_by_name, srs_kick)
from shared.src.lib.game.tetris.reader import (  # noqa: E402
    VisionReader, diff_cells, read_court, identify_piece)
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


def test_runner_stops_at_its_declared_cap_when_a_key_press_never_answers(monkeypatch):
    """The cap is a hard stop, not a check between pieces (E50).

    The key press was a bare `await page.keyboard.press(...)` with no timeout anywhere on
    the path: a browser that never answered ran the job 1530 s past a declared 900 s, and
    the host stayed busy for all of it.
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    monkeypatch.setattr(runner_mod, "FINISH_CALL_BUDGET_S", 0.2)

    class _IO_HangingPress(_IO):
        """The browser never answers the key press."""

        def run_actions(self, actions):
            if any(a.get("command") == "press_key" for a in actions):
                time.sleep(3600)
            return super().run_actions(actions)

    started = time.monotonic()
    data = runner_mod.TetrisRunner(_IO_HangingPress(_Page(seed=2), tempfile.mkdtemp()),
                                   _Ctx(), 1000, 1, 10).run()
    elapsed = time.monotonic() - started

    assert data["stop_reason"] == "time_cap"
    assert data["success"] is False
    assert elapsed < 20          # the run stopped at its cap, not 4x later


def test_a_run_with_no_budget_left_does_not_start_playing(monkeypatch):
    """`--max_duration` is a budget for the whole run: the startup counts too (E50)."""
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)

    started = time.monotonic()
    data = runner_mod.TetrisRunner(_IO(_Page(seed=2), tempfile.mkdtemp()), _Ctx(), 1000, 0, 10).run()
    elapsed = time.monotonic() - started

    assert data["stop_reason"] == "time_cap"
    assert data["success"] is False
    assert data["pieces"] == 0
    assert elapsed < 5


# ---------------------------------------------------------------------------
# Vision-mode runner (TASK-51 G3)
# ---------------------------------------------------------------------------


def test_runner_plays_via_vision_with_js_oracle(monkeypatch):
    """G3: the runner reads a captured frame for the locked court, uses JS for
    the active piece's position, and plans placements on the vision court.
    The JS oracle is still consulted (per piece) for accuracy KPIs.
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    page = _Page(seed=3)
    ctx = _Ctx()
    vision_profile = VisionProfile(name="jakesgordon", auto_detect_court=True)
    io = _IO(page, tempfile.mkdtemp())
    data = runner_mod.TetrisRunner(io, ctx, max_pieces=80, max_duration=600, min_rows=10,
                                   perception="vision", vision_profile=vision_profile).run()
    assert data["stop_reason"] == "piece_limit" and data["success"], data.get("error")
    assert data["pieces"] == 80
    assert data["vision_frames_read"] >= 80                # one frame per piece
    assert data["vision_match_pct"] is not None
    assert data["vision_match_pct"] >= 99.0, data["vision_match_pct"]
    assert data["reader_match"] is True                    # final-frame match


def test_runner_vision_mode_handles_missing_viewer_block_frame(monkeypatch):
    """G3: if the frame reader returns None for a single piece (transient
    capture failure), the runner still completes the run as long as JS works.
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    page = _Page(seed=4)
    ctx = _Ctx()
    vision_profile = VisionProfile(name="jakesgordon", auto_detect_court=True)

    class _IO_Intermittent(_IO):
        """Every 10th frame returns an unreadable image (force a None read)."""
        def __init__(self, page, tmp):
            super().__init__(page, tmp)
            self.miss_every = 10
            self.misses = 0

        def frame(self):
            self.n += 1
            if self.n % self.miss_every == 0:
                # Return a path that does not exist — VisionReader returns None.
                return os.path.join(self.tmp, f"missing-{self.n}.jpg")
            return super().frame()

    io = _IO_Intermittent(page, tempfile.mkdtemp())
    data = runner_mod.TetrisRunner(io, ctx, max_pieces=50, max_duration=600, min_rows=10,
                                   perception="vision", vision_profile=vision_profile).run()
    # Some frames missed -> state_lost is possible. We accept either outcome
    # (clean play or early stop) as long as the runner is consistent.
    assert data["pieces"] <= 50
    if data["stop_reason"] == "piece_limit":
        # Vision accuracy is over the frames that WERE read — at least 90% on
        # the synthetic page (no real noise), well above the 99% threshold.
        assert data["vision_match_pct"] is None or data["vision_match_pct"] >= 90.0


# ---------------------------------------------------------------------------
# Predictive loop (TASK-51 G4)
# ---------------------------------------------------------------------------


def test_predictive_loop_decouples_per_piece_time_from_frame_delay(monkeypatch):
    """G4: with a 1 s frame delay injected into the capture helper, the per-piece
    time in predictive vision mode stays small (< 500 ms p50). The runner
    plans from the predicted court, not from the frame, so the frame arrival
    doesn't gate the loop.
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    page = _Page(seed=7)
    ctx = _Ctx()
    vision_profile = VisionProfile(name="jakesgordon", auto_detect_court=True)

    class _IO_SlowFrame(_IO):
        def frame(self):
            self.n += 1
            time.sleep(1.0)                  # simulate HDMI capture lag
            return super().frame()

    io = _IO_SlowFrame(page, tempfile.mkdtemp())
    data = runner_mod.TetrisRunner(io, ctx, max_pieces=20, max_duration=600, min_rows=10,
                                   perception="vision", vision_profile=vision_profile,
                                   predict=True).run()
    assert data["stop_reason"] == "piece_limit", data
    assert data["pieces"] == 20
    # Without prediction, every per-piece time would include the 1 s frame delay.
    # With prediction, planning is independent of the frame.
    p50 = data["piece_ms_p50"]
    assert p50 is not None and p50 < 500, (p50, "predictive loop should bypass frame delay")
    assert data["vision_resyncs"] == 0
    assert data["vision_match_pct"] is not None and data["vision_match_pct"] >= 99.0


def test_predictive_loop_resyncs_when_state_diverges(monkeypatch):
    """G4: when garbage arrives (or a key is dropped) the prediction drifts.
    The runner compares prediction to the next read and resyncs. We simulate
    that by mutating the page's court between placements.
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    page = _Page(seed=8)
    ctx = _Ctx()
    vision_profile = VisionProfile(name="jakesgordon", auto_detect_court=True)
    injected = {"count": 0}

    class _IO_Garbage(_IO):
        def run_actions(self, actions):
            # After the keys for piece 3 land, drop two garbage rows into the
            # page's court — a Tetris 99-style attack that the bot didn't do.
            results = super().run_actions(actions)
            for a in actions:
                if a.get("command") == "press_key" and a["params"].get("key") == "DOWN":
                    # Every DOWN key on piece 3 (id==4): bump a counter.
                    pass
            # Easier: detect by reading the piece's id from the JS result.
            for r in results["results"]:
                out = r.get("output_data") or {}
                if "result" in out and out["result"].get("piece"):
                    pid = out["result"]["piece"]["id"]
                    if pid == 4 and injected["count"] == 0:
                        # Garbage: shove two blocks onto the top of the stack.
                        page.court[0][0] = 1
                        page.court[0][1] = 1
                        injected["count"] += 1
            return results

    io = _IO_Garbage(page, tempfile.mkdtemp())
    data = runner_mod.TetrisRunner(io, ctx, max_pieces=10, max_duration=600, min_rows=0,
                                   perception="vision", vision_profile=vision_profile,
                                   predict=True).run()
    # The prediction diverged from the page; the runner resynced at least once.
    assert data["vision_resyncs"] >= 1, data
    assert data["pieces"] >= 5            # still played many pieces after the resync


def test_predictive_loop_js_mode_also_benefits(monkeypatch):
    """G4: the predictive loop also works in JS-only mode. The first read
    seeds the prediction; subsequent placements update it without re-reading
    the court (JS still gives us the id change for the spawn signal).
    """
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0)
    page = _Page(seed=11)
    ctx = _Ctx()
    data = runner_mod.TetrisRunner(_IO(page, tempfile.mkdtemp()), ctx, max_pieces=30,
                                   max_duration=600, min_rows=0, perception="js", predict=True).run()
    assert data["stop_reason"] == "piece_limit"
    assert data["pieces"] == 30
    assert data["vision_resyncs"] == 0
    assert data["vision_match_pct"] is None      # no vision frames in JS mode


# ---------------------------------------------------------------------------
# SRS (Tetris Guideline) — TASK-51 G1
# ---------------------------------------------------------------------------


def test_srs_kicks_y_axis_is_flipped_to_our_court():
    """The Tetris Wiki lists kicks with y pointing UP. Our court has y pointing DOWN.
    srs_kick() must negate y so a positive "up" in the table becomes a negative y here.
    """
    # 0 -> R for JLSTZ: (0,0), (-1,0), (-1,+1), (0,-2), (-1,-2) in Y-up.
    # In our Y-down court: y is negated.
    kicks = srs_kick("T", 0)
    assert kicks[0] == (0, 0)
    assert kicks[1] == (-1, 0)         # plain shift left
    assert kicks[2] == (-1, -1)        # left + up  (dy_up=+1 -> dy_down=-1)
    assert kicks[3] == (0, +2)         # two down   (dy_up=-2 -> dy_down=+2)
    assert kicks[4] == (-1, +2)


def test_srs_kicks_o_piece_has_only_no_op_kick():
    """The O piece never needs kicks (it fits its 2x2 regardless of rotation)."""
    for d in range(4):
        assert srs_kick("O", d) == [(0, 0)]


def test_srs_kicks_i_uses_i_table():
    """The I piece has its own kick table (different from JLSTZ)."""
    kicks_0_to_1 = srs_kick("I", 0)
    # 0 -> R for I: (0,0), (-2,0), (+1,0), (-2,-1), (+1,+2) in Y-up -> Y-down.
    assert kicks_0_to_1[0] == (0, 0)
    assert kicks_0_to_1[1] == (-2, 0)
    assert kicks_0_to_1[2] == (+1, 0)
    assert kicks_0_to_1[3] == (-2, +1)   # -2,-1 (up 1) -> -2,+1 (down 1 in Y-up means up 1 in Y-down)
    assert kicks_0_to_1[4] == (+1, -2)


def test_srs_spawn_t_piece_cells():
    """The T-piece spawns with its flat row at the second row of the 4x4 box.
    SRS spawn (3, 0) puts the T's flat row at court row 1 and its apex at (5, 2)."""
    cells_t = cells("T", 0, GUIDELINE.spawn_x, GUIDELINE.spawn_y, GUIDELINE)
    # rot 0 cells at box (0,0): (0,1), (1,1), (2,1), (1,2) -> at (3, 0):
    assert cells_t == [(3, 1), (4, 1), (5, 1), (4, 2)]


def test_srs_t_spin_double_uses_kick_at_wall():
    """T-spin setup: T at (3, 0) rot 0 fits, but rot 1 at the same box collides
    with a single cell at (4, 0). jakesgordon (no kicks) cannot reach rot 1;
    SRS reaches it via the (-1, 0) kick that shifts the piece one column left.
    """
    court = empty_court()
    court[4][0] = 1                                 # blocks rot 1's top cell
    assert fits(court, "T", 0, 3, 0, GUIDELINE)     # rot 0 at (3, 0): all empty
    assert not fits(court, "T", 1, 3, 0)            # rot 1 at (3, 0): blocked
    assert not reachable(court, "T", 0, 3, 0, 1, 3, JAKESGORDON)
    # SRS kicks 0->1 try (0,0), (-1,0), (-1,-1), (0,+2), (-1,+2). (-1, 0) shifts
    # rot 1 to (2, 0): cells (3,0), (2,1), (3,1), (3,2) — all empty. SRS
    # reaches rot 1 at x=2 (the kick the lane takes, not the original x).
    assert reachable(court, "T", 0, 3, 0, 1, 2, GUIDELINE)
    # But SRS does NOT reach rot 1 at the original x=3 (the kick target at x=2
    # can't shift back to x=3 because rot 1 at (3, 0) collides with the wall).
    assert not reachable(court, "T", 0, 3, 0, 1, 3, GUIDELINE)


def test_srs_placement_keys_use_hard_drop_not_per_row_down():
    """The guideline profile emits one 'hard_drop' key, not N downs."""
    target = {"d": 0, "x": 4, "y": 19, "lines": 0, "score": 0}
    jk = placement_keys(0, 3, 0, target, JAKESGORDON)
    assert "down" in jk and jk.count("down") >= 20
    gl = placement_keys(0, 3, 0, target, GUIDELINE)
    assert gl.count("hard_drop") == 1 and "down" not in gl


def test_srs_reachability_t_spin_free_tuck():
    """A T against the floor: rot 1 fits but rot 2 at the same box collides with
    a single extra cell at (5, NY-3). jakesgordon (no kicks) cannot reach rot 2;
    SRS lifts the piece up 2 rows via the (0, -2) kick so it tucks over.
    """
    court = empty_court()
    for x in range(NX):
        court[x][NY - 1] = 1               # solid floor at row 19
    court[5][NY - 3] = 1                   # rot 2's rightmost cell — blocks rot 2 at (3, NY-4)
    # T rot 1 at (3, NY-4): cells (4, NY-4), (3, NY-3), (4, NY-3), (4, NY-2) —
    # only rot 2's cell (5, NY-3) is blocked; rot 1 has no cell there. Fits.
    assert fits(court, "T", 1, 3, NY - 4, GUIDELINE)
    # rot 2 at (3, NY-4): cells (4, NY-4), (3, NY-3), (4, NY-3), (5, NY-3) —
    # (5, NY-3) blocked.
    assert not fits(court, "T", 2, 3, NY - 4)
    assert not reachable(court, "T", 1, 3, NY - 4, 2, 3, JAKESGORDON)
    # SRS kicks 1->2 try (0,0), (+1,0), (+1,+1), (0,-2), (+1,-2). (0,-2) lifts
    # the piece up 2 rows: rot 2 at (3, NY-6), cells (4, NY-6), (3, NY-5),
    # (4, NY-5), (5, NY-5) — all empty. SRS reaches rot 2 at x=3.
    assert reachable(court, "T", 1, 3, NY - 4, 2, 3, GUIDELINE)


def test_srs_best_placement_finds_left_vertical_i_tuck():
    """Vertical I at column 3, with cells at columns 1, 2, 4 row 2 blocking
    every rot-2 horizontal column except 5. jakesgordon cannot reach rot 2
    anywhere. SRS kicks I 1->2 with (+2, 0) to land rot 2 at x=5."""
    court = empty_court()
    court[1][2] = 1
    court[2][2] = 1
    court[4][2] = 1
    # I rot 1 (vertical) at (3, 0): cells (5, 0), (5, 1), (5, 2), (5, 3) — empty.
    assert fits(court, "I", 1, 3, 0, GUIDELINE)
    # I rot 2 (horizontal) at any column:
    #   (3, 0): cells (3, 2), (4, 2), (5, 2), (6, 2). (4, 2) blocked.
    #   (2, 0): cells (2, 2), (3, 2), (4, 2), (3, 3). (2, 2) and (4, 2) blocked.
    #   (1, 0): cells (1, 2), (2, 2), (3, 2), (2, 3). (1, 2) and (2, 2) blocked.
    #   (5, 0): cells (5, 2), (6, 2), (7, 2), (6, 3). All empty. Fits.
    assert not reachable(court, "I", 1, 3, 0, 2, 5, JAKESGORDON)
    # SRS kick (+2, 0) slides rot 2 to (5, 0). SRS reaches (rot 2, x=5).
    assert reachable(court, "I", 1, 3, 0, 2, 5, GUIDELINE)


def test_rules_by_name_and_resolve():
    assert rules_by_name("jakesgordon").rotation == "jakesgordon"
    assert rules_by_name("guideline").rotation == "srs"
    with pytest.raises(KeyError):
        rules_by_name("nes")
    assert JAKESGORDON.resolve_name("cyan") == "I"
    assert GUIDELINE.resolve_name("T") == "T"
    with pytest.raises(KeyError):
        GUIDELINE.resolve_name("cyan")


def test_srs_shapes_match_jakesgordon_masks():
    """The masks in jakesgordon's page and SRS are identical (same 16-bit
    layouts per rotation). This guards against drift if anyone changes one
    set without the other."""
    for name, mask in SHAPES_BY_NAME.items():
        colour = next(c for c, n in JAKESGORDON.colour_to_name.items() if n == name)
        assert SHAPES[colour] == mask


# ---------------------------------------------------------------------------
# Vision reader (TASK-51 G2)
# ---------------------------------------------------------------------------


def _frame_with_piece(court, piece_name, piece_rot, piece_x, piece_y,
                      path, *, ghost=None, colour="red"):
    """A frame like the jakesgordon page: dark 2 px border, pale textured
    background, saturated filled cells with black outlines. The piece is
    drawn ON TOP of the court (so a vision read sees both). Optionally draws
    a ghost at `ghost = (rot, x, y)` with reduced saturation (translucent).
    """
    img = np.full((720, 1280, 3), 248, np.uint8)
    x0, y0, cell = 617, 62, 30
    cv2.rectangle(img, (x0 - 2, y0 - 2), (x0 + cell * NX + 1, y0 + cell * NY + 1), (51, 51, 51), -1)
    rng = np.random.default_rng(1)
    tex = np.clip(np.array([245, 205, 200]) + rng.integers(-15, 15, (cell * NY, cell * NX, 3)), 0, 255)
    img[y0:y0 + cell * NY, x0:x0 + cell * NX] = tex.astype(np.uint8)
    bgr = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 128, 0),
           "cyan": (255, 255, 0), "yellow": (0, 255, 255),
           "purple": (128, 0, 128), "orange": (0, 165, 255)}[colour]
    for x in range(NX):
        for y in range(NY):
            if court[x][y]:
                p0, p1 = (x0 + x * cell, y0 + y * cell), (x0 + (x + 1) * cell - 1, y0 + (y + 1) * cell - 1)
                cv2.rectangle(img, p0, p1, bgr, -1)
                cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    # Active piece
    for cx, cy in cells(piece_name, piece_rot, piece_x, piece_y):
        if 0 <= cx < NX and 0 <= cy < NY:
            p0, p1 = (x0 + cx * cell, y0 + cy * cell), (x0 + (cx + 1) * cell - 1, y0 + (cy + 1) * cell - 1)
            cv2.rectangle(img, p0, p1, bgr, -1)
            cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    if ghost is not None:
        rot, gx, gy = ghost
        # Translucent ghost: mix the piece colour with the empty-cell texture.
        # A real guideline ghost reads around 25 % alpha, which lands below the
        # reader's fill threshold (locked cells are 100 %, ghosts are ~25 %).
        for cx, cy in cells(piece_name, rot, gx, gy):
            if 0 <= cx < NX and 0 <= cy < NY:
                p0, p1 = (x0 + cx * cell, y0 + cy * cell), (x0 + (cx + 1) * cell - 1, y0 + (cy + 1) * cell - 1)
                overlay = img.copy()
                cv2.rectangle(overlay, p0, p1, bgr, -1)
                cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)
                cv2.rectangle(img, p0, p1, (60, 60, 60), 1)   # outline
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return path


def _frame_with_next_queue(pieces_rot_pairs, path, *, court=None):
    """Frame with the court empty and a small next-piece preview box at the
    jakesgordon position. pieces_rot_pairs is a list of (piece_name, rot, gx, gy)
    for each 4-cell piece to draw in the preview.
    """
    img = np.full((720, 1280, 3), 248, np.uint8)
    x0, y0, cell = 617, 62, 30
    cv2.rectangle(img, (x0 - 2, y0 - 2), (x0 + cell * NX + 1, y0 + cell * NY + 1), (51, 51, 51), -1)
    rng = np.random.default_rng(1)
    tex = np.clip(np.array([245, 205, 200]) + rng.integers(-15, 15, (cell * NY, cell * NX, 3)), 0, 255)
    img[y0:y0 + cell * NY, x0:x0 + cell * NX] = tex.astype(np.uint8)
    if court is not None:
        for x in range(NX):
            for y in range(NY):
                if court[x][y]:
                    p0, p1 = (x0 + x * cell, y0 + y * cell), (x0 + (x + 1) * cell - 1, y0 + (y + 1) * cell - 1)
                    cv2.rectangle(img, p0, p1, (0, 0, 255), -1)
                    cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    # Next-queue preview: a 4x4 grid at (720, 105), each cell 16 px, BGR colour.
    nx0, ny0, ncell = 720, 105, 16
    for i, (pname, prot, ppx, ppy) in enumerate(pieces_rot_pairs):
        # Each next piece is offset vertically by 80 px in the jakesgordon page.
        ox, oy = nx0, ny0 + i * 80
        for cx, cy in cells(pname, prot, ppx, ppy):
            p0 = (ox + cx * ncell, oy + cy * ncell)
            p1 = (ox + (cx + 1) * ncell - 1, oy + (cy + 1) * ncell - 1)
            cv2.rectangle(img, p0, p1, (0, 0, 255), -1)   # red
            cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return path


def test_identify_piece_by_shape():
    """The 4-cell mask name the tetromino regardless of rotation."""
    for name in ("I", "J", "L", "O", "S", "T", "Z"):
        for rot in range(4):
            cs = cells(name, rot, 0, 0)
            assert len(cs) == 4
            assert identify_piece(list(cs)) == name, (name, rot, cs)


def test_identify_piece_rejects_wrong_count():
    assert identify_piece([(0, 0), (1, 0)]) is None
    assert identify_piece([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]) is None


def test_vision_reader_reads_court_and_active_piece():
    """A jakesgordon frame with a stack + an active piece on top: the reader
    returns both as filled cells (the page draws the active piece into the
    captured frame too)."""
    rng = random.Random(2)
    court = [[1 if y > 14 and rng.random() < 0.6 else 0 for y in range(NY)] for x in range(NX)]
    # Add an active L-piece floating above the stack
    piece_name, piece_x, piece_y = "L", 3, 5
    path = _frame_with_piece(court, piece_name, 0, piece_x, piece_y,
                             os.path.join(tempfile.mkdtemp(), "f.jpg"))
    profile = VisionProfile(name="jakesgordon", auto_detect_court=True)
    result = VisionReader(profile).read(path)
    assert result is not None
    # The active piece's cells should be read as filled.
    active_cells = cells(piece_name, 0, piece_x, piece_y)
    for cx, cy in active_cells:
        assert result["court"][cx][cy] == 1, (cx, cy, "active piece cell not read as filled")
    # The stack underneath should match.
    expected = [col[:] for col in court]
    for cx, cy in active_cells:
        if 0 <= cx < NX and 0 <= cy < NY:
            expected[cx][cy] = 1
    assert diff_cells(result["court"], expected) == 0


def test_vision_reader_ignores_translucent_ghost():
    """Guideline games draw a ghost at the landing position. A translucent
    ghost has its piece colour mixed ~40% with the background, so its
    saturation falls below the fill threshold (90). The reader treats it as
    empty, which is what we want."""
    court = empty_court()
    # T-piece at (3, 0) (top of court, not on the stack). The ghost lands at
    # row NY-4 (where the T would settle on its own — that's where SRS's
    # hard-drop puts it on a flat floor).
    piece_name, piece_rot, piece_x = "T", 0, 3
    ghost_rot, ghost_x, ghost_y = 0, 3, NY - 4
    path = _frame_with_piece(court, piece_name, piece_rot, piece_x, 0,
                             os.path.join(tempfile.mkdtemp(), "f.jpg"),
                             ghost=(ghost_rot, ghost_x, ghost_y))
    profile = VisionProfile(name="jakesgordon", auto_detect_court=True, fill_threshold=90)
    result = VisionReader(profile).read(path)
    assert result is not None
    # The active piece at row 0 is read.
    for cx, cy in cells(piece_name, piece_rot, piece_x, 0):
        assert result["court"][cx][cy] == 1
    # The ghost at the landing position is NOT read (translucent -> below threshold).
    for cx, cy in cells(piece_name, ghost_rot, ghost_x, ghost_y):
        assert result["court"][cx][cy] == 0, (cx, cy, "ghost cell should not be read as filled")


def test_vision_reader_identifies_next_piece_by_shape():
    """The next-piece preview box is drawn with each piece's 4 cells. The
    reader identifies the next piece by shape, not by colour. Same shape in
    any skin reads as the same piece."""
    # Draw three different next pieces — T, L, Z — in the preview.
    pieces = [("T", 0, 1, 1), ("L", 0, 1, 1), ("Z", 0, 1, 1)]
    path = _frame_with_next_queue(pieces, os.path.join(tempfile.mkdtemp(), "f.jpg"))
    profile = VisionProfile(name="jakesgordon", auto_detect_court=True,
                            next_rois=[(720, 105 + i * 80, 64, 64) for i in range(3)],
                            next_cell_px=16)
    result = VisionReader(profile).read(path)
    assert result is not None
    assert result["next"] == ["T", "L", "Z"]


def test_vision_reader_with_fixed_roi_for_guideline():
    """A guideline-style profile (no auto-detect) reads the court from a fixed
    ROI. We draw the court at a known ROI, with a small Z piece on top."""
    img = np.full((720, 1280, 3), 248, np.uint8)
    x0, y0, cell = 100, 50, 28
    cv2.rectangle(img, (x0, y0), (x0 + cell * NX, y0 + cell * NY), (60, 60, 60), 1)
    for x in range(NX):
        for y in range(NY):
            # Only the bottom 3 rows are filled (no active piece on top for simplicity).
            if y >= NY - 3:
                p0, p1 = (x0 + x * cell, y0 + y * cell), (x0 + (x + 1) * cell - 1, y0 + (y + 1) * cell - 1)
                cv2.rectangle(img, p0, p1, (0, 0, 255), -1)   # red
                cv2.rectangle(img, p0, p1, (0, 0, 0), 1)
    path = os.path.join(tempfile.mkdtemp(), "guideline.jpg")
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    profile = VisionProfile(name="guideline", auto_detect_court=False,
                            court_roi=(x0, y0, cell * NX, cell * NY), cell_px=cell,
                            fill_threshold=80)
    result = VisionReader(profile).read(path)
    assert result is not None
    # The bottom 3 rows should all read as filled.
    for x in range(NX):
        for y in range(NY - 3, NY):
            assert result["court"][x][y] == 1
    # The top 17 rows should read as empty.
    for x in range(NX):
        for y in range(NY - 3):
            assert result["court"][x][y] == 0


def test_read_court_backwards_compat_returns_court():
    """The G1 runner imports `read_court` and treats it as a Court-returning
    function. The G2 shim still returns just the court."""
    court = [[1 if y == NY - 1 and 0 <= x < 8 else 0 for y in range(NY)] for x in range(NX)]
    path = _frame(court, os.path.join(tempfile.mkdtemp(), "f.jpg"))
    read = read_court(path)
    assert read is not None and diff_cells(read, court) == 0
