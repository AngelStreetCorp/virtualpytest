"""Planning agents on the simulated room's map: routes go through the gap, legs are guard-clean."""
import sys

import pytest

from shared.src.lib.drone.agents import HiderAgent, Navigator, ScanAgent
from shared.src.lib.drone.roommap import RoomMap
from shared.src.lib.drone.safety import SafetyGuard, SafetyLimits
from shared.src.lib.drone.sim.world import HIDE_SPOTS, START_SPOTS, Pose, default_room

LIM = SafetyLimits(room_map=RoomMap.from_sim_room(default_room()))


def fly(nav, guard, goal, steps=80):
    nav.set_goal(guard.pose, goal)
    guard.apply("takeoff")
    for _ in range(steps):
        cmd = nav.step(guard.pose)
        if cmd is None:
            return True
        ok, to_send, why = guard.check(cmd)
        assert ok and to_send == cmd, f"{cmd}: {why}"  # a planned leg is never refused or clipped
        guard.apply(to_send)
    return False


def test_navigator_flies_round_the_divider_without_guard_interventions():
    g = SafetyGuard(LIM, START_SPOTS[2].copy())
    assert fly(Navigator(LIM), g, (350, 430))
    assert abs(g.pose.x - 360) < 40 and abs(g.pose.y - 435) < 40


def test_hider_picks_a_reachable_spot_and_holds_there():
    h = HiderAgent(LIM, START_SPOTS[2], HIDE_SPOTS, start=START_SPOTS[1])
    g = SafetyGuard(LIM, START_SPOTS[1].copy())
    g.apply("takeoff")
    d = h.decide(None, g.pose)
    for _ in range(80):
        if d.action == "hold":
            break
        ok, to_send, why = g.check(d.action)
        assert ok and to_send == d.action, why
        g.apply(to_send)
        d = h.decide(None, g.pose)
    assert d.action == "hold" and abs(g.pose.x - h.spot[0]) < 40 and abs(g.pose.y - h.spot[1]) < 40


def test_scan_waypoints_are_reachable_cells():
    a = ScanAgent(object(), LIM)
    a.start("sofa")
    p = Pose(100, 100, 80, 0)
    seen = []
    for _ in range(12):
        w = a._next_waypoint(p)
        assert w is not None
        assert LIM.room_map.inside(w[0], w[1], 30, 80) is None  # never inside furniture
        assert LIM.room_map.plan((p.x, p.y), w, 60) is not None
        seen.append(w)
        p = Pose(w[0], w[1], 80, 0)
    assert len(set(seen)) == len(seen)  # unvisited first


def test_unreachable_goal_fails_instead_of_looping():
    nav = Navigator(LIM)
    assert nav.set_goal(Pose(100, 100, 80, 0), (100, 100)) in (True, False)
    nav.blocked(Pose(100, 100, 80, 0))
    nav.blocked(Pose(100, 100, 80, 0))
    nav.blocked(Pose(100, 100, 80, 0))
    nav.blocked(Pose(100, 100, 80, 0))
    assert nav.failed and nav.step(Pose(100, 100, 80, 0)) is None


def test_real_run_refuses_without_a_room_map():
    sys.path.insert(0, "test_scripts/drone/local")
    import run_local
    with pytest.raises(SystemExit, match="room_map"):
        run_local.main(["--real", "--game", "race"])
