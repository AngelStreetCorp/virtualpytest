"""Game logic against fake drones: claims, referee, penalties, landing, operator kill."""
import threading

import numpy as np

from shared.src.lib.drone.agents import HiderAgent, ScanAgent
from shared.src.lib.drone.games import HideAndSeekGame, ObjectRaceGame
from shared.src.lib.drone.perception import Detection
from shared.src.lib.drone.referee import Referee
from shared.src.lib.drone.safety import SafetyLimits
from shared.src.lib.drone.sim.world import START_SPOTS


class FakeIO:
    def __init__(self, name, index, bat=90, on_command=None):
        self.name, self.index = name, index
        self.cmds = []
        self.bat = bat
        self.on_command = on_command
        self.lock = threading.Lock()

    def command(self, cmd, timeout_s=None):
        with self.lock:
            self.cmds.append(cmd)
        if self.on_command:
            self.on_command(self, cmd)
        return True, "ok"

    def frame(self, fresh=False):
        return np.full((720, 960, 3), self.index, np.uint8)

    def telemetry(self):
        return {"bat": self.bat, "temph": 50, "h": 80}

    def close(self):
        pass


class Det:
    """Detects the target on drone `who` once it has sent >= n commands."""
    name = "fake"

    def __init__(self, n_by_io, conf=0.9):
        self.n_by_io, self.conf = n_by_io, conf
        self.ios = {}

    def detect(self, frame, target):
        for io, n in self.n_by_io.items():
            if io.index == int(frame[0, 0, 0]) and len(io.cmds) >= n:
                return Detection(target, self.conf, (10, 10, 50, 50), "fake")
        return None


class RefDet(Det):
    def detect(self, frame, target):
        return Detection(target, self.conf, (10, 10, 50, 50), "fakeref") if self.on else None

    def __init__(self, on=True, conf=0.9):
        self.on, self.conf = on, conf


class FakeReporter:
    def __init__(self):
        self.steps = []

    def step(self, drone, message, success, frame=None, details=None, kind="turn"):
        self.steps.append((drone, message, success, kind))

    def finish(self, summary):
        return "fake-report"


LIM = SafetyLimits()


def race(a, b, perception, ref, kill_file, **kw):
    ios = [a, b]
    agents = [ScanAgent(perception, LIM), ScanAgent(perception, LIM)]
    rep = FakeReporter()
    g = ObjectRaceGame(ios, agents, perception, Referee(ref, settle_s=0), rep, LIM, "sofa", timeout_s=10,
                       penalty_s=0.2, kill_file=kill_file, **kw)
    return g, rep


def test_race_first_confirmed_claim_wins_and_all_land(tmp_path):
    a, b = FakeIO("d1", 1), FakeIO("d2", 2)
    per = Det({a: 4})
    g, rep = race(a, b, per, RefDet(True), str(tmp_path / "kill"))
    k = g.run()
    assert k["winner"] == "d1" and k["false_claims"] == 0 and k["claims"] >= 1
    assert a.cmds[-1] == "land" and b.cmds[-1] == "land" and k["landed"]
    assert any(s[3] == "winner" for s in rep.steps)


def test_race_false_claim_costs_penalty_then_game_times_out(tmp_path):
    a, b = FakeIO("d1", 1), FakeIO("d2", 2)
    per = Det({a: 3})
    g, rep = race(a, b, per, RefDet(False), str(tmp_path / "kill"))
    g.timeout_s = 2
    k = g.run()
    assert k["winner"] is None and k["false_claims"] >= 1 and k["landed"]


def test_race_single_drone(tmp_path):
    a = FakeIO("d1", 1)
    g, _ = race(a, FakeIO("x", 2), Det({a: 3}), RefDet(True), str(tmp_path / "kill"))
    g2 = ObjectRaceGame([a], [ScanAgent(Det({a: 3}), LIM)], Det({a: 3}), Referee(RefDet(True), settle_s=0),
                        FakeReporter(), LIM, "sofa", timeout_s=5, kill_file=str(tmp_path / "kill"))
    assert g2.run()["winner"] == "d1"


def test_kill_file_sends_emergency_to_every_drone_and_stops(tmp_path):
    kill = tmp_path / "kill"

    def trip(io, cmd):
        if len(io.cmds) == 5:
            kill.write_text("x")

    a, b = FakeIO("d1", 1, on_command=trip), FakeIO("d2", 2)
    g, rep = race(a, b, Det({}), RefDet(True), str(kill))
    g.timeout_s = 30
    k = g.run()
    assert k["killed"] and k["winner"] is None
    assert a.cmds.count("emergency") == 1 and b.cmds.count("emergency") == 1
    assert "land" not in a.cmds and "land" not in b.cmds  # motors are cut, no land after emergency
    assert len(a.cmds) < 20


def test_stale_kill_file_prevents_start(tmp_path):
    kill = tmp_path / "kill"
    kill.write_text("x")
    a, b = FakeIO("d1", 1), FakeIO("d2", 2)
    g, _ = race(a, b, Det({}), RefDet(True), str(kill))
    k = g.run()
    assert k["killed"] and "takeoff" not in a.cmds + b.cmds


def test_exception_in_agent_lands_everyone(tmp_path):
    a, b = FakeIO("d1", 1), FakeIO("d2", 2)

    class Boom(ScanAgent):
        def decide(self, *args, **kw):
            raise RuntimeError("boom")

    rep = FakeReporter()
    g = ObjectRaceGame([a, b], [Boom(Det({}), LIM), ScanAgent(Det({}), LIM)], Det({}), Referee(RefDet(), settle_s=0),
                       rep, LIM, "sofa", timeout_s=1.5, kill_file=str(tmp_path / "kill"))
    k = g.run()
    assert k["landed"] and a.cmds[-1] == "land" and b.cmds[-1] == "land"
    assert any("boom" in s[1] for s in rep.steps)


def test_low_battery_lands_that_drone_only(tmp_path):
    a, b = FakeIO("d1", 1, bat=15), FakeIO("d2", 2)
    g, _ = race(a, b, Det({}), RefDet(True), str(tmp_path / "kill"))
    g.timeout_s = 1
    g.run()
    assert "takeoff" not in a.cmds  # below the 40% takeoff floor
    assert "takeoff" in b.cmds and b.cmds[-1] == "land"


def test_hide_and_seek_seeker_finds_hider(tmp_path):
    h, s = FakeIO("d1", 1), FakeIO("d2", 2)
    per = Det({s: 12})
    ref = RefDet(True)
    rep = FakeReporter()
    g = HideAndSeekGame(h, s, HiderAgent(LIM, START_SPOTS[2]),
                        ScanAgent(per, LIM), per, Referee(ref, settle_s=0), rep, LIM, hide_s=1.5, seek_s=10,
                        kill_file=str(tmp_path / "kill"))
    k = g.run()
    assert k["winner"] == "d2" and k["landed"] and h.cmds[-1] == "land" and s.cmds[-1] == "land"
    assert k["game"] == "hide_and_seek"
