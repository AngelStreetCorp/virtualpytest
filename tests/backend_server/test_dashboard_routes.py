"""TASK-123: /server/dashboard/summary and /server/dashboard/system (no DB, no network)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.utils import response_cache  # noqa: E402
from backend_server.src.routes import server_dashboard_routes as routes  # noqa: E402
from tests.backend_server._task42_common import TEAM_A, FakeHostManager, make_task42_app  # noqa: E402

pytestmark = pytest.mark.unit

NOW = datetime.now(timezone.utc)


def _iso(delta_h):
    return (NOW - timedelta(hours=delta_h)).isoformat()


def _row(i, script="zap", ok=True, host="h1", hours=1, err=None):
    t = _iso(hours)
    return {"id": f"r{i}", "script_name": script, "host_name": host, "device_name": "device1",
            "success": ok, "started_at": _iso(hours + 0.1), "completed_at": t, "error_msg": err}


@pytest.fixture
def make(monkeypatch):
    response_cache._response_cache.clear()
    seen = {}

    def build(role="viewer", rows=None, recent=None):
        rows = rows if rows is not None else []
        monkeypatch.setattr(routes.dashboard_db, "get_results_since", lambda t, s, limit=5000: seen.setdefault("team", t) and rows)
        monkeypatch.setattr(routes.dashboard_db, "get_recent_results", lambda t, limit=1000: recent if recent is not None else rows)
        monkeypatch.setattr(routes.dashboard_db, "get_active_executions", lambda t: [
            {"status": "running", "started_at": _iso(0.2), "script_result_id": "r9",
             "deployments": {"host_name": "h1", "device_id": "device1", "script_name": "zap"}},
            {"status": "queued", "deployments": {"host_name": "h1", "device_id": "device2", "script_name": "x"}}])
        monkeypatch.setattr(routes.dashboard_db, "get_active_deployments", lambda t: [
            {"name": "nightly", "status": "active", "cron_expression": "0 3 * * *", "max_executions": None,
             "scheduled_today": [{"start": (NOW + timedelta(hours=2)).isoformat()}]},
            {"name": "queued_one", "status": "active", "cron_expression": "0 0 1 1 *", "max_executions": 1}])
        monkeypatch.setattr(routes.dashboard_db, "get_host_status_rows", lambda: [
            {"host_name": "h1", "reachability": "reporting", "disk_percent": 40},
            {"host_name": "h2", "reachability": "silent", "disk_percent": None},
            {"host_name": "ghost", "reachability": "silent", "disk_percent": 10}])
        hm = FakeHostManager({"h1": [("device1", "a"), ("device2", "b")]})
        hm._hosts["h1"]["status"] = "online"
        hm._hosts["h2"] = {"host_name": "h2", "status": "offline"}
        monkeypatch.setattr(routes, "get_host_manager", lambda: hm)
        monkeypatch.setattr(routes, "get_all_locked_devices", lambda: {
            "h1:device2": {"host_name": "h1", "device_id": "device2", "owner_user_name": "ada", "locked_at": NOW.timestamp()}})
        monkeypatch.setattr(routes, "running_script_tasks", lambda t: [])
        app, _, _ = make_task42_app(monkeypatch, blueprints=[routes.server_dashboard_bp], role=role, team_ids=(TEAM_A,))
        return app.test_client(), seen
    return build


def test_summary_shape_and_counts(make):
    rows = [_row(1), _row(2, ok=False, err="boom"), _row(3, ok=False, err="Aborted by user"),
            _row(4, script="menu", ok=False, hours=2), _row(5, script="menu", hours=3)]
    client, seen = make("viewer", rows)
    body = client.get(f"/server/dashboard/summary?team_id={TEAM_A}&range=24h").get_json()
    assert body["success"] and body["range"] == "24h" and seen["team"] == TEAM_A
    assert (body["results"]["total"], body["results"]["passed"], body["results"]["failed"], body["results"]["aborted"]) == (5, 2, 2, 1)
    assert len(body["results"]["trend"]) in (24, 25) and sum(b["total"] for b in body["results"]["trend"]) == 5
    assert {f["result_id"] for f in body["failures"]} == {"r2", "r4"}
    assert body["flaky"] == [{"script_name": "menu", "runs": 2, "failed": 1}, {"script_name": "zap", "runs": 2, "failed": 1}] or \
        {f["script_name"] for f in body["flaky"]} == {"menu", "zap"}
    assert body["running"]["count"] == 1 and body["running"]["queued"] == 1
    assert body["running"]["items"][0]["result_id"] == "r9"
    assert body["deployments"]["active"] == 1 and body["deployments"]["items"][0]["next_run_at"]
    assert body["devices"] == {"total": 2, "free": 1, "locked": 1, "down": 0,
                               "locked_items": [{"host_name": "h1", "device_id": "device2", "holder": "ada",
                                                 "since": body["devices"]["locked_items"][0]["since"]}],
                               "down_items": [], "hosts": [{"host_name": "h1", "total": 2, "down": 0, "locked": 1}]}
    # one row per failing script (zap, menu), not one row per failed run
    failing = {f["script_name"]: f for f in body["failing"]}
    assert set(failing) == {"zap", "menu"} and failing["zap"]["failed"] == 1 and failing["zap"]["runs"] == 2
    assert failing["menu"]["runs"] == 2 and failing["menu"]["last_verdict"] in ("failed", "passed")


def test_range_validation_and_day_buckets(make):
    client, _ = make("viewer", [_row(1, hours=30)])
    assert client.get(f"/server/dashboard/summary?team_id={TEAM_A}&range=1y").status_code == 400
    body = client.get(f"/server/dashboard/summary?team_id={TEAM_A}&range=7d").get_json()
    assert 7 <= len(body["results"]["trend"]) <= 8 and body["results"]["total"] == 1


def test_missing_source_degrades_to_null(make, monkeypatch):
    client, _ = make("viewer", [])
    monkeypatch.setattr(routes.dashboard_db, "get_active_deployments", lambda t: (_ for _ in ()).throw(RuntimeError("db down")))
    resp = client.get(f"/server/dashboard/summary?team_id={TEAM_A}&range=24h")
    body = resp.get_json()
    assert resp.status_code == 200 and body["deployments"] is None and body["devices"]["total"] == 2


def test_other_team_refused(make):
    client, _ = make("viewer", [])
    assert client.get("/server/dashboard/summary?team_id=00000000-0000-0000-0000-00000000000b&range=24h").status_code == 403


def test_system_forbidden_for_non_admin(make):
    for role in ("viewer", "tester"):
        client, _ = make(role)
        resp = client.get("/server/dashboard/system")
        assert resp.status_code == 403, role
    client, _ = make("viewer")
    assert client.get(f"/server/dashboard/summary?team_id={TEAM_A}").status_code == 200


def test_system_admin_blocks(make, monkeypatch):
    monkeypatch.setattr(routes, "_ai_usage", lambda t: {"cost_7d": 1.5, "top_model": "gpu"})
    vms = [{"id": "server", "name": "Server", "cpu": 10.0, "load1": 0.5, "ram": 40.0, "disk": 50.0, "status": "ok", "checked_at": None},
           {"id": "database", "name": "Database", "cpu": 5.0, "load1": 0.1, "ram": 60.0, "disk": 80.0, "status": "warning", "checked_at": None}]
    monkeypatch.setattr(routes, "_vms", lambda now: vms)
    monkeypatch.setattr(routes, "_services", lambda: {"ok": 7, "total": 8})
    client, _ = make("admin")
    body = client.get(f"/server/dashboard/system?team_id={TEAM_A}").get_json()
    assert body["success"] and "leases" not in body
    assert "database" not in body  # the database VM is a row of `vms`
    assert body["vms"] == vms and body["services"] == {"ok": 7, "total": 8}
    assert body["monitoring"] == {"hosts_total": 2, "hosts_ok": 1, "problems": [{"host_name": "h2", "detail": "offline"}]}
    assert body["ai_usage"]["top_model"] == "gpu" and set(body["storage"]) == {"disk_pct", "inode_pct"}


def test_vm_status_thresholds():
    now = datetime.now(timezone.utc)
    assert routes._vm_status(10, 20, 30, now, now) == "ok"
    assert routes._vm_status(10, 85, 30, now, now) == "warning"
    assert routes._vm_status(10, 20, 95, now, now) == "error"
    assert routes._vm_status(10, 20, 30, now - timedelta(minutes=30), now) == "stale"


def test_failed_never_exceeds_runs_for_failing_and_flaky():
    """fails and runs of a script come from the same rows (aborts count in neither), so failed <= runs always."""
    rows = []
    n = 0
    for script, verdicts in {"a": "fffpfaff", "b": "pfpfpf", "c": "aaff", "d": "p" * 5 + "f" * 23, "e": "fffffff"}.items():
        for v in verdicts:
            n += 1
            rows.append(_row(n, script=script, ok=(v == "p"), err="Aborted by user" if v == "a" else "boom", hours=n / 10))
    failing = routes._failing(rows)
    flaky = routes._flaky(rows)
    assert failing and flaky
    for entry in failing + flaky:
        assert 0 <= entry["failed"] <= entry["runs"], entry
    by = {e["script_name"]: e for e in failing}
    assert by["c"] == {**by["c"], "runs": 2, "failed": 2}          # the two aborts count in neither number
    assert by["d"]["runs"] == 28 and by["d"]["failed"] == 23       # failing counts the whole range
    assert {e["script_name"]: e["runs"] for e in flaky}["d"] == 10  # flaky looks at the last 10 runs only


def test_monitoring_judges_registered_hosts_like_the_hosts_list(monkeypatch):
    """vpt-lenovo1 case: a host in the database-wide analytics roster that is not registered here (another server's
    host, or a retired one) is neither listed nor 'silent'; a registered host with an old heartbeat IS a problem."""
    import time
    hm = FakeHostManager(["fresh", "stale", "gone"])
    hm._hosts["fresh"].update(status="online", last_seen=time.time())
    hm._hosts["stale"].update(status="online", last_seen=time.time() - 600)
    hm._hosts["gone"].update(status="offline")
    monkeypatch.setattr(routes, "get_host_manager", lambda: hm)
    monkeypatch.setattr(routes.dashboard_db, "get_host_status_rows", lambda: [
        {"host_name": "other-server-host", "reachability": "silent", "disk_percent": 5},
        {"host_name": "fresh", "reachability": "reporting", "disk_percent": 95}])
    out = routes._monitoring()
    assert out["hosts_total"] == 3 and out["hosts_ok"] == 0
    assert {(p["host_name"], p["detail"]) for p in out["problems"]} == {("fresh", "disk 95% full"), ("stale", "offline"), ("gone", "offline")}
    assert all(p["host_name"] != "other-server-host" for p in out["problems"])


def test_ai_waste_share_and_top(monkeypatch):
    """_ai_waste: wasted cost / spend over the last day's rollup, busiest wasters first; None without calls."""
    from shared.src.lib.database import ai_routing_db
    base = {"usage_key": "ask", "profile": "m", "tokens_in": 500, "tokens_out": 500, "errors": 0, "avoided": 0}
    rows = [
        {**base, "calls": 8, "cost": 6.0, "priced_calls": 8, "script_name": None, "origin": "agent", "agent_id": "a1"},
        {**base, "calls": 4, "cost": 4.0, "priced_calls": 4, "errors": 4, "origin": "agent", "agent_id": "a2"},
    ]
    monkeypatch.setattr(ai_routing_db, "get_calls_rollup", lambda *a, **k: rows)
    waste = routes._ai_waste(TEAM_A)
    assert waste["spend"] == 10.0 and waste["cost"] == 4.0 and waste["share_pct"] == 40.0
    assert waste["tokens"] > 0 and waste["top"] and waste["top"][0]["cost"] == 4.0
    monkeypatch.setattr(ai_routing_db, "get_calls_rollup", lambda *a, **k: [])
    assert routes._ai_waste(TEAM_A) is None


def test_monitoring_host_disk_severity_follows_85_95(monkeypatch):
    """TASK-156: 84 % is fine, 85-94 % is a warning problem, 95 % and up is an error."""
    import time
    hm = FakeHostManager(["a", "b", "c"])
    for n in ("a", "b", "c"):
        hm._hosts[n].update(status="online", last_seen=time.time())
    monkeypatch.setattr(routes, "get_host_manager", lambda: hm)
    monkeypatch.setattr(routes.dashboard_db, "get_host_status_rows", lambda: [
        {"host_name": "a", "disk_percent": 84}, {"host_name": "b", "disk_percent": 88}, {"host_name": "c", "disk_percent": 100}])
    monkeypatch.setattr("shared.src.lib.database.system_metrics_db.get_oldest_disk_sample", lambda *a, **k: None)
    out = routes._monitoring()
    assert out["hosts_ok"] == 1
    assert {p["host_name"]: p["severity"] for p in out["problems"]} == {"b": "warning", "c": "error"}


def test_monitoring_flags_a_fast_filling_disk_below_the_line(monkeypatch):
    """TASK-156 goal 4: 40 % -> 70 % in 4 h is full in ~4 h; a flat host and a slow riser stay ok."""
    import time
    from datetime import datetime, timedelta, timezone
    hm = FakeHostManager(["fast", "flat"])
    for n in ("fast", "flat"):
        hm._hosts[n].update(status="online", last_seen=time.time())
    monkeypatch.setattr(routes, "get_host_manager", lambda: hm)
    monkeypatch.setattr(routes.dashboard_db, "get_host_status_rows", lambda: [
        {"host_name": "fast", "disk_percent": 70}, {"host_name": "flat", "disk_percent": 50}])
    four_h_ago = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    old = {"fast": 40, "flat": 49}
    monkeypatch.setattr("shared.src.lib.database.system_metrics_db.get_oldest_disk_sample",
                        lambda name, hours: {"timestamp": four_h_ago, "disk_percent": old[name]})
    out = routes._monitoring()
    assert [(p["host_name"], p["severity"]) for p in out["problems"]] == [("fast", "warning")]
    assert "filling" in out["problems"][0]["detail"] and out["hosts_ok"] == 1
