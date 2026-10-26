"""TASK-128 G1/G2: Platform update settings store, the resolver its consumers use, the routes and the agent token."""
import json
import logging
import os
import re
import stat
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import backup, db_backup, frontend_ssh, migrations as mig, settings  # noqa: E402
from backend_server.src.lib.platform_update.runs import PlatformUpdateError  # noqa: E402


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("VPT_CONFIG_DIR", str(tmp_path))
    for var in ("FRONTEND_DEPLOY_HOST", "FRONTEND_DEPLOY_SSH_USER", "FRONTEND_DEPLOY_SSH_KEY", "PLATFORM_UPDATE_DB_URI",
                "SUPABASE_DB_URI", "DATABASE_URL", "VM_AGENT_ACTION_TOKEN", "INFRA_VM_AGENTS", "VPT_GITHUB_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    # these tests exercise the file store: the settings table is "not applied"
    def _missing(*_a, **_k):
        raise settings.db.TableMissing("table not applied")
    monkeypatch.setattr(settings.db, "load", _missing)
    monkeypatch.setattr(settings.db, "save", _missing)
    settings._forget()
    return tmp_path / "platform-update" / "settings.json"


# -- store ----------------------------------------------------------------------------------------
def test_write_is_0600_atomic_and_leaves_no_temp_file(state):
    settings.update({"frontend_deploy_host": "10.0.0.5"})
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert json.loads(state.read_text()) == {"frontend_deploy_host": "10.0.0.5"}
    assert [p.name for p in state.parent.iterdir()] == ["settings.json"]


def test_env_is_the_fallback_and_the_store_wins(monkeypatch):
    monkeypatch.setenv("FRONTEND_DEPLOY_HOST", "from-env")
    assert settings.get("frontend_deploy_host") == "from-env" and settings.source("frontend_deploy_host") == "env"
    settings.update({"frontend_deploy_host": "local"})
    assert settings.get("frontend_deploy_host") == "local" and settings.source("frontend_deploy_host") == "store"


def test_empty_string_clears_back_to_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_UPDATE_DB_URI", "postgresql://env/db")
    settings.update({"db_dsn": "postgresql://store/db"})
    assert settings.get("db_dsn") == "postgresql://store/db"
    settings.update({"db_dsn": ""})
    assert settings.get("db_dsn") == "postgresql://env/db"


def test_db_dsn_env_order_and_agent_from_infra(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://c")
    monkeypatch.setenv("SUPABASE_DB_URI", "postgres://b")
    assert settings.get("db_dsn") == "postgres://b"
    monkeypatch.setenv("INFRA_VM_AGENTS", "storage=1.1.1.1:9110,database=10.0.0.2:9110")
    assert settings.get("database_agent") == "10.0.0.2:9110"
    settings.update({"database_agent": "10.9.9.9:9110"})
    assert settings.get("database_agent") == "10.9.9.9:9110"


def test_view_masks_secrets():
    settings.update({"db_dsn": "postgresql://u:hunter2@h/db", "frontend_deploy_ssh_user": "deploy"})
    token = settings.generate_agent_token()
    v = settings.view()
    assert v["db_dsn"] == {"secret": True, "set": True, "source": "store"}
    assert v["vm_agent_action_token"] == {"secret": True, "set": True, "source": "store"}
    assert v["frontend_deploy_ssh_user"]["value"] == "deploy"
    dumped = json.dumps(v)
    assert "hunter2" not in dumped and token not in dumped
    assert settings.view()["frontend_deploy_host"] == {"secret": False, "set": False, "source": "none", "value": ""}


@pytest.mark.parametrize("key,value", [
    ("frontend_deploy_host", "bad host!"), ("frontend_deploy_host", "a;b"), ("frontend_deploy_ssh_key", "relative/key"),
    ("db_dsn", "mysql://x"), ("frontend_deploy_ssh_user", "a b"), ("database_agent", "nohost"), ("nope", "x"),
])
def test_validation_rejects(key, value):
    with pytest.raises(PlatformUpdateError):
        settings.update({key: value})


@pytest.mark.parametrize("key,value", [
    ("frontend_deploy_host", "LOCAL"), ("frontend_deploy_host", "none"), ("frontend_deploy_host", "fe.example.org"),
    ("frontend_deploy_host", "192.168.1.9"), ("frontend_deploy_ssh_key", "/home/u/.ssh/id_ed25519"),
    ("db_dsn", "postgres://u:p@h:5432/db"), ("db_dsn", "postgresql://h/db"),
])
def test_validation_accepts(key, value):
    settings.update({key: value})
    assert settings.get(key) == (value.lower() if value.lower() in ("local", "none") else value)


# -- the resolver is what the consumers read ----------------------------------------------------------
def test_frontend_ssh_config_reads_the_store_then_the_given_env():
    settings.update({"frontend_deploy_host": "10.0.0.5", "frontend_deploy_ssh_user": "deploy",
                     "frontend_deploy_ssh_key": "/k/id"})
    cfg = frontend_ssh.config()
    assert (cfg["mode"], cfg["host"], cfg["user"], cfg["key"]) == ("ssh", "10.0.0.5", "deploy", "/k/id")
    settings.update({"frontend_deploy_host": "", "frontend_deploy_ssh_user": ""})
    cfg = frontend_ssh.config({"FRONTEND_DEPLOY_HOST": "local", "FRONTEND_DEPLOY_SSH_USER": "envu"})
    assert (cfg["mode"], cfg["user"]) == ("local", "envu")
    assert backup.Deps().frontend_cfg()["key"] == "/k/id"


def test_migrations_backend_uses_the_stored_dsn(monkeypatch):
    monkeypatch.setenv("PLATFORM_UPDATE_DB_URI", "postgresql://env/db")
    assert mig.PsycopgBackend().dsn == "postgresql://env/db"
    settings.update({"db_dsn": "postgresql://store/db"})
    b = mig.PsycopgBackend()
    assert b.dsn == "postgresql://store/db" and b.can_execute
    assert mig.PsycopgBackend("postgresql://explicit/db").dsn == "postgresql://explicit/db"


def test_db_backup_reads_agent_and_token_from_the_store():
    token = settings.generate_agent_token()
    settings.update({"database_agent": "10.0.0.2:9110"})
    calls = []
    deps = db_backup.Deps(env={}, http=lambda m, u, h, t: calls.append((m, u, h)) or (200, {}))
    assert db_backup.agent_answers(deps)[0] is True
    assert calls == [("GET", "http://10.0.0.2:9110/actions/db-backup", {"X-VM-Agent-Token": token})]


# -- token + command --------------------------------------------------------------------------------
def test_generated_token_is_64_hex_unique_and_not_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        a = settings.generate_agent_token()
        b = settings.generate_agent_token()
    assert re.fullmatch(r"[0-9a-f]{64}", a) and a != b
    assert settings.get("vm_agent_action_token") == b                      # regenerating replaces the token
    assert a not in caplog.text and b not in caplog.text


def test_setup_command_format():
    cmd = db_backup.setup_command("a" * 64, "/opt/virtualpytest/", "10.0.0.7")
    assert cmd == ("(umask 077; printf '%s' '" + "a" * 64 + "' > /root/vm_agent_token) && "
                   "/opt/virtualpytest/infra/vm_agent/install.sh --containers '<your existing --containers value>' "
                   "--allow 10.0.0.7 --action db-backup --action-token-file /root/vm_agent_token")
    assert "--allow <this server IP>" in db_backup.setup_command("a" * 64, "/p")


# -- routes ------------------------------------------------------------------------------------------
@pytest.fixture
def client():
    from tests.backend_server import _task42_services_common as common
    from backend_server.src.routes.server_platform_update_routes import server_platform_update_bp
    return lambda role="admin": common.make_app(server_platform_update_bp, role=role).test_client()


def test_routes_are_admin_only(client):
    for method, path in (("get", "/server/platform-update/settings"), ("put", "/server/platform-update/settings"),
                         ("post", "/server/platform-update/settings/db-backup/token"),
                         ("post", "/server/platform-update/settings/db-backup/check")):
        assert getattr(client("tester"), method)(path).status_code == 403


def test_put_get_validates_masks_and_clears(client):
    c = client()
    r = c.put("/server/platform-update/settings", json={"frontend_deploy_host": "fe.example.org", "db_dsn": "postgres://u:s3@h/d"})
    assert r.status_code == 200 and r.get_json()["settings"]["db_dsn"]["set"] is True
    body = c.get("/server/platform-update/settings").get_data(as_text=True)
    assert "s3@h" not in body and "fe.example.org" in body
    assert c.put("/server/platform-update/settings", json={"db_dsn": "mysql://x"}).status_code == 400
    assert c.put("/server/platform-update/settings", json={"frontend_deploy_ssh_key": "rel"}).status_code == 400
    assert c.put("/server/platform-update/settings", json={"db_dsn": ""}).get_json()["settings"]["db_dsn"]["set"] is False


def test_token_route_shows_the_token_once_in_the_command(client):
    c = client()
    c.put("/server/platform-update/settings", json={"database_agent": "127.0.0.1:9110"})
    body = c.post("/server/platform-update/settings/db-backup/token").get_json()
    token = settings.get("vm_agent_action_token")
    assert token in body["command"] and "--action db-backup" in body["command"] and "--allow 127.0.0.1" in body["command"]
    assert token not in json.dumps(body["settings"])
    assert token not in c.get("/server/platform-update/settings").get_data(as_text=True)


# -- TASK-128 G4: server SSH key ---------------------------------------------------------------------------------
@pytest.fixture
def ssh_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home / ".ssh" / "id_ed25519"


def test_ssh_key_routes_are_admin_only(client):
    for method in ("get", "post"):
        assert getattr(client("viewer"), method)("/server/platform-update/settings/ssh-key").status_code == 403


def test_ssh_key_created_once_never_overwritten_with_from_line(client, ssh_home):
    c = client()
    assert c.get("/server/platform-update/settings/ssh-key").get_json()["exists"] is False
    first = c.post("/server/platform-update/settings/ssh-key").get_json()
    assert first["created"] is True and first["exists"] is True and first["path"] == str(ssh_home)
    assert first["public_key"].startswith("ssh-ed25519 ")
    assert stat.S_IMODE(ssh_home.stat().st_mode) == 0o600 and stat.S_IMODE(ssh_home.parent.stat().st_mode) == 0o700
    line = first["authorized_keys_line"]
    assert line.startswith('from="') and 'no-agent-forwarding,no-X11-forwarding,no-port-forwarding ssh-ed25519 ' in line
    assert first["public_key"] in first["frontend_command"] and "adduser" in first["frontend_command"] \
        and "vpt-update-frontend" in first["frontend_command"]
    before = ssh_home.read_bytes()
    second = c.post("/server/platform-update/settings/ssh-key").get_json()
    assert second["created"] is False and second["public_key"] == first["public_key"] and ssh_home.read_bytes() == before
    assert c.get("/server/platform-update/settings/ssh-key").get_json()["public_key"] == first["public_key"]


def test_ssh_key_follows_the_configured_path_and_ssh_user(client, tmp_path):
    key = tmp_path / "k" / "fe_key"
    settings.update({"frontend_deploy_ssh_key": str(key), "frontend_deploy_ssh_user": "svc_deploy"})
    body = client().post("/server/platform-update/settings/ssh-key").get_json()
    assert key.exists() and body["path"] == str(key)
    assert "/home/svc_deploy/.ssh" in body["frontend_command"] and "s/^deploy /svc_deploy /" in body["frontend_command"]


def test_frontend_ssh_ko_row_carries_the_key_actions(ssh_home):
    from backend_server.src.lib.platform_update import prerequisites as pr, server_key
    server_key.create(server_key.key_path())
    settings.update({"frontend_deploy_host": "10.255.255.1", "frontend_deploy_ssh_user": "deploy"})

    def run(argv, timeout, env=None):
        return __import__("subprocess").CompletedProcess(argv, 255, "", "Permission denied")
    deps = pr.Deps(run=run, which=lambda n: "/usr/bin/" + n, hosts=lambda: [], env={})
    chk = pr.check_frontend_ssh(pr.Ctx("zip", "none", deps))
    assert chk["status"] == "ko" and chk["actions"][0]["machine"] == "frontend VM"
    assert "from=" in chk["actions"][0]["command"] and "visudo -cf" in chk["actions"][0]["command"]


# -- TASK-128 G13: set up the frontend VM with a one-time password -------------------------------------------------
PW = "S3cret-pw!x"
SETUP = "/server/platform-update/settings/frontend-setup"


@pytest.fixture
def setup_env(ssh_home, monkeypatch):
    import subprocess
    from backend_server.src.lib.platform_update import frontend_setup as fs
    calls = []

    def fake(argv, stdin, env, timeout):
        calls.append({"argv": argv, "stdin": stdin, "env": env})
        return subprocess.CompletedProcess(argv, fake.rc, "", fake.err)
    fake.rc, fake.err = 0, ""
    monkeypatch.setattr(fs, "_run", fake)
    monkeypatch.setattr(fs.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(fs.server_key, "server_ip", lambda a: "10.0.0.9")
    monkeypatch.setattr(fs.prerequisites, "check_frontend_ssh", lambda ctx: {"status": "ok", "detail": "login ok"})
    monkeypatch.setattr(fs, "run", (lambda orig: lambda *a, **k: orig(*a, run_cmd=fake, **k))(fs.run))
    return calls, fake


def _post(client, **over):
    body = {"host": "fe.example.org", "admin_user": "root", "password": PW, **over}
    return client().post(SETUP, json=body)


def test_frontend_setup_is_admin_only(client):
    assert client("viewer").post(SETUP, json={}).status_code == 403


def test_frontend_setup_password_never_in_argv_or_output(client, setup_env):
    calls, fake = setup_env
    fake.rc, fake.err = 1, f"sudo: bad {PW} attempt"
    r = _post(client, admin_user="ops")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and r.get_json()["ok"] is False
    assert PW not in body and "***" in body
    c = calls[0]
    assert all(PW not in a for a in c["argv"]) and c["argv"][:3] == ["sshpass", "-e", "ssh"]
    assert c["env"] == {"SSHPASS": PW} and c["stdin"].startswith(PW + "\n")
    assert "PubkeyAuthentication=no" in c["argv"] and "ops@fe.example.org" in c["argv"]
    assert settings.get("frontend_deploy_host") == ""     # a failed run saves nothing


def test_frontend_setup_success_saves_settings_and_runs_the_g4_command(client, setup_env):
    from backend_server.src.lib.platform_update import server_key
    calls, _ = setup_env
    body = _post(client).get_json()
    assert body["ok"] is True and [s["name"] for s in body["steps"]][-2:] == ["save settings", "check the SSH connection"]
    assert PW not in json.dumps(body)
    assert settings.get("frontend_deploy_host") == "fe.example.org" and settings.get("frontend_deploy_ssh_user") == "deploy"
    assert settings.get("frontend_deploy_ssh_key") == server_key.key_path()
    script = calls[0]["stdin"].split("\n", 1)[1]
    assert script == server_key.view()["frontend_command"]
    assert 'from="10.0.0.9"' in script and "visudo -cf" in script


def test_frontend_setup_validates_input(client, setup_env):
    for over in ({"host": "a;b"}, {"host": "local"}, {"host": ""}, {"admin_user": "ro ot"}, {"password": ""},
                 {"password": "a\nb"}):
        assert _post(client, **over).status_code == 400
    assert not setup_env[0]


def test_frontend_setup_409_when_running(client, setup_env):
    from backend_server.src.lib.platform_update import frontend_setup as fs
    assert fs._lock.acquire(blocking=False)
    try:
        assert _post(client).status_code == 409
    finally:
        fs._lock.release()


def test_frontend_setup_creates_the_missing_key_first(client, setup_env, ssh_home):
    assert not ssh_home.exists()
    steps = _post(client).get_json()["steps"]
    assert steps[0] == {"name": "server key", "ok": True, "detail": "created"} and ssh_home.exists()


def test_frontend_setup_unexpected_error_is_masked(client, setup_env, monkeypatch):
    from backend_server.src.lib.platform_update import frontend_setup as fs
    def boom(*a, **k):
        raise RuntimeError(f"leak {PW}")
    monkeypatch.setattr(fs, "run", boom)
    r = _post(client)
    assert r.status_code == 500 and PW not in r.get_data(as_text=True)
