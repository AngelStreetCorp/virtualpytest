"""Tello simulator + TelloClient + FrameGrabber tests (all on loopback, no hardware)."""

import socket
import time

import cv2
import pytest

from shared.src.lib.drone.sim.render import render_view
from shared.src.lib.drone.sim.tello_sim import SimRegistry, TelloSim, sim_ip
from shared.src.lib.drone.sim.world import CLASS_COLORS, Pose, default_room
from shared.src.lib.drone.tello import TelloClient, TelloError, parse_state, tello_endpoints
from shared.src.lib.drone.video import FrameGrabber


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def rig():
    """One sim on 127.0.0.11 plus a connected client; yields (sim, client)."""
    state_port = _free_udp_port()
    sim = TelloSim(default_room(), 1, sim_ip(1), state_port=state_port, video_port=_free_udp_port(),
                   drift=0.0, seed=1, time_scale=8.0, idle_timeout_s=1.0, start_pose=Pose(100, 100, 0, 0))
    sim.start()
    client = TelloClient(sim_ip(1), state_port=state_port, local_ip="127.0.0.1", name="t1", timeout_s=5.0)
    client.connect()
    yield sim, client
    client.close()
    sim.stop()


def test_roundtrip_and_queries(rig):
    sim, c = rig
    assert c.send("command") == "ok"
    assert int(c.send("battery?")) >= 90
    assert c.send("sdk?") == "20"
    assert c.send("bogus") .startswith("error")
    assert c.send_ok("speed 50")
    assert c.send("speed 5").startswith("error")


def test_takeoff_move_rotate_pose(rig):
    sim, c = rig
    x0, y0 = sim.pose.x, sim.pose.y
    assert c.send_ok("takeoff", 10)
    assert sim.pose.z == pytest.approx(80, abs=1)
    assert c.send_ok("forward 100", 10)  # yaw 0 = +y
    assert sim.pose.y == pytest.approx(y0 + 100, abs=3)
    assert sim.pose.x == pytest.approx(x0, abs=3)
    assert c.send_ok("cw 90", 10)
    assert sim.pose.yaw_deg == pytest.approx(90, abs=1)
    assert c.send_ok("forward 50", 10)  # now +x
    assert sim.pose.x == pytest.approx(x0 + 50, abs=3)
    assert c.send_ok("up 40", 10)
    assert sim.pose.z == pytest.approx(120, abs=2)
    assert c.send("forward 5").startswith("error")  # out of range (20-500)
    assert c.send_ok("land", 10)
    assert sim.pose.z == 0 and not sim.flying


def test_move_while_landed_is_error(rig):
    _, c = rig
    assert c.send("forward 50") == "error Motor stop"
    assert c.send("cw 90").startswith("error")


def test_collision_stops_at_obstacle(rig):
    sim, c = rig
    c.send_ok("takeoff", 10)
    c.send_ok("forward 500", 20)  # north wall is 400 cm away
    assert sim.pose.y < sim.room.depth - 10 + 0.1


def test_state_datagram_parsed(rig):
    sim, c = rig
    c.send_ok("takeoff", 10)
    time.sleep(0.4)
    st = c.state()
    assert st["h"] == pytest.approx(80, abs=2) and st["bat"] >= 90 and "temph" in st and "yaw" in st
    assert c.state_age_s() < 1.0
    p = parse_state("pitch:0;roll:0;yaw:-5;baro:20.50;time:3;agz:-1000.00;\r\n")
    assert p["yaw"] == -5 and isinstance(p["yaw"], int) and p["baro"] == 20.5


def test_auto_land_after_idle(rig):
    sim, c = rig  # idle_timeout_s=1.0
    c.send_ok("takeoff", 10)
    assert sim.flying
    time.sleep(1.8)
    assert not sim.flying and sim.pose.z == 0
    assert c.send("forward 50").startswith("error")


def test_keepalive_prevents_auto_land(rig):
    sim, c = rig
    c.send_ok("takeoff", 10)
    c.start_keepalive(period_s=0.4)
    time.sleep(2.0)
    c.stop_keepalive()
    assert sim.flying


def test_client_timeout_raises():
    c = TelloClient("127.0.0.1", cmd_port=_free_udp_port(), state_port=_free_udp_port(), local_ip="127.0.0.1",
                    timeout_s=0.3)
    c._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c._cmd_sock.bind(("127.0.0.1", 0))
    with pytest.raises(TelloError):
        c.send("command")
    c._cmd_sock.close()


def test_tello_endpoints():
    e = tello_endpoints(2)
    assert e == {"ip": "10.200.2.2", "cmd_port": 8889, "state_port": 8891, "video_port": 11112}


def test_two_sims_side_by_side():
    reg = SimRegistry()
    sims, clients = [], []
    try:
        for i in (1, 2):
            sp = _free_udp_port()
            s = TelloSim(default_room(), i, sim_ip(i), state_port=sp, video_port=_free_udp_port(), drift=0.0,
                         registry=reg, time_scale=8.0, start_pose=Pose(100 if i == 1 else 500, 100, 0, 0))  # facing north
            s.start()
            sims.append(s)
            c = TelloClient(sim_ip(i), state_port=sp, local_ip="127.0.0.1", name=f"d{i}", timeout_s=5.0)
            c.connect()
            clients.append(c)
        assert clients[0].send_ok("takeoff", 10)
        assert sims[1].pose.z == 0  # the other drone is unaffected
        assert clients[1].send("forward 50").startswith("error")
        assert clients[1].send_ok("takeoff", 10) and clients[1].send_ok("left 100", 10)
        assert sims[1].pose.x == pytest.approx(400, abs=3)
        assert reg.get(2).x == pytest.approx(400, abs=3)
        assert [i for i, _ in reg.others(1)] == [2]
    finally:
        for c in clients:
            c.close()
        for s in sims:
            s.stop()


def _aruco_ids(img):
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
                                  cv2.aruco.DetectorParameters())
    ids = det.detectMarkers(img)[1]
    return [] if ids is None else [int(i) for i in ids.ravel()]


def test_render_marker_and_colors():
    room = default_room()
    me = Pose(200, 100, 80, 90)
    for dist in (150, 250):
        img = render_view(room, Pose(me.x, me.y, 80, 90), [(2, Pose(me.x + dist, me.y, 80, 0))])
        assert img.shape == (720, 960, 3) and _aruco_ids(img) == [2]
    # facing away: marker not in view; behind the sofa-wall occlusion not tested here
    assert _aruco_ids(render_view(room, Pose(200, 100, 80, 270), [(2, Pose(350, 100, 80, 0))])) == []
    # a wall between drone and marker occludes it: put a tall box between
    from shared.src.lib.drone.sim.world import Room, SimObject
    blocked = Room(objects=[SimObject("wall", "sofa", 300, 100, 20, 200, 200, CLASS_COLORS["sofa"])])
    assert _aruco_ids(render_view(blocked, Pose(200, 100, 80, 90), [(2, Pose(450, 100, 80, 0))])) == []
    # facing the sofa: the sofa colour dominates the centre
    img = render_view(room, Pose(200, 330, 80, 0), [])  # north of the divider, sofa straight ahead
    b, g, r = (int(v) for v in img[400, 480])
    assert r > 150 and g < 60 and b < 60


def test_video_frame_grabber_and_marker():
    """streamon -> FrameGrabber gets a decoded 960x720 frame; drone 2's marker is visible in drone 1's view."""
    reg = SimRegistry()
    vport, sport = _free_udp_port(), _free_udp_port()
    s1 = TelloSim(default_room(), 1, sim_ip(1), state_port=sport, video_port=vport, drift=0.0, registry=reg,
                  fps=15, time_scale=8.0, idle_timeout_s=60, start_pose=Pose(200, 100, 0, 90))
    s2 = TelloSim(default_room(), 2, sim_ip(2), state_port=_free_udp_port(), video_port=_free_udp_port(),
                  drift=0.0, registry=reg, start_pose=Pose(350, 100, 0, 0), idle_timeout_s=60)
    s1.start()
    s2.start()
    c = TelloClient(sim_ip(1), state_port=sport, local_ip="127.0.0.1", timeout_s=5.0)
    c2 = TelloClient(sim_ip(2), state_port=s2.state_port, local_ip="127.0.0.1", timeout_s=5.0)
    grabber = FrameGrabber(f"udp://127.0.0.1:{vport}")
    try:
        c.connect()
        c2.connect()
        grabber.start()
        assert c.send_ok("takeoff", 10) and c2.send_ok("takeoff", 10)
        assert c.send_ok("streamon")
        t0 = time.time()
        frame = grabber.wait_frame(0.0, timeout_s=10)
        assert frame is not None and frame.shape == (720, 960, 3)
        # a frame captured after both drones were airborne and settled
        fresh = grabber.wait_frame(t0 + 0.5, timeout_s=10)
        assert fresh is not None
        assert 2 in _aruco_ids(fresh)
        assert c.send_ok("streamoff")
    finally:
        grabber.stop()
        c.close()
        c2.close()
        s1.stop()
        s2.stop()
