"""
The two drone demos over DroneIO + Reporter: hide and seek, and the find-the-object race.

Each drone runs the same loop in its own thread: capture a frame, let the agent pick one action,
pass it through the safety guard, send it, report the turn. Agents only claim; the referee decides.
All drones are landed in a finally block. An operator kill file sends `emergency` to every drone.
"""

import os
import threading
import time
from typing import Dict, List, Optional

import numpy as np

from .agents import Decision
from .io import DroneIO
from .perception import draw_detection
from .referee import Referee
from .report import Reporter
from .safety import SafetyGuard, SafetyLimits
from .sim.world import START_SPOTS, Pose

KILL_FILE = "/tmp/vpt-drone-kill"
KEEPALIVE_S = 4.0
LAND_TIMEOUT_S = 20.0


class KillSwitch:
    """Operator kill: when the file appears every drone gets `emergency` (motors off) and the game stops."""

    def __init__(self, path: Optional[str] = KILL_FILE):
        self.path = path
        self.ios: List[DroneIO] = []
        self.event = threading.Event()
        self._lock = threading.Lock()

    def triggered(self) -> bool:
        if self.event.is_set():
            return True
        if self.path and os.path.exists(self.path):
            with self._lock:
                if not self.event.is_set():
                    self.event.set()
                    for io in self.ios:
                        try:
                            io.command("emergency", timeout_s=3)
                        except Exception:
                            pass
        return self.event.is_set()


class DroneRunner:
    """One drone: guard, agent and the counters that become KPIs."""

    def __init__(self, io: DroneIO, agent, guard: SafetyGuard, limits: SafetyLimits, reporter: Reporter,
                 stop: threading.Event, kill: KillSwitch):
        self.io, self.agent, self.guard, self.limits = io, agent, guard, limits
        if hasattr(agent, "set_peers"):
            agent.set_peers(guard.peers)
        self.reporter, self.stop, self.kill = reporter, stop, kill
        self.turns = self.commands = self.blocks = self.claims = self.false_claims = 0
        self.ai_calls = self.tokens_in = self.tokens_out = 0
        self.blocked: Optional[str] = None
        self.dead = False
        self.battery_start: Optional[int] = None
        self.battery_end: Optional[int] = None
        self._last_ka = time.time()
        self._last_hold = False
        self._cmd_done_at = 0.0

    SETTLE_S = 0.35

    @property
    def name(self) -> str:
        return self.io.name

    def halted(self) -> bool:
        return self.stop.is_set() or self.kill.triggered() or self.dead

    def battery(self) -> Optional[int]:
        bat = (self.io.telemetry() or {}).get("bat")
        if bat is not None:
            self.battery_end = bat
            if self.battery_start is None:
                self.battery_start = bat
        return bat

    def _send(self, cmd: str, timeout_s: float) -> tuple:
        ok, reply = self.io.command(cmd, timeout_s=timeout_s)
        self.commands += 1
        if not ok and not reply.lower().startswith("error") and not self.kill.triggered():
            ok, reply = self.io.command(cmd, timeout_s=timeout_s)  # one retry on a timeout
            self.commands += 1
            if not ok and not reply.lower().startswith("error") and cmd != "land":
                self.reporter.step(self.name, f"{cmd}: no answer twice, landing", False, kind="info")
                self.land(force=True)
                self.dead = True
        return ok, reply

    def exec(self, cmd: str) -> tuple:
        """Run cmd through the guard. Returns (ok, text); text is the guard reason when it intervened."""
        allowed, to_send, reason = self.guard.check(cmd)
        if not allowed:
            self.blocks += 1
            if to_send == "land":
                self.reporter.step(self.name, f"guard: {reason}", False, kind="info")
                self.land()
                self.dead = True
            return False, reason
        if to_send != cmd:
            self.blocks += 1
        timeout = self.limits.takeoff_timeout_s if to_send in ("takeoff", "land") else self.limits.cmd_timeout_s
        ok, reply = self._send(to_send, timeout)
        if ok:
            self.guard.apply(to_send)
        if ok:
            return True, reason if reason != "ok" else "ok"
        return False, reply if reason == "ok" else f"{reply} ({reason})"

    def takeoff(self) -> bool:
        self.battery()
        ok, text = self.exec("takeoff")
        self.reporter.step(self.name, f"takeoff: {text}", ok, kind="info")
        if ok:
            start = getattr(self.io, "start_keepalive", None)
            if start:
                start(5.0)
        else:
            self.dead = True
        return ok

    def land(self, force: bool = False) -> None:
        if self.guard.pose.z <= 5 and not force and not self.kill.event.is_set():
            return
        if self.kill.event.is_set():
            self.guard.pose.z = 0
            return
        for _ in range(2):
            ok, reply = self.io.command("land", timeout_s=LAND_TIMEOUT_S)
            if ok:
                self.guard.apply("land")
                self.reporter.step(self.name, "landed", True, kind="info")
                return
            self.reporter.step(self.name, f"land failed: {reply}", False, kind="info")

    def keepalive(self) -> None:
        if time.time() - self._last_ka >= KEEPALIVE_S:
            self.io.command("battery?", timeout_s=3)
            self._last_ka = time.time()

    def turn(self) -> Optional[Decision]:
        """One perceive-decide-act turn. Returns the decision (None when no frame / drone halted)."""
        if self.halted():
            return None
        bat = self.battery()
        if bat is not None and bat <= self.limits.bat_land:
            self.reporter.step(self.name, f"battery {bat}%, landing", False, kind="info")
            self.land()
            self.dead = True
            return None
        wait = self.SETTLE_S - (time.time() - self._cmd_done_at)
        if wait > 0:
            time.sleep(wait)  # the video lags the drone: let the picture catch up with the finished move
        frame = self.io.frame(fresh=True)  # a stale frame would show where the drone was, not where it is
        if frame is None:
            time.sleep(0.2)
            return None
        self.guard.sync_yaw(self.io.telemetry() or {})
        pose = self.guard.pose
        d = self.agent.decide(frame, pose, self.blocked)
        self.turns += 1
        self.ai_calls += d.ai_calls
        self.tokens_in += d.tokens_in
        self.tokens_out += d.tokens_out
        details = {"pose": [round(pose.x), round(pose.y), round(pose.z), round(pose.yaw_deg)], "action": d.action}
        if d.detection:
            details["detection"] = {"label": d.detection.label, "conf": round(d.detection.confidence, 2),
                                    "bbox": list(d.detection.bbox), "source": d.detection.source}
        if d.tokens_in or d.tokens_out:
            details["tokens"] = [d.tokens_in, d.tokens_out]
        shown = draw_detection(frame, d.detection)
        if d.action == "claim":
            return d  # the game reports the claim with the referee verdict
        if d.action == "hold":
            if not self._last_hold:
                self.reporter.step(self.name, f"hold: {d.note}", True, shown, details)
            self._last_hold = True
            self.keepalive()
            time.sleep(0.5)
            return d
        self._last_hold = False
        ok, text = self.exec(d.action)
        self._cmd_done_at = time.time()
        self.blocked = None if ok and text == "ok" else text
        details["result"] = text
        self.reporter.step(self.name, f"{d.action}: {d.note} -> {text}", ok, shown, details)
        return d


def _kpis(game: str, runners: List[DroneRunner], extra_objs: list, **kw) -> dict:
    """KPIs. The agent's AI calls (a planning model) and the perception's (a vision model on frames) are
    counted apart and summed into ai_calls / tokens_in / tokens_out."""
    a_calls = sum(r.ai_calls for r in runners)
    a_in, a_out = sum(r.tokens_in for r in runners), sum(r.tokens_out for r in runners)
    p_calls = p_in = p_out = 0
    models = set()
    seen = set()
    for o in extra_objs:
        if o is not None and id(o) not in seen and hasattr(o, "ai_calls"):
            seen.add(id(o))
            p_calls += o.ai_calls
            p_in += getattr(o, "tokens_in", 0)
            p_out += getattr(o, "tokens_out", 0)
            models |= set(getattr(o, "models", ()))
    for r in runners:
        models |= set(getattr(r.agent, "models", ()))
    return {
        "game": game,
        "turns_by_drone": {r.name: r.turns for r in runners},
        "claims": sum(r.claims for r in runners),
        "false_claims": sum(r.false_claims for r in runners),
        "commands_sent": sum(r.commands for r in runners),
        "guard_blocks": sum(r.blocks for r in runners),
        "battery_start": {r.name: r.battery_start for r in runners},
        "battery_end": {r.name: r.battery_end for r in runners},
        "ai_calls": a_calls + p_calls, "tokens_in": a_in + p_in, "tokens_out": a_out + p_out,
        "agent_ai_calls": a_calls, "agent_tokens_in": a_in, "agent_tokens_out": a_out,
        "perception_ai_calls": p_calls, "perception_tokens_in": p_in, "perception_tokens_out": p_out,
        "agent_fallbacks": sum(getattr(r.agent, "fallbacks", 0) for r in runners),
        "ai_models": sorted(models),
        **kw,
    }


def _land_all(runners: List[DroneRunner], kill: KillSwitch) -> bool:
    for r in runners:
        try:
            r.land()
        except Exception:
            pass
    return all(r.guard.pose.z <= 5 for r in runners)


def _sleep(seconds: float, runner_halted) -> None:
    end = time.time() + seconds
    while time.time() < end and not runner_halted():
        time.sleep(0.1)


def _make_guard(io: DroneIO, limits: SafetyLimits, start_poses: Optional[Dict[int, Pose]], peers) -> SafetyGuard:
    spots = start_poses or START_SPOTS
    return SafetyGuard(limits, spots[io.index], peers=peers, telemetry=io.telemetry)


class ObjectRaceGame:
    def __init__(self, drones: List[DroneIO], agents: list, perception, referee: Referee, reporter: Reporter,
                 limits: SafetyLimits, target: str, timeout_s: float = 180, penalty_s: float = 3.0,
                 start_poses: Optional[Dict[int, Pose]] = None, kill_file: Optional[str] = KILL_FILE):
        self.drones, self.agents, self.perception, self.referee = drones, agents, perception, referee
        self.reporter, self.limits, self.target = reporter, limits, target
        self.timeout_s, self.penalty_s = timeout_s, penalty_s
        self.kill = KillSwitch(kill_file)
        self.kill.ios = list(drones)
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self.winner: Optional[DroneRunner] = None
        self.win_frame: Optional[np.ndarray] = None
        self.win_verdict: Optional[dict] = None
        self.t_win: Optional[float] = None
        self.runners: List[DroneRunner] = []
        for io, agent in zip(drones, agents):
            self.runners.append(DroneRunner(
                io, agent, _make_guard(io, limits, start_poses,
                                       lambda me=io: [r.guard.pose for r in self.runners if r.io is not me]),
                limits, reporter, self.stop, self.kill))

    def run(self) -> dict:
        landed = False
        barrier = threading.Barrier(len(self.runners))
        self.t0 = time.time()
        threads = [threading.Thread(target=self._drone_loop, args=(r, barrier), daemon=True, name=r.name)
                   for r in self.runners]
        try:
            if self.kill.triggered():
                self.reporter.step("operator", "kill file present, not starting", False, kind="info")
            else:
                for t in threads:
                    t.start()
                while any(t.is_alive() for t in threads):
                    self.kill.triggered()
                    for t in threads:
                        t.join(0.2)
        except BaseException:
            self.stop.set()
            raise
        finally:
            self.stop.set()
            for t in threads:
                if t.is_alive():
                    t.join(5)
            landed = _land_all(self.runners, self.kill)
        if self.winner:
            self.reporter.step(self.winner.name, f"Winner: {self.winner.name} found the {self.target} "
                               f"in {self.t_win:.1f}s", True, self.win_frame, self.win_verdict, kind="winner")
        else:
            self.reporter.step("referee", "No winner" + (" (operator kill)" if self.kill.event.is_set() else ""),
                               False, kind="winner")
        k = _kpis("race", self.runners, [self.perception, self.referee.detector],
                  winner=self.winner.name if self.winner else None, target=self.target,
                  time_to_win_s=round(self.t_win, 2) if self.t_win is not None else None,
                  perception=getattr(self.perception, "name", "?"),
                  agent=getattr(self.agents[0], "name", "?"), landed=landed, killed=self.kill.event.is_set())
        k["report"] = self.reporter.finish(k)
        return k

    def _drone_loop(self, r: DroneRunner, barrier: threading.Barrier) -> None:
        try:
            r.agent.start(self.target)
            ok = r.takeoff() if not self.kill.triggered() else False
            try:
                barrier.wait(self.limits.takeoff_timeout_s + 15)
            except threading.BrokenBarrierError:
                pass
            if not ok:
                return
            t0 = time.time()
            while not r.halted() and time.time() - t0 < self.timeout_s:
                d = r.turn()
                if d is not None and d.action == "claim":
                    self._claim(r, d, t0)
        except Exception as e:  # keep the other drone flying; the finally of run() lands everyone
            self.reporter.step(r.name, f"error: {e!r}", False, kind="info")
            r.dead = True

    def _claim(self, r: DroneRunner, d: Decision, t0: float) -> None:
        r.claims += 1
        verdict, frame = self.referee.verify(r.io, self.target)
        details = {"verdict": verdict, "agent_detection": d.detection.confidence if d.detection else None}
        if verdict["confirmed"]:
            with self._lock:
                first = self.winner is None
                if first:
                    self.winner, self.win_frame, self.win_verdict = r, frame, verdict
                    self.t_win = time.time() - t0
                    self.stop.set()
            self.reporter.step(r.name, "claim confirmed" + ("" if first else " (too late)"), True, frame,
                               details, kind="claim")
        else:
            r.false_claims += 1
            self.reporter.step(r.name, f"claim rejected: {verdict['reason']}, {self.penalty_s:g}s penalty", False,
                               frame, details, kind="claim")
            r.agent.rejected()
            _sleep(self.penalty_s, r.halted)


class HideAndSeekGame:
    def __init__(self, hider: DroneIO, seeker: DroneIO, hider_agent, seeker_agent, perception, referee: Referee,
                 reporter: Reporter, limits: SafetyLimits, hide_s: float = 60, seek_s: float = 180,
                 start_poses: Optional[Dict[int, Pose]] = None, kill_file: Optional[str] = KILL_FILE):
        self.hider_io, self.seeker_io = hider, seeker
        self.perception, self.referee, self.reporter, self.limits = perception, referee, reporter, limits
        self.hide_s, self.seek_s = hide_s, seek_s
        self.kill = KillSwitch(kill_file)
        self.kill.ios = [hider, seeker]
        self.stop = threading.Event()
        self.runners: List[DroneRunner] = []
        self.hider = DroneRunner(hider, hider_agent, _make_guard(hider, limits, start_poses,
                                 lambda: [self.seeker.guard.pose]), limits, reporter, self.stop, self.kill)
        self.seeker = DroneRunner(seeker, seeker_agent, _make_guard(seeker, limits, start_poses,
                                  lambda: [self.hider.guard.pose]), limits, reporter, self.stop, self.kill)
        self.runners = [self.hider, self.seeker]

    def run(self) -> dict:
        found = False
        t_find: Optional[float] = None
        frame = verdict = None
        landed = False
        hold = threading.Thread(target=self._hider_hold, daemon=True)
        try:
            if self.kill.triggered():
                self.reporter.step("operator", "kill file present, not starting", False, kind="info")
            else:
                self.hider.agent.start("")
                self.seeker.agent.start(str(self.hider_io.index))
                if self.hider.takeoff():
                    self._hide_phase()
                if not self.hider.dead and not self.kill.triggered():
                    hold.start()
                    found, t_find, frame, verdict = self._seek_phase()
        finally:
            self.stop.set()
            if hold.is_alive():
                hold.join(5)
            landed = _land_all(self.runners, self.kill)
        killed = self.kill.event.is_set()
        if found:
            self.reporter.step(self.seeker.name, f"Winner: {self.seeker.name} (seeker) found {self.hider.name} "
                               f"in {t_find:.1f}s", True, frame, verdict, kind="winner")
        else:
            self.reporter.step(self.hider.name, "Winner: " + (f"{self.hider.name} (hider) stayed hidden"
                               if not killed and not self.hider.dead and not self.seeker.dead else "nobody (aborted)"),
                               not killed, kind="winner")
        aborted = killed or self.hider.dead or self.seeker.dead
        winner = self.seeker.name if found else (None if aborted else self.hider.name)
        k = _kpis("hide_and_seek", self.runners, [self.perception, self.referee.detector], winner=winner,
                  target=f"marker {self.hider_io.index}",
                  time_to_win_s=round(t_find, 2) if t_find is not None else None,
                  perception=getattr(self.perception, "name", "?"),
                  agent=getattr(self.seeker.agent, "name", "?"), landed=landed, killed=killed,
                  hiding_spot=getattr(self.hider.agent, "spot", None))
        k["report"] = self.reporter.finish(k)
        return k

    def _hide_phase(self) -> None:
        t0 = time.time()
        while time.time() - t0 < self.hide_s and not self.hider.halted():
            self.hider.turn()

    def _hider_hold(self) -> None:
        while not self.stop.is_set() and not self.hider.halted():
            self.hider.keepalive()
            self.hider.battery()
            if (self.hider.battery_end or 100) <= self.limits.bat_land:
                self.hider.land()
                self.hider.dead = True
            time.sleep(0.5)

    def _seek_phase(self):
        s = self.seeker
        if not s.takeoff():
            return False, None, None, None
        t0 = time.time()
        while not s.halted() and not self.hider.dead and time.time() - t0 < self.seek_s:
            d = s.turn()
            if d is not None and d.action == "claim":
                s.claims += 1
                verdict, frame = self.referee.verify(s.io, str(self.hider_io.index))
                details = {"verdict": verdict}
                if verdict["confirmed"]:
                    self.reporter.step(s.name, "claim confirmed", True, frame, details, kind="claim")
                    return True, time.time() - t0, frame, verdict
                s.false_claims += 1
                self.reporter.step(s.name, f"claim rejected: {verdict['reason']}", False, frame, details,
                                   kind="claim")
                s.agent.rejected()
        return False, None, None, None
