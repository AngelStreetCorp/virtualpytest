"""TASK-95: Platform update run model, maintenance view and migration runner (no network, no database)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import migrations as mig  # noqa: E402
from backend_server.src.lib.platform_update.runs import (  # noqa: E402
    ActiveRunExists, PlatformUpdateError, RunNotFound, RunStore, StepOrderError,
)


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "pu")


def _complete_through(store, run_id, last):
    for i in range(last + 1):
        store.begin_step(run_id, i)
        store.finish_step(run_id, i, True, "", {"backup": {"ok": True, "items": []}} if i == 1 else None)


# -- run model ------------------------------------------------------------------------------------
def test_start_makes_step0_waiting_and_rest_pending(store):
    run = store.start("a@x")
    assert [s["state"] for s in run["steps"]] == ["waiting"] + ["pending"] * 6
    assert run["scope"] == "platform" and run["device_ids"] == []
    assert run["status"] == "active"


def test_only_one_active_run(store):
    store.start("a@x")
    with pytest.raises(ActiveRunExists):
        store.start("b@x")


def test_window_validation_and_reserved_scope(store):
    with pytest.raises(PlatformUpdateError):
        store.start("a@x", "2026-10-14T10:00:00Z", "2026-10-14T09:00:00Z")
    with pytest.raises(PlatformUpdateError):
        store.start("a@x", scope="devices", device_ids=["d1"])
    with pytest.raises(PlatformUpdateError):
        store.start("a@x", scope="nope")


def test_steps_must_run_in_order(store):
    run = store.start("a@x")
    with pytest.raises(StepOrderError):
        store.begin_step(run["id"], 2)
    store.begin_step(run["id"], 0)
    with pytest.raises(StepOrderError):  # already running
        store.begin_step(run["id"], 0)
    store.finish_step(run["id"], 0, True, "ok")
    run = store.get(run["id"])
    assert run["steps"][0]["state"] == "done" and run["steps"][1]["state"] == "waiting"
    with pytest.raises(StepOrderError):  # done steps do not re-run
        store.begin_step(run["id"], 0)


def test_failed_step_blocks_next_and_can_be_retried(store):
    run = store.start("a@x")
    store.begin_step(run["id"], 0)
    store.finish_step(run["id"], 0, False, "backup failed")
    assert store.get(run["id"])["steps"][0]["state"] == "failed"
    with pytest.raises(StepOrderError):
        store.begin_step(run["id"], 1)
    store.begin_step(run["id"], 0)  # retry
    store.finish_step(run["id"], 0, True)
    store.begin_step(run["id"], 1)


def test_finish_requires_running(store):
    run = store.start("a@x")
    with pytest.raises(StepOrderError):
        store.finish_step(run["id"], 0, True)


def test_close_ok_requires_all_steps_done(store):
    run = store.start("a@x")
    _complete_through(store, run["id"], 3)
    with pytest.raises(StepOrderError):
        store.close(run["id"], "ok")
    _complete_through_rest = [4, 5]
    for i in _complete_through_rest:
        store.begin_step(run["id"], i)
        store.finish_step(run["id"], i, True)
    closed = store.close(run["id"], "ok", "all good")
    assert closed["status"] == "ok" and closed["steps"][6]["state"] == "done"
    assert store.active() is None
    with pytest.raises(StepOrderError):  # closed run takes no more steps
        store.begin_step(run["id"], 0)


def test_close_failed_and_rolled_back_allowed_midway(store):
    run = store.start("a@x")
    assert store.close(run["id"], "rolled_back", "reverted")["status"] == "rolled_back"
    run2 = store.start("a@x")
    assert store.close(run2["id"], "failed")["status"] == "failed"
    with pytest.raises(PlatformUpdateError):
        store.start("a@x") and store.close(store.active()["id"], "bogus")


def test_close_refused_while_step_running(store):
    run = store.start("a@x")
    store.begin_step(run["id"], 0)
    with pytest.raises(StepOrderError):
        store.close(run["id"], "failed")


def test_log_is_written_and_tailed(store):
    run = store.start("a@x")
    store.begin_step(run["id"], 0)
    store.log(run["id"], "line one\nline two", 0)
    lines = store.log_lines(run["id"])
    assert any("[step 0] line two" in ln for ln in lines)
    assert store.log_path(run["id"]).is_file()
    assert store.with_log(store.get(run["id"]))["log"] == lines


def test_unknown_or_unsafe_run_id(store):
    with pytest.raises(RunNotFound):
        store.get("nope")
    with pytest.raises(RunNotFound):
        store.get("../etc/passwd")


# -- maintenance view -----------------------------------------------------------------------------
def test_maintenance_active_exposes_window_not_log(store):
    run = store.start("joe@x", note="n")
    view = store.maintenance()
    assert view["active"] is True
    w = view["window"]
    assert w["scope"] == "platform" and w["device_ids"] == [] and w["started_by"] == "joe@x"
    assert w["current_step"] == {"index": 0, "title": "Prerequisites", "state": "waiting"}
    assert "log" not in w and "steps" not in w
    assert w["run_id"] == run["id"]


def test_maintenance_idle_then_notice_then_expires(store):
    assert store.maintenance() == {"active": False, "window": None, "notice": None}
    run = store.start("a@x")
    store.close(run["id"], "failed", "boom")
    view = store.maintenance()
    assert view["active"] is False and view["notice"]["status"] == "failed" and view["notice"]["message"] == "boom"
    old = store.get(run["id"])
    old["closed_at"] = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store._save(old)
    assert store.maintenance()["notice"] is None


# -- migrations -----------------------------------------------------------------------------------
class FakeBackend:
    def __init__(self, applied=None, can_execute=True, fail_on=None):
        self.applied = applied
        self.can_execute = can_execute
        self.fail_on = fail_on
        self.executed = []
        self.methods = {}

    def read_applied(self):
        return None if self.applied is None else list(self.applied)

    def execute_file(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("syntax error")
        self.executed.append(sql)

    def record(self, filename, applied_by, method):
        self.applied = (self.applied or []) + [filename]
        self.methods[filename] = method


@pytest.fixture
def mdir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    for name in ["20260101a_one.sql", "20260101a_one_rollback.sql", "20260102a_two.sql",
                 "20260103a_three.sql", mig.TRACKER_FILE]:
        (d / name).write_text(f"-- {name}\n")
    return d


def test_list_files_sorted_without_rollbacks(mdir):
    names = mig.list_files(mdir)
    assert names == sorted(names) and not any(n.endswith("_rollback.sql") for n in names)
    assert "20260101a_one.sql" in names


def test_status_tracker_missing(mdir):
    st = mig.status(FakeBackend(applied=None), mdir)
    assert st["tracker"] == "missing" and st["pending"] == [] and st["total"] == 4


def test_status_lists_pending_by_name(mdir):
    st = mig.status(FakeBackend(applied=["20260101a_one.sql"]), mdir)
    assert st["tracker"] == "ready" and st["applied"] == 1
    assert st["pending"] == ["20260102a_two.sql", "20260103a_three.sql", mig.TRACKER_FILE]


def test_apply_needs_confirm_and_exact_prefix(mdir):
    b = FakeBackend(applied=[])
    pending = mig.status(b, mdir)["pending"]
    with pytest.raises(mig.MigrationError):
        mig.apply(b, pending[:1], False, "me", mdir)
    with pytest.raises(mig.MigrationError):  # skipping the first
        mig.apply(b, pending[1:2], True, "me", mdir)
    assert b.executed == []
    done = mig.apply(b, pending[:2], True, "me", mdir)
    assert done == pending[:2] and len(b.executed) == 2
    assert mig.status(b, mdir)["pending"] == pending[2:]


def test_apply_stops_on_first_error_and_records_only_successes(mdir):
    b = FakeBackend(applied=[], fail_on="two")
    pending = mig.status(b, mdir)["pending"]
    logs = []
    with pytest.raises(mig.MigrationError):
        mig.apply(b, pending, True, "me", mdir, log=logs.append)
    assert b.applied == ["20260101a_one.sql"]
    assert any("FAILED 20260102a_two.sql" in ln for ln in logs)


def test_apply_refused_without_db_connection_or_tracker(mdir):
    with pytest.raises(mig.MigrationError):
        mig.apply(FakeBackend(applied=[], can_execute=False), ["20260101a_one.sql"], True, "me", mdir)
    with pytest.raises(mig.MigrationError):
        mig.apply(FakeBackend(applied=None), ["20260101a_one.sql"], True, "me", mdir)


def test_tracker_install_and_baseline(mdir):
    b = FakeBackend(applied=None)
    mig.install_tracker(b, "me", mdir)
    assert b.applied == [mig.TRACKER_FILE] and len(b.executed) == 1
    with pytest.raises(mig.MigrationError):
        mig.install_tracker(b, "me", mdir)
    with pytest.raises(mig.MigrationError):
        mig.baseline(b, "20260102a_two.sql", "me", False, mdir)
    marked = mig.baseline(b, "20260102a_two.sql", "me", True, mdir)
    assert marked == ["20260101a_one.sql", "20260102a_two.sql"]
    assert b.methods["20260101a_one.sql"] == "baseline" and len(b.executed) == 1  # nothing was run
    assert mig.status(b, mdir)["pending"] == ["20260103a_three.sql"]
    with pytest.raises(mig.MigrationError):
        mig.baseline(b, "unknown.sql", "me", True, mdir)


def test_baseline_refused_without_db_connection(mdir):
    b = FakeBackend(applied=[], can_execute=False)
    with pytest.raises(mig.MigrationError, match="connection string"):
        mig.baseline(b, "20260102a_two.sql", "me", True, mdir)
    assert b.applied == []


def test_real_migration_folder_lists_and_tracker_file_exists():
    names = mig.list_files()
    assert mig.TRACKER_FILE in names and len(names) > 100
    assert not any(n.endswith("_rollback.sql") for n in names)


# -- routes (handlers called without the auth decorators) -----------------------------------------
def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _route_env(store, monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_platform_update_routes as r
    monkeypatch.setattr(r, "_store", lambda: store)
    app = Flask(__name__)

    def call(run_id, index, body):
        with app.test_request_context(json=body):
            resp = _unwrap(r.run_step)(run_id, index)
            return resp[0].get_json() if isinstance(resp, tuple) and resp[1] == 200 else resp
    return r, call


def test_new_step_order_and_names():
    from backend_server.src.lib.platform_update.runs import (
        BACKUP_STEP, BUNDLE_STEP, DEPLOY_STEP, MIGRATIONS_STEP, PREREQ_STEP, STEPS, TESTING_STEP)
    assert [s["title"] for s in STEPS] == ["Prerequisites", "Backup", "Bundle", "Deploy", "Migrations", "Testing", "Close"]
    assert (PREREQ_STEP, BACKUP_STEP, BUNDLE_STEP, DEPLOY_STEP, MIGRATIONS_STEP, TESTING_STEP) == (0, 1, 2, 3, 4, 5)
    assert not any(s["key"] == "services" for s in STEPS)


def test_step_route_flow_report_and_close(store, monkeypatch):
    r, call = _route_env(store, monkeypatch)
    run = store.start("a@x")

    # the bundle (step 2) cannot be reported before steps 0 and 1 are done
    out = call(run["id"], 2, {"action": "report", "ok": True, "version": "v1"})
    assert out[1] == 409
    _complete_through(store, run["id"], 1)
    out = call(run["id"], 2, {"action": "report", "ok": True, "version": "v1", "source": "zip"})
    assert out["run"]["steps"][2]["state"] == "done" and out["run"]["steps"][2]["data"]["version"] == "v1"
    out = call(run["id"], 3, {"action": "report", "ok": False, "detail": "host a failed",
                              "targets": [{"target": "a", "success": False, "error": "x"}]})
    assert out["run"]["steps"][3]["state"] == "failed"
    assert call(run["id"], 3, {"action": "nonsense"})[1] == 400
    assert call(run["id"], 6, {"action": "x"})[1] == 400
    # the old "services" action no longer exists anywhere
    assert call(run["id"], 4, {"action": "run"})[1] == 400


def test_step0_done_only_when_no_required_check_is_ko(store, monkeypatch):
    r, call = _route_env(store, monkeypatch)
    run = store.start("a@x")
    ko = {"ok": False, "passed": 1, "total": 2, "checks": [
        {"id": "disk", "title": "Disk space", "required": True, "status": "ko"},
        {"id": "x", "title": "Fine", "required": True, "status": "ok"}]}
    seen = {}
    monkeypatch.setattr(r.prerequisites, "run_all", lambda core, overlay, *a, **k: seen.update(core=core, overlay=overlay) or ko)
    out = call(run["id"], 0, {"action": "check", "core": "zip", "overlay": "gitlab"})
    step = out["run"]["steps"][0]
    assert step["state"] == "failed" and "Disk space" in step["detail"] and step["data"]["prerequisites"] == ko
    assert seen == {"core": "zip", "overlay": "gitlab"}
    # a warning-only KO (not required) does not block
    ok = {"ok": True, "passed": 1, "total": 2, "checks": [
        {"id": "no_test_running", "title": "No test run", "required": False, "status": "ko"}]}
    monkeypatch.setattr(r.prerequisites, "run_all", lambda *a, **k: ok)
    out = call(run["id"], 0, {"action": "check"})  # retry from failed
    step = out["run"]["steps"][0]
    assert step["state"] == "done" and step["detail"] == "1/2 OK"
    assert out["run"]["steps"][1]["state"] == "waiting"


def test_step0_has_no_manual_checkboxes(store, monkeypatch):
    r, call = _route_env(store, monkeypatch)
    run = store.start("a@x")
    monkeypatch.setattr(r.prerequisites, "run_all", lambda *a, **k: {"ok": True, "passed": 0, "total": 0, "checks": []})
    out = call(run["id"], 0, {"action": "check", "lease_confirmed": False, "queue_paused_confirmed": False})
    assert out["run"]["steps"][0]["state"] == "done"  # the old confirmations are ignored, not required
    assert "lease" not in out["run"]["steps"][0]["data"]


def test_run_from_before_the_step_change_is_refused(store, monkeypatch):
    import json
    r, call = _route_env(store, monkeypatch)
    run = store.start("a@x")
    stored = store.get(run["id"])
    stored.pop("layout")  # what a run written by the old code looks like
    (store.dir / f"{run['id']}.json").write_text(json.dumps(stored))
    out = call(run["id"], 0, {"action": "check"})
    assert out[1] == 409
    assert out[0].get_json()["error"] == (
        "This update was started before the 7-step change; close it and start a new one")
    assert store.get(run["id"])["steps"][0]["state"] == "waiting"  # untouched
    # it can still be closed, and the payload says it is legacy
    assert store.close(run["id"], "failed", "old")["status"] == "failed"
    assert r._run_payload(run["id"])["run"]["legacy"] is True


def test_new_run_is_not_legacy(store, monkeypatch):
    r, _call = _route_env(store, monkeypatch)
    run = store.start("a@x")
    assert r._run_payload(run["id"])["run"]["legacy"] is False


def test_smoke_requires_health_first(store, monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_platform_update_routes as r
    monkeypatch.setattr(r, "_store", lambda: store)
    run = store.start("a@x")
    _complete_through(store, run["id"], 4)
    app = Flask(__name__)
    with app.test_request_context(json={"action": "smoke", "ok": True}):
        resp = _unwrap(r.run_step)(run["id"], 5)
    assert resp[1] == 400
    store.begin_step(run["id"], 5)
    store.set_data(run["id"], 5, {"health_ok": True})
    with app.test_request_context(json={"action": "smoke", "ok": True, "script_name": "s", "task_id": "t"}):
        resp = _unwrap(r.run_step)(run["id"], 5)
    assert resp[1] == 200 and store.get(run["id"])["steps"][5]["state"] == "done"


def test_mark_failed_reopens_a_done_step(store):
    run = store.start("a@x")
    _complete_through(store, run["id"], 2)
    store.mark_failed(run["id"], 2, "rolled back")
    assert store.get(run["id"])["steps"][2]["state"] == "failed"
    with pytest.raises(StepOrderError):
        store.begin_step(run["id"], 3)
    store.begin_step(run["id"], 2)


# -- standalone maintenance windows (TASK-97) -----------------------------------------------------
from backend_server.src.lib.platform_update.windows import WindowStore  # noqa: E402


def _iso_in(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def wstore(tmp_path):
    return WindowStore(tmp_path / "mw")


def test_window_create_device_scope(wstore):
    w = wstore.create("a@x", _iso_in(-1), _iso_in(1), "swap cable", "devices", ["d1", "d2", "d1"])
    assert w["device_ids"] == ["d1", "d2"] and w["scope"] == "devices" and w["reason"] == "swap cable"
    assert [x["id"] for x in wstore.active()] == [w["id"]]


def test_window_validation(wstore):
    with pytest.raises(PlatformUpdateError):
        wstore.create("a@x", _iso_in(2), _iso_in(1), scope="platform")
    with pytest.raises(PlatformUpdateError):
        wstore.create("a@x", scope="devices", device_ids=[])
    with pytest.raises(PlatformUpdateError):
        wstore.create("a@x", scope="nope")
    assert wstore.create("a@x", scope="platform", device_ids=["d1"])["device_ids"] == []


def test_window_active_filters_by_time(wstore):
    wstore.create("a@x", _iso_in(1), _iso_in(2), scope="platform")   # upcoming
    wstore.create("a@x", _iso_in(-3), _iso_in(-2), scope="platform")  # expired
    now = wstore.create("a@x", _iso_in(-1), _iso_in(1), scope="platform")
    assert [w["id"] for w in wstore.active()] == [now["id"]]
    assert sorted(w["state"] for w in wstore.list_all()) == ["active", "ended", "upcoming"]


def test_window_end_and_edit(wstore):
    w = wstore.create("a@x", _iso_in(-1), _iso_in(1), scope="devices", device_ids=["d1"])
    w = wstore.update(w["id"], window_end=_iso_in(3), reason="longer", device_ids=["d2"])
    assert w["device_ids"] == ["d2"] and w["reason"] == "longer"
    wstore.end(w["id"])
    assert wstore.active() == []
    assert wstore.list_all()[0]["state"] == "ended"
    with pytest.raises(PlatformUpdateError):
        wstore.update(w["id"], reason="x")
    with pytest.raises(RunNotFound):
        wstore.end("mw-nope")


def test_window_public_shape_hides_nothing_secret(wstore):
    w = wstore.create("a@x", _iso_in(-1), _iso_in(1), "r", "devices", ["d1"])
    pub = wstore.active()[0]
    assert pub["source"] == "settings" and pub["started_by"] == "a@x" and pub["reason"] == "r"
    assert "created_at" not in pub and pub["id"] == w["id"]
