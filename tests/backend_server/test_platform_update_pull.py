"""TASK-101 G4 server side: gate, deploy order (frontend -> hosts -> server), awaiting-confirmation, archive route auth."""
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

import pytest
from flask import Flask, request

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import bundle_jobs, pull_deploy as pd  # noqa: E402
from backend_server.src.lib.platform_update.runs import PlatformUpdateError, RunStore  # noqa: E402
from backend_server.src.routes import server_platform_update_routes as routes  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    bundle_jobs._RUNNING.clear()
    yield
    bundle_jobs._RUNNING.clear()


def make_bundle(tmp_path):
    path = tmp_path / "vpt.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("virtualpytest/BUNDLE_MANIFEST.txt", "m")
        zf.writestr("virtualpytest/VERSION.txt", "7.7.7\n")
        zf.writestr("virtualpytest/scripts/code-deploy.sh", "#!/bin/bash\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ready(tmp_path, monkeypatch):
    """A run whose steps 0 to 2 are done, with a real archive."""
    root = tmp_path / "opt"
    root.mkdir()
    (root / "VERSION.txt").write_text("7.7.7\n")
    monkeypatch.setattr(pd, "project_root", lambda: str(root))
    monkeypatch.setenv("TEST_ROOT", str(root))
    store = RunStore(tmp_path / "pu")
    run = store.start("a@x")
    for i in (0, 1):
        store.begin_step(run["id"], i)
        store.finish_step(run["id"], i, True, "", {"backup": {"ok": True, "items": []}} if i == 1 else None)
    archive, sha = make_bundle(tmp_path)
    store.begin_step(run["id"], 2)
    store.finish_step(run["id"], 2, True, "x", {"bundle": {"name": "vpt.zip", "path": str(archive), "sha256": sha,
                                                         "dir": str(tmp_path)},
                                              "spec": {"core": "zip", "overlay": "none"}})
    monkeypatch.setattr(pd.prerequisites, "run_all", lambda *a, **k: {"ok": True, "checks": []})
    return store, run["id"], archive, sha


class FakeEnv(pd.Env):
    def __init__(self, hosts=("h1", "h2"), fail_host=None, frontend=False, health=200, mode=None):
        self.events, self.restarts, self.calls = [], 0, []
        self.hosts = lambda: [{"host_name": h} for h in hosts]
        self.fail_host, self.health = fail_host, health
        mode = mode or ("ssh" if frontend else "none")
        self.frontend_cfg = lambda: {"mode": mode, "host": "fe" if mode == "ssh" else "", "user": "u", "password": "", "key": "", "target_dir": "/opt/v",
                                    "backup_root": "/b", "service": "vpt-frontend", "service_user": "vpt_user"}
        self.sleep = lambda s: None
        self.server_name = lambda: "srv"
        self.backup = lambda root, backup_root: ("/b/1", {"backup_id": "bk1"})
        self.schedule_restart = self._restart

    def _restart(self):
        self.restarts += 1
        self.events.append("server-restart")

    def run(self, argv, timeout, env=None):
        self.events.append(argv[0] if argv[0] != "sudo" else "reconcile")
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    def call_host(self, host, endpoint, method="POST", data=None, timeout=60):
        name = host["host_name"]
        if endpoint.endswith("applyBundle"):
            self.events.append(f"apply:{name}")
            self.calls.append((name, data))
            if name == self.fail_host:
                return {"success": False, "error": "sha256 mismatch", "progress": []}, 500
            lines = [pd.progress(name, "host", p, "ok", "") for p in ("rsync", "install", "restart")]
            lines.append(pd.progress(name, "host", "health", "skipped", "x").replace('"phase":', '"phase":'))
            return {"success": True, "progress": lines, "version_before": "1", "version_after": "7.7.7", "backup_id": "b"}, 200
        return {}, self.health


def test_gate_refuses_while_required_check_is_ko(ready, monkeypatch):
    store, run_id, *_ = ready
    monkeypatch.setattr(pd.prerequisites, "run_all", lambda *a, **k: {"ok": False, "checks": [
        {"title": "Sudo rights on hosts", "required": True, "status": "ko"},
        {"title": "No test run in progress", "required": False, "status": "ko"}]})
    env = FakeEnv()
    with pytest.raises(PlatformUpdateError) as e:
        pd.start(store, run_id, {}, threaded=False, env=env)
    assert "Sudo rights on hosts" in str(e.value) and "No test run" not in str(e.value)
    assert env.events == [] and not bundle_jobs.is_running("deploy")
    assert store.get(run_id)["steps"][3]["state"] == "waiting"      # nothing started


def test_gate_uses_the_sources_of_the_bundle_step(ready, monkeypatch):
    store, run_id, *_ = ready
    seen = []
    monkeypatch.setattr(pd.prerequisites, "run_all", lambda core, overlay, deps=None: seen.append((core, overlay)) or {"ok": True, "checks": []})
    pd.start(store, run_id, {}, threaded=False, env=FakeEnv(hosts=()))
    assert seen == [("zip", "none")]


def test_order_is_frontend_then_hosts_then_server_and_awaits_confirmation(ready):
    store, run_id, archive, sha = ready
    env = FakeEnv(frontend=True)
    pd.start(store, run_id, {}, threaded=False, env=env)
    order = [e for e in env.events]
    assert order.index("apply:h1") < order.index("apply:h2") < order.index("server-restart")
    assert order[0] == "rsync" and order.index("ssh") < order.index("apply:h1")      # frontend before any host
    assert order.index("reconcile") < order.index("server-restart")                    # server restart is the very last act
    assert order[-1] == "server-restart"
    # hosts are told the path on THIS server and the archive sha256
    assert ("h1", {"url": f"/server/platform-update/bundle/{run_id}/archive", "sha256": sha}) in env.calls
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "running" and step["data"]["job"]["state"] == "awaiting_confirmation"
    assert step["data"]["expected_version"] == "7.7.7"
    assert not bundle_jobs.is_running("deploy")
    # the restart does not make the page mark it interrupted
    assert bundle_jobs.recover_interrupted(store, store.get(run_id))["steps"][3]["state"] == "running"
    log = "\n".join(store.log_lines(run_id, tail=1000))
    from backend_server.src.lib.platform_update import deployment
    view = deployment.build_view(store.log_lines(run_id, tail=10_000))
    cards = {(c["role"], c["host"]): c for c in view["hosts"]}
    assert cards[("frontend", "fe")]["phases"]["restart"]["state"] == "ok"
    assert cards[("host", "h1")]["phases"]["health"]["state"] == "ok"        # reported by the server, not the host
    assert cards[("host", "h1")]["state"] == "ok" and cards[("host", "h2")]["state"] == "ok"
    assert cards[("server", "srv")]["phases"]["rsync"]["state"] == "ok"
    assert "vpt-server restarts" in log


def test_no_frontend_host_skips_it(ready):
    store, run_id, *_ = ready
    env = FakeEnv(frontend=False)
    pd.start(store, run_id, {}, threaded=False, env=env)
    assert "ssh" not in env.events and "rsync" in env.events        # the only rsync is the server's own
    assert "skipped" in "\n".join(store.log_lines(run_id, tail=1000))


def test_frontend_local_builds_after_the_server_tree_and_before_its_restart(ready):
    store, run_id, *_ = ready
    env = FakeEnv(hosts=(), mode="local")
    pd.start(store, run_id, {}, threaded=False, env=env)
    cmds = [" ".join(c) for c in env.calls if isinstance(c, list)]
    build = next(i for i, c in enumerate(cmds) if "ensure_dist.sh" in c)
    restart = next(i for i, c in enumerate(cmds) if c == "sudo -n systemctl restart vpt-frontend")
    reconcile = next(i for i, c in enumerate(cmds) if "vpt-reconcile-feature-units" in c)
    assert reconcile < build < restart and "ssh" not in env.events
    assert env.events[-1] == "server-restart" and store.get(run_id)["steps"][3]["data"]["job"]["state"] == "awaiting_confirmation"
    assert not any("reconcile_feature_units.sh" in c for c in cmds)         # the root-owned helper only


def test_frontend_local_failure_fails_the_step_loudly(ready):
    store, run_id, *_ = ready
    env = FakeEnv(hosts=(), mode="local")
    base = env.run
    env.run = lambda argv, timeout, e=None: (subprocess.CompletedProcess(argv, 1, "", "vite failed") if "ensure_dist.sh" in " ".join(argv) else base(argv, timeout, e))
    pd.start(store, run_id, {}, threaded=False, env=env)
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "failed" and "frontend" in step["detail"] and "vite failed" in step["detail"]
    assert "server-restart" not in env.events


def test_frontend_unset_refuses_instead_of_silently_skipping(ready):
    store, run_id, *_ = ready
    env = FakeEnv(mode="unset")
    pd.start(store, run_id, {}, threaded=False, env=env)
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "failed" and "FRONTEND_DEPLOY_HOST" in step["detail"] and "apply:h1" not in env.events


def test_first_host_failure_stops_everything_and_server_is_untouched(ready):
    store, run_id, *_ = ready
    env = FakeEnv(fail_host="h1")
    pd.start(store, run_id, {}, threaded=False, env=env)
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "failed" and "h1" in step["detail"] and "sha256 mismatch" in step["detail"]
    assert "apply:h2" not in env.events and "server-restart" not in env.events and "rsync" not in env.events
    assert not bundle_jobs.is_running("deploy")


def test_host_that_never_comes_back_fails_the_step(ready, monkeypatch):
    store, run_id, *_ = ready
    monkeypatch.setattr(pd, "deploy_host", lambda env, host, run_id, sha, log, wait_seconds=120: {"host": "h1", "ok": False, "detail": "the host did not come back after the restart"})
    env = FakeEnv()
    pd.start(store, run_id, {}, threaded=False, env=env)
    assert store.get(run_id)["steps"][3]["state"] == "failed" and "server-restart" not in env.events


def test_deploy_host_waits_for_health(monkeypatch):
    env = FakeEnv(health=503)
    lines = []
    t = [0.0]
    monkeypatch.setattr(pd.time, "monotonic", lambda: t.__setitem__(0, t[0] + 50) or t[0])
    res = pd.deploy_host(env, {"host_name": "h1"}, "r", "a" * 64, lines.append, wait_seconds=120)
    assert not res["ok"] and any('"state": "failed"' in l and "health" in l for l in lines)


def test_confirm_requires_a_restart_and_the_bundle_version(ready, monkeypatch):
    store, run_id, *_ = ready
    with pytest.raises(PlatformUpdateError, match="nothing to confirm"):
        pd.confirm(store, run_id, lambda m: None)
    pd.start(store, run_id, {}, threaded=False, env=FakeEnv(hosts=()))
    with pytest.raises(PlatformUpdateError, match="not restarted"):                  # same process still running
        pd.confirm(store, run_id, lambda m: None)
    monkeypatch.setattr(pd, "PROCESS_START", time.time() + 100)                         # a new process started later
    (open(os.path.join(os.environ["TEST_ROOT"], "VERSION.txt"), "w")).write("1.0.0\n")
    with pytest.raises(PlatformUpdateError, match="reports version 1.0.0"):
        pd.confirm(store, run_id, lambda m: None)
    (open(os.path.join(os.environ["TEST_ROOT"], "VERSION.txt"), "w")).write("7.7.7\n")
    pd.confirm(store, run_id, lambda m: None)
    step = store.get(run_id)["steps"][3]
    assert step["state"] == "done" and step["data"]["job"]["state"] == "done"


def test_unsafe_archive_fails_before_touching_any_machine(ready, tmp_path):
    store, run_id, archive, _ = ready
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("../evil", "x")
    env = FakeEnv()
    pd.start(store, run_id, {}, threaded=False, env=env)
    assert store.get(run_id)["steps"][3]["state"] == "failed" and env.events == []


def test_only_one_deploy_at_a_time(ready):
    store, run_id, *_ = ready
    bundle_jobs._claim("deploy", "other")
    with pytest.raises(bundle_jobs.JobBusy):
        pd.start(store, run_id, {}, threaded=False, env=FakeEnv())


# -- archive route ---------------------------------------------------------------------------------
@pytest.fixture
def client(ready, monkeypatch):
    store, run_id, archive, sha = ready
    monkeypatch.setattr(routes, "_store", lambda: store)
    app = Flask(__name__)
    app.register_blueprint(routes.server_platform_update_bp)

    @app.before_request
    def principal():                      # what the global /server/* guard does after validating a credential
        role = request.headers.get("X-Test-Role")
        if role:
            request.user_role, request.user_id, request.user_email = role, "t", "t@x"
    return app.test_client(), run_id, archive, sha


def test_archive_download_roles(client):
    c, run_id, archive, sha = client
    url = f"/server/platform-update/bundle/{run_id}/archive"
    for role in ("service", "admin"):
        r = c.get(url, headers={"X-Test-Role": role})
        assert r.status_code == 200 and hashlib.sha256(r.data).hexdigest() == sha
    for role in ("viewer", "tester"):
        assert c.get(url, headers={"X-Test-Role": role}).status_code == 403
    assert c.get(url).status_code in (401, 500)              # no principal and no JWT secret: never served


def test_archive_unknown_run_and_unbuilt_run(client, ready):
    c, run_id, *_ = client
    assert c.get("/server/platform-update/bundle/nope/archive", headers={"X-Test-Role": "service"}).status_code == 404
    store = ready[0]
    other = store.close(run_id, "failed", "x") and None
    # a run whose bundle step never finished
    store2 = RunStore(os.path.join(os.path.dirname(str(store.dir)), "pu2"))
    r2 = store2.start("a@x")
    routes._store = lambda: store2
    assert c.get(f"/server/platform-update/bundle/{r2['id']}/archive", headers={"X-Test-Role": "service"}).status_code == 404


def test_ping_and_prerequisites_roles(client, monkeypatch):
    c, *_ = client
    body = c.get("/server/platform-update/bundle/ping", headers={"X-Test-Role": "service"}).get_json()
    assert hashlib.sha256(body["body"].encode()).hexdigest() == body["sha256"]
    assert c.get("/server/platform-update/bundle/ping", headers={"X-Test-Role": "viewer"}).status_code == 403
    monkeypatch.setattr(routes.prerequisites, "run_all", lambda core, overlay, fmt="zip": {"ok": True, "core": core, "overlay": overlay, "checks": [], "passed": 0, "total": 0})
    r = c.get("/server/platform-update/prerequisites?core=zip&overlay=gitlab", headers={"X-Test-Role": "admin"})
    assert r.status_code == 200 and r.get_json()["overlay"] == "gitlab" and r.get_json()["success"]
    assert c.get("/server/platform-update/prerequisites", headers={"X-Test-Role": "service"}).status_code == 403


def test_step_route_deploy_pull_is_gated(client, monkeypatch):
    c, run_id, *_ = client
    monkeypatch.setattr(pd.prerequisites, "run_all", lambda *a, **k: {"ok": False, "checks": [{"title": "Disk space", "required": True, "status": "ko"}]})
    r = c.post(f"/server/platform-update/runs/{run_id}/steps/3", json={"action": "deploy_pull"}, headers={"X-Test-Role": "admin"})
    assert r.status_code == 400 and "Disk space" in r.get_json()["error"]


# -- versions before the deploy are kept in the run (TASK-109) ---------------------------------------------
def test_before_versions_are_stored_in_the_run_at_deploy_start(ready):
    store, run_id, *_ = ready
    env = FakeEnv(hosts=())
    env.hosts = lambda: [{"host_name": "h1", "deployed_version": "current: 1.0-aaa"}, {"host_name": "h2", "deployed_version": "1.0-bbb"}]
    pd.start(store, run_id, {"frontend_version": "1.0-ccc"}, threaded=False, env=env)
    before = store.get(run_id)["steps"][3]["data"]["versions_before"]
    assert before["server"] == "7.7.7"                      # read from the server tree BEFORE it is synced
    assert before["frontend"] == "1.0-ccc"
    assert before["hosts"] == {"h1": "1.0-aaa", "h2": "1.0-bbb"}   # the "current:" label is dropped
    assert before["captured_at"]


def test_before_versions_survive_a_page_reload_and_a_redeploy(ready):
    store, run_id, *_ = ready
    env = FakeEnv(hosts=())
    env.hosts = lambda: [{"host_name": "h1", "deployed_version": "1.0-aaa"}]
    pd.start(store, run_id, {}, threaded=False, env=env)
    first = store.get(run_id)["steps"][3]["data"]["versions_before"]
    # the run is read again from disk (reload / other browser): same record, nothing client-side needed
    assert RunStore(store.dir).get(run_id)["steps"][3]["data"]["versions_before"] == first
    # a failed deploy re-run later must not record half-updated versions as the "before"
    store.mark_failed(run_id, 3, "retry")
    env2 = FakeEnv(hosts=())
    env2.hosts = lambda: [{"host_name": "h1", "deployed_version": "9.9-new"}]
    pd.start(store, run_id, {"frontend_version": "9.9"}, threaded=False, env=env2)
    assert store.get(run_id)["steps"][3]["data"]["versions_before"] == first


def test_unreadable_host_list_does_not_stop_the_deploy(ready):
    store, run_id, *_ = ready
    env = FakeEnv(hosts=())

    def boom():
        raise RuntimeError("no registry")
    env.hosts = boom
    from backend_server.src.lib.platform_update import before_versions as bv
    bv.capture_for_deploy(store, run_id, "/nonexistent", boom)
    assert store.get(run_id)["steps"][3]["data"]["versions_before"]["hosts"] == {}
