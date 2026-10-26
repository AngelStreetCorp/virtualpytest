"""TASK-128 G12: pause / resume / abort at safe points, impact, roll back order, migration rollback, backup gate."""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import bundle_jobs, pull_deploy as pd, rollback as rb  # noqa: E402
from backend_server.src.lib.platform_update.runs import PlatformUpdateError, RunStore, StepOrderError  # noqa: E402
from tests.backend_server.test_platform_update_pull import FakeEnv, ready, _clean  # noqa: E402,F401

SERVER_BACKUP = "20261018_100000_000001"
FE_BACKUP = "/b/20261018_090000"


class Env(FakeEnv):
    """FakeEnv that gives every machine its own backup, understands rollbackBundle and lets a test act between machines."""

    def __init__(self, *a, hooks=None, fail_rollback=None, **k):
        super().__init__(*a, **k)
        self.hooks = hooks or {}                      # event -> callable run right after that event
        self.fail_rollback = set(fail_rollback or [])
        self.backup = lambda root, backup_root: ("/b/1", {"backup_id": SERVER_BACKUP})
        names = k.get("hosts", ("h1", "h2"))
        self.hosts = lambda: [{"host_name": h, "deployed_version": "1.0.0"} for h in names]

    def _event(self, name):
        self.events.append(name)
        if name in self.hooks:
            self.hooks[name]()

    def run(self, argv, timeout, env=None):
        joined = " ".join(argv)
        if argv[0] == "ssh" and "code-deploy.sh" in joined:
            self.events.append("fe-sync")
            return subprocess.CompletedProcess(argv, 0, f"VERSION_BEFORE=1\nBACKUP_DIR={FE_BACKUP}\n", "")
        if argv[0] == "ssh" and "rsync -a --delete" in joined and FE_BACKUP in joined:
            self.events.append("fe-restore")
            self.calls.append(argv)
        elif argv[0] == "rsync":
            self.events.append("server-restore" if SERVER_BACKUP in joined else "rsync")
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        else:
            self.calls.append(argv)
            self.events.append(argv[0] if argv[0] != "sudo" else "reconcile")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    def call_host(self, host, endpoint, method="POST", data=None, timeout=60):
        name = host["host_name"]
        if endpoint.endswith("applyBundle"):
            body, status = super().call_host(host, endpoint, method, data, timeout)
            if isinstance(body, dict) and body.get("success"):
                body["backup_id"] = f"bk-{name}"
            self._event(f"apply:{name}")
            self.events.pop(-2)                      # super() already logged it; keep one entry, hook fired after
            return body, status
        if endpoint.endswith("rollbackBundle"):
            self.events.append(f"rollback:{name}")
            self.calls.append(("rollback", name, data))
            if name in self.fail_rollback:
                return {"success": False, "error": "boom"}, 500
            return {"success": True, "version_before": "7.7.7", "version_after": "1.0.0", "log": ["restored"]}, 200
        return {}, self.health


def deploy(ready, **kw):
    store, run_id, *_ = ready
    env = Env(**kw)
    pd.start(store, run_id, {"frontend_version": "1.0.0"}, threaded=False, env=env)
    return store, run_id, env


# -- gate ---------------------------------------------------------------------------------------------
def test_deploy_refused_without_this_runs_backup(ready):
    store, run_id, *_ = ready
    step1 = store.get(run_id)["steps"][1]
    run = store.get(run_id)
    run["steps"][1]["data"] = {}                           # step 1 "done" but no saved backup
    store._save(run)
    env = Env()
    with pytest.raises(StepOrderError):
        pd.start(store, run_id, {}, threaded=False, env=env)
    with pytest.raises(StepOrderError):
        bundle_jobs.start_deploy(store, run_id, {}, threaded=False)
    assert env.events == [] and step1["state"] == "done" and store.get(run_id)["steps"][3]["state"] == "waiting"


# -- pause / resume / abort ------------------------------------------------------------------------------
def test_pause_waits_between_machines_then_resume_continues(ready):
    store, run_id, *_ = ready
    seen = {}

    def pause():
        store.request_control(run_id, "pause", "me")

    env = Env(hooks={"apply:h1": pause})

    def sleep(_s):
        if "state" not in seen and store.get(run_id)["steps"][3]["data"]["job"]["state"] == "paused":    # first poll while paused: look, then resume
            seen["state"] = store.get(run_id)["steps"][3]["data"]["job"]["state"]
            seen["h2_done"] = "apply:h2" in env.events
            store.request_control(run_id, "resume", "me")
    env.sleep = sleep
    pd.start(store, run_id, {}, threaded=False, env=env)
    assert seen == {"state": "paused", "h2_done": False}
    assert env.events.index("apply:h1") < env.events.index("apply:h2") < env.events.index("server-restart")
    assert store.get(run_id)["steps"][3]["data"]["job"]["state"] == "awaiting_confirmation"
    assert "Resumed" in "\n".join(store.log_lines(run_id, 1000))


def test_abort_is_taken_between_machines_never_inside_one(ready):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h1": lambda: store.request_control(run_id, "abort", "me")})
    pd.start(store, run_id, {}, threaded=False, env=env)
    step = store.get(run_id)["steps"][3]
    assert "apply:h1" in env.events and "apply:h2" not in env.events and "server-restart" not in env.events
    assert step["state"] == "failed" and step["data"]["job"]["state"] == "aborted" and step["data"]["aborted"] is True
    assert [(u["name"], u["ok"], u["backup"]) for u in step["data"]["updated"]] == [("h1", True, "bk-h1")]    # h1 finished whole
    assert not bundle_jobs.is_running("deploy")


def test_abort_before_the_server_leaves_it_untouched(ready):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h2": lambda: store.request_control(run_id, "abort", "me")})
    pd.start(store, run_id, {}, threaded=False, env=env)
    step = store.get(run_id)["steps"][3]
    assert "rsync" not in env.events and "server-restart" not in env.events
    assert [u["name"] for u in step["data"]["updated"]] == ["h1", "h2"] and step["data"]["job"]["state"] == "aborted"


def test_abort_while_paused_and_flags_are_cleared_by_a_new_deploy(ready):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h1": lambda: store.request_control(run_id, "pause", "me")})
    env.sleep = lambda s: store.get(run_id)["steps"][3]["data"]["job"]["state"] == "paused" and store.request_control(run_id, "abort", "me")
    pd.start(store, run_id, {}, threaded=False, env=env)
    assert store.get(run_id)["steps"][3]["data"]["job"]["state"] == "aborted" and "apply:h2" not in env.events
    assert store.control(run_id)["abort"] is True
    with pytest.raises(StepOrderError):
        store.request_control(run_id, "pause", "me")        # an abort cannot be taken back
    pd.start(store, run_id, {}, threaded=False, env=Env())  # re-run: flags reset
    assert store.control(run_id) == {"pause": False, "abort": False} and store.get(run_id)["steps"][3]["data"]["job"]["state"] == "awaiting_confirmation"
    # the first backup of h1 is kept, not replaced by the second run's half-updated tree
    assert next(u for u in store.get(run_id)["steps"][3]["data"]["updated"] if u["name"] == "h1")["backup"] == "bk-h1"


def test_a_restart_while_paused_is_reported_as_interrupted(ready):
    store, run_id, *_ = ready
    store.set_data(run_id, 3, {"job": {"state": "paused", "mode": "pull"}})
    store.begin_step(run_id, 3)
    run = bundle_jobs.recover_interrupted(store, store.get(run_id))
    assert run["steps"][3]["state"] == "failed"


# -- impact ----------------------------------------------------------------------------------------------
def test_impact_after_abort_lists_new_untouched_and_migrations(ready, tmp_path):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h1": lambda: store.request_control(run_id, "abort", "me")})
    run = store.get(run_id)
    pd.start(store, run_id, {"frontend_version": "1.0.0"}, threaded=False, env=env)
    store.set_data(run_id, 4, {"applied": ["20261001a_x.sql"]})
    (tmp_path / "20261001a_x_rollback.sql").write_text("select 1;")
    hosts_now = [{"host_name": "h1", "deployed_version": "7.7.7"}, {"host_name": "h2", "deployed_version": "1.0.0"}]
    view = rb.impact(store.get(run_id), hosts_now, "1.0.0", tmp_path)
    rows = {(m["role"], m["name"]): m for m in view["machines"]}
    assert rows[("host", "h1")]["state"] == "new" and rows[("host", "h1")]["now"] == "7.7.7"
    assert rows[("host", "h2")]["state"] == "untouched" and rows[("host", "h2")]["now"] == "1.0.0"
    assert rows[("server", "server")]["state"] == "untouched"
    assert view["mixed"] and "h1: 1.0.0 -> 7.7.7" in view["mixed_summary"] and "h2" in view["mixed_summary"]
    assert view["migrations"]["plan"] == [{"file": "20261001a_x.sql", "rollback_file": "20261001a_x_rollback.sql", "has_rollback": True}]
    assert view["can_rollback"] and view["aborted"] and run  # noqa


# -- roll back ----------------------------------------------------------------------------------------------
def full_deploy(ready, monkeypatch, tmp_path, **kw):
    store, run_id, *_ = ready
    srv = tmp_path / "sbk"
    (srv / SERVER_BACKUP).mkdir(parents=True)
    monkeypatch.setattr(rb, "_server_backup_root", lambda: str(srv))
    env = Env(frontend=True, **kw)
    pd.start(store, run_id, {"frontend_version": "1.0.0"}, threaded=False, env=env)
    env.events.clear()
    env.calls.clear()
    return store, run_id, env


def test_rollback_order_hosts_newest_first_then_frontend_then_server(ready, monkeypatch, tmp_path):
    store, run_id, env = full_deploy(ready, monkeypatch, tmp_path)
    assert [t["name"] for t in rb.plan(store.get(run_id))] == ["h2", "h1", "fe", "srv"]
    rb.run_rollback(store, run_id, env, "me", threaded=False)
    order = [e for e in env.events if e.startswith("rollback:") or e in ("fe-restore", "server-restore", "server-restart")]
    assert order == ["rollback:h2", "rollback:h1", "fe-restore", "server-restore", "server-restart"]
    assert ("rollback", "h2", {"backup_id": "bk-h2"}) in env.calls and ("rollback", "h1", {"backup_id": "bk-h1"}) in env.calls
    assert any(FE_BACKUP in " ".join(c) for c in env.calls if isinstance(c, list) and c[0] == "ssh")
    state = rb.rollback_state(store, run_id)
    assert state["state"] == "awaiting_confirmation" and [a["state"] for a in state["actions"]] == ["ok"] * 4
    log = "\n".join(store.log_lines(run_id, 1000))
    assert "Roll back host h2" in log and "Roll back the server" in log
    assert not bundle_jobs.is_running("deploy")
    # after the restart the page confirms: process started after the schedule, version = the one before the update
    monkeypatch.setattr(pd, "PROCESS_START", state["restart_scheduled_at"] + 5)
    rb.confirm_rollback(store, run_id, lambda line: None)
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "failed" and step["data"]["rolled_back"] and rb.rollback_state(store, run_id)["state"] == "done"
    assert not rb.can_rollback(store.get(run_id))
    rows = {(m["role"], m["name"]): m["state"] for m in rb.impact(store.get(run_id), [], "7.7.7")["machines"]}
    assert set(rows.values()) == {"rolled_back"}


def test_confirm_rollback_refuses_before_the_restart(ready, monkeypatch, tmp_path):
    store, run_id, env = full_deploy(ready, monkeypatch, tmp_path)
    rb.run_rollback(store, run_id, env, "me", threaded=False)
    monkeypatch.setattr(pd, "PROCESS_START", 0)
    with pytest.raises(PlatformUpdateError, match="not restarted"):
        rb.confirm_rollback(store, run_id, lambda line: None)


def test_rollback_stops_at_the_first_failure_and_rerun_skips_done_machines(ready, monkeypatch, tmp_path):
    store, run_id, env = full_deploy(ready, monkeypatch, tmp_path, fail_rollback=["h1"])
    rb.run_rollback(store, run_id, env, "me", threaded=False)
    assert env.events.count("rollback:h2") == 1 and "fe-restore" not in env.events and "server-restore" not in env.events
    state = rb.rollback_state(store, run_id)
    assert state["state"] == "failed" and [(a["name"], a["state"]) for a in state["actions"]] == [("h2", "ok"), ("h1", "failed")]
    env.fail_rollback.clear()
    env.events.clear()
    rb.run_rollback(store, run_id, env, "me", threaded=False)
    assert "rollback:h2" not in env.events and "rollback:h1" in env.events and "server-restore" in env.events


def test_rollback_after_abort_touches_only_updated_machines_and_needs_no_restart(ready, monkeypatch, tmp_path):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h1": lambda: store.request_control(run_id, "abort", "me")})
    pd.start(store, run_id, {}, threaded=False, env=env)
    env.events.clear()
    rb.run_rollback(store, run_id, env, "me", threaded=False)
    assert env.events == ["rollback:h1"] and env.restarts == 0
    assert rb.rollback_state(store, run_id)["state"] == "done" and store.get(run_id)["steps"][3]["state"] == "failed"


def test_rollback_refused_while_the_deploy_runs(ready):
    store, run_id, *_ = ready
    store.begin_step(run_id, 3)
    store.set_data(run_id, 3, {"job": {"state": "running", "mode": "pull"}})
    with pytest.raises(PlatformUpdateError, match="still running"):
        rb.run_rollback(store, run_id, Env(), "me", threaded=False)


def test_server_restore_refuses_a_backup_outside_the_backup_root(ready, monkeypatch, tmp_path):
    store, run_id, *_ = ready
    monkeypatch.setattr(rb, "_server_backup_root", lambda: str(tmp_path))
    with pytest.raises(PlatformUpdateError):
        rb.restore_server_tree(Env(), "../../etc", lambda line: None)
    with pytest.raises(PlatformUpdateError, match="gone"):
        rb.restore_server_tree(Env(), SERVER_BACKUP, lambda line: None)


# -- leave partial ----------------------------------------------------------------------------------------
def test_leave_partial_needs_confirm_and_closes_the_step_as_failed(ready):
    store, run_id, *_ = ready
    env = Env(hooks={"apply:h1": lambda: store.request_control(run_id, "abort", "me")})
    pd.start(store, run_id, {"frontend_version": "1.0.0"}, threaded=False, env=env)
    with pytest.raises(PlatformUpdateError, match="confirmation"):
        rb.leave_partial(store, run_id, False, "me", [], "1.0.0")
    rb.leave_partial(store, run_id, True, "me", [{"host_name": "h1", "deployed_version": "7.7.7"}], "1.0.0")
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "failed" and step["data"]["partial"]["by"] == "me" and "h1" in step["detail"] and "Left partial" in step["detail"]


# -- migrations -------------------------------------------------------------------------------------------
class FakeBackend:
    can_execute = True

    def __init__(self):
        self.executed, self.unrecorded = [], []

    def execute_file(self, sql):
        self.executed.append(sql)

    def unrecord(self, name):
        self.unrecorded.append(name)


def migrations_run(ready, tmp_path, files, with_rollback):
    store, run_id, *_ = ready
    for f in files:
        (tmp_path / f).write_text(f"-- {f}")
    for f in with_rollback:
        (tmp_path / (f[:-4] + "_rollback.sql")).write_text(f"-- undo {f}")
    run = store.get(run_id)
    run["steps"][1]["data"]["backup"]["items"] = [{"id": "database", "restore_command": "docker cp dump && pg_restore"}]
    store._save(run)
    store.begin_step(run_id, 3)
    store.finish_step(run_id, 3, True)
    store.begin_step(run_id, 4)
    store.set_data(run_id, 4, {"applied": list(files)})
    return store, run_id


def test_migrations_roll_back_newest_first_after_the_second_confirm(ready, tmp_path):
    files = ["20261001a_a.sql", "20261001b_b.sql"]
    store, run_id = migrations_run(ready, tmp_path, files, files)
    backend = FakeBackend()
    newest_first = ["20261001b_b.sql", "20261001a_a.sql"]
    with pytest.raises(PlatformUpdateError, match="confirmation"):
        rb.rollback_migrations(store, run_id, backend, newest_first, False, "me", tmp_path)
    with pytest.raises(PlatformUpdateError, match="does not match"):
        rb.rollback_migrations(store, run_id, backend, files, True, "me", tmp_path)       # wrong order
    assert backend.executed == []
    done = rb.rollback_migrations(store, run_id, backend, newest_first, True, "me", tmp_path)
    assert done == newest_first and backend.executed == ["-- undo 20261001b_b.sql", "-- undo 20261001a_a.sql"]
    assert backend.unrecorded == newest_first
    step = store.get(run_id)["steps"][4]
    assert step["state"] == "failed" and step["data"]["rolled_back"] == newest_first


def test_missing_rollback_file_stops_and_shows_the_dump_restore_command(ready, tmp_path):
    files = ["20261001a_a.sql", "20261001b_b.sql", "20261001c_c.sql"]
    store, run_id = migrations_run(ready, tmp_path, files, ["20261001a_a.sql", "20261001c_c.sql"])   # b has no rollback
    backend = FakeBackend()
    plan = rb.migration_plan(store.get(run_id), tmp_path)
    assert [(i["file"], i["has_rollback"]) for i in plan["plan"]] == [("20261001c_c.sql", True), ("20261001b_b.sql", False), ("20261001a_a.sql", True)]
    with pytest.raises(rb.MigrationRollbackStop) as e:
        rb.rollback_migrations(store, run_id, backend, [i["file"] for i in plan["plan"]], True, "me", tmp_path)
    assert backend.executed == ["-- undo 20261001c_c.sql"] and backend.unrecorded == ["20261001c_c.sql"]        # a is never touched
    assert "20261001b_b_rollback.sql" in str(e.value) and "docker cp dump && pg_restore" in str(e.value)
    data = store.get(run_id)["steps"][4]["data"]
    assert data["rolled_back"] == ["20261001c_c.sql"] and data["needs_dump_restore"] is True
