"""TASK-109 G3: the host endpoint that hands its .env files to the Platform update backup."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.src.lib.utils import env_backup  # noqa: E402


def test_collect_returns_only_the_listed_env_files(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / "backend_host" / "src").mkdir(parents=True)
    (tmp_path / "backend_host" / "src" / ".env").write_text("B=2\n")
    (tmp_path / "secrets.txt").write_text("nope")
    (tmp_path / "backend_server").mkdir()
    (tmp_path / "backend_server" / ".env").write_text("not a host file")
    got = {f["name"]: f["content"] for f in env_backup.collect(str(tmp_path))}
    assert got == {".env": "A=1\n", "backend_host/src/.env": "B=2\n"}


def test_collect_skips_missing_files(tmp_path):
    assert env_backup.collect(str(tmp_path)) == []


def test_the_route_returns_files_without_caching_and_the_listed_names_are_fixed(tmp_path, monkeypatch):
    from flask import Flask
    from backend_host.src.routes import host_system_routes as hr
    (tmp_path / ".env").write_text("K=v\n")
    monkeypatch.setattr(hr, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(hr, "_host_name", lambda: "h1")
    app = Flask(__name__)
    app.register_blueprint(hr.host_system_bp)
    r = app.test_client().get("/host/system/envFiles")
    body = r.get_json()
    assert r.status_code == 200 and body["success"] and body["host_name"] == "h1"
    assert body["files"] == [{"name": ".env", "content": "K=v\n"}]
    assert r.headers["Cache-Control"] == "no-store"
    # no parameter can select another file
    r = app.test_client().get("/host/system/envFiles?path=/etc/passwd&name=../x")
    assert r.get_json()["files"] == [{"name": ".env", "content": "K=v\n"}]


def test_the_endpoint_sits_behind_the_global_host_api_key_guard():
    """Every /host/* route except health and public media needs X-API-Key (backend_host/src/app.py)."""
    src = open(os.path.join(_repo_root, "backend_host", "src", "app.py"), encoding="utf-8").read()
    assert "request.path.startswith('/host/')" in src and "/host/system/envFiles" not in src  # not exempted


# -- TASK-128 G7: restoreEnvFile --------------------------------------------------------------------------------
def _host_app(tmp_path, monkeypatch):
    from flask import Flask
    from backend_host.src.routes import host_system_routes as hr
    monkeypatch.setattr(hr, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(hr, "_host_name", lambda: "h1")
    app = Flask(__name__)
    app.register_blueprint(hr.host_system_bp)
    return app.test_client()


def test_restore_writes_a_fixed_name_atomically_keeping_a_copy_and_the_mode(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OLD=1\n")
    os.chmod(tmp_path / ".env", 0o640)
    r = _host_app(tmp_path, monkeypatch).post("/host/system/restoreEnvFile", json={"name": ".env", "content": "NEW=2\n"})
    body = r.get_json()
    assert r.status_code == 200 and body["success"] and body["name"] == ".env" and r.headers["Cache-Control"] == "no-store"
    assert (tmp_path / ".env").read_text() == "NEW=2\n" and oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o640"
    copy = tmp_path / body["backup"]
    assert body["backup"].startswith(".env.bak-") and copy.read_text() == "OLD=1\n" and oct(copy.stat().st_mode & 0o777) == "0o640"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_restore_creates_a_missing_nested_file_0600_when_its_folder_exists(tmp_path, monkeypatch):
    (tmp_path / "backend_host" / "src").mkdir(parents=True)
    r = _host_app(tmp_path, monkeypatch).post("/host/system/restoreEnvFile", json={"name": "backend_host/src/.env", "content": "A=1\n"})
    path = tmp_path / "backend_host" / "src" / ".env"
    assert r.status_code == 200 and r.get_json()["backup"] == "" and path.read_text() == "A=1\n" and oct(path.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("body", [
    {"name": "../../etc/passwd", "content": "x"}, {"name": "backend_server/.env", "content": "x"}, {"name": "/etc/passwd", "content": "x"},
    {"name": ".env"}, {"name": ".env", "content": 5}, {"name": ".env", "content": "a\x00b"}, {"content": "x"}, {},
    {"name": ".env", "content": "x" * (256 * 1024 + 1)},
])
def test_restore_refuses_anything_but_a_fixed_name_with_text_content(tmp_path, monkeypatch, body):
    (tmp_path / ".env").write_text("OLD=1\n")
    r = _host_app(tmp_path, monkeypatch).post("/host/system/restoreEnvFile", json=body)
    assert r.status_code == 400 and r.get_json()["success"] is False
    assert (tmp_path / ".env").read_text() == "OLD=1\n" and not (tmp_path.parent / "etc").exists()


def test_restore_refuses_a_symlinked_env_and_the_endpoint_is_not_exempt_from_the_key_guard(tmp_path, monkeypatch):
    target = tmp_path / "real"
    target.write_text("R=1\n")
    os.symlink(target, tmp_path / ".env")
    r = _host_app(tmp_path, monkeypatch).post("/host/system/restoreEnvFile", json={"name": ".env", "content": "NEW=1\n"})
    assert r.status_code == 400 and target.read_text() == "R=1\n"
    src = open(os.path.join(_repo_root, "backend_host", "src", "app.py"), encoding="utf-8").read()
    assert "/host/system/restoreEnvFile" not in src
