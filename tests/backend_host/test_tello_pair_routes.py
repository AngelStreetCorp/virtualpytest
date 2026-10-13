"""Regression tests for the Tello pairing route (TASK-32).

Two bugs shipped together and were found together on vpt-pi4 (2026-10-12):

  1. ``controller_class_patterns`` in ``host_utils`` had no ``tello`` key, so
     ``get_remote_controller_by_type(device, "tello")`` returned ``None`` and
     every ``/host/drone/tello/*`` route bailed at the controller stage — even
     though ``controllers/__init__.py`` builds a ``TelloRemoteController``
     happily from ``DEVICE{i}_TELLO_IP``.
  2. ``_join_ap()`` shelled out to ``sudo nmcli ...``, which the service user
     cannot do (polkit refuses to change a connection; vpt_user is not in the
     ``network`` group), so the route 500'd at stage ``join``.

Both are invisible until a real drone is on the bench, which is why they are
pinned here instead of only in the runbook.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List

import pytest
from flask import Flask

from backend_host.src.lib.utils import host_utils
from backend_host.src.routes import host_drone_routes


class _FakeTelloController:
    """Stands in for TelloRemoteController; only the class name is matched."""


_FakeTelloController.__name__ = "TelloRemoteController"


# --- bug 1: the controller lookup must know about tello -------------------


def test_get_remote_controller_by_type_resolves_tello(monkeypatch) -> None:
    class _Device:
        def get_controllers(self, kind: str) -> List[Any]:
            assert kind == "remote"
            return [_FakeTelloController()]

    class _Host:
        def get_device(self, device_id: str) -> _Device:
            return _Device()

    monkeypatch.setattr(host_utils, "get_host", lambda: _Host())

    found = host_utils.get_remote_controller_by_type("device5", "tello", quiet=True)

    assert isinstance(found, _FakeTelloController), (
        "'tello' missing from controller_class_patterns: every "
        "/host/drone/tello/* route resolves to None"
    )


def test_unknown_remote_type_still_returns_none(monkeypatch) -> None:
    class _Host:
        def get_device(self, device_id: str) -> None:
            return None

    monkeypatch.setattr(host_utils, "get_host", lambda: _Host())
    assert host_utils.get_remote_controller_by_type("device5", "nope", quiet=True) is None


# --- bug 2: joining the AP must work without a privileged service --------


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_join_ap_is_a_no_op_when_already_associated(monkeypatch) -> None:
    """The common case on vpt-pi4: wlan0 is already on the drone AP."""
    monkeypatch.setattr(host_drone_routes, "_active_wifi_ssid", lambda: "TELLO-C5B142")

    def _boom(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("nmcli must not be called when already associated")

    monkeypatch.setattr(host_drone_routes.subprocess, "run", _boom)

    assert host_drone_routes._join_ap("TELLO-C5B142") == {"ok": True, "already_active": True}


def test_join_ap_falls_back_to_sudo_when_polkit_refuses(monkeypatch) -> None:
    """polkit allows a scan but not a connect; sudo -n is the second try."""
    calls: List[List[str]] = []

    def _run(args, **_k):
        calls.append(list(args))
        if args[0] == "nmcli":
            return _completed(1, stderr="Error: Not authorized to control networking.")
        return _completed(0, stdout="Device 'wlan0' successfully activated")

    monkeypatch.setattr(host_drone_routes, "_active_wifi_ssid", lambda: None)
    monkeypatch.setattr(host_drone_routes.subprocess, "run", _run)

    result = host_drone_routes._join_ap("TELLO-C5B142")

    assert result["ok"] is True
    assert calls[0][:2] == ["nmcli", "device"]
    assert calls[1][:3] == ["sudo", "-n", "nmcli"]


def test_join_ap_reports_the_sudo_reason_not_polkits(monkeypatch) -> None:
    """"a password is required" is the actionable message, polkit's is not."""
    def _run(args, **_k):
        if args[0] == "nmcli":
            return _completed(1, stderr="Error: Not authorized to control networking.")
        return _completed(1, stderr="sudo: a password is required")

    monkeypatch.setattr(host_drone_routes, "_active_wifi_ssid", lambda: None)
    monkeypatch.setattr(host_drone_routes.subprocess, "run", _run)

    result = host_drone_routes._join_ap("TELLO-C5B142")

    assert result["ok"] is False
    assert "password is required" in result["reason"]


def test_join_ap_believes_the_association_over_a_failed_command(monkeypatch) -> None:
    """Some NetworkManager versions report a landed join as an error."""
    states = iter([None, "TELLO-C5B142"])
    monkeypatch.setattr(host_drone_routes, "_active_wifi_ssid", lambda: next(states, "TELLO-C5B142"))
    monkeypatch.setattr(host_drone_routes.subprocess, "run", lambda *_a, **_k: _completed(1, stderr="boom"))

    assert host_drone_routes._join_ap("TELLO-C5B142")["ok"] is True


# --- the route: a failed join must not sink a working link ---------------


def _app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(host_drone_routes.host_drone_bp)
    return app


@pytest.fixture()
def client():
    return _app().test_client()


def _stub_route(monkeypatch, *, join: Dict[str, Any], link: Dict[str, Any]) -> None:
    monkeypatch.setattr(host_drone_routes, "_join_ap", lambda *_a, **_k: join)
    monkeypatch.setattr(host_drone_routes, "_verify_link", lambda *_a, **_k: link)
    monkeypatch.setattr(host_drone_routes.time, "sleep", lambda *_a, **_k: None)

    class _Controller:
        def execute_command(self, *_a, **_k):
            return {"success": True}

    monkeypatch.setattr(host_drone_routes, "get_remote_controller_by_type", lambda *_a, **_k: _Controller())


def test_pair_succeeds_when_the_link_verifies_even_if_the_join_failed(client, monkeypatch) -> None:
    """An unprivileged service may not be able to change the connection and
    still reach the drone; the SDK link is what decides."""
    _stub_route(
        monkeypatch,
        join={"ok": False, "reason": "sudo: a password is required"},
        link={"ok": True, "bytes": 2},
    )

    res = client.post("/host/drone/tello/pair", json={"device_id": "device5", "ssid": "TELLO-C5B142"})

    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["success"] is True
    assert body["join"]["ok"] is False  # reported honestly, not fatal
    assert body["link"]["ok"] is True


def test_pair_fails_at_the_link_stage_and_carries_the_join_detail(client, monkeypatch) -> None:
    _stub_route(
        monkeypatch,
        join={"ok": True, "already_active": True},
        link={"ok": False, "reason": "no reply from 192.168.10.1:8889 in 5.0s"},
    )

    res = client.post("/host/drone/tello/pair", json={"device_id": "device5", "ssid": "TELLO-C5B142"})

    assert res.status_code == 500
    body = res.get_json()
    assert body["stage"] == "link"
    assert body["join"]["already_active"] is True


def test_pair_rejects_an_ssid_that_is_not_a_tello(client, monkeypatch) -> None:
    """SSID validation is the second gate behind the sudoers TELLO-* pin."""
    _stub_route(monkeypatch, join={"ok": True}, link={"ok": True, "bytes": 2})

    res = client.post("/host/drone/tello/pair", json={"device_id": "device5", "ssid": "HomeWifi"})

    assert res.status_code == 400
    assert "TELLO-" in res.get_json()["error"]

# --- BUG-0500: the status route the device page polls --------------------
#
# /server/drone/tello/status used to proxy to /host/remote/getStatus, which has
# never existed. The Device tile's poll aborts on any non-2xx, so a 404 there
# meant the tile never reached its scan step and could only ever say "could not
# check". These pin both halves: the route exists, and "no controller" answers
# 200 with linked=false rather than hiding behind a 404.


def test_status_returns_the_controllers_link_state(client, monkeypatch) -> None:
    class _Controller:
        def get_status(self) -> Dict[str, Any]:
            return {"success": True, "linked": True, "airborne": False, "ip": "192.168.10.1"}

    monkeypatch.setattr(host_drone_routes, "get_remote_controller_by_type", lambda *_a, **_k: _Controller())

    res = client.post("/host/drone/tello/status", json={"device_id": "device5"})

    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["linked"] is True
    assert body["ip"] == "192.168.10.1"


def test_status_answers_no_controller_with_200_not_404(client, monkeypatch) -> None:
    """The regression itself: a 404 here aborts the tile's whole poll chain."""
    monkeypatch.setattr(host_drone_routes, "get_remote_controller_by_type", lambda *_a, **_k: None)

    res = client.post("/host/drone/tello/status", json={"device_id": "device5"})

    assert res.status_code == 200, (
        "no controller must answer 200/linked=false — a 404 throws in the tile's "
        "catch block and it never reaches the scan"
    )
    assert res.get_json()["linked"] is False


def test_status_requires_a_device_id(client) -> None:
    assert client.post("/host/drone/tello/status", json={}).status_code == 400
