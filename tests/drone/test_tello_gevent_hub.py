"""BUG-0511: a Tello command waiting on the drone must not freeze vpt-host.

vpt-host serves Flask-SocketIO on gevent WITHOUT monkey patching, so a blocking UDP recv on the
request greenlet stalls the hub and every other request (stream playlists included). Here a
takeoff (or the pair route's link) waits on a real socket for a drone that never answers, inside
a greenlet, while the main greenlet asks /host/drone/tello/status: it must answer within 0.5 s
and the command must still be waiting. Before the fix the status call only ran once the command
had given up.
"""

import os
import time

import pytest
from flask import Flask

gevent = pytest.importorskip("gevent")

from backend_host.src.controllers.remote.tello import TelloRemoteController  # noqa: E402
from backend_host.src.routes import host_drone_routes  # noqa: E402
from tests.drone.test_tello_controller import _free_udp_port, _make  # noqa: E402


def _status_client(monkeypatch, ctrl):
    monkeypatch.setattr(host_drone_routes, "get_remote_controller_by_type", lambda *_a, **_k: ctrl)
    monkeypatch.setattr(host_drone_routes, "get_device_by_id", lambda *_a, **_k: None)
    app = Flask(__name__)
    app.register_blueprint(host_drone_routes.host_drone_bp)
    return app.test_client()


def _assert_status_answers_while_waiting(client, pending):
    gevent.sleep(0.2)  # let the command reach its blocking wait
    t0 = time.monotonic()
    res = client.post("/host/drone/tello/status", json={"device_id": "device1"})
    elapsed = time.monotonic() - t0
    assert res.status_code == 200, res.get_json()
    assert elapsed < 0.5, f"status took {elapsed:.2f}s while the command waited"
    assert not pending.ready(), "the command finished before status ran: the hub was blocked"


def test_takeoff_to_an_unreachable_drone_leaves_the_host_answering(monkeypatch):
    sim, ctrl = _make()
    try:
        assert ctrl.execute_command("link")["success"]
        sim.stop()  # drone gone: takeoff (and the land after it) wait out their timeouts
        ctrl.limits.takeoff_timeout_s = 1.0
        client = _status_client(monkeypatch, ctrl)

        takeoff = gevent.spawn(ctrl.execute_command, "takeoff")
        _assert_status_answers_while_waiting(client, takeoff)

        r = takeoff.get(timeout=30)
        assert r["success"] is False and not ctrl.airborne
    finally:
        ctrl.disconnect()
        sim.stop()


def test_pair_link_to_an_unreachable_drone_leaves_the_host_answering(monkeypatch):
    ctrl = TelloRemoteController(tello_ip="127.0.0.1", cmd_port=_free_udp_port(), state_port=_free_udp_port(),
                                 local_ip="127.0.0.1", local_cmd_port=_free_udp_port(), name="nobody")
    ctrl.connect()
    try:
        client = _status_client(monkeypatch, ctrl)

        link = gevent.spawn(ctrl.execute_command, "link")
        _assert_status_answers_while_waiting(client, link)

        assert link.get(timeout=30)["success"] is False
    finally:
        ctrl.disconnect()


def test_rc_is_dropped_behind_a_command_in_flight_not_queued(monkeypatch):
    sim, ctrl = _make()
    try:
        assert ctrl.execute_command("link")["success"]
        sim.stop()
        ctrl.limits.takeoff_timeout_s = 1.0
        takeoff = gevent.spawn(ctrl.execute_command, "takeoff")
        gevent.sleep(0.2)
        t0 = time.monotonic()
        r = ctrl.execute_command("rc", {"lr": 0, "fb": 0, "ud": 0, "yaw": 0})
        assert r["success"] is False and r.get("busy") is True
        assert time.monotonic() - t0 < 1.0
        takeoff.get(timeout=30)
    finally:
        ctrl.disconnect()
        sim.stop()


def _fake_nmcli(tmp_path, monkeypatch, connect_s):
    """An `nmcli` on PATH whose `wifi connect` is a real blocking `sleep` subprocess."""
    script = tmp_path / "nmcli"
    script.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *connect*) exec sleep {connect_s} ;; esac\n'
        "exit 0\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def test_pair_wifi_join_leaves_the_host_answering(monkeypatch, tmp_path):
    """BUG-0512: the pair route's nmcli join (up to 30 s) ran subprocess.run on the hub."""
    _fake_nmcli(tmp_path, monkeypatch, connect_s=3)
    ctrl = TelloRemoteController(tello_ip="127.0.0.1", cmd_port=_free_udp_port(), state_port=_free_udp_port(),
                                 local_ip="127.0.0.1", local_cmd_port=_free_udp_port(), name="nobody")
    ctrl.connect()
    try:
        client = _status_client(monkeypatch, ctrl)

        t0 = time.monotonic()
        pair = gevent.spawn(client.post, "/host/drone/tello/pair",
                            json={"device_id": "device1", "ssid": "TELLO-C5B142", "tello_ip": "127.0.0.1"})
        _assert_status_answers_while_waiting(client, pair)
        # A join on the hub stalls inside the 0.2 s gevent.sleep, not the status call: time it all.
        assert time.monotonic() - t0 < 1.0, "the nmcli join blocked the hub"

        assert pair.get(timeout=30).get_json()["join"] == {"ok": True, "already_active": False}
    finally:
        ctrl.disconnect()
