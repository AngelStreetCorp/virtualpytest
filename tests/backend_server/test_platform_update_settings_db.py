"""TASK-128 G9: Platform update settings in the database (per server), the file fallback, the one-time import,
the resolver order and the GitHub token. The Supabase client is mocked."""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import bundle_jobs, settings  # noqa: E402
from shared.src.lib.database import platform_update_settings_db as db  # noqa: E402
from shared.src.lib.utils import git_auth  # noqa: E402

TOKEN = "ghp_" + "a" * 36


class FakeTable:
    """Just enough of the supabase query builder: select/eq/upsert/delete on one table."""

    def __init__(self, store, missing=False):
        self.store, self.missing, self.filters, self.op, self.payload = store, missing, {}, None, None

    def _boom(self):
        if self.missing:
            raise Exception("{'code': 'PGRST205', 'message': \"Could not find the table 'public.platform_update_settings'\"}")

    def select(self, _cols):
        self.op = "select"
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.payload = "upsert", rows
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        self._boom()
        if self.op == "select":
            return type("R", (), {"data": [dict(r) for r in self.store.values() if r["server_name"] == self.filters["server_name"]]})()
        if self.op == "upsert":
            for r in self.payload:
                self.store[(r["server_name"], r["key"])] = r
        if self.op == "delete":
            self.store.pop((self.filters["server_name"], self.filters["key"]), None)
        return type("R", (), {"data": []})()


class FakeClient:
    def __init__(self, missing=False):
        self.rows, self.missing = {}, missing

    def table(self, name):
        assert name == "platform_update_settings"
        return FakeTable(self.rows, self.missing)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VPT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("SERVER_NAME", "srv-a")
    for var in ("FRONTEND_DEPLOY_HOST", "VPT_GITHUB_TOKEN", "GITHUB_TOKEN", "PLATFORM_UPDATE_DB_URI", "SUPABASE_DB_URI", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    fake = FakeClient()
    monkeypatch.setattr(db, "get_supabase", lambda: fake)
    settings._forget()
    yield fake
    settings._forget()


def _file(tmp_path):
    return tmp_path / "platform-update" / "settings.json"


# -- DB module CRUD ---------------------------------------------------------------------------------
def test_db_save_load_delete_are_scoped_to_the_server_name(client):
    db.save("srv-a", {"frontend_deploy_host": "10.0.0.5", "github_token": TOKEN}, settings.SECRET_KEYS, "me")
    db.save("srv-b", {"frontend_deploy_host": "other"}, settings.SECRET_KEYS)
    assert db.load("srv-a") == {"frontend_deploy_host": "10.0.0.5", "github_token": TOKEN}
    assert client.rows[("srv-a", "github_token")]["is_secret"] is True
    assert client.rows[("srv-a", "frontend_deploy_host")]["is_secret"] is False
    db.save("srv-a", {"frontend_deploy_host": ""}, settings.SECRET_KEYS)
    assert db.load("srv-a") == {"github_token": TOKEN} and db.load("srv-b") == {"frontend_deploy_host": "other"}


def test_missing_table_and_missing_client_raise_table_missing(monkeypatch):
    monkeypatch.setattr(db, "get_supabase", lambda: FakeClient(missing=True))
    with pytest.raises(db.TableMissing):
        db.load("srv-a")
    with pytest.raises(db.TableMissing):
        db.save("srv-a", {"db_dsn": "x"}, settings.SECRET_KEYS)
    monkeypatch.setattr(db, "get_supabase", lambda: None)
    with pytest.raises(db.TableMissing):
        db.load("srv-a")


# -- settings on top of the DB ----------------------------------------------------------------------
def test_server_name_comes_from_server_name_env(monkeypatch):
    monkeypatch.setenv("SERVER_NAME", " srv-a ")
    assert settings.server_name() == "srv-a"
    monkeypatch.delenv("SERVER_NAME")
    assert settings.server_name() == "default"


def test_update_writes_to_the_db_and_the_resolver_reads_it(client, tmp_path):
    assert settings.storage() == "db"
    settings.update({"frontend_deploy_host": "local"})
    assert client.rows[("srv-a", "frontend_deploy_host")]["value"] == "local"
    assert settings.get("frontend_deploy_host") == "local" and settings.source("frontend_deploy_host") == "store"
    assert not _file(tmp_path).exists()
    settings.update({"frontend_deploy_host": ""})
    assert ("srv-a", "frontend_deploy_host") not in client.rows


def test_resolver_order_is_db_then_env(client, monkeypatch):
    monkeypatch.setenv("FRONTEND_DEPLOY_HOST", "from-env")
    assert settings.get("frontend_deploy_host") == "from-env" and settings.source("frontend_deploy_host") == "env"
    settings.update({"frontend_deploy_host": "from-db"})
    assert settings.get("frontend_deploy_host") == "from-db"


def test_table_missing_falls_back_to_the_file_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("VPT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(db, "get_supabase", lambda: FakeClient(missing=True))
    settings._forget()
    assert settings.storage() == "file"
    settings.update({"frontend_deploy_host": "10.0.0.9"})
    assert json.loads(_file(tmp_path).read_text()) == {"frontend_deploy_host": "10.0.0.9"}
    assert settings.get("frontend_deploy_host") == "10.0.0.9"


def test_first_db_write_imports_the_file_once_and_renames_it(client, tmp_path):
    _file(tmp_path).parent.mkdir(parents=True)
    _file(tmp_path).write_text(json.dumps({"frontend_deploy_host": "old-host", "frontend_deploy_ssh_user": "deploy"}))
    settings.update({"frontend_deploy_host": "new-host"})
    assert not _file(tmp_path).exists()
    assert json.loads((_file(tmp_path).parent / "settings.json.imported").read_text())["frontend_deploy_host"] == "old-host"
    assert client.rows[("srv-a", "frontend_deploy_ssh_user")]["value"] == "deploy"      # imported
    assert client.rows[("srv-a", "frontend_deploy_host")]["value"] == "new-host"        # the new value wins
    settings.update({"frontend_deploy_ssh_user": "ops"})                                 # no second import
    assert client.rows[("srv-a", "frontend_deploy_ssh_user")]["value"] == "ops"


def test_the_db_row_wins_over_a_stale_file_on_import(client, tmp_path):
    db.save("srv-a", {"frontend_deploy_ssh_user": "from-db"}, settings.SECRET_KEYS)
    settings._forget()
    _file(tmp_path).parent.mkdir(parents=True)
    _file(tmp_path).write_text(json.dumps({"frontend_deploy_ssh_user": "from-file"}))
    settings.update({"frontend_deploy_host": "local"})
    assert client.rows[("srv-a", "frontend_deploy_ssh_user")]["value"] == "from-db"


def test_view_reports_secrets_as_set_only(client):
    settings.update({"github_token": TOKEN})
    v = settings.view()["github_token"]
    assert v == {"secret": True, "set": True, "source": "store"} and TOKEN not in json.dumps(settings.view())


# -- GitHub token -----------------------------------------------------------------------------------
def test_github_token_is_validated(client):
    with pytest.raises(settings.PlatformUpdateError):
        settings.update({"github_token": "has space and is short"})


def test_saved_github_token_wins_over_the_env_in_git_auth_and_bundle_jobs(client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "e" * 36)
    assert git_auth.github_token() == "ghp_" + "e" * 36
    settings.update({"github_token": TOKEN})
    assert git_auth.github_token() == TOKEN and bundle_jobs.github_token() == TOKEN
    assert git_auth.github_token({"GITHUB_TOKEN": "explicit"}) == "explicit"   # an explicit env is still honoured as given
    settings.update({"github_token": ""})
    assert git_auth.github_token() == "ghp_" + "e" * 36
