"""
2048 game loop on any device, through the navigation executor.

The device-specific parts live in the userinterface tree (game2048-web,
game2048-android-mobile): the entry edge opens the game, the action nodes move_left /
move_right / move_up / move_down / new_game carry the key presses or swipes, and the
game / game_over nodes carry the checks. The runner only navigates to those nodes, reads
the board from captured frames (reader.py) and asks the player for each move.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from shared.src.lib.utils.device_utils import capture_screenshot, capture_screenshot_for_script

from .board import Board, apply_move, legal_moves, max_tile, merge_gain
from .player import LLM_USAGE, MOVES, Decider
from .reader import BoardReader

UI_PREFIX = "game2048-"
FRAME_POLL_S = 0.1
# HDMI/VNC capture lags the screen by up to ~1.5 s on a loaded host.
MOVE_SETTLE_TIMEOUT_S = 5.0
BOARD_READ_TIMEOUT_S = 8.0
MAX_UNAPPLIED_MOVES = 3


def resolve_userinterface(requested: Optional[str], device_model: str, team_id: str) -> Optional[str]:
    """The game2048-* userinterface for this device (an explicit game2048-* name wins)."""
    if requested and requested.startswith(UI_PREFIX):
        return requested
    from shared.src.lib.config.device_capabilities import model_matches_any
    from shared.src.lib.database.userinterface_db import get_all_userinterfaces
    for ui in sorted(get_all_userinterfaces(team_id) or [], key=lambda u: u.get("name", "")):
        if ui.get("name", "").startswith(UI_PREFIX) and model_matches_any(device_model, ui.get("models") or []):
            return ui["name"]
    return None


class GameRunner:
    def __init__(self, device, context, userinterface: str, tree_id: str, decide: Decider, player: str,
                 max_moves: int, max_duration: int, min_score: int, min_tile: int):
        self.device = device
        self.context = context
        self.userinterface = userinterface
        self.tree_id = tree_id
        self.decide = decide
        self.player = player
        self.max_moves = max_moves
        self.max_duration = max_duration
        self.min_score = min_score
        self.min_tile = min_tile
        self.reader = BoardReader()
        self.data: Dict[str, Any] = {
            "path": userinterface[len(UI_PREFIX):],
            "userinterface": userinterface,
            "device_model": getattr(device, "device_model", ""),
            "player": player,
            "strategy": f"llm:{LLM_USAGE}" if player == "llm" else ">".join(MOVES),
            "final_score": 0,
            "max_tile": 0,
            "move_count": 0,
            "moves_by_direction": {d: 0 for d in MOVES},
            "stop_reason": "",
            "reached_2048": False,
            "play_duration_s": 0.0,
            "avg_move_ms": None,
            "board_resyncs": 0,
            "llm_usage": LLM_USAGE if player == "llm" else "",
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "avg_llm_ms": None,
            "llm_models": [],
            "llm_endpoints": [],
            "decisions_by": {},
        }

    # --- device access (executors + capture helper only) ------------------------------
    def navigate(self, node: str) -> Dict[str, Any]:
        return asyncio.run(self.device.navigation_executor.execute_navigation(
            tree_id=self.tree_id,
            userinterface_name=self.userinterface,
            target_node_label=node,
            team_id=self.context.team_id,
            context=self.context,
        ))

    def frame(self) -> Optional[str]:
        return capture_screenshot(self.device)

    def evidence(self, name: str) -> str:
        captured = capture_screenshot_for_script(self.device, self.context, name)
        return self.context.screenshot_paths[-1] if captured and self.context.screenshot_paths else ""

    # --- report -------------------------------------------------------------------------
    def record_step(self, message: str, success: bool, node: str, details: Dict[str, Any],
                    screenshot: str = "", started: Optional[float] = None, label: str = "") -> None:
        now = time.time()
        started = started or now
        self.context.record_step_immediately({
            "success": success,
            "message": message,
            "from_node": node,
            "to_node": node,
            "execution_time_ms": int((now - started) * 1000),
            "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
            "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "screenshot_path": screenshot or None,
            "step_end_screenshot_path": screenshot or None,
            "action_screenshots": [screenshot] if screenshot else [],
            "actions": [],
            "verifications": [{"verification_type": "game2048", "command": label or "check", "label": message,
                               "success": success, "details": details}],
            "verification_results": [],
            "step_category": "game2048",
        })

    def enrich_move_step(self, first_new: int, message: str, success: bool, decision: Dict[str, Any],
                         details: Dict[str, Any], screenshot: str) -> None:
        """Put the decision and the board read on the navigation step of this move."""
        steps = self.context.step_results[first_new:]
        if not steps:
            self.record_step(message, success, "game", details, screenshot, label="read_board")
            return
        step = steps[-1]
        step["message"] = message
        step["success"] = bool(step.get("success", True)) and success
        if screenshot:
            step["screenshot_path"] = screenshot
            step["step_end_screenshot_path"] = screenshot
        if decision.get("llm_called"):
            step["actions"] = [{
                "command": "ai.gateway.complete", "action_type": "ai",
                "params": {
                    "usage": LLM_USAGE, "model": decision.get("model"), "profile": decision.get("profile"),
                    "endpoint": decision.get("endpoint"), "tokens_in": decision.get("tokens_in", 0),
                    "tokens_out": decision.get("tokens_out", 0), "latency_ms": decision.get("llm_ms"),
                },
            }] + list(step.get("actions") or [])
        step["verifications"] = list(step.get("verifications") or []) + [{
            "verification_type": "game2048", "command": "read_board", "label": "Decision and board",
            "success": success, "details": details}]

    # --- board reading ------------------------------------------------------------------
    def read_fresh_board(self) -> Optional[Board]:
        """Two different frames must show the same two-tile board (new tiles scale in)."""
        deadline = time.time() + BOARD_READ_TIMEOUT_S
        last_path, last = None, None
        while time.time() < deadline:
            path = self.frame()
            if path and path != last_path:
                board = self.reader.read_fresh(path)
                if board and board == last:
                    return board
                last_path, last = path, board
            time.sleep(FRAME_POLL_S)
        return None

    def read_after_move(self, before: Board, predicted: Board) -> tuple:
        """(status, board): ok | resync | unapplied | lost."""
        deadline = time.time() + MOVE_SETTLE_TIMEOUT_S
        last_path, last = None, None
        while time.time() < deadline:
            path = self.frame()
            if path and path != last_path:
                # A new tile scaling in looks like a 4 (4 sits between empty and 2), so two
                # different frames must agree before the read counts.
                status, board = self.reader.track(path, predicted)
                if status == "ok" and board == last:
                    return "ok", board
                last_path, last = path, (board if status == "ok" else None)
            time.sleep(FRAME_POLL_S)
        path = self.frame()
        # No tile can exceed twice the current biggest one.
        blind = self.reader.read(path, max_tile(before) * 2) if path else None
        if blind is None:
            return "lost", None
        if blind == before:
            return "unapplied", None
        return "resync", blind

    # --- game ---------------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        data = self.data
        started = time.time()
        nav = self.navigate("game")
        if not nav.get("success"):
            return self._fail("menu_not_ready", f"Could not open the game: {nav.get('error', 'navigation failed')}")

        board = self.read_fresh_board()
        if board is None:
            # Read the screen even when new_game reports a failure: after a finished game the
            # tap works but there is no confirm dialog, so its "OK" step fails (phone).
            self.navigate("new_game")
            board = self.read_fresh_board()
        shot = self.evidence("game2048_fresh_board")
        self.record_step(
            "Fresh board: two tiles" if board else "Fresh board not found",
            board is not None, "game",
            {"board": board, "board_rect": self.reader.rect, "colour_offset": [round(v) for v in self.reader.offset]},
            shot, started, "read_fresh_board",
        )
        if board is None:
            return self._fail("menu_not_ready", "No fresh 2048 board found on screen")

        score = 0
        unapplied = 0
        llm_ms_total = 0
        input_ms_total = 0
        play_started = time.time()
        while True:
            if not legal_moves(board):
                data["stop_reason"] = "game_over"
                break
            if data["move_count"] >= self.max_moves:
                data["stop_reason"] = "move_limit"
                break
            if time.time() - play_started >= self.max_duration:
                data["stop_reason"] = "time_cap"
                break

            decision_started = time.time()
            decision = self.decide(board, score)
            move = decision.get("move")
            if decision.get("llm_called"):
                data["llm_calls"] += 1
                data["tokens_in"] += decision.get("tokens_in", 0)
                data["tokens_out"] += decision.get("tokens_out", 0)
                llm_ms_total += decision.get("llm_ms") or 0
                for key, field in (("model", "llm_models"), ("endpoint", "llm_endpoints")):
                    if decision.get(key) and decision[key] not in data[field]:
                        data[field].append(decision[key])
            if move is None:
                data["stop_reason"] = "game_over"
                break
            by = decision.get("decided_by", "heuristic")
            data["decisions_by"][by] = data["decisions_by"].get(by, 0) + 1

            first_new = len(self.context.step_results)
            move_started = time.time()
            nav = self.navigate(f"move_{move.lower()}")
            predicted = apply_move(board, move)
            status, after = self.read_after_move(board, predicted) if nav.get("success") else ("lost", None)
            input_ms = int((time.time() - move_started) * 1000)
            applied = status in ("ok", "resync")
            if applied:
                unapplied = 0
                gain = merge_gain(board, move)
                score += gain
                data["move_count"] += 1
                data["moves_by_direction"][move] += 1
                input_ms_total += input_ms
                if status == "resync":
                    data["board_resyncs"] += 1
            else:
                unapplied += 1
                gain = 0
            shot = self.evidence(f"game2048_move_{data['move_count']:04d}")
            self._report_move(first_new, decision, applied, status, board, after, score, gain, input_ms,
                              int((time.time() - decision_started) * 1000), shot)
            if status == "lost":
                data["stop_reason"] = "board_lost"
                break
            if unapplied >= MAX_UNAPPLIED_MOVES:
                data["stop_reason"] = "input_not_applied"
                break
            if applied:
                board = after

        play_s = time.time() - play_started
        data["play_duration_s"] = round(play_s, 2)
        if data["move_count"]:
            data["avg_move_ms"] = int(input_ms_total / data["move_count"])
        if data["llm_calls"]:
            data["avg_llm_ms"] = int(llm_ms_total / data["llm_calls"])
        data["final_score"] = score
        data["final_board"] = board
        data["max_tile"] = max_tile(board)
        data["reached_2048"] = data["max_tile"] >= 2048
        return self._finish()

    def _report_move(self, first_new, decision, applied, status, before, after, score, gain, input_ms, step_ms, shot):
        move = decision["move"]
        by = decision.get("decided_by")
        reasoning = decision.get("reasoning") or ""
        n = self.data["move_count"] if applied else self.data["move_count"] + 1
        if by == "llm":
            label = f"{move} by {decision.get('model') or 'LLM'}"
        elif by == "heuristic_fallback":
            label = f"{move} by heuristic fallback"
        else:
            label = reasoning or move
        message = f"Move {n}: {label} (+{gain}, score {score})"
        if by == "llm" and reasoning:
            message += f" - {reasoning[:90]}"
        elif by == "heuristic_fallback":
            message += f" - {(decision.get('error') or '')[:90]}"
        if not applied:
            message += f" [{status}]"
        details = {
            "decided_by": by,
            "chosen": move,
            "reasoning": reasoning,
            "legal_moves": decision.get("legal") or legal_moves(before),
            "model": decision.get("model", ""),
            "tokens_in": decision.get("tokens_in", 0),
            "tokens_out": decision.get("tokens_out", 0),
            "llm_ms": decision.get("llm_ms"),
            "error": decision.get("error", ""),
            "raw_answer": decision.get("raw_answer", ""),
            "board_before": before,
            "board_after": after,
            "read_status": status,
            "gain": gain,
            "score": score,
            "max_tile": max_tile(after or before),
            "move_to_board_ms": input_ms,
            "step_ms": step_ms,
        }
        self.enrich_move_step(first_new, message, applied, decision, details, shot)

    def _finish(self) -> Dict[str, Any]:
        data = self.data
        game_over = data["stop_reason"] == "game_over"
        move_limit = data["stop_reason"] == "move_limit"
        if game_over:
            nav = self.navigate("game_over")
            game_over = bool(nav.get("success"))
            if not game_over:
                data["stop_reason"] = "game_over_not_confirmed"
        # The floors describe a full game; a move-limited run only reports the values.
        tile_ok = move_limit or data["max_tile"] >= self.min_tile
        score_ok = move_limit or data["final_score"] >= self.min_score
        self.record_step(
            f"KPI: score {data['final_score']}, max tile {data['max_tile']}"
            + (" (partial game, floors not applied)" if move_limit else ""),
            tile_ok and score_ok, "game_over" if game_over else "game",
            {"final_score": data["final_score"], "max_tile": data["max_tile"], "min_score": self.min_score,
             "min_tile": self.min_tile, "stop_reason": data["stop_reason"], "final_board": data.get("final_board")},
            self.evidence("game2048_final"), label="kpi",
        )
        data["success"] = (game_over or move_limit) and tile_ok and score_ok
        if not (game_over or move_limit):
            data["error"] = f"2048 run did not reach game over (stop_reason={data['stop_reason']})"
        elif not (tile_ok and score_ok):
            data["error"] = (f"2048 KPI below floor: score {data['final_score']} (min {self.min_score}), "
                             f"max tile {data['max_tile']} (min {self.min_tile})")
        return data

    def _fail(self, reason: str, error: str) -> Dict[str, Any]:
        self.data.update({"stop_reason": reason, "success": False, "error": error})
        return self.data


def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    lines = [
        "GAME_2048 SUMMARY",
        f"Userinterface: {data.get('userinterface', '')} (device model {data.get('device_model', '')})",
        f"Player: {data.get('player', '')}"
        + (f" (AI usage {data.get('llm_usage')}; models {', '.join(data.get('llm_models') or []) or 'none'}"
           f" via {', '.join(data.get('llm_endpoints') or []) or 'none'})" if data.get("player") == "llm" else ""),
        f"Final score: {data.get('final_score', 0)}",
        f"Max tile: {data.get('max_tile', 0)}",
        f"Moves: {data.get('move_count', 0)} {data.get('moves_by_direction', {})}",
        f"Decisions: {data.get('decisions_by', {})}",
        f"AI usage: {data.get('llm_calls', 0)} LLM calls, tokens in {data.get('tokens_in', 0)} / out {data.get('tokens_out', 0)}"
        + (f", avg {data.get('avg_llm_ms')} ms/decision" if data.get("avg_llm_ms") else ""),
        f"Board resyncs: {data.get('board_resyncs', 0)}",
        f"Stop reason: {data.get('stop_reason', '')}",
        f"Play duration: {data.get('play_duration_s', 0)}s (avg {data.get('avg_move_ms')} ms from move to settled board)",
        f"Result: {'PASS' if success else 'FAIL'}",
    ]
    if error:
        lines.append(f"Error: {error}")
    return "\n".join(lines)


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "path", "userinterface", "device_model", "player", "strategy", "final_score", "max_tile", "move_count",
        "moves_by_direction", "stop_reason", "reached_2048", "play_duration_s", "avg_move_ms", "final_board",
        "board_resyncs", "llm_usage", "llm_calls", "tokens_in", "tokens_out", "avg_llm_ms", "llm_models",
        "llm_endpoints", "decisions_by",
    )
    return {k: data[k] for k in keys if k in data}
