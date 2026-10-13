"""TelloRemoteController against the Tello simulator (loopback, no hardware).

The sim is drone 3 (127.0.0.13) with its own free state/video ports, so it never collides with
test_tello_sim.py or a developer's own simulators on 127.0.0.11/12.
"""

import socket
import time

import pytest

from backend_host.src.controllers.remote.tello import TelloRemoteController
from shared.src.lib.drone.sim.tello_sim import TelloSim, sim_ip
from shared.src.lib.drone.sim.world import Pose, default_room


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make(idle_timeout_s: float = 30.0, keepalive_s: float = 5.0):
    state_port = _free_udp_port()
    sim = TelloSim(default_room(), 3, sim_ip(3), state_port=state_port, video_port=_free_udp_port(),
                   drift=0.0, seed=1, time_scale=8.0, idle_timeout_s=idle_timeout_s,
                   start_pose=Pose(100, 100, 0, 0))
    sim.start()
    ctrl = TelloRemoteController(tello_ip=sim_ip(3), state_port=state_port, local_ip="127.0.0.1",
                                 name="t3", keepalive_s=keepalive_s)
    ctrl.connect()
    return sim, ctrl


@pytest.fixture
def rig():
    sim, ctrl = _make()
    yield sim, ctrl
    ctrl.disconnect()
    sim.stop()


def _move(ctrl, direction, cm):
    return ctrl.execute_command("move", {"direction": direction, "cm": cm})


def test_takeoff_move_rotate_land(rig):
    sim, ctrl = rig
    r = ctrl.execute_command("takeoff")
    assert r["success"] is True and sim.flying
    assert ctrl.airborne and ctrl.pose().z == 80

    r = _move(ctrl, "forward", 100)  # yaw 0 = +y
    assert r["success"] is True and r["sent"] == "forward 100"
    assert abs(ctrl.pose().y - 200) < 1e-6 and abs(sim.pose.y - 200) < 15

    r = ctrl.execute_command("rotate", {"direction": "cw", "deg": 90})
    assert r["success"] is True
    assert abs(ctrl.pose().yaw_deg - 90) < 1e-6

    r = _move(ctrl, "forward", 100)  # now +x
    assert r["success"] is True and abs(ctrl.pose().x - 200) < 1e-6

    r = ctrl.execute_command("land")
    assert r["success"] is True and not sim.flying and not ctrl.airborne
    assert ctrl.pose().z == 0


def test_guard_refusal_returns_false_and_sends_nothing(rig):
    sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]
    sent = ctrl.commands_sent

    # Separation: a flying peer 50 cm ahead on the way, closer than 100 cm and getting closer.
    ctrl.set_peers(lambda: [Pose(100, 250, 80, 0)])
    r = _move(ctrl, "forward", 100)
    assert r["success"] is False and r["blocked"] is True and "separation" in r["error"]
    assert ctrl.commands_sent == sent and ctrl.guard_blocks == 1
    assert abs(ctrl.pose().y - 100) < 1e-6  # dead reckoning untouched
    ctrl.set_peers(lambda: [])

    # Raw SDK text is still guarded: rc (open-loop sticks) is not on the allow list.
    r = ctrl.execute_command("sdk", {"cmd": "rc 0 50 0 0"})
    assert r["success"] is False and r["blocked"] is True
    assert ctrl.commands_sent == sent

    # Bad arguments never reach the guard or the drone.
    assert _move(ctrl, "sideways", 50)["success"] is False
    assert _move(ctrl, "forward", 5)["success"] is False
    assert ctrl.execute_command("rotate", {"direction": "cw", "deg": 0})["success"] is False
    assert ctrl.execute_command("nope")["success"] is False
    assert ctrl.commands_sent == sent


def test_move_while_landed_is_refused(rig):
    _sim, ctrl = rig
    r = _move(ctrl, "forward", 50)
    assert r["success"] is False and r["blocked"] is True and "not flying" in r["error"]


def test_geofence_clips_a_long_move(rig):
    _sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]
    r = _move(ctrl, "forward", 500)  # y 100 -> fence at 450: clipped to 350
    assert r["success"] is True and r["sent"] == "forward 350" and r["clipped_from"] == "forward 500"
    assert abs(ctrl.pose().y - 450) < 1e-6


def test_height_ceiling_clips_up(rig):
    _sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]
    r = _move(ctrl, "up", 200)  # 80 -> ceiling 150: clipped to 70
    assert r["success"] is True and r["sent"] == "up 70"
    assert _move(ctrl, "up", 50)["success"] is False  # already at the ceiling


def test_low_battery_refuses_takeoff(rig):
    sim, ctrl = rig
    sim.battery = 30.0
    assert ctrl.execute_command("get_telemetry")["success"]
    time.sleep(0.4)  # a fresh state datagram with the low battery
    r = ctrl.execute_command("takeoff")
    assert r["success"] is False and r["blocked"] is True and "battery" in r["error"]
    assert not sim.flying


def test_battery_at_land_floor_lands_the_drone(rig):
    sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]
    sim.battery = 15.0
    time.sleep(0.4)
    r = _move(ctrl, "forward", 50)
    assert r["success"] is False and r.get("landed") is True
    assert not sim.flying and not ctrl.airborne


def test_land_on_error(rig, monkeypatch):
    """A move that gets no answer (twice) lands the drone instead of leaving it flying."""
    sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"] and sim.flying
    real_raw = ctrl._raw
    seen = []

    def flaky(cmd, timeout_s):
        seen.append(cmd)
        return None if cmd.startswith("forward") else real_raw(cmd, timeout_s)

    monkeypatch.setattr(ctrl, "_raw", flaky)
    r = _move(ctrl, "forward", 50)
    assert r["success"] is False and r["landed"] is True
    assert seen.count("forward 50") == 2 and seen[-1] == "land"  # one retry, then land
    assert not sim.flying and not ctrl.airborne


def test_exception_lands_the_drone(rig, monkeypatch):
    sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]

    def boom(cmd):
        raise RuntimeError("guard crashed")

    monkeypatch.setattr(ctrl.guard, "check", boom)
    r = _move(ctrl, "forward", 50)
    assert r["success"] is False and "guard crashed" in r["error"]
    assert not sim.flying


def test_press_key_mapping(rig):
    sim, ctrl = rig
    assert ctrl.press_key("OK") is True and sim.flying
    assert ctrl.press_key("UP") is True and abs(ctrl.pose().y - 150) < 1e-6
    assert ctrl.press_key("RIGHT") is True and abs(ctrl.pose().yaw_deg - 30) < 1e-6
    assert ctrl.press_key("LEFT") is True and abs(ctrl.pose().yaw_deg) < 1e-6
    assert ctrl.press_key("DOWN") is True and abs(ctrl.pose().y - 100) < 1e-6
    assert ctrl.press_key("BACK") is True and not sim.flying
    assert ctrl.press_key("MENU") is False


def test_telemetry_and_raw_sdk_read(rig):
    _sim, ctrl = rig
    t = ctrl.execute_command("get_telemetry")
    assert t["success"] is True and t["telemetry"]["bat"] > 90 and t["output_data"]["airborne"] is False
    r = ctrl.execute_command("sdk", {"cmd": "battery?"})
    assert r["success"] is True and int(r["reply"]) > 90


def test_configure_geofence_and_start_spot(rig):
    _sim, ctrl = rig
    assert ctrl.execute_command("configure", {"room_w": 300, "room_d": 300, "max_h": 120,
                                              "x": 150, "y": 150, "yaw": 90})["success"]
    assert ctrl.limits.room_w == 300 and ctrl.limits.max_h == 120
    assert (ctrl.pose().x, ctrl.pose().y, ctrl.pose().yaw_deg) == (150, 150, 90)


def test_configure_room_map_reaches_the_guard(rig):
    _sim, ctrl = rig
    rm = {"width": 600, "depth": 500, "obstacles": [{"name": "shelf", "x0": 0, "x1": 380, "y0": 285, "y1": 315, "h": 200}]}
    assert ctrl.execute_command("configure", {"room_map": rm, "x": 100, "y": 100, "yaw": 0})["success"]
    assert ctrl.limits.room_map.obstacles[0].name == "shelf"
    assert ctrl.guard.limits.room_map is ctrl.limits.room_map
    assert ctrl.execute_command("configure", {"room_w": 500})["success"]  # a later configure keeps the map
    assert ctrl.limits.room_map is not None


def test_configure_refused_while_airborne(rig):
    _sim, ctrl = rig
    assert ctrl.execute_command("takeoff")["success"]
    assert ctrl.execute_command("configure", {"room_w": 300})["success"] is False


def test_keepalive_prevents_the_firmware_auto_land():
    sim, ctrl = _make(idle_timeout_s=1.0, keepalive_s=0.3)
    try:
        assert ctrl.execute_command("takeoff")["success"]
        time.sleep(2.5)  # 2.5x the sim's idle auto-land window with no command from the caller
        assert sim.flying
    finally:
        ctrl.disconnect()
        sim.stop()


def test_disconnect_lands_an_airborne_drone():
    sim, ctrl = _make()
    try:
        assert ctrl.execute_command("takeoff")["success"] and sim.flying
        ctrl.disconnect()
        assert not sim.flying
    finally:
        sim.stop()


def test_unreachable_drone_reports_the_error_not_an_exception():
    ctrl = TelloRemoteController(tello_ip="127.0.0.1", cmd_port=_free_udp_port(), state_port=_free_udp_port(),
                                 local_ip="127.0.0.1", name="nobody")
    r = ctrl.execute_command("takeoff")
    assert r["success"] is False and r["error"]


def test_factory_and_capabilities():
    from backend_host.src.controllers.controller_config_factory import create_controller_configs_from_device_info
    from shared.src.lib.config.device_capabilities import DEVICE_CONTROLLER_MAP, get_device_capabilities

    assert DEVICE_CONTROLLER_MAP["tello"]["remote"] == ["tello"]
    assert get_device_capabilities("tello")["remote"] == "tello"
    base = {"device_id": "device6", "device_name": "Tello 1", "device_model": "tello",
            "video": "udp://0.0.0.0:11111", "video_capture_path": "/tmp/capture6"}

    configs = create_controller_configs_from_device_info({**base, "tello_ip": "10.200.1.2",
                                                          "tello_state_port": "8890", "tello_video_port": "11111"})
    assert configs["av"]["implementation"] == "rtsp_stream"
    assert configs["av"]["params"]["rtsp_url"] == "udp://0.0.0.0:11111"
    assert configs["remote"]["implementation"] == "tello"
    assert configs["remote"]["params"] == {"tello_ip": "10.200.1.2", "state_port": 8890,
                                           "video_port": 11111, "name": "Tello 1"}

    skipped = create_controller_configs_from_device_info(base)
    assert skipped["remote"]["params"].get("_skip_controller") is True
