"""Group remote control (TASK-76): backend_server/src/lib/utils/group_remote_utils.py.

No Flask, no hosts: host lookup, locks and the sender are fakes.

Run: pytest tests/backend_server/test_group_remote_utils.py -v
"""
import os
import sys

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.utils.group_remote_utils import (  # noqa: E402
    fan_out,
    lock_blocker,
    per_target_mismatches,
    resolve_per_target_profiles,
    resolve_targets,
    skew_ms,
    validate_group,
)

pytestmark = pytest.mark.unit

HOSTS = {
    "pi1": {"host_name": "pi1", "devices": [
        {"device_id": "device1", "device_model": "stb", "remote_profiles": ["ir:stb"]},
        {"device_id": "device2", "device_model": "stb", "remote_profiles": ["ble:arris"]},
    ]},
    "pi2": {"host_name": "pi2", "devices": [
        {"device_id": "device1", "device_model": "stb", "remote_profiles": ["ir:stb"]},
    ]},
}


def _resolve(*pairs):
    return resolve_targets([{"host_name": h, "device_id": d} for h, d in pairs], HOSTS.get)


def test_resolve_reports_unknown_targets():
    resolved, missing = _resolve(("pi1", "device1"), ("pi9", "device1"), ("pi2", "device7"))
    assert [d["host_name"] for _, d in resolved] == ["pi1"]
    assert [(m["host_name"], m["device_id"]) for m in missing] == [("pi9", "device1"), ("pi2", "device7")]


def test_ir_and_ble_stb_are_rejected_together():
    resolved, _ = _resolve(("pi1", "device1"), ("pi1", "device2"), ("pi2", "device1"))
    model, bad = validate_group(resolved, "ir:stb")
    assert model == "stb"
    assert [(b["host_name"], b["device_id"]) for b in bad] == [("pi1", "device2")]


def test_same_profile_group_is_valid():
    resolved, _ = _resolve(("pi1", "device1"), ("pi2", "device1"))
    assert validate_group(resolved, "ir:stb")[1] == []


def test_lock_blocker():
    assert lock_blocker(None, ["s1"], "u1") is None
    assert lock_blocker({"owner_session_id": "s1"}, ["s1", None], None) is None
    assert lock_blocker({"owner_session_id": "x", "owner_user_id": "u1"}, ["s1"], "u1") is None
    assert lock_blocker({"owner_session_id": "x", "owner_user_name": "marie"}, ["s1"], "u1") == "locked by marie"


def test_fan_out_sends_remote_type_and_keeps_order():
    # TASK-80 mandates per-target profiles. Each job is (host, device, profile).
    resolved, _ = _resolve(("pi1", "device1"), ("pi2", "device1"))
    sent = []

    def send(host, body):
        sent.append((host["host_name"], body))
        if host["host_name"] == "pi2":
            return {"success": False, "error": "IR timeout"}, 200
        return {"success": True}, 200

    jobs = [(h, d, "ir:stb") for h, d in resolved]
    results = fan_out(jobs, "press_key", {"key": "POWER"}, send)
    assert {b["remote_type"] for _, b in sent} == {"ir_remote"}
    assert [(r["host_name"], r["success"], r["error"]) for r in results] == [
        ("pi1", True, None), ("pi2", False, "IR timeout")]


def test_fan_out_survives_a_dead_host():
    resolved, _ = _resolve(("pi1", "device1"), ("pi2", "device1"))

    def send(host, body):
        if host["host_name"] == "pi1":
            raise ConnectionError("host down")
        return {"success": True}, 200

    jobs = [(h, d, "ir:stb") for h, d in resolved]
    results = fan_out(jobs, "press_key", {"key": "OK"}, send)
    assert [r["success"] for r in results] == [False, True]
    assert "host down" in results[0]["error"]


def test_fan_out_legacy_2tuple_jobs_do_not_stamp_remote_type():
    """Backwards-compat: a caller that still passes (host, device) tuples (without a
    per-target profile) gets the bare payload — no `remote_type` key — so the host
    routes on the device's own controller. Use this only when every device shares
    a single profile. Per-target groups must pass 3-tuples."""
    resolved, _ = _resolve(("pi1", "device1"), ("pi2", "device1"))
    sent = []

    def send(host, body):
        sent.append((host["host_name"], body))
        return {"success": True}, 200

    results = fan_out([(h, d) for h, d in resolved], "press_key", {"key": "POWER"}, send)
    assert all("remote_type" not in b for _, b in sent)
    assert all(r["remote_profile"] is None for r in results)


# --- TASK-80 per-target profile (multi-transport group) -------------------------

def test_fan_out_per_target_profiles_stamp_distinct_remote_types():
    # pi1/device1 = STB on IR, pi1/device2 = STB on BLE. Both on the same model.
    resolved, _ = _resolve(("pi1", "device1"), ("pi1", "device2"))
    sent = []

    def send(host, body):
        sent.append((host["host_name"], body["remote_type"]))
        return {"success": True}, 200

    jobs = [
        (resolved[0][0], resolved[0][1], "ir:stb"),
        (resolved[1][0], resolved[1][1], "ble:arris"),
    ]
    results = fan_out(jobs, "press_key", {"key": "POWER"}, send)
    # IR on device1, BLE on device2 — different `remote_type` per target.
    assert sorted(sent) == sorted([("pi1", "ir_remote"), ("pi1", "bluetooth_remote")])
    # Each result carries the per-target profile so the frontend can label the cell.
    assert [r["remote_profile"] for r in results] == ["ir:stb", "ble:arris"]
    assert all(r["success"] for r in results)


def test_resolve_per_target_profiles_uses_default_when_target_omits():
    targets = [
        {"host_name": "pi1", "device_id": "device1"},  # no profile → uses default
        {"host_name": "pi2", "device_id": "device1", "remote_profile": "ir:stb"},
    ]
    resolved, _ = _resolve(*[(t["host_name"], t["device_id"]) for t in targets])
    profiles = resolve_per_target_profiles(resolved, targets, default_profile="ir:stb")
    assert profiles == ["ir:stb", "ir:stb"]


def test_per_target_mismatches_reports_missing_profile():
    # pi1/device1 = STB on IR only — would not satisfy a request for ble:arris.
    resolved, _ = _resolve(("pi1", "device1"))
    bad = per_target_mismatches(resolved, ["ble:arris"], device_model="stb")
    assert len(bad) == 1
    assert bad[0]["device_id"] == "device1"
    assert "no ble:arris remote" in bad[0]["reason"]


def test_per_target_mismatches_reports_model_mismatch():
    # pi1/device1 is a stb; a fire_tv_fireos request must fail with model reason.
    resolved, _ = _resolve(("pi1", "device1"))
    bad = per_target_mismatches(resolved, ["ir:stb"], device_model="fire_tv_fireos")
    assert len(bad) == 1
    assert "model stb is not fire_tv_fireos" in bad[0]["reason"]


def test_per_target_mismatches_reports_missing_profile_when_default_only():
    resolved, _ = _resolve(("pi1", "device1"))
    bad = per_target_mismatches(resolved, [None], device_model="stb")
    assert bad[0]["reason"] == "no remote_profile set for this target"


def test_skew_ignores_skipped():
    assert skew_ms([{"ms": 40}, {"ms": 120}, {"ms": 0, "skipped": True}]) == 80
    assert skew_ms([{"ms": 40}]) == 0


# --- Route: /server/remote/executeCommandGroup -----------------------------------------

def _client(monkeypatch, locks=None, fail_host=None):
    from flask import Flask

    import backend_server.src.routes.server_remote_routes as routes

    class _Hosts:
        get_host = staticmethod(HOSTS.get)

    calls = []

    def fake_call_host(host, endpoint, method="POST", data=None, **_):
        calls.append((host["host_name"], endpoint, data))
        if host["host_name"] == fail_host:
            return {"success": False, "error": "IR timeout"}, 200
        return {"success": True}, 200

    monkeypatch.setattr(routes, "get_host_manager", lambda: _Hosts())
    monkeypatch.setattr(routes, "call_host", fake_call_host)
    monkeypatch.setattr(routes, "get_device_lock_info", lambda h, d: (locks or {}).get((h, d)))
    monkeypatch.setattr(routes, "resolve_lock_owner", lambda data: ("u-me", None))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes.server_remote_bp)
    return app.test_client(), calls


def _body(*pairs, profile="ir:stb"):
    return {"targets": [{"host_name": h, "device_id": d} for h, d in pairs],
            "remote_profile": profile, "command": "press_key", "params": {"key": "POWER"}}


def test_route_rejects_mixed_ir_ble(monkeypatch):
    client, calls = _client(monkeypatch)
    res = client.post("/server/remote/executeCommandGroup", json=_body(("pi1", "device1"), ("pi1", "device2")))
    assert res.status_code == 400
    assert res.get_json()["mismatches"][0]["device_id"] == "device2"
    assert calls == []


def test_route_fans_out_and_skips_foreign_lock(monkeypatch):
    locks = {("pi2", "device1"): {"owner_session_id": "other", "owner_user_id": "u-x", "owner_user_name": "marie"}}
    client, calls = _client(monkeypatch, locks=locks)
    res = client.post("/server/remote/executeCommandGroup", json=_body(("pi1", "device1"), ("pi2", "device1")))
    data = res.get_json()
    assert res.status_code == 200
    assert [c[0] for c in calls] == ["pi1"]
    assert calls[0][1] == "/host/remote/executeCommand"
    assert calls[0][2]["remote_type"] == "ir_remote"
    assert {(r["host_name"], r.get("skipped", False)) for r in data["results"]} == {("pi1", False), ("pi2", True)}
    assert data["success"] is False


def test_route_reports_partial_failure(monkeypatch):
    client, _ = _client(monkeypatch, fail_host="pi2")
    data = client.post("/server/remote/executeCommandGroup", json=_body(("pi1", "device1"), ("pi2", "device1"))).get_json()
    assert [r["success"] for r in data["results"]] == [True, False]
    assert data["results"][1]["error"] == "IR timeout"
    assert "skew_ms" in data
