"""
Real-time Flappy Bird loop with planned jumps.

A jump window is ~3 game frames (~50 ms) and one executor action costs ~25 ms on a host, so
"read, decide, press" in separate actions lands the jump a step late. Instead each step is ONE
execute_javascript action that:
  1. reads the bird and the next gap exactly as the page's gameloop computes them;
  2. simulates the next frames with the page's physics (gravity 0.25 px/frame², jump -4.6);
  3. finds the frame where the bird would drop below the gap's bottom minus a margin, and
     schedules Space for the frame before it (a keydown sent to the page's own handler), unless
     the jump's ~42 px rise would hit the upper pipe;
  4. cancels the previous step's pending press, so every plan uses the freshest reading.
The runner sets the margin and the lookahead (its measured loop time in frames) on every step.
Measured locally: alive at every time cap with 25-40 ms (+ jitter) per action
(docs/tasks/TASK-33-2048-game-showcase.md §000, test_scripts/game/local/flappy_predict.py).
"""

import asyncio
import statistics
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

UI_NAME = "flappy-web"
FRAME_MS = 1000 / 60
MARGIN_PX = 6
REPORT_EVERY = 10   # pipes per report step (no screenshots while flying: they would stall the loop)

# Bird box and next gap, exactly as the page's gameloop() computes them.
_JS_STATE = """
  const box = document.getElementById('player').getBoundingClientRect();
  const boxheight = (24.0 + box.height) / 2;
  const top = ((box.height - boxheight) / 2) + box.top;
  const bottom = top + boxheight;
  let pipe = null;
  if (pipes[0]) { const u = pipes[0].children('.pipe_upper');
    const pt = u.offset().top + u.height(); pipe = {top: pt, bottom: pt + pipeheight}; }
  const fly = $('#flyarea').offset().top, land = $('#land').offset().top;
"""
_JS_PLAN = """() => {
  if (typeof currentstate === 'undefined') return null;
""" + _JS_STATE + """
  const margin = __MARGIN__, lookahead = __LOOKAHEAD__;
  const target = pipe ? pipe.bottom - margin : (fly + land) / 2 + 20;
  clearTimeout(window.__vptTimer);
  let fire = -1, b = bottom, t = top, v = velocity;
  for (let f = 0; f <= lookahead; f++) {
    if (b > target) { fire = Math.max(0, f - 1); break; }
    v += 0.25; b += v; t += v;
  }
  let planned = null;
  if (currentstate === 1 && fire >= 0 && (!pipe || (t - v) - 42.3 > pipe.top + 1)) {
    const press = () => { if (performance.now() - (window.__vptJump || 0) > 16.7) {
      document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 32, bubbles: true}));
      window.__vptJump = performance.now(); window.__vptJumps = (window.__vptJumps || 0) + 1; } };
    if (fire === 0) press(); else window.__vptTimer = setTimeout(press, fire * 16.7);
    planned = fire;
  }
  return {state: currentstate, score, v: velocity, top, bottom, pipe, planned, jumps: window.__vptJumps || 0};
}"""


def plan_script(margin: int, lookahead: int) -> str:
    return _JS_PLAN.replace("__MARGIN__", str(int(margin))).replace("__LOOKAHEAD__", str(int(lookahead)))


def lookahead_frames(loop_ms: float) -> int:
    """Frames until the next step has replanned: the loop time in frames, plus two."""
    return max(1, round(loop_ms / FRAME_MS)) + 2


class VptIO:
    """Device access through the executors and the capture helper only."""

    def __init__(self, device, context, tree_id: str, userinterface: str):
        self.device, self.context, self.tree_id, self.userinterface = device, context, tree_id, userinterface

    def navigate(self, node: str) -> Dict[str, Any]:
        return asyncio.run(self.device.navigation_executor.execute_navigation(
            tree_id=self.tree_id, userinterface_name=self.userinterface, target_node_label=node,
            team_id=self.context.team_id, context=self.context))

    def run_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        return asyncio.run(ExecutionOrchestrator.execute_actions(
            self.device, actions, team_id=self.context.team_id, context=self.context))

    def evidence(self, name: str) -> str:
        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
        captured = capture_screenshot_for_script(self.device, self.context, name)
        return self.context.screenshot_paths[-1] if captured and self.context.screenshot_paths else ""


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 1)


def _js_result(result: Dict[str, Any]) -> Any:
    for r in reversed(result.get("results") or []):
        out = r.get("output_data") or {}
        if "result" in out:
            return out["result"]
    return None


class FlappyRunner:
    def __init__(self, io, context, max_pipes: int, max_duration: int, min_pipes: int, margin: int = MARGIN_PX):
        self.io = io
        self.context = context
        self.max_pipes = max_pipes
        self.max_duration = max_duration
        self.min_pipes = min_pipes
        self.margin = margin
        self.data: Dict[str, Any] = {
            "userinterface": UI_NAME, "strategy": "planned-jump", "margin_px": margin,
            "pipes": 0, "jumps": 0, "steps": 0, "stop_reason": "", "play_duration_s": 0.0,
            "loop_ms_p50": None, "loop_ms_p95": None, "loop_ms_max": None, "lookahead_frames_p50": None,
            "last_readings": [],
        }

    def step(self, lookahead: int) -> Optional[Dict[str, Any]]:
        return _js_result(self.io.run_actions([{"command": "execute_javascript", "action_type": "web",
                                                "params": {"script": plan_script(self.margin, lookahead), "wait_time": 0}}]))

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
            "verifications": [{"verification_type": "flappy", "command": "fly", "label": message,
                               "success": success, "details": details}],
            "verification_results": [], "step_category": "flappy",
        })

    def _fail(self, reason: str, error: str) -> Dict[str, Any]:
        self.data.update({"stop_reason": reason, "success": False, "error": error})
        return self.data

    def run(self) -> Dict[str, Any]:
        data = self.data
        started = time.time()
        nav = self.io.navigate("game")
        if not nav.get("success"):
            return self._fail("page_not_ready", f"Could not open the game: {nav.get('error', 'navigation failed')}")
        nav = self.io.navigate("start")  # fresh page load, then Space: the game starts with a jump
        if not nav.get("success"):
            return self._fail("not_started", f"Could not start: {nav.get('error', 'navigation failed')}")
        self.record_step("Game started", True, "game", {}, self.io.evidence("flappy_start"), started)

        loops, lookaheads, history = [], [], []
        loop_ms = 50.0
        batch_started, next_report = time.time(), REPORT_EVERY
        play_started = time.time()
        while True:
            if time.time() - play_started >= self.max_duration:
                data["stop_reason"] = "time_cap"
                break
            t0 = time.perf_counter()
            lookahead = lookahead_frames(loop_ms)
            s = self.step(lookahead)
            if s is None:
                return self._fail("state_lost", "The page state could not be read")
            data["steps"] += 1
            data["pipes"], data["jumps"] = s.get("score", 0), s.get("jumps", 0)
            if s["state"] != 1:
                data["stop_reason"] = "died" if s["state"] == 2 else f"state_{s['state']}"
                break
            pipe = s.get("pipe")
            history = (history + [{"t": round(time.time() - play_started, 2), "top": round(s["top"]),
                                   "bottom": round(s["bottom"]), "v": round(s["v"], 2), "planned": s.get("planned"),
                                   "gap": [round(pipe["top"]), round(pipe["bottom"])] if pipe else None}])[-12:]
            dt = (time.perf_counter() - t0) * 1000
            loops.append(dt)
            lookaheads.append(lookahead)
            loop_ms = 0.8 * loop_ms + 0.2 * dt
            if data["pipes"] >= next_report:
                self.record_step(f"Pipes {next_report - REPORT_EVERY + 1}-{next_report}: loop {_pct(loops[-200:], 0.5)} ms p50",
                                 True, "game", {"pipes": data["pipes"], "jumps": data["jumps"],
                                                "loop_ms_p50": _pct(loops[-200:], 0.5), "loop_ms_p95": _pct(loops[-200:], 0.95)},
                                 "", batch_started)
                batch_started, next_report = time.time(), next_report + REPORT_EVERY
            if data["pipes"] >= self.max_pipes:
                data["stop_reason"] = "pipe_limit"  # stop steering: the bird falls and the game ends
                break

        data["play_duration_s"] = round(time.time() - play_started, 2)
        data["loop_ms_p50"], data["loop_ms_p95"] = _pct(loops, 0.5), _pct(loops, 0.95)
        data["loop_ms_max"] = round(max(loops), 1) if loops else None
        data["lookahead_frames_p50"] = statistics.median(lookaheads) if lookaheads else None
        data["last_readings"] = history
        return self._finish()

    def _finish(self) -> Dict[str, Any]:
        data = self.data
        nav = self.io.navigate("game_over")
        over_ok = bool(nav.get("success"))
        shot = self.io.evidence("flappy_final")
        enough = data["stop_reason"] == "pipe_limit" or data["pipes"] >= self.min_pipes
        success = over_ok and enough and data["stop_reason"] in ("died", "pipe_limit")
        self.record_step(
            f"KPI: {data['pipes']} pipes, {data['jumps']} jumps ({data['stop_reason']}), "
            f"loop {data['loop_ms_p50']} / {data['loop_ms_p95']} ms p50 / p95",
            success, "game_over" if over_ok else "game",
            {k: data[k] for k in ("pipes", "jumps", "steps", "stop_reason", "loop_ms_p50", "loop_ms_p95", "loop_ms_max",
                                  "lookahead_frames_p50", "margin_px", "last_readings")},
            shot)
        data["success"] = success
        if not success:
            data["error"] = ("game over screen not confirmed" if not over_ok else
                             f"{data['pipes']} pipes < {self.min_pipes}" if not enough else
                             f"stopped: {data['stop_reason']}")
        return data


KPI_FIELDS = ("userinterface", "strategy", "margin_px", "pipes", "jumps", "steps", "stop_reason", "play_duration_s",
              "loop_ms_p50", "loop_ms_p95", "loop_ms_max", "lookahead_frames_p50", "last_readings")


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data.get(k) for k in KPI_FIELDS}


def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    return "\n".join([
        "Flappy Bird (TASK-33 phase 3c)",
        f"Pipes: {data.get('pipes', 0)}  Jumps: {data.get('jumps', 0)}  Stop reason: {data.get('stop_reason', '')}",
        f"Loop: {data.get('loop_ms_p50')} ms p50 / {data.get('loop_ms_p95')} ms p95 / {data.get('loop_ms_max')} ms max, "
        f"lookahead {data.get('lookahead_frames_p50')} frames",
        f"Result: {'PASS' if success else 'FAIL'}" + (f" - {error}" if error else ""),
    ])
