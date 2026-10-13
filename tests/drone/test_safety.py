
import pytest

from shared.src.lib.drone.safety import SafetyGuard, SafetyLimits
from shared.src.lib.drone.sim.world import Pose


def guard(x=300, y=250, z=80, yaw=0, peers=None, tel=None, **lim):
    return SafetyGuard(SafetyLimits(**lim), Pose(x, y, z, yaw), peers=lambda: peers or [],
                       telemetry=lambda: tel or {"bat": 90, "temph": 50, "h": z})


def test_forward_follows_yaw_and_right_is_yaw_plus_90():
    g = guard(yaw=90)  # facing +x
    g.apply("forward 100")
    assert (round(g.pose.x), round(g.pose.y)) == (400, 250)
    g.apply("right 50")  # right of +x is -y
    assert (round(g.pose.x), round(g.pose.y)) == (400, 200)
    g.apply("cw 90")
    assert g.pose.yaw_deg == 180
    g.apply("left 50")  # facing -y, left is +x
    assert round(g.pose.x) == 450
    g.apply("ccw 270")
    assert g.pose.yaw_deg == 270


def test_height_clip_and_refuse():
    g = guard(z=80)
    ok, cmd, reason = g.check("up 100")
    assert ok and cmd == "up 70" and "max height" in reason
    g.apply(cmd)
    ok, cmd, reason = g.check("up 30")
    assert not ok and cmd is None


def test_height_uses_telemetry():
    g = guard(z=80, tel={"bat": 90, "h": 140})
    ok, cmd, _ = g.check("up 50")
    assert not ok


def test_geofence_clip_and_refuse():
    g = guard(x=300, y=100, yaw=0)  # fence y in [50, 450]; forward 500 would leave
    ok, cmd, reason = g.check("forward 500")
    assert ok and cmd == "forward 350" and "geofence" in reason
    g = guard(x=300, y=440, yaw=0)  # only 10 cm left
    ok, cmd, reason = g.check("forward 50")
    assert not ok and "geofence" in reason
    ok, cmd, _ = g.check("back 50")
    assert ok and cmd == "back 50"


def test_geofence_all_sides():
    g = guard(x=60, y=250, yaw=270)  # facing -x
    assert not g.check("forward 100")[0]
    g = guard(x=540, y=250, yaw=90)
    assert not g.check("forward 100")[0]
    g = guard(x=300, y=60, yaw=180)
    assert not g.check("forward 100")[0]


def test_min_move_and_unknown_command():
    g = guard()
    assert not g.check("forward 10")[0]
    assert not g.check("flip f")[0]
    assert g.check("cw 30")[0]


def test_separation_refuses_closing_in_but_allows_leaving():
    peer = Pose(300, 380, 80, 0)
    g = guard(x=300, y=250, yaw=0, peers=[peer])
    ok, _, reason = g.check("forward 50")  # 130 -> 80 cm
    assert not ok and "separation" in reason
    assert g.check("back 50")[0]
    assert g.check("forward 20")[0]  # 110 cm still fine


def test_landed_peer_is_ignored():
    g = guard(x=300, y=250, yaw=0, peers=[Pose(300, 330, 0, 0)])
    assert g.check("forward 50")[0]


def test_battery_gates():
    g = guard(z=0, tel={"bat": 39, "temph": 40})
    ok, _, reason = g.check("takeoff")
    assert not ok and "battery" in reason
    g = guard(z=0, tel={"bat": 80, "temph": 85})
    ok, _, reason = g.check("takeoff")
    assert not ok and "temperature" in reason
    assert guard(z=0).check("takeoff")[0]


def test_land_at_low_battery():
    g = guard(tel={"bat": 20, "h": 80})
    ok, cmd, reason = g.check("forward 50")
    assert not ok and cmd == "land" and "battery" in reason
    assert g.check("land")[0]


def test_not_flying_and_takeoff_pose():
    g = guard(z=0)
    assert not g.check("forward 50")[0]
    g.apply("takeoff")
    assert g.pose.z == 80 and g.flying
    assert not g.check("takeoff")[0]
    g.apply("land")
    assert g.pose.z == 0


def test_down_floor():
    g = guard(z=80)
    ok, cmd, _ = g.check("down 100")
    assert ok and cmd == "down 50"
    g = guard(z=40)
    assert not g.check("down 30")[0]


# ---------- room map / obstacles ----------
from shared.src.lib.drone.roommap import Obstacle, RoomMap  # noqa: E402


def mapped_guard(x, y, yaw, z=80, **kw):
    rm = RoomMap(600, 500, [Obstacle("shelf", 100, 300, 240, 260, 200), Obstacle("mat", 400, 450, 100, 150, 20)])
    return guard(x=x, y=y, yaw=yaw, z=z, room_map=rm, **kw)


def test_obstacle_clips_30cm_before():
    g = mapped_guard(200, 100, 0)  # facing +y towards the shelf (y 240..260, inflated 210)
    ok, cmd, reason = g.check("forward 200")
    assert ok and cmd == "forward 110" and "shelf" in reason


def test_obstacle_refused_when_too_close():
    g = mapped_guard(200, 200, 0)  # 10 cm from the inflated edge
    ok, cmd, reason = g.check("forward 100")
    assert not ok and "shelf" in reason
    assert g.check("back 50")[0]  # moving away is fine


def test_obstacle_parallel_move_beside_it_is_fine():
    g = mapped_guard(200, 150, 90)  # facing +x along y=150, shelf is 90 cm north
    assert g.check("forward 100")[0]


def test_flying_over_a_low_obstacle():
    assert mapped_guard(425, 50, 0, z=80).check("forward 200")[0]  # mat is 20 cm high: 80 >= 20 + 30
    ok, cmd, _ = mapped_guard(425, 50, 0, z=40).check("forward 200")
    assert cmd == "forward 20" or not ok  # too low to clear it


def test_diagonal_and_sideways_moves_checked():
    g = mapped_guard(200, 150, 90)  # right of +x is -y; left is +y (towards the shelf)
    ok, cmd, _ = g.check("left 200")
    assert ok and cmd == "left 60"


def test_limits_accept_room_map_dict():
    lim = SafetyLimits(room_map=RoomMap(600, 500, [Obstacle("a", 1, 2, 3, 4, 5)]).to_dict())
    assert lim.room_map.obstacles[0].name == "a"


def test_roommap_json_roundtrip_and_planner(tmp_path):
    from shared.src.lib.drone.sim.world import default_room
    m = RoomMap.from_sim_room(default_room())
    m.save(str(tmp_path / "m.json"))
    m2 = RoomMap.load(str(tmp_path / "m.json"))
    assert m2.to_dict() == m.to_dict() and any(o.name == "shelf" for o in m2.obstacles)
    path = m.plan((100, 100), (350, 430), 50)
    assert path and path[0] == (100, 100)
    for a, b in zip(path, path[1:]):
        assert m.first_hit(a[0], a[1], b[0], b[1], 30, 80) is None  # every leg is clear for the guard
    assert path[-1][0] > 330  # went round through the gap on the east side


def test_standing_on_the_fence_line_is_not_a_violation():
    g = guard(x=550.6, y=300, yaw=179)  # rounding put us 0.6 cm outside; heading south with a tiny +x component
    ok, cmd, _ = g.check("forward 36")
    assert ok and cmd == "forward 36"


def test_yaw_is_taken_from_the_imu_once_airborne():
    tel = {"bat": 90, "temph": 50, "yaw": 20, "h": 0}
    g = SafetyGuard(SafetyLimits(), Pose(300, 250, 0, 180), telemetry=lambda: tel)
    assert g.check("takeoff")[0]  # landed: only records the offset between the IMU zero and the known heading
    assert g.pose.yaw_deg == 180
    g.apply("takeoff")
    tel["yaw"] = 20 + 95  # we commanded cw 90 but the drone really turned 95
    g.apply("cw 90")
    g.check("forward 50")
    assert g.pose.yaw_deg == pytest.approx(180 + 90)  # state may still predate the turn: not trusted yet
    g._applied_at -= 1.0  # a moment later the datagram is fresh
    assert g.check("forward 50")[0]
    assert g.pose.yaw_deg == pytest.approx((180 + 95) % 360)
    tel["yaw"] = -170  # IMU wraps at +-180
    g.check("forward 50")
    assert g.pose.yaw_deg == pytest.approx((180 - 190) % 360)
