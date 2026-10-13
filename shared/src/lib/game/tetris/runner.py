"""
Real-time Tetris game loop.

The tetris-web userinterface holds the device specifics: the entry edge opens the page, the
action nodes under `game` carry the keys (rotate, left, right, down, start, quit) and the
`game` / `game_over` nodes carry the checks. Unlike 2048, a placement is up to ~25 keys and
the piece falls meanwhile, so the runner does not navigate once per key: it reads each action
node's actions from the loaded tree once and fires them in one batch through the action
executor, with no wait between keys.

Per piece: read the page state (one execute_javascript action), pick the placement
(board.best_placement), send rotations + shifts + one DOWN per row. The page handles one key
per frame and drops its key queue when the piece lands. At the end (game over or piece
budget) the court is read from the captured pixels and compared with the page state.

Device access goes through an IO object: VptIO (navigation / action executors and the capture
helper) or a local Playwright stand-in for development (test_scripts/game/local/).
"""

import asyncio
import json
import statistics
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .board import NX, NY, PIECE_NAMES, best_placement, cells, court_from_string, court_rows, placement_keys
from .reader import diff_cells, read_court

UI_NAME = "tetris-web"
KEY_NODES = ("rotate", "left", "right", "down", "quit")
REPORT_EVERY = 25        # pieces per report step
NEW_PIECE_TIMEOUT_S = 3.0
SETTLE_S = 1.5           # capture lag before the final pixel read

# Page state through execute_javascript. Each piece object gets an id (the page has none),
# so the runner knows when a new piece has spawned.
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


class TetrisRunner:
    def __init__(self, io, context, max_pieces: int, max_duration: int, min_rows: int):
        self.io = io
        self.context = context
        self.max_pieces = max_pieces
        self.max_duration = max_duration
        self.min_rows = min_rows
        self.keys: Dict[str, List[Dict[str, Any]]] = {}
        self.data: Dict[str, Any] = {
            "userinterface": UI_NAME, "player": "heuristic", "strategy": "el-tetris",
            "pieces": 0, "rows": 0, "score": 0, "max_speed_s": None, "stop_reason": "",
            "pieces_by_type": {}, "key_presses": 0,
            "decision_ms_p50": None, "decision_ms_max": None,
            "piece_ms_p50": None, "piece_ms_p95": None, "state_ms_p50": None, "keys_ms_per_key": None,
            "missed_pieces": 0, "reader_match": None, "reader_diff_cells": None,
            "final_court": [], "play_duration_s": 0.0,
        }

    # --- device helpers --------------------------------------------------------------
    def state(self) -> Optional[Dict[str, Any]]:
        return _js_result(self.io.run_actions([{"command": "execute_javascript", "action_type": "web",
                                                "params": {"script": JS_STATE, "wait_time": 0}}]))

    def press(self, names: List[str]) -> bool:
        actions = []
        for name in names:
            for action in self.keys[name]:
                a = json.loads(json.dumps(action))
                a.setdefault("params", {})["wait_time"] = 0  # real time: no pause between keys
                actions.append(a)
        if not actions:
            return True
        return bool(self.io.run_actions(actions).get("success", True))

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
        for name in KEY_NODES:
            self.keys[name] = self.io.edge_actions("game", name)
            if not self.keys[name]:
                return self._fail("tree_incomplete", f"The {UI_NAME} tree has no actions on game → {name}")

        nav = self.io.navigate("game")
        if not nav.get("success"):
            return self._fail("page_not_ready", f"Could not open the game: {nav.get('error', 'navigation failed')}")
        nav = self.io.navigate("start")
        s = self.state()
        if not s or not s.get("playing"):
            return self._fail("not_started", f"The game did not start ({'no page state' if not s else 'not playing'})")
        self.record_step("Game started", True, "game", {"next": s.get("next")}, self.io.evidence("tetris_start"), started)

        decision_ms, piece_ms, state_ms, key_ms_per_key = [], [], [], []
        last_id, piece_t0, batch_started, batch_rows = None, time.perf_counter(), time.time(), 0
        play_started = time.time()
        while True:
            if data["pieces"] >= self.max_pieces:
                data["stop_reason"] = "piece_limit"
                break
            if time.time() - play_started >= self.max_duration:
                data["stop_reason"] = "time_cap"
                break
            t0 = time.perf_counter()
            s = self.state()
            state_ms.append((time.perf_counter() - t0) * 1000)
            if not s:
                return self._fail("state_lost", "The page state could not be read")
            data.update({"rows": s["rows"], "score": s["score"]})
            if not s["playing"]:
                data["stop_reason"] = "game_over"
                break
            piece = s["piece"]
            if piece["id"] == last_id:
                if time.perf_counter() - piece_t0 > NEW_PIECE_TIMEOUT_S:
                    return self._fail("piece_stuck", f"Piece {piece['id']} never landed")
                continue
            if last_id is not None and piece["id"] != last_id + 1:
                data["missed_pieces"] += piece["id"] - last_id - 1
            last_id, piece_t0 = piece["id"], time.perf_counter()

            court = court_from_string(s["court"])
            t1 = time.perf_counter()
            target = best_placement(court, piece["t"], piece["d"], piece["x"], piece["y"])
            decision_ms.append((time.perf_counter() - t1) * 1000)
            if target is None:
                data["stop_reason"] = "no_placement"
                break
            keys = placement_keys(piece["d"], piece["x"], piece["y"], target)
            t2 = time.perf_counter()
            if not self.press(keys):
                return self._fail("input_failed", f"Keys for piece {piece['id']} were not sent")
            if keys:
                key_ms_per_key.append((time.perf_counter() - t2) * 1000 / len(keys))
            piece_ms.append((time.perf_counter() - t0) * 1000)
            data["key_presses"] += len(keys)
            data["pieces"] += 1
            kind = PIECE_NAMES.get(piece["t"], piece["t"])
            data["pieces_by_type"][kind] = data["pieces_by_type"].get(kind, 0) + 1
            data["max_speed_s"] = round(s["step"], 3)

            if data["pieces"] % REPORT_EVERY == 0:
                self.record_step(
                    f"Pieces {data['pieces'] - REPORT_EVERY + 1}-{data['pieces']}: rows {s['rows']} "
                    f"(+{s['rows'] - batch_rows}), score {s['score']}, speed {s['step']:.2f} s/row",
                    True, "game",
                    {"rows": s["rows"], "score": s["score"], "speed_s_per_row": s["step"],
                     "piece_ms_p50": _pct(piece_ms[-REPORT_EVERY:], 0.5), "court": court_rows(court)},
                    self.io.evidence(f"tetris_{data['pieces']:05d}"), batch_started)
                batch_started, batch_rows = time.time(), s["rows"]

        data["play_duration_s"] = round(time.time() - play_started, 2)
        data["decision_ms_p50"] = round(statistics.median(decision_ms), 2) if decision_ms else None
        data["decision_ms_max"] = round(max(decision_ms), 2) if decision_ms else None
        data["piece_ms_p50"], data["piece_ms_p95"] = _pct(piece_ms, 0.5), _pct(piece_ms, 0.95)
        data["state_ms_p50"] = _pct(state_ms, 0.5)
        data["keys_ms_per_key"] = round(statistics.median(key_ms_per_key), 1) if key_ms_per_key else None
        return self._finish()

    def _finish(self) -> Dict[str, Any]:
        data = self.data
        if data["stop_reason"] != "game_over":
            self.press(["quit"])  # the page's Esc: ends the game, so the court stops moving
        nav = self.io.navigate("game_over")
        over_ok = bool(nav.get("success"))

        # The court is static now: compare the captured pixels with the page state.
        time.sleep(SETTLE_S)
        s = self.state() or {}
        frame = self.io.frame()
        pixel = read_court(frame) if frame else None
        if s.get("court"):
            page_court = court_from_string(s["court"])
            # The page keeps drawing the current piece, which is not in its `blocks`.
            piece = s.get("piece")
            if piece:
                for cx, cy in cells(piece["t"], piece["d"], piece["x"], piece["y"]):
                    if 0 <= cx < NX and 0 <= cy < NY:
                        page_court[cx][cy] = 1
            data["final_court"] = court_rows(page_court)
            data.update({"rows": s.get("rows", data["rows"]), "score": s.get("score", data["score"])})
            if pixel is not None:
                data["reader_diff_cells"] = diff_cells(pixel, page_court)
                data["reader_match"] = data["reader_diff_cells"] == 0
        shot = self.io.evidence("tetris_final")

        full_game = data["stop_reason"] == "game_over"
        rows_ok = not full_game or data["rows"] >= self.min_rows
        success = over_ok and rows_ok and data["reader_match"] is not False and data["stop_reason"] in ("game_over", "piece_limit")
        self.record_step(
            f"KPI: {data['rows']} rows, score {data['score']}, {data['pieces']} pieces "
            f"({data['stop_reason']}); pixel court {'matches' if data['reader_match'] else 'DIFFERS from' if data['reader_match'] is False else 'not read against'} the page",
            success, "game_over" if over_ok else "game",
            {k: data[k] for k in ("rows", "score", "pieces", "stop_reason", "max_speed_s", "reader_match",
                                  "reader_diff_cells", "piece_ms_p50", "piece_ms_p95", "keys_ms_per_key",
                                  "decision_ms_p50", "missed_pieces", "final_court")},
            shot)
        data["success"] = success
        if not success:
            data["error"] = ("game over screen not confirmed" if not over_ok else
                             f"rows {data['rows']} < {self.min_rows}" if not rows_ok else
                             f"pixel court differs from the page in {data['reader_diff_cells']} cells" if data["reader_match"] is False else
                             f"stopped: {data['stop_reason']}")
        return data


KPI_FIELDS = ("userinterface", "player", "strategy", "pieces", "rows", "score", "max_speed_s", "stop_reason",
            "pieces_by_type", "key_presses", "decision_ms_p50", "decision_ms_max", "piece_ms_p50", "piece_ms_p95",
            "state_ms_p50", "keys_ms_per_key", "missed_pieces", "reader_match", "reader_diff_cells",
            "final_court", "play_duration_s")


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data.get(k) for k in KPI_FIELDS}


def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    lines = [
        "Tetris (TASK-33 phase 3)",
        f"Rows: {data.get('rows', 0)}  Score: {data.get('score', 0)}  Pieces: {data.get('pieces', 0)}",
        f"Stop reason: {data.get('stop_reason', '')}  Top speed: {data.get('max_speed_s')} s/row",
        f"Per piece: {data.get('piece_ms_p50')} ms p50 / {data.get('piece_ms_p95')} ms p95, "
        f"{data.get('keys_ms_per_key')} ms per key, decision {data.get('decision_ms_p50')} ms",
        f"Pixel court vs page: {data.get('reader_match')} ({data.get('reader_diff_cells')} cells differ)",
        f"Result: {'PASS' if success else 'FAIL'}" + (f" - {error}" if error else ""),
    ]
    return "\n".join(lines)
