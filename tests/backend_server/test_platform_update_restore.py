"""TASK-128 G7: restore one .env from a Platform update backup - fixed names only, atomic, current file kept, mode kept."""
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import backup as bk, db_backup, restore as rs  # noqa: E402
from backend_server.src.lib.platform_update.runs import PlatformUpdateError, RunStore  # noqa: E402

FOLDER = "20261018-120000"
NOW = datetime(2026, 10, 18, 13, 0, 0, tzinfo=timezone.utc)
CFG = {"mode": "ssh", "host": "fe", "user": "deploy", "password": "", "key": "", "target_dir": "/opt/v",
       "backup_root": "/b", "service": "vpt-frontend", "service_user": "vpt_user"}


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Env:
    def __init__(self, tmp_path):
        self.state = tmp_path / "pu"
        self.root = tmp_path / "opt"
        (self.root / "backend_server" / "src").mkdir(parents=True)
        self.folder = self.state / "backups" / FOLDER
        self.calls, self.ssh = [], []
        self.host_reply = ({"success": True, "backup": ".env.bak-1"}, 200)
        self.ssh_rc = 0
        files = {"server/env": "SAVED=1\n", "server/backend_server_src.env": "SRC=1\n", "hosts/h1/env": "H=1\n",
                 "hosts/h1/backend_host_src.env": "HS=1\n", "frontend/env": "FE=1\n", "frontend/frontend_env.production": "V=1\n"}
        for rel, text in files.items():
            (self.folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.folder / rel).write_text(text)
        items = [{"id": "database", "status": "ok", "files": []},
                 {"id": "server", "status": "ok", "files": ["server/env", "server/backend_server_src.env"]},
                 {"id": "host:h1", "status": "ok", "files": ["hosts/h1/env", "hosts/h1/backend_host_src.env"]},
                 {"id": "frontend", "status": "ok", "files": ["frontend/env", "frontend/frontend_env.production"]},
                 {"id": "host:h2", "status": "ko", "files": []}]
        (self.folder / "manifest.json").write_text(json.dumps({"items": items}))
        self.deps = rs.Deps(hosts=lambda: [{"host_name": "h1"}], call_host=self.call_host, run_input=self.run_input,
                            frontend_cfg=lambda: dict(CFG), project_root=lambda: str(self.root), now=lambda: NOW)

    def call_host(self, host, endpoint, method, timeout, data):
        self.calls.append((host["host_name"], endpoint, method, data))
        return self.host_reply

    def run_input(self, argv, timeout, env, stdin):
        self.ssh.append((argv, stdin))
        return subprocess.CompletedProcess(argv, self.ssh_rc, "", "Permission denied" if self.ssh_rc else "")

    def go(self, item, file, folder=FOLDER):
        return rs.restore(self.state, folder, item, file, self.deps)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# -- server ------------------------------------------------------------------------------------------
def test_server_restore_keeps_a_copy_of_the_current_file_and_its_mode(env):
    target = env.root / ".env"
    target.write_text("CURRENT=1\n")
    os.chmod(target, 0o640)
    out = env.go("server", "server/env")
    assert target.read_text() == "SAVED=1\n" and mode(target) == 0o640
    copy = env.root / ".env.bak-20261018-130000"
    assert copy.read_text() == "CURRENT=1\n" and mode(copy) == 0o640 and out["backup_of_current"] == copy.name
    assert out["restart"] == {"machine": "this server", "command": "sudo systemctl restart vpt-server"}
    assert [p.name for p in env.root.iterdir() if p.name.startswith(".restore-")] == []        # no temp file left


def test_server_restore_maps_the_stored_name_to_the_nested_env_and_creates_a_missing_file_0600(env):
    out = env.go("server", "server/backend_server_src.env")
    path = env.root / "backend_server" / "src" / ".env"
    assert path.read_text() == "SRC=1\n" and mode(path) == 0o600 and out["backup_of_current"] == ""
    assert out["restored"] == "backend_server/src/.env"


def test_a_failed_write_leaves_the_current_file_untouched(env, monkeypatch):
    target = env.root / ".env"
    target.write_text("CURRENT=1\n")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PlatformUpdateError, match="PermissionError"):
        env.go("server", "server/env")
    assert target.read_text() == "CURRENT=1\n"
    assert [p.name for p in env.root.iterdir() if p.name.endswith(".tmp")] == []


# -- what can be asked -------------------------------------------------------------------------------
@pytest.mark.parametrize("item,file,folder", [
    ("server", "server/../../etc/passwd", FOLDER),
    ("server", "server/nothere", FOLDER),
    ("server", "manifest.json", FOLDER),
    ("server", "hosts/h1/env", FOLDER),               # in the backup, but not this item's file
    ("host:h1", "server/env", FOLDER),
    ("frontend", "hosts/h1/env", FOLDER),
    ("host:h2", "hosts/h2/env", FOLDER),              # item was KO: nothing saved
    ("other", "server/env", FOLDER),
    ("server", "server/env", "../etc"),
    ("server", "server/env", "20261018-999999-x"),
    ("server", "server/env", "20200101-000000"),
])
def test_only_files_listed_in_the_manifest_of_a_real_folder_are_restorable(env, item, file, folder):
    with pytest.raises(PlatformUpdateError):
        env.go(item, file, folder)
    assert not (env.root / ".env").exists() and env.calls == [] and env.ssh == []


def test_the_database_is_never_restored_by_the_app(env):
    with pytest.raises(PlatformUpdateError, match="by hand"):
        env.go("database", "anything")


def test_a_symlink_inside_the_backup_is_refused(env, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP=1\n")
    (env.folder / "server" / "env").unlink()
    os.symlink(secret, env.folder / "server" / "env")
    with pytest.raises(PlatformUpdateError, match="plain file"):
        env.go("server", "server/env")


# -- host --------------------------------------------------------------------------------------------
def test_host_restore_posts_the_fixed_name_and_content_through_call_host(env):
    out = env.go("host:h1", "hosts/h1/backend_host_src.env")
    assert env.calls == [("h1", "/host/system/restoreEnvFile", "POST", {"name": "backend_host/src/.env", "content": "HS=1\n"})]
    assert out["machine"] == "h1" and out["restart"]["command"] == "sudo systemctl restart vpt-host" and out["backup_of_current"] == ".env.bak-1"


@pytest.mark.parametrize("reply,message", [(({"success": False, "error": "unknown file name"}, 400), "refused: unknown file name"),
                                             (({}, 404), "predates the restore endpoint")])
def test_host_refusal_is_reported(env, reply, message):
    env.host_reply = reply
    with pytest.raises(PlatformUpdateError, match=message):
        env.go("host:h1", "hosts/h1/env")


def test_host_that_is_gone_or_silent_gets_a_clear_error(env):
    env.deps.hosts = lambda: []
    with pytest.raises(PlatformUpdateError, match="not registered"):
        env.go("host:h1", "hosts/h1/env")
    env.deps.hosts = lambda: [{"host_name": "h1"}]
    env.deps.call_host = lambda *a, **k: (_ for _ in ()).throw(ConnectionError())
    with pytest.raises(PlatformUpdateError, match="did not answer"):
        env.go("host:h1", "hosts/h1/env")


# -- frontend ----------------------------------------------------------------------------------------
def test_frontend_restore_pipes_the_content_on_stdin_never_in_the_command(env):
    out = env.go("frontend", "frontend/frontend_env.production")
    argv, stdin = env.ssh[0]
    assert stdin == "V=1\n" and "V=1" not in " ".join(argv)
    remote = argv[-1]
    assert "frontend/.env.production" in remote and ".bak-20261018-130000" in remote and "mv -f" in remote and "sudo -n" in remote
    assert out["restart"] == {"machine": "frontend VM", "command": "sudo systemctl restart vpt-frontend"} and "rebuilds" in out["note"]


def test_frontend_password_mode_and_non_ssh_modes_are_refused_and_nothing_is_sent(env):
    env.deps.frontend_cfg = lambda: {**CFG, "password": "pw"}
    with pytest.raises(PlatformUpdateError, match="password mode"):
        env.go("frontend", "frontend/env")
    env.deps.frontend_cfg = lambda: {**CFG, "mode": "local", "host": ""}
    with pytest.raises(PlatformUpdateError, match="no separate frontend"):
        env.go("frontend", "frontend/env")
    assert env.ssh == []


def test_frontend_ssh_failure_is_reported_and_masked(env):
    env.ssh_rc = 255
    with pytest.raises(PlatformUpdateError, match="Permission denied"):
        env.go("frontend", "frontend/env")


# -- items and the database command ------------------------------------------------------------------
def test_backup_items_list_the_restorable_files_with_their_target_names():
    assert bk._restorable(bk.SERVER_FILES, ["server/env", "server/backend_server_src.env"]) == [
        {"file": "server/env", "name": ".env"}, {"file": "server/backend_server_src.env", "name": "backend_server/src/.env"}]
    assert bk._restorable(bk.FRONTEND_FILES, ["frontend/frontend_env.production"])[0]["name"] == "frontend/.env.production"


def test_database_item_carries_the_pg_restore_command_for_the_dump_it_made():
    cmd = db_backup.restore_command("vpt_postgres_20261018_020000.dump · 45M · NFS copy yes")
    assert "docker cp /data/backups/vpt_postgres_20261018_020000.dump supabase_db_supabase:/tmp/restore.dump" in cmd
    assert "pg_restore -U postgres -d postgres --clean --if-exists -F c /tmp/restore.dump" in cmd
    assert cmd.endswith("docker restart supabase_rest_supabase")
    assert db_backup.restore_command("The database VM never reported a backup") == ""
    assert db_backup.restore_command("x; rm -rf / vpt_postgres_1.dump") .count("rm -rf") == 0


# -- the route ---------------------------------------------------------------------------------------
@pytest.fixture
def client(env, monkeypatch):
    from tests.backend_server import _task42_services_common as common
    from backend_server.src.routes import server_platform_update_routes as r
    monkeypatch.setattr(r, "_store", lambda: RunStore(env.state))
    monkeypatch.setattr(r, "PROJECT_ROOT", str(env.root))
    return lambda role="admin": common.make_app(r.server_platform_update_bp, role=role).test_client()


def test_route_is_admin_only(client, env):
    body = {"folder": FOLDER, "item_id": "server", "file": "server/env"}
    for role in ("tester", "viewer", "developer"):
        assert client(role).post("/server/platform-update/restore", json=body).status_code == 403
    assert not (env.root / ".env").exists()


def test_route_restores_and_answers_with_the_restart_command(client, env):
    r = client().post("/server/platform-update/restore", json={"folder": FOLDER, "item_id": "server", "file": "server/env"})
    body = r.get_json()
    assert r.status_code == 200 and body["success"] and body["restart"]["command"] == "sudo systemctl restart vpt-server"
    assert (env.root / ".env").read_text() == "SAVED=1\n"


@pytest.mark.parametrize("body,code", [({}, 400), ({"folder": FOLDER, "item_id": "server", "file": "/etc/passwd"}, 400),
                                       ({"folder": FOLDER, "item_id": "database", "file": "x"}, 400),
                                       ({"folder": "20200101-000000", "item_id": "server", "file": "server/env"}, 404)])
def test_route_refuses_bad_requests(client, env, body, code):
    assert client().post("/server/platform-update/restore", json=body).status_code == code
