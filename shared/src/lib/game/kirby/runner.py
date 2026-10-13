"""
Real-time Kirby fight loop on a Nintendo Switch.

The bot acts every frame: read the capture, run a tactic to compute the Switch action(s), send them.
Jev (the platform's decision model) runs in a single-worker background thread and never blocks the
bot. The chooser is injected (the script builds the Jev chooser; tests pass a fake one). The loop
ends when the fight ends (the HP bar is gone for 25 frames, ~5 s), the time budget runs out, or no fight is
visible on the HUD for 10 s.

The runner is meant to be fed a live device. ``VptIO`` (a tiny IO adapter, like the Tetris one)
wraps the executors and the capture helper so the runner never imports controllers or the host
directly. For unit tests, a fake IO can stand in.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import cv2

from .tactics import TACTICS, _action, bot_step, state_text
from .vision import read as read_vision
from shared.src.lib.utils import cv2_io

REPORT_EVERY_S = 15.0       # periodic record_step
SHOT_EVERY_S = 3.0          # screenshots inside a report window (several per step, like kpi_measurement)
NO_FIGHT_TIMEOUT_S = 10.0   # first frames not in_fight this long -> no_fight
END_NOT_FIGHT_FRAMES = 25   # consecutive frames without Kirby's HP bar (~5 s at 5 fps) = fight over
OUTCOME_WINDOW_S = 2.0      # HP loss measured this long after a Jev decision lands
IDLE_S = 0.02               # poll pause while waiting for a new frame
JEV_TRIGGER_S = 2.0         # ask Jev at least this often
HP_LOSS_TRIGGER = 0.05      # ask Jev if Kirby lost >= 5% HP since the last decision
DIST_TRIGGER_PX = 180       # ask Jev if the distance crossed this either way


class VptIO:
    """Live device IO through the executors and the capture helper only."""

    def __init__(self, device, context):
        self.device, self.context = device, context

    def frame(self) -> Optional[str]:
        from shared.src.lib.utils.device_utils import capture_screenshot
        return capture_screenshot(self.device)

    def run_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        return asyncio.run(ExecutionOrchestrator.execute_actions(
            self.device, actions, team_id=self.context.team_id, context=self.context))

    def evidence(self, name: str) -> str:
        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
        ok = capture_screenshot_for_script(self.device, self.context, name)
        return self.context.screenshot_paths[-1] if ok and self.context.screenshot_paths else ""


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 1)


def _read_frame(path: Optional[str]) -> Optional[Any]:
    """cv2 BGR load; matches the Tetris / Flappy use of cv2.imread on the latest capture."""
    if not path or not os.path.exists(path):
        return None
    return cv2_io.imread(path)


class KirbyRunner:
    """The fight loop. ``choose`` has the ``(state, options, instructions) -> dict`` contract;
    ``choose=None`` runs the bot alone with the ``rush`` tactic (the baseline)."""

    def __init__(self, io, context, choose: Optional[Callable] = None, max_duration: int = 170):
        self.io = io
        self.context = context
        self.choose = choose
        self.max_duration = max_duration
        self.tactic = "rush"
        self.tactic_start_hp: Optional[float] = None
        self.fight_start = time.time()
        self.last_ask_t = 0.0
        self.last_ask_hp: Optional[float] = None
        self.last_ask_dx: Optional[float] = None
        self.pending: Optional[concurrent.futures.Future] = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.history = collections.deque(maxlen=120)   # per-frame obs + t, for speed / HP-loss reads
        self.tactic_frames: Dict[str, int] = {t: 0 for t in TACTICS}
        self.window_frames: Dict[str, int] = {t: 0 for t in TACTICS}
        self.window_decisions: List[Dict[str, Any]] = []
        self.jev_ms: List[float] = []
        self.open_outcomes: List[Dict[str, Any]] = []   # decisions waiting for their 2 s HP window
        self.data: Dict[str, Any] = {
            "chooser": "fixed" if choose is None else "jev",
            "fight_s": 0.0,
            "end_reason": "",
            "kirby_hp_end": None,
            "mate_hp_end": None,
            "frames": 0,
            "loop_ms_p50": None,
            "decisions": 0,
            "tactics": {},
            "jev_ms_p50": None,
            "jev_cost_usd": 0.0,
            "jev_input_tokens": 0,
            "jev_output_tokens": 0,
            "actions_sent": 0,
        }

    # --- Jev (background) -------------------------------------------------------------
    def options(self) -> List[Dict[str, str]]:
        return [{"id": t, "facts": TACTICS[t]} for t in TACTICS]

    def instructions(self) -> str:
        return "Pick the tactic that wins the boss fight fastest without Kirby being knocked out."

    def _maybe_ask(self, obs: dict, now: float) -> None:
        """Submit a Jev decision if none is pending and a trigger fired. Never blocks."""
        if self.choose is None or (self.pending is not None and not self.pending.done()):
            return
        kx, bx = obs.get("kirby_x"), obs.get("boss_x")
        dx = (bx - kx) if (kx is not None and bx is not None) else None
        khp = obs.get("kirby_hp")

        hp_lost = self.last_ask_hp is not None and khp is not None and self.last_ask_hp - khp >= HP_LOSS_TRIGGER
        crossed = (self.last_ask_dx is not None and dx is not None
                   and (abs(dx) >= DIST_TRIGGER_PX) != (abs(self.last_ask_dx) >= DIST_TRIGGER_PX))
        if not (now - self.last_ask_t >= JEV_TRIGGER_S or hp_lost or crossed):
            return

        lost = 0.0 if self.tactic_start_hp is None or khp is None else max(0.0, self.tactic_start_hp - khp)
        state = state_text(obs, list(self.history), self.tactic, lost, self.fight_start, now)
        self.last_ask_t, self.last_ask_hp, self.last_ask_dx = now, khp, dx
        self.pending = self.executor.submit(self.choose, state, self.options(), self.instructions())

    def _harvest(self, obs: dict, now: float) -> None:
        """Apply a finished Jev decision (no-op while it is still running)."""
        if self.pending is None or not self.pending.done():
            return
        future, self.pending = self.pending, None
        try:
            result = future.result()
        except Exception as e:  # Jev must never crash the fight
            print(f"[game_kirby] chooser raised: {e}")
            return
        choice = (result or {}).get("choice")
        if choice not in TACTICS:
            return
        self.tactic = choice
        self.tactic_start_hp = obs.get("kirby_hp")
        self.data["decisions"] += 1
        self.data["jev_cost_usd"] = round(self.data["jev_cost_usd"] + float(result.get("cost") or 0.0), 6)
        usage = result.get("usage") or {}
        self.data["jev_input_tokens"] += int(usage.get("input_tokens") or 0)
        self.data["jev_output_tokens"] += int(usage.get("output_tokens") or 0)
        if result.get("ms") is not None:
            self.jev_ms.append(result["ms"])
        self.window_decisions.append({"tactic": choice, "confidence": result.get("confidence"),
                                      "ms": result.get("ms")})
        if result.get("decision_id"):
            self.open_outcomes.append({"id": result["decision_id"], "t": now,
                                       "kirby_hp": obs.get("kirby_hp"), "mate_hp": obs.get("mate_hp")})

    def _settle_outcomes(self, obs: dict, now: float, outcome_writer: Optional[Callable], force: bool = False) -> None:
        """Write the HP lost in the 2 s after each decision (``decisions.set_outcome``), main thread."""
        still_open = []
        for o in self.open_outcomes:
            if not force and now - o["t"] < OUTCOME_WINDOW_S:
                still_open.append(o)
                continue
            if outcome_writer is None or None in (o["kirby_hp"], obs.get("kirby_hp")):
                continue
            mate_lost = (max(0.0, o["mate_hp"] - obs["mate_hp"])
                         if o["mate_hp"] is not None and obs.get("mate_hp") is not None else 0.0)
            try:
                outcome_writer([o["id"]], {"kirby_hp_lost": round(max(0.0, o["kirby_hp"] - obs["kirby_hp"]), 4),
                                           "mate_hp_lost": round(mate_lost, 4), "window_s": OUTCOME_WINDOW_S})
            except Exception as e:
                print(f"[game_kirby] outcome_writer failed for {o['id']}: {e}")
        self.open_outcomes = still_open

    # --- report ------------------------------------------------------------------------
    def record_step(self, message: str, success: bool, details: Dict[str, Any],
                    screenshot: str = "", started: Optional[float] = None,
                    shots: Optional[List[Dict[str, Any]]] = None) -> None:
        """``shots``: several screenshots for one step, ``[{"path", "label", ...}]`` in time order."""
        now = time.time()
        started = started or now
        shots = [x for x in (shots or []) if x.get("path")]
        if screenshot:
            shots.append({"path": screenshot, "label": "end"})
        self.context.record_step_immediately({
            "success": success, "message": message, "from_node": "game", "to_node": "game",
            "execution_time_ms": int((now - started) * 1000),
            "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
            "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "screenshot_path": shots[-1]["path"] if shots else None,
            "step_end_screenshot_path": shots[-1]["path"] if shots else None,
            "action_screenshots": [x["path"] for x in shots],
            "actions": [{"command": x["label"], "params": {k: v for k, v in x.items() if k not in ("path", "label")}}
                        for x in shots],
            "verifications": [{"verification_type": "kirby", "command": "play", "label": message,
                               "success": success, "details": details}],
            "verification_results": [], "step_category": "kirby",
        })

    # --- main loop --------------------------------------------------------------------
    def run(self, outcome_writer: Optional[Callable] = None) -> Dict[str, Any]:
        data = self.data
        self.fight_start = start = time.time()
        loop_ms: List[float] = []
        last_path: Optional[str] = None
        last_report_t = start
        last_shot_t = start
        self.window_shots: List[Dict[str, Any]] = []
        streak = 0              # consecutive frames without Kirby's HP bar
        saw_fight = False
        fight_obs: Dict[str, Any] = {}   # last frame with Kirby's HP bar, for the final outcomes
        self.record_step(f"Kirby fight started, chooser={data['chooser']}", True,
                         {"chooser": data["chooser"], "max_duration": self.max_duration},
                         self.io.evidence("kirby_fight_start"))

        while True:
            now = time.time()
            if now - start >= self.max_duration:
                data["end_reason"] = "max_duration"
                break
            if not saw_fight and now - start >= NO_FIGHT_TIMEOUT_S:
                data["end_reason"] = "no_fight"
                break
            path = self.io.frame()
            if not path or path == last_path:
                time.sleep(IDLE_S)   # no new frame yet: poll again (cheap, nothing is decoded)
                continue
            last_path = path
            img = _read_frame(path)
            if img is None:
                continue
            t0 = time.perf_counter()
            obs = read_vision(img)
            data["frames"] += 1
            self._harvest(obs, now)
            self._settle_outcomes(obs, now, outcome_writer)

            if not obs["in_fight"]:
                streak += 1
                if saw_fight and streak >= END_NOT_FIGHT_FRAMES:
                    data["end_reason"] = "fight_over"
                    break
                continue   # never press buttons on a result / menu screen
            streak = 0
            fight_obs = obs
            if not saw_fight:
                saw_fight = True
                self.tactic_start_hp = obs.get("kirby_hp")
            self.history.append({"t": now, "boss_x": obs.get("boss_x"), "kirby_x": obs.get("kirby_x"),
                                 "kirby_hp": obs.get("kirby_hp"), "mate_hp": obs.get("mate_hp")})
            data["kirby_hp_end"], data["mate_hp_end"] = obs.get("kirby_hp"), obs.get("mate_hp")
            self._maybe_ask(obs, now)

            actions = bot_step(self.tactic, obs, self.history[-2] if len(self.history) > 1 else None)
            self.tactic_frames[self.tactic] += 1
            self.window_frames[self.tactic] += 1
            loop_ms.append((time.perf_counter() - t0) * 1000)   # decide time, excludes sending
            data["actions_sent"] += len(actions)
            self._send_actions(actions)

            if time.time() - last_shot_t >= SHOT_EVERY_S:
                last_shot_t = time.time()
                self.window_shots.append({
                    "path": self.io.evidence(f"kirby_fight_{int(last_shot_t - start)}s"),
                    "label": f"t+{int(last_shot_t - start)}s {self.tactic}",
                    "kirby_hp": obs.get("kirby_hp"), "kirby_x": obs.get("kirby_x"), "boss_x": obs.get("boss_x"),
                })

            if time.time() - last_report_t >= REPORT_EVERY_S:
                self.record_step(
                    f"Fight window: {int(time.time() - last_report_t)} s, tactic={self.tactic}, "
                    f"Kirby HP {int(round((obs.get('kirby_hp') or 0) * 100))} %",
                    True,
                    {"kirby_hp": obs.get("kirby_hp"), "mate_hp": obs.get("mate_hp"),
                     "tactic": self.tactic, "tactics_window": dict(self.window_frames),
                     "decisions": self.window_decisions, "loop_ms_p50": _pct(loop_ms[-200:], 0.5)},
                    "", last_report_t,
                    shots=self.window_shots or [{"path": self.io.evidence(f"kirby_fight_{int(time.time() - start)}s"),
                                            "label": f"t+{int(time.time() - start)}s {self.tactic}"}])
                self.window_shots = []
                last_report_t = time.time()
                self.window_frames = {t: 0 for t in TACTICS}
                self.window_decisions = []

        if fight_obs:
            self._settle_outcomes(fight_obs, time.time(), outcome_writer, force=True)
        data["fight_s"] = round(time.time() - start, 2)
        data["loop_ms_p50"] = _pct(loop_ms, 0.5)
        data["tactics"] = dict(self.tactic_frames)
        data["jev_ms_p50"] = _pct(self.jev_ms, 0.5)
        return self._finish()

    def _send_actions(self, actions: List[Dict[str, Any]]) -> None:
        """One batch per frame: consecutive actions go in one call; an action with ``pre_wait_ms``
        starts a new call after that sleep (the controller call itself costs ~170 ms)."""
        batch: List[Dict[str, Any]] = []
        for action in actions:
            wait = action.get("pre_wait_ms")
            body = {k: v for k, v in action.items() if k != "pre_wait_ms"}
            if wait and batch:
                self._run(batch)
                batch = []
            if wait:
                time.sleep(wait / 1000.0)
            batch.append(body)
        self._run(batch)

    def _run(self, batch: List[Dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            self.io.run_actions(batch)
        except Exception as e:
            print(f"[game_kirby] actions {[a.get('command') for a in batch]} failed: {e}")

    def _finish(self) -> Dict[str, Any]:
        data = self.data
        self._run([_action("release")])   # never leave a held button behind
        shot = self.io.evidence("kirby_final")
        self.record_step(
            f"KPI: fight {data['fight_s']} s, {data['frames']} frames, "
            f"{data['decisions']} Jev decisions, end_reason={data['end_reason']}",
            True,
            {k: data[k] for k in ("frames", "fight_s", "end_reason", "kirby_hp_end", "mate_hp_end",
                                  "decisions", "tactics", "loop_ms_p50", "jev_ms_p50",
                                  "jev_cost_usd", "jev_input_tokens", "jev_output_tokens", "actions_sent",
                                  "chooser")},
            shot, shots=self.window_shots)   # the last, unfinished window's screenshots
        self.executor.shutdown(wait=False)
        return data


KPI_FIELDS = ("chooser", "fight_s", "end_reason", "kirby_hp_end", "mate_hp_end", "frames",
              "loop_ms_p50", "decisions", "tactics", "jev_ms_p50", "jev_cost_usd",
              "jev_input_tokens", "jev_output_tokens", "actions_sent")


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data.get(k) for k in KPI_FIELDS}


def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    return "\n".join([
        "Super Kirby Clash (TASK-51)",
        f"Fight: {data.get('fight_s', 0)} s, {data.get('frames', 0)} frames, "
        f"end_reason={data.get('end_reason', '')}",
        f"Kirby HP: {data.get('kirby_hp_end')}, teammate HP: {data.get('mate_hp_end')}",
        f"Decisions: {data.get('decisions', 0)} ({data.get('jev_ms_p50')} ms p50, "
        f"${data.get('jev_cost_usd', 0)}, {data.get('jev_input_tokens', 0)} in / "
        f"{data.get('jev_output_tokens', 0)} out tokens)",
        f"Tactics: {data.get('tactics', {})}",
        f"Loop: {data.get('loop_ms_p50')} ms p50, {data.get('actions_sent', 0)} actions sent",
        f"Result: {'PASS' if success else 'FAIL'}" + (f" - {error}" if error else ""),
    ])