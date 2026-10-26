"""TASK-109 G3: Platform update step 1, the backup. The database VM request, host calls and SSH are mocked; files are real."""
import json
import os
import stat
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import backup as bk  # noqa: E402
from backend_server.src.lib.platform_update.runs import RunStore  # noqa: E402

DB_OK = {"status": "ok", "detail": "vpt_postgres_20261015_020000.dump · 45M · NFS copy yes", "size": 0, "fix": ""}


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Fake:
    """Collects what the backup asked of the OS and of other machines."""

    def __init__(self, tmp_path, database=None, hosts=("h1",), frontend="ssh", host_reply=None, ssh_out=None, ssh_rc=0):
        self.root = tmp_path / "opt"
        self.root.mkdir(exist_ok=True)
        (self.root / ".env").write_text("API_KEY=server-secret\n")
        self.db_calls, self.host_calls, self.ssh_calls = [], [], []
        self.db_reply, self.host_reply, self.ssh_rc = database or DB_OK, host_reply or {}, ssh_rc
        self.ssh_out = ssh_out if ssh_out is not None else (
            "\n::VPT-FILE:: .env\nFE=1\n\n::VPT-FILE:: frontend/.env.production\nVITE=2\n")
        self.deps = bk.Deps(
            database=self.database,
            hosts=lambda: [{"host_name": h} for h in hosts], call_host=self.call_host, run=self.ssh,
            frontend_cfg=lambda: {"mode": frontend, "host": "fe" if frontend == "ssh" else "", "user": "deploy", "password": "",
                                  "key": "", "target_dir": "/opt/v", "backup_root": "/b", "service": "vpt-frontend",
                                  "service_user": "vpt_user"},
            project_root=lambda: str(self.root),
        )

    def database(self, log):
        self.db_calls.append(1)
        log("requested")
        return self.db_reply

    def call_host(self, host, endpoint, method="GET", timeout=30):
        self.host_calls.append((host["host_name"], endpoint, method))
        reply = self.host_reply.get(host["host_name"])
        if reply is None:
            reply = ({"success": True, "host_name": host["host_name"], "files": [
                {"name": ".env", "content": "HOST_KEY=h-secret\n"},
                {"name": "backend_host/src/.env", "content": "X=1\n"},
                {"name": "../../etc/passwd", "content": "evil"}]}, 200)
        return reply

    def ssh(self, argv, timeout, env=None):
        self.ssh_calls.append(argv)
        return subprocess.CompletedProcess(argv, self.ssh_rc, self.ssh_out, "Permission denied" if self.ssh_rc else "")


def test_full_backup_contents_and_file_modes(tmp_path):
    f = Fake(tmp_path)
    out = bk.run_backup(tmp_path / "pu", "run1", f.deps)
    assert out["ok"] is True
    folder = tmp_path / "pu" / "backups" / out["folder"]
    assert str(folder) == out["path"]
    # content
    assert not (folder / "schema.sql").exists()                      # the server no longer dumps anything
    assert (folder / "server" / "env").read_text() == "API_KEY=server-secret\n"
    assert (folder / "hosts" / "h1" / "env").read_text() == "HOST_KEY=h-secret\n"
    assert (folder / "hosts" / "h1" / "backend_host_src.env").read_text() == "X=1\n"
    assert (folder / "frontend" / "env").read_text() == "FE=1\n"
    assert (folder / "frontend" / "frontend_env.production").read_text() == "VITE=2\n"
    # a name the host invents is ignored: nothing is written outside the folder
    assert not any("passwd" in str(p) for p in folder.rglob("*")) and not (tmp_path / "etc").exists()
    # modes: folders 0700, files 0600
    for p in [folder, folder / "hosts", folder / "hosts" / "h1", folder / "server", folder / "frontend", tmp_path / "pu" / "backups"]:
        assert mode(p) == 0o700, p
    for p in folder.rglob("*"):
        if p.is_file():
            assert mode(p) == 0o600, p
    # one line per item with sizes
    assert [i["id"] for i in out["items"]] == ["database", "server", "host:h1", "frontend"]
    assert out["items"][0]["label"] == "Database" and out["items"][0]["detail"] == DB_OK["detail"] and out["items"][0]["files"] == []
    assert all(i["status"] == "ok" and (i["size"] > 0 or i["id"] == "database") for i in out["items"])
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["run_id"] == "run1" and "h-secret" not in json.dumps(manifest)


def test_the_server_never_runs_pg_dump():
    src = open(bk.__file__, encoding="utf-8").read()
    assert "'pg_dump'" not in src and '"pg_dump"' not in src and "schema-only" not in src and "psycopg2" not in src


def test_database_item_comes_from_the_database_vm_and_is_logged(tmp_path):
    f = Fake(tmp_path)
    logs = []
    out = bk.run_backup(tmp_path / "pu", "r", f.deps, logs.append)
    assert f.db_calls == [1] and out["items"][0]["id"] == "database"
    assert any(l.startswith("Backup Database: OK - vpt_postgres_") for l in logs)


def test_database_ko_fails_the_backup_with_its_fix_and_leaves_no_folder(tmp_path):
    ko = {"status": "ko", "detail": "The database backup script failed (exit 1): disk full", "size": 0,
          "fix": "Run on the database VM: sudo bash /usr/local/bin/vpt-db-backup.sh"}
    f = Fake(tmp_path, database=ko)
    out = bk.run_backup(tmp_path / "pu", "r", f.deps)
    item = out["items"][0]
    assert out["ok"] is False and item["status"] == "ko" and "disk full" in item["detail"] and item["fix"].startswith("Run on the database VM")
    assert not os.path.exists(out["path"])


def test_database_exception_is_a_ko_not_a_crash(tmp_path):
    f = Fake(tmp_path)
    f.database = lambda log: (_ for _ in ()).throw(RuntimeError("x"))
    f.deps.database = f.database
    out = bk.run_backup(tmp_path / "pu", "r", f.deps)
    assert out["items"][0]["status"] == "ko" and out["items"][0]["fix"]


def test_host_without_the_endpoint_or_unreachable_is_ko(tmp_path):
    f = Fake(tmp_path, hosts=("old", "down", "good"), host_reply={
        "old": ({"error": "nf"}, 404), "down": ({"success": False, "error": "x"}, 504)})
    out = bk.run_backup(tmp_path / "pu", "r", f.deps)
    by = {i["id"]: i for i in out["items"]}
    assert out["ok"] is False
    assert by["host:old"]["status"] == "ko" and "predates" in by["host:old"]["detail"]
    assert by["host:down"]["status"] == "ko" and by["host:good"]["status"] == "ok"
    assert all(i["fix"] for i in out["items"] if i["status"] == "ko")
    assert not os.path.exists(out["path"])


def test_hosts_are_asked_with_get_on_the_env_endpoint(tmp_path):
    f = Fake(tmp_path, hosts=("a", "b"))
    bk.run_backup(tmp_path / "pu", "r", f.deps)
    assert sorted(f.host_calls) == [("a", "/host/system/envFiles", "GET"), ("b", "/host/system/envFiles", "GET")]


def test_frontend_local_and_none_are_skipped(tmp_path):
    for mode_ in ("local", "none"):
        f = Fake(tmp_path, frontend=mode_)
        out = bk.run_backup(tmp_path / "pu", "r", f.deps)
        item = out["items"][-1]
        assert item["id"] == "frontend" and item["status"] == "na" and f.ssh_calls == [] and out["ok"] is True


def test_frontend_ssh_failure_is_ko_and_never_shows_file_content(tmp_path):
    f = Fake(tmp_path, ssh_rc=255, ssh_out="FE=leaked\n")
    out = bk.run_backup(tmp_path / "pu", "r", f.deps)
    item = out["items"][-1]
    assert item["status"] == "ko" and "leaked" not in json.dumps(out) and out["ok"] is False


def test_frontend_runs_as_the_service_user_over_ssh(tmp_path):
    f = Fake(tmp_path)
    bk.run_backup(tmp_path / "pu", "r", f.deps)
    argv = f.ssh_calls[0]
    assert argv[0] == "ssh" and "deploy@fe" in argv and "vpt_user" in argv[-1] and "cat" in argv[-1]


def test_missing_server_env_is_ko(tmp_path):
    f = Fake(tmp_path)
    (f.root / ".env").unlink()
    out = bk.run_backup(tmp_path / "pu", "r", f.deps)
    assert {i["id"]: i for i in out["items"]}["server"]["status"] == "ko"


def test_two_backups_in_the_same_second_get_two_folders(tmp_path):
    f = Fake(tmp_path)
    a = bk.run_backup(tmp_path / "pu", "r", f.deps)
    b = bk.run_backup(tmp_path / "pu", "r", f.deps)
    assert a["folder"] != b["folder"] and os.path.isdir(a["path"]) and os.path.isdir(b["path"])


# -- the step, through the route ------------------------------------------------------------------
@pytest.fixture
def step_env(tmp_path, monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_platform_update_routes as r
    store = RunStore(tmp_path / "pu")
    monkeypatch.setattr(r, "_store", lambda: store)
    app = Flask(__name__)
    fake = Fake(tmp_path)
    monkeypatch.setattr(r.step_backup, "Deps", lambda: fake.deps)

    def call(run_id, body, index=1):
        fn = r.run_step
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        with app.test_request_context(json=body):
            resp = fn(run_id, index)
            return resp[0].get_json() if resp[1] == 200 else resp
    run = store.start("a@x")
    store.begin_step(run["id"], 0)
    store.finish_step(run["id"], 0, True)
    return store, run["id"], call, fake


def test_backup_step_waits_for_the_snapshot_box(step_env):
    store, rid, call, _ = step_env
    out = call(rid, {"action": "backup"})
    step = out["run"]["steps"][1]
    assert step["state"] == "running" and step["data"]["backup"]["ok"] is True
    assert store.get(rid)["steps"][2]["state"] == "pending"      # the bundle is not reachable yet
    assert call(rid, {"action": "confirm"})[1] == 400                  # box not ticked
    assert call(rid, {"action": "confirm", "snapshotted": "yes"})[1] == 400
    out = call(rid, {"action": "confirm", "snapshotted": True})
    step = out["run"]["steps"][1]
    assert step["state"] == "done" and step["data"]["snapshotted"] is True
    assert out["run"]["steps"][2]["state"] == "waiting"


def test_confirm_before_any_backup_is_refused(step_env):
    _store, rid, call, _ = step_env
    assert call(rid, {"action": "confirm", "snapshotted": True})[1] == 400


def test_failed_backup_fails_the_step_and_can_be_retried(step_env):
    store, rid, call, fake = step_env
    fake.host_reply["h1"] = ({"error": "nf"}, 404)
    out = call(rid, {"action": "backup"})
    step = out["run"]["steps"][1]
    assert step["state"] == "failed" and step["detail"].startswith("KO:") and step["data"]["backup"]["ok"] is False
    fake.host_reply.pop("h1")
    out = call(rid, {"action": "backup"})
    assert out["run"]["steps"][1]["state"] == "running" and out["run"]["steps"][1]["data"]["backup"]["ok"] is True


def test_step_runs_only_after_step_zero(tmp_path, monkeypatch):
    from backend_server.src.lib.platform_update.runs import StepOrderError
    store = RunStore(tmp_path / "pu")
    run = store.start("a@x")
    with pytest.raises(StepOrderError):
        store.begin_step(run["id"], 1)


def test_no_route_serves_a_backup():
    from backend_server.src.routes import server_platform_update_routes as r
    src = open(r.__file__, encoding="utf-8").read()
    assert "send_file(path" in src and "backups" not in src       # the only file download is the bundle archive
    from backend_server.src.lib.platform_update import backup
    assert "send_file" not in open(backup.__file__, encoding="utf-8").read()
