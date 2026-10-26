"""Drone driving history: every command sent is logged (memory + JSONL), with what was really sent and the outcome."""
import json
import socket
import time

from flask import Flask

from shared.src.lib.drone.command_log import CommandLog


def _res(**kw):
    return dict({"success": True, "reply": "ok"}, **kw)


def test_entries_carry_the_outcome_and_land_in_the_file(tmp_path):
    log = CommandLog("h", "device1", log_dir=str(tmp_path))
    t = time.time()
    log.record("takeoff", {}, _res(sent="takeoff"), t, True, {"bat": 90, "h": 80}, {"x": 1, "y": 2, "z": 80, "yaw": 0})
    log.record("move", {"direction": "forward", "cm": 600}, {"success": False, "blocked": True, "error": "blocked: geofence"}, t, True)
    log.record("land", {}, _res(sent="land"), t, False)
    rows = log.history()
    assert [r["command"] for r in rows] == ["takeoff", "move", "land"] and [r["seq"] for r in rows] == [1, 2, 3]
    assert rows[0]["bat"] == 90 and rows[0]["pose"]["z"] == 80 and rows[0]["flight"] == 1
    assert rows[1]["blocked"] is True and rows[1]["success"] is False and rows[1]["error"] == "blocked: geofence"
    lines = [json.loads(x) for x in open(log.path)]
    assert [x["seq"] for x in lines] == [1, 2, 3]


def test_reads_are_not_logged_and_a_held_stick_is_one_entry(tmp_path):
    log = CommandLog("h", "d", log_dir=str(tmp_path))
    assert log.record("get_telemetry", {}, _res(), time.time(), False) is None
    for _ in range(50):
        log.record("rc", {"fb": 50}, _res(sent="rc 0 50 0 0"), time.time(), True)
    log.record("rc", {}, _res(sent="rc 0 0 0 0"), time.time(), True)
    log.record("rc", {}, _res(sent="rc 0 0 0 0"), time.time(), True)
    assert [r["sent"] for r in log.history()] == ["rc 0 50 0 0", "rc 0 0 0 0"]


def test_flights_are_counted_by_takeoff_and_filterable(tmp_path):
    log = CommandLog("h", "d", log_dir=str(tmp_path))
    for _ in range(2):
        log.record("takeoff", {}, _res(sent="takeoff"), time.time(), True)
        log.record("move", {}, _res(sent="forward 50"), time.time(), True)
        log.record("land", {}, _res(sent="land"), time.time(), False)
    assert [r["command"] for r in log.history(flight=2)] == ["takeoff", "move", "land"]
    assert all(r["flight"] == 2 for r in log.history(flight=2))
    assert [r["seq"] for r in log.history(since_seq=4)] == [5, 6]
    assert len(log.history(limit=2)) == 2


def test_the_ring_keeps_only_the_newest(tmp_path):
    log = CommandLog("h", "d", log_dir=str(tmp_path), ring=5)
    for i in range(12):
        log.record("move", {"i": i}, _res(sent=f"forward {20 + i}"), time.time(), True)
    assert [r["seq"] for r in log.history(limit=100)] == [8, 9, 10, 11, 12]
    assert sum(1 for _ in open(log.path)) == 12       # the file keeps everything


def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_the_controller_logs_every_command_including_refused_ones(tmp_path):
    from backend_host.src.controllers.remote.tello import TelloRemoteController
    from shared.src.lib.drone.sim.tello_sim import TelloSim
    from shared.src.lib.drone.sim.world import Pose, default_room

    cmd, state = _free_udp_port(), _free_udp_port()
    sim = TelloSim(default_room(), 3, "127.0.0.1", cmd_port=cmd, state_port=state, video_port=_free_udp_port(), drift=0.0, seed=1,
                   time_scale=8.0, start_pose=Pose(100, 100, 0, 0))
    sim.start()
    ctrl = TelloRemoteController(tello_ip="127.0.0.1", cmd_port=cmd, state_port=state, local_ip="127.0.0.1", local_cmd_port=_free_udp_port(),
                                 name="t3", command_log_dir=str(tmp_path))
    try:
        ctrl.connect()
        assert ctrl.execute_command("takeoff")["success"]
        assert ctrl.execute_command("move", {"direction": "forward", "cm": 100})["success"]
        assert ctrl.execute_command("move", {"direction": "forward", "cm": 5000}).get("success") is False   # out of range: refused
        ctrl.execute_command("get_telemetry")
        assert ctrl.execute_command("rotate", {"direction": "cw", "deg": 90})["success"]
        assert ctrl.execute_command("land")["success"]
    finally:
        ctrl.disconnect()
        sim.stop()
    rows = ctrl.command_log.history()
    assert [r["command"] for r in rows] == ["takeoff", "move", "move", "rotate", "land"]
    assert rows[1]["sent"] == "forward 100" and rows[1]["reply"] == "ok" and rows[1]["airborne"] is True and rows[1]["pose"]["y"] > 100
    assert rows[2]["success"] is False and rows[2]["error"]
    assert {r["flight"] for r in rows} == {1}
    assert rows[-1]["airborne"] is False
    assert sum(1 for _ in open(ctrl.command_log.path)) == 5


def test_the_host_route_returns_the_history(tmp_path, monkeypatch):
    from backend_host.src.routes import host_drone_routes

    log = CommandLog("h", "device1", log_dir=str(tmp_path))
    log.record("takeoff", {}, _res(sent="takeoff"), time.time(), True)
    log.record("land", {}, _res(sent="land"), time.time(), False)

    class Ctrl:
        command_log = log
    monkeypatch.setattr(host_drone_routes, "get_remote_controller_by_type", lambda d, t: Ctrl() if d == "device1" else None)
    app = Flask(__name__)
    app.register_blueprint(host_drone_routes.host_drone_bp)
    c = app.test_client()
    body = c.post("/host/drone/tello/command_history", json={"device_id": "device1", "limit": 1}).get_json()
    assert body["success"] and [r["command"] for r in body["commands"]] == ["land"] and body["flight"] == 1
    assert c.post("/host/drone/tello/command_history", json={"device_id": "nope"}).status_code == 404
    assert c.post("/host/drone/tello/command_history", json={"device_id": "device1", "limit": "x"}).status_code == 400


def test_the_server_route_proxies_to_the_host_route(monkeypatch):
    from backend_server.src.routes import server_drone_routes

    seen = {}

    def proxy(endpoint, method="GET", data=None, query_params=None, *a, **k):
        seen.update(endpoint=endpoint, method=method, data=data)
        return {"success": True, "commands": []}, 200
    monkeypatch.setattr(server_drone_routes, "proxy_to_host_with_params", proxy)
    app = Flask(__name__)
    app.register_blueprint(server_drone_routes.server_drone_bp)
    r = app.test_client().post("/server/drone/tello/command_history", json={"host_name": "h", "device_id": "device1"})
    assert r.status_code == 200 and seen["endpoint"] == "/host/drone/tello/command_history" and seen["method"] == "POST"
    assert app.test_client().post("/server/drone/tello/command_history", json={"device_id": "device1"}).status_code == 400
