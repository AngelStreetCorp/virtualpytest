"""
Real-time Tetris game loop (TASK-33 phase 3, TASK-51 G3/G4).

The userinterface tree holds the device specifics: the entry edge opens the
page, the action nodes under `game` carry the keys (rotate, left, right,
down, hard_drop, start, quit) and the `game` / `game_over` nodes carry the
checks. The runner reads each action's actions from the loaded tree once
and fires them in one batch through `ExecutionOrchestrator.execute_actions`,
with `wait_time` 0 between keys (real time).

Per piece:

  - read state (one `execute_javascript` action OR a captured frame),
  - plan the placement with `best_placement`,
  - send rotations + shifts + drop keys.

The state source is the `perception` flag (TASK-51 G3):

  - "js"      (default, web + jakesgordon). The page's JS exposes `blocks`,
              `current`, `next`, `playing`, `score`, `rows`, `step`. Fast,
              no capture lag. Used by the original TASK-33 runner.
  - "vision"  (TASK-51 G3). The runner reads a captured frame and the
              `VisionReader` returns the locked court + the next queue. The
              JS still runs as the oracle: it supplies the active piece's
              position + id (so we know when a new piece spawns) and the
              score / rows for accuracy KPIs.

Predictive loop (TASK-51 G4): in vision mode the runner predicts the court
*after* each placement (the rules are deterministic, as in 2048) and plans
the next piece from the preview. A frame arriving later *confirms* the
prediction; a mismatch (garbage, a missed key, animation frame) triggers a
resync. The per-piece time is no longer gated by the frame's capture lag.
The runner still waits for the new piece's id (the first confirmation) so
the bot doesn't lock two pieces at the same time.

Device access goes through an IO object: VptIO (navigation / action
executors and the capture helper) or a local Playwright stand-in for
development (test_scripts/game/local/).
"""

import asyncio
import json
import statistics
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .board import (NX, NY, PIECE_NAME_BY_COLOUR, best_placement, cells,
                    court_from_string, court_rows, place, placement_keys)
from .profiles import VisionProfile
from .reader import VisionReader, diff_cells

UI_NAME = "tetris-web"
UI_PREFIX = "tetris-"
# Keys the runner reads from the tree once at start. The web UI has these;
# platform-specific UIs (tetris-switch, tetris-android-mobile) define their
# own subsets — the runner skips any it doesn't use.
KEY_NODES = ("start", "rotate", "rotate_ccw", "left", "right", "down",
             "soft_drop", "hard_drop", "hold", "quit")
REPORT_EVERY = 25
NEW_PIECE_TIMEOUT_S = 3.0
SETTLE_S = 1.5
# How long to wait between polls while the game has not dropped the next piece yet. Tetris
# gravity is around a second, so this costs nothing in latency -- but without it the wait was
# a hot spin: it re-read the page through the host's single Playwright controller loop as fast
# as that loop would answer, with no sleep anywhere on the path. Every poll was a browser
# round-trip competing with the after-action screenshot the same loop had to serve, so the
# runner starved the loop it was waiting on and a run stopped fitting in its time budget
# (BUG-0841).
PIECE_POLL_S = 0.05
# The budget the runner spends on the finish sequence (quit key, final state read, final
# screenshot) once the play is over. It sits outside the play cap on purpose: the run must
# still write its result after it stopped.
FINISH_CALL_BUDGET_S = 10.0


class _TimeCapReached(Exception):
    """The run spent its time budget, or a device call did not answer in time."""


def resolve_userinterface(requested: Optional[str], device_model: str,
                       team_id: str) -> Optional[str]:
    """The tetris-* userinterface for this device. An explicit tetris-* name
    wins; "auto" picks the first tetris-* userinterface whose `models[]`
    matches the device model.
    """
    if requested and requested.startswith(UI_PREFIX):
        return requested
    from shared.src.lib.config.device_capabilities import model_matches_any
    from shared.src.lib.database.userinterface_db import get_all_userinterfaces
    for ui in sorted(get_all_userinterfaces(team_id) or [], key=lambda u: u.get("name", "")):
        if ui.get("name", "").startswith(UI_PREFIX) and model_matches_any(device_model, ui.get("models") or []):
            return ui["name"]
    return None


def resolve_profile(userinterface: str) -> str:
    """The game profile for a userinterface. tetris-web is jakesgordon; the
    Switch / NSO UIs are guideline. Override with an explicit --profile name.
    """
    from .profiles import rules_by_name
    if userinterface == "tetris-web":
        return "jakesgordon"
    if userinterface.startswith("tetris-"):
        # tetris-switch, tetris-android-mobile, tetris99-switch, ... default to
        # guideline. New UIs override this.
        return "guideline"
    raise KeyError(f"unknown Tetris userinterface {userinterface!r}")


def resolve_vision_profile(profile_name: str) -> VisionProfile:
    """The vision profile that matches a game profile."""
    from .profiles import JAKESGORDON_VISION, GUIDELINE_VISION
    if profile_name == "jakesgordon":
        return JAKESGORDON_VISION
    if profile_name == "guideline":
        return GUIDELINE_VISION
    raise KeyError(f"unknown Tetris game profile {profile_name!r}")

JS_STATE = """() => {
  if (typeof playing === 'undefined') return null;
  if (current && current.__vpt === undefined) { window.__vptPieces = (window.__vptPieces || 0) + 1; current.__vpt = window.__vptPieces; }
  let court = '';
  for (let x = 0; x < 10; x++) for (let y = 0; y < 20; y++) court += (blocks[x] && blocks[x][y]) ? '1' : '0';
  return {playing, score, rows, step,
          piece: current ? {id: current.__vpt, t: current.type.color, x: current.x, y: current.y, d: current.dir} : null,
          next: next ? next.type.color : null, court};
}"""


class VptIO:
    """Device access through the executors and the capture helper only."""

    def __init__(self, device, context, tree_id: str, userinterface: str):
        self.device, self.context, self.tree_id, self.userinterface = device, context, tree_id, userinterface

    def navigate(self, node: str) -> Dict[str, Any]:
        return asyncio.run(self.device.navigation_executor.execute_navigation(
            tree_id=self.tree_id, userinterface_name=self.userinterface, target_node_label=node,
            team_id=self.context.team_id, context=self.context))

    def edge_actions(self, source: str, target: str) -> List[Dict[str, Any]]:
        graph = getattr(self.device.navigation_executor, "unified_graph", None)
        data = graph.get_edge_data(source, target) if graph is not None else None
        if not data:
            return []
        sets = data.get("action_sets") or []
        chosen = next((s for s in sets if s.get("id") == data.get("default_action_set_id")), sets[0] if sets else {})
        return list(chosen.get("actions") or [])

    def run_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        return asyncio.run(ExecutionOrchestrator.execute_actions(
            self.device, actions, team_id=self.context.team_id, context=self.context))

    def frame(self) -> Optional[str]:
        from shared.src.lib.utils.device_utils import capture_screenshot
        return capture_screenshot(self.device)

    def evidence(self, name: str) -> str:
        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
        captured = capture_screenshot_for_script(self.device, self.context, name)
        return self.context.screenshot_paths[-1] if captured and self.context.screenshot_paths else ""


def _pct(values: List[float], p: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    return int(ordered[min(len(ordered) - 1, int(len(ordered) * p))])


def _js_result(result: Dict[str, Any]) -> Any:
    """The value returned by the last execute_javascript action of a batch."""
    for r in reversed(result.get("results") or []):
        out = r.get("output_data") or {}
        if "result" in out:
            return out["result"]
    return None


def _cells_in(court, piece, profile) -> None:
    """Set the active piece's cells to 0 in `court` (in place). Used when we
    have a frame that already shows the active piece and we need the locked
    stack only."""
    for cx, cy in cells(piece["t"], piece["d"], piece["x"], piece["y"], profile):
        if 0 <= cx < NX and 0 <= cy < NY:
            court[cx][cy] = 0


class TetrisRunner:
    def __init__(self, io, context, max_pieces: int, max_duration: int, min_rows: int,
                 perception: str = "js", rules=None, vision_profile: Optional[VisionProfile] = None,
                 predict: bool = False):
        if perception not in ("js", "vision"):
            raise ValueError(f"perception must be 'js' or 'vision', got {perception!r}")
        self.io = io
        self.context = context
        self.max_pieces = max_pieces
        self.max_duration = max_duration
        self.min_rows = min_rows
        self.perception = perception
        self.rules = rules
        # The hard stop of the run: `--max_duration` is a budget for the WHOLE run, not
        # a check between pieces (E50). Set when the run starts.
        self._deadline: Optional[float] = None
        self.vision_profile = vision_profile
        self.vision_reader = VisionReader(vision_profile) if vision_profile else None
        # Predictive loop (TASK-51 G4): the runner keeps a `predicted_court`
        # that mirrors what the rules say will happen after each placement.
        # The next placement plans on that, never on a frame. Frames are still
        # read (vision mode) to *confirm* the prediction; a mismatch forces a
        # resync. The per-piece time no longer waits for capture lag.
        self.predict = predict
        self.predicted_court: Optional[List[List[int]]] = None
        self.keys: Dict[str, List[Dict[str, Any]]] = {}
        self.data: Dict[str, Any] = {
            "userinterface": UI_NAME, "player": "heuristic", "strategy": "el-tetris",
            "perception": perception, "predict": predict,
            "pieces": 0, "rows": 0, "score": 0, "max_speed_s": None, "stop_reason": "",
            "pieces_by_type": {}, "key_presses": 0,
            "decision_ms_p50": None, "decision_ms_max": None,
            "piece_ms_p50": None, "piece_ms_p95": None, "state_ms_p50": None, "keys_ms_per_key": None,
            "missed_pieces": 0, "reader_match": None, "reader_diff_cells": None,
            "vision_cells_total": 0, "vision_cells_matched": 0, "vision_match_pct": None,
            "vision_frames_read": 0, "vision_resyncs": 0,
            "final_court": [], "play_duration_s": 0.0,
        }

    # --- device helpers --------------------------------------------------------------
    def _budget_left(self) -> Optional[float]:
        """Seconds left before the declared cap, None when no cap is in force."""
        if self._deadline is None:
            return None
        return self._deadline - time.monotonic()

    def _call(self, fn, *args, budget: Optional[float] = None, **kwargs):
        """Run a device call, bounded by the remaining time budget.

        The cap was only checked between pieces, so a key press the browser never
        answered ran the job 1530 s past a declared 900 s (E50). The call runs in a
        worker thread and is abandoned when the budget is spent, so a hung device
        call can no longer eat the whole run.
        """
        left = self._budget_left() if budget is None else budget
        if left is None:
            return fn(*args, **kwargs)
        if left <= 0:
            raise _TimeCapReached()
        outcome: Dict[str, Any] = {}

        def _target():
            try:
                outcome['value'] = fn(*args, **kwargs)
            except BaseException as exc:   # noqa: BLE001 - re-raised in the caller
                outcome['error'] = exc

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        worker.join(timeout=left)
        if worker.is_alive():
            raise _TimeCapReached()
        if 'error' in outcome:
            raise outcome['error']
        return outcome.get('value')

    def _try_call(self, fn, *args, budget: float = FINISH_CALL_BUDGET_S, default=None, **kwargs):
        """A bounded call that never raises: the finish sequence must always end."""
        try:
            return self._call(fn, *args, budget=budget, **kwargs)
        except _TimeCapReached:
            return default
        except Exception:
            return default

    def state(self, budget: Optional[float] = None) -> Optional[Dict[str, Any]]:
        return _js_result(self._call(self.io.run_actions, [{"command": "execute_javascript",
                                                            "action_type": "web",
                                                            "params": {"script": JS_STATE, "wait_time": 0}}],
                                     budget=budget))

    def press(self, names: List[str], budget: Optional[float] = None) -> bool:
        """Send a batch of inputs by name. The runner reads each name's actions
        from the loaded tree once at start; absent names (a `hold` on a tree
        that doesn't define one) are skipped silently."""
        actions = []
        for name in names:
            for action in self.keys.get(name, []):
                a = json.loads(json.dumps(action))
                a.setdefault("params", {})["wait_time"] = 0
                actions.append(a)
        if not actions:
            return True
        return bool(self._call(self.io.run_actions, actions, budget=budget).get("success", True))

    # --- state readers ---------------------------------------------------------------
    def _read_state(self) -> Optional[Dict[str, Any]]:
        """Per-piece state: court (locked, without active piece) + active piece
        info. The source depends on `self.perception`.

        Returns None when the page state cannot be read at all (the runner
        treats this as `state_lost`). Returns a dict with `playing: False`
        when the game ended cleanly so the caller can `break` instead.
        """
        s = self.state()
        if not s:
            return None
        js_court = court_from_string(s["court"]) if s.get("court") else None
        if not s.get("playing"):
            return {"playing": False, "court": js_court or [[0] * NY for _ in range(NX)],
                    "piece": None, "rows": s["rows"], "score": s["score"],
                    "step": s.get("step", 0), "next": s.get("next"), "frame": None}
        if self.perception == "js":
            return {"court": js_court, "piece": s["piece"], "rows": s["rows"],
                    "score": s["score"], "step": s["step"], "next": s.get("next"),
                    "frame": None, "js_court": js_court}
        # vision
        frame = self._call(self.io.frame)
        if not frame or not self.vision_reader:
            return None
        result = self.vision_reader.read(frame)
        if result is None:
            return None
        self.data["vision_frames_read"] += 1
        court = [col[:] for col in result["court"]]
        # The frame shows both the locked stack AND the active piece on top.
        # Subtract the active piece so the placement AI plans on the locked
        # cells only. Use the SAME piece position we just got from JS so the
        # subtraction is consistent with the JS oracle we report against.
        if s.get("piece"):
            _cells_in(court, s["piece"], self.rules)
        return {"court": court, "piece": s["piece"], "rows": s["rows"],
                "score": s["score"], "step": s["step"], "next": s.get("next"),
                "frame": frame, "vision_next": result.get("next"),
                "js_court": js_court}

    # --- report ----------------------------------------------------------------------
    def record_step(self, message: str, success: bool, node: str, details: Dict[str, Any],
                    screenshot: str = "", started: Optional[float] = None) -> None:
        now = time.time()
        started = started or now
        self.context.record_step_immediately({
            "success": success, "message": message, "from_node": node, "to_node": node,
            "execution_time_ms": int((now - started) * 1000),
            "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
            "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "screenshot_path": screenshot or None, "step_end_screenshot_path": screenshot or None,
            "action_screenshots": [screenshot] if screenshot else [], "actions": [],
            "verifications": [{"verification_type": "tetris", "command": "play", "label": message,
                               "success": success, "details": details}],
            "verification_results": [], "step_category": "tetris",
        })

    def _fail(self, reason: str, error: str) -> Dict[str, Any]:
        self.data.update({"stop_reason": reason, "success": False, "error": error})
        return self.data

    # --- game ------------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        data = self.data
        started = time.time()
        # `--max_duration` is the hard stop of the whole run: the budget starts now, so
        # the startup (tree, navigation, first read) is part of it and nothing can push
        # the play past the declared cap (E50).
        self._deadline = time.monotonic() + self.max_duration
        for name in KEY_NODES:
            self.keys[name] = self.io.edge_actions("game", name)
        # Required: the UI must define at least start, rotate, left, right, down, quit.
        required = ("start", "rotate", "left", "right", "down", "quit")
        for r in required:
            if not self.keys.get(r):
                return self._fail("tree_incomplete", f"The {UI_NAME} tree has no actions on game → {r}")

        try:
            nav = self._call(self.io.navigate, "game")
            if not nav.get("success"):
                return self._fail("page_not_ready", f"Could not open the game: {nav.get('error', 'navigation failed')}")
            nav = self._call(self.io.navigate, "start")
            s = self.state()
        except _TimeCapReached:
            return self._fail("time_cap", "The run spent its time budget before the game started")
        if not s or not s.get("playing"):
            return self._fail("not_started", f"The game did not start ({'no page state' if not s else 'not playing'})")
        self.record_step("Game started", True, "game", {"next": s.get("next")},
                         self._try_call(self.io.evidence, "tetris_start", budget=FINISH_CALL_BUDGET_S), started)

        decision_ms, piece_ms, state_ms, key_ms_per_key = [], [], [], []
        last_id, piece_t0, batch_started, batch_rows = None, time.perf_counter(), time.time(), 0
        play_started = time.time()
        # Seed the prediction from the first read: the runner hasn't played yet,
        # so the predicted court *is* the observed court. After every placement
        # we update the prediction by running `place()` on the previous one.
        self.predicted_court = None
        try:
            while True:
                if data["pieces"] >= self.max_pieces:
                    data["stop_reason"] = "piece_limit"
                    break
                if self._budget_left() <= 0:
                    data["stop_reason"] = "time_cap"
                    break
                t0 = time.perf_counter()
                s = self._read_state()
                state_ms.append((time.perf_counter() - t0) * 1000)
                if not s:
                    return self._fail("state_lost", "The page state could not be read")
                data.update({"rows": s["rows"], "score": s["score"]})
                if not s.get("playing", True):
                    data["stop_reason"] = "game_over"
                    break
                if not s.get("piece"):
                    data["stop_reason"] = "game_over"
                    break
                piece = s["piece"]
                if piece["id"] == last_id:
                    if time.perf_counter() - piece_t0 > NEW_PIECE_TIMEOUT_S:
                        return self._fail("piece_stuck", f"Piece {piece['id']} never landed")
                    # Waiting for gravity to drop the next piece. Check the cap here too: the
                    # check at the top of the loop is only reached between pieces, so a run
                    # waiting on the game could sit here well past max_duration.
                    if self._budget_left() <= 0:
                        data["stop_reason"] = "time_cap"
                        break
                    time.sleep(PIECE_POLL_S)
                    continue
                if last_id is not None and piece["id"] != last_id + 1:
                    data["missed_pieces"] += piece["id"] - last_id - 1
                # The first piece of the run seeds the prediction from the observed
                # court; every subsequent piece has its prediction updated by the
                # `place()` call below. A resync replaces the prediction with the
                # observed court when a frame disagrees (G4 two-frame resync).
                if self.predict and self.predicted_court is not None and s.get("js_court") is not None:
                    if diff_cells(self.predicted_court, s["js_court"]) > 0:
                        self.data["vision_resyncs"] += 1
                        self.predicted_court = [col[:] for col in s["js_court"]]
                elif self.predict:
                    self.predicted_court = [col[:] for col in s["js_court"] or s["court"]]
                last_id, piece_t0 = piece["id"], time.perf_counter()

                # Per-piece time below: only the planner + key batch, NOT the
                # state read above (that's `state_ms`). The G4 predictive loop
                # relies on this distinction — the frame capture lag must not
                # appear in `piece_ms`.
                t_piece = time.perf_counter()
                # In predictive mode we plan from the predicted court (which already
                # reflects our previous placement). In non-predictive mode we plan
                # from the read court (the truth at this moment). Either way the
                # planner sees the locked stack without the floating piece.
                court = self.predicted_court if (self.predict and self.predicted_court) else s["court"]
                t1 = time.perf_counter()
                target = best_placement(court, piece["t"], piece["d"], piece["x"], piece["y"], self.rules)
                decision_ms.append((time.perf_counter() - t1) * 1000)
                if target is None:
                    data["stop_reason"] = "no_placement"
                    break
                keys = placement_keys(piece["d"], piece["x"], piece["y"], target, self.rules)
                t2 = time.perf_counter()
                if not self.press(keys):
                    return self._fail("input_failed", f"Keys for piece {piece['id']} were not sent")
                if keys:
                    key_ms_per_key.append((time.perf_counter() - t2) * 1000 / len(keys))
                piece_ms.append((time.perf_counter() - t_piece) * 1000)
                data["key_presses"] += len(keys)
                data["pieces"] += 1
                kind = PIECE_NAME_BY_COLOUR.get(piece["t"], piece["t"])
                data["pieces_by_type"][kind] = data["pieces_by_type"].get(kind, 0) + 1
                data["max_speed_s"] = round(s["step"], 3)

                # Update the prediction. `place()` returns the court after the piece
                # locks and any full rows clear — the same operation the page runs.
                if self.predict and self.predicted_court is not None:
                    self.predicted_court, _, _ = place(self.predicted_court, piece["t"],
                                                       target["d"], target["x"], target["y"], self.rules)

                # Vision accuracy KPI (per piece). Compare the vision-read court
                # (locked only — the active piece was subtracted) against the JS
                # state's locked court (page's `blocks`). Both come from the same
                # JS read, so they describe the same instant and the diff is clean.
                if s.get("frame") and self.perception == "vision" and s.get("js_court") is not None:
                    self.data["vision_cells_total"] += NX * NY
                    self.data["vision_cells_matched"] += NX * NY - diff_cells(court, s["js_court"])

                if data["pieces"] % REPORT_EVERY == 0:
                    self.record_step(
                        f"Pieces {data['pieces'] - REPORT_EVERY + 1}-{data['pieces']}: rows {s['rows']} "
                        f"(+{s['rows'] - batch_rows}), score {s['score']}, speed {s['step']:.2f} s/row",
                        True, "game",
                        {"rows": s["rows"], "score": s["score"], "speed_s_per_row": s["step"],
                         "piece_ms_p50": _pct(piece_ms[-REPORT_EVERY:], 0.5), "court": court_rows(court)},
                        self._try_call(self.io.evidence, f"tetris_{data['pieces']:05d}",
                                       budget=FINISH_CALL_BUDGET_S), batch_started)
                    batch_started, batch_rows = time.time(), s["rows"]

        except _TimeCapReached:
            data["stop_reason"] = "time_cap"

        data["play_duration_s"] = round(time.time() - play_started, 2)
        data["decision_ms_p50"] = round(statistics.median(decision_ms), 2) if decision_ms else None
        data["decision_ms_max"] = round(max(decision_ms), 2) if decision_ms else None
        data["piece_ms_p50"], data["piece_ms_p95"] = _pct(piece_ms, 0.5), _pct(piece_ms, 0.95)
        data["state_ms_p50"] = _pct(state_ms, 0.5)
        data["keys_ms_per_key"] = round(statistics.median(key_ms_per_key), 1) if key_ms_per_key else None
        if data["vision_cells_total"]:
            data["vision_match_pct"] = round(100 * data["vision_cells_matched"] / data["vision_cells_total"], 2)
        return self._finish()

    def _finish(self) -> Dict[str, Any]:
        data = self.data
        # The finish sequence runs on its own small budget: the play cap is spent by now,
        # and the run still has to write its result (E50).
        if data["stop_reason"] != "game_over":
            try:
                self.press(["quit"], budget=FINISH_CALL_BUDGET_S)
            except Exception:   # noqa: BLE001 - a device that does not answer must not lose the result
                pass
        nav = self._try_call(self.io.navigate, "game_over", budget=FINISH_CALL_BUDGET_S, default={})
        over_ok = bool(nav.get("success"))

        time.sleep(SETTLE_S)
        s = self._try_call(self.state, budget=FINISH_CALL_BUDGET_S, default={}) or {}
        frame = self._try_call(self.io.frame, budget=FINISH_CALL_BUDGET_S)
        pixel = None
        if frame:
            if self.vision_reader:
                result = self.vision_reader.read(frame)
                pixel = result["court"] if result else None
            else:
                # Backwards-compat: no vision profile -> use the simple jakesgordon
                # reader (auto-detect court by dark 2 px border).
                from .reader import read_court
                pixel = read_court(frame)
        if s.get("court"):
            page_court = court_from_string(s["court"])
            piece = s.get("piece")
            if piece:
                for cx, cy in cells(piece["t"], piece["d"], piece["x"], piece["y"], self.rules):
                    if 0 <= cx < NX and 0 <= cy < NY:
                        page_court[cx][cy] = 1
            data["final_court"] = court_rows(page_court)
            data.update({"rows": s.get("rows", data["rows"]), "score": s.get("score", data["score"])})
            if pixel is not None:
                data["reader_diff_cells"] = diff_cells(pixel, page_court)
                data["reader_match"] = data["reader_diff_cells"] == 0
        shot = self._try_call(self.io.evidence, "tetris_final", budget=FINISH_CALL_BUDGET_S)

        full_game = data["stop_reason"] == "game_over"
        rows_ok = not full_game or data["rows"] >= self.min_rows
        vision_ok = (data["vision_match_pct"] is None or data["vision_match_pct"] >= 99.0)
        success = (over_ok and rows_ok and vision_ok
                   and data["reader_match"] is not False
                   and data["stop_reason"] in ("game_over", "piece_limit"))
        self.record_step(
            f"KPI: {data['rows']} rows, score {data['score']}, {data['pieces']} pieces "
            f"({data['stop_reason']}); pixel court {'matches' if data['reader_match'] else 'DIFFERS from' if data['reader_match'] is False else 'not read against'} the page"
            + (f"; vision {data['vision_match_pct']}% over the run" if data['vision_match_pct'] is not None else ""),
            success, "game_over" if over_ok else "game",
            {k: data[k] for k in ("rows", "score", "pieces", "stop_reason", "max_speed_s", "reader_match",
                                  "reader_diff_cells", "piece_ms_p50", "piece_ms_p95", "keys_ms_per_key",
                                  "decision_ms_p50", "missed_pieces", "vision_match_pct",
                                  "vision_frames_read", "final_court")},
            shot)
        data["success"] = success
        if not success:
            data["error"] = ("game over screen not confirmed" if not over_ok else
                             f"rows {data['rows']} < {self.min_rows}" if not rows_ok else
                             f"vision match {data['vision_match_pct']}% < 99%" if not vision_ok else
                             f"pixel court differs from the page in {data['reader_diff_cells']} cells" if data["reader_match"] is False else
                             f"stopped: {data['stop_reason']}")
        return data


KPI_FIELDS = ("userinterface", "player", "strategy", "perception", "pieces", "rows", "score", "max_speed_s",
              "stop_reason", "pieces_by_type", "key_presses", "decision_ms_p50", "decision_ms_max",
              "piece_ms_p50", "piece_ms_p95", "state_ms_p50", "keys_ms_per_key", "missed_pieces",
              "reader_match", "reader_diff_cells", "vision_cells_total", "vision_cells_matched",
              "vision_match_pct", "vision_frames_read", "vision_resyncs",
              "final_court", "play_duration_s")


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data.get(k) for k in KPI_FIELDS}


def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    lines = [
        f"Tetris ({data.get('perception', 'js')})",
        f"Rows: {data.get('rows', 0)}  Score: {data.get('score', 0)}  Pieces: {data.get('pieces', 0)}",
        f"Stop reason: {data.get('stop_reason', '')}  Top speed: {data.get('max_speed_s')} s/row",
        f"Per piece: {data.get('piece_ms_p50')} ms p50 / {data.get('piece_ms_p95')} ms p95, "
        f"{data.get('keys_ms_per_key')} ms per key, decision {data.get('decision_ms_p50')} ms",
        f"Pixel court vs page: {data.get('reader_match')} ({data.get('reader_diff_cells')} cells differ)",
    ]
    vmp = data.get('vision_match_pct')
    if vmp is not None:
        lines.append(f"Vision reader accuracy over the run: {vmp}% "
                     f"({data.get('vision_cells_matched')}/{data.get('vision_cells_total')} cells)")
    lines.append(f"Result: {'PASS' if success else 'FAIL'}" + (f" - {error}" if error else ""))
    return "\n".join(lines)