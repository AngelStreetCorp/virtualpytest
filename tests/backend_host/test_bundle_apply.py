"""TASK-101 G3/G4: host applyBundle + updatePrereqs. Real temp dirs and a real rsync; download and sudo mocked."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.src.lib.utils import bundle_apply as ba  # noqa: E402
from shared.src.lib.utils import bundle_archive as arc  # noqa: E402

needs_rsync = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
SERVER = "https://vpt.example.org"
URL = "/server/platform-update/bundle/run1/archive"


class FakeResp:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.headers = status, data, {"Content-Length": str(len(data))}

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._data), 7):
            yield self._data[i:i + 7]

    def close(self):
        pass


def make_zip(path, files, extra=None):
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return open(path, "rb").read()


GOOD = {
    "virtualpytest/BUNDLE_MANIFEST.txt": "bundle",
    "virtualpytest/VERSION.txt": "9.9.9\n",
    "virtualpytest/app.py": "print('new')\n",
    "virtualpytest/.env": "FROM_BUNDLE=1\n",
}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "opt" / "virtualpytest"
    r.mkdir(parents=True)
    (r / ".env").write_text("SECRET=keep\n")
    (r / "VERSION.txt").write_text("1.0.0\n")
    (r / "stale.py").write_text("old")
    (r / "venv").mkdir()
    (r / "venv" / "keep.txt").write_text("v")
    (r / "backend_host" / "config" / "user_data").mkdir(parents=True)
    (r / "backend_host" / "config" / "user_data" / "profile").write_text("local")
    return r


def backup_fn(target, backup_root, reason):
    bid = "b1"
    dest = os.path.join(backup_root, bid)
    shutil.copytree(target, dest)
    return dest, {"backup_id": bid}


def run_real_rsync_fake_sudo(sudo_rc=0):
    calls = []

    def run(cmd, timeout):
        calls.append(cmd)
        if cmd[0] == "rsync":
            return subprocess.run(cmd, capture_output=True, text=True)
        return subprocess.CompletedProcess(cmd, sudo_rc, "", "sudo: a password is required" if sudo_rc else "")
    run.calls = calls
    return run


def apply(root, tmp_path, data, sha=None, url=URL, run=None, restart=None, max_bytes=ba.MAX_BUNDLE_BYTES):
    restarts = []
    result = ba.apply_bundle(
        project_root=str(root), backup_root=str(tmp_path / "backups"), url=url,
        sha256=sha or hashlib.sha256(data).hexdigest(), host_name="h1", server_url=SERVER,
        headers={"X-API-Key": "k"}, backup_fn=backup_fn, prune_fn=lambda *_: None,
        restart_fn=restart or (lambda: restarts.append(1)), work_root=str(tmp_path),
        get=lambda u, **kw: FakeResp(data), run=run or run_real_rsync_fake_sudo(), max_bytes=max_bytes,
    )
    result["_restarts"] = restarts
    return result


def phases(result):
    return [(json.loads(l.split("VPT_PROGRESS ", 1)[1])["phase"], json.loads(l.split("VPT_PROGRESS ", 1)[1])["state"])
            for l in result["progress"]]


@needs_rsync
def test_apply_syncs_keeps_local_state_backs_up_and_restarts(root, tmp_path):
    data = make_zip(tmp_path / "b.zip", GOOD)
    res = apply(root, tmp_path, data)
    assert res["success"], res
    assert (root / "app.py").read_text() == "print('new')\n"
    assert (root / "VERSION.txt").read_text() == "9.9.9\n"
    assert not (root / "stale.py").exists()
    assert (root / ".env").read_text() == "SECRET=keep\n"            # never overwritten
    assert (root / "venv" / "keep.txt").exists()
    assert (root / "backend_host/config/user_data/profile").read_text() == "local"
    assert (tmp_path / "backups" / "b1" / "stale.py").exists()        # the backup holds the old tree
    assert res["backup_id"] == "b1" and res["version_before"] == "1.0.0" and res["version_after"] == "9.9.9"
    assert phases(res) == [("rsync", "start"), ("rsync", "ok"), ("install", "start"), ("install", "ok"),
                           ("restart", "start"), ("restart", "ok"), ("health", "skipped")]
    assert res["_restarts"] == [1]
    assert not [p for p in os.listdir(tmp_path) if p.startswith("vpt-bundle-")]   # workdir cleaned


@needs_rsync
def test_progress_lines_parse_with_the_task99_parser(root, tmp_path):
    sys.path.insert(0, os.path.join(_repo_root, "setup", "proxmox", "node", "lib"))
    import deploy_progress
    res = apply(root, tmp_path, make_zip(tmp_path / "b.zip", GOOD))
    card = deploy_progress.parse(res["progress"])["hosts"][0]
    assert card["host"] == "h1" and card["state"] == "ok"
    assert set(card["phases"]) == {"rsync", "install", "restart", "health"}


@needs_rsync
def test_reconcile_failure_is_a_warning_not_a_failure(root, tmp_path):
    res = apply(root, tmp_path, make_zip(tmp_path / "b.zip", GOOD), run=run_real_rsync_fake_sudo(sudo_rc=1))
    assert res["success"] and res["warnings"] and ("install", "failed") in phases(res)
    assert res["_restarts"] == [1]


def test_sha_mismatch_touches_nothing(root, tmp_path):
    data = make_zip(tmp_path / "b.zip", GOOD)
    res = apply(root, tmp_path, data, sha="0" * 64)
    assert not res["success"] and "sha256 mismatch" in res["error"]
    assert (root / "stale.py").exists() and (root / "VERSION.txt").read_text() == "1.0.0\n"
    assert not (tmp_path / "backups").exists() and res["_restarts"] == []
    assert phases(res)[-1] == ("rsync", "failed")


@pytest.mark.parametrize("bad", ["../evil.py", "/abs/evil.py", "virtualpytest/../../evil.py", "virtualpytest\\x.py"])
def test_zip_path_traversal_rejected(root, tmp_path, bad):
    data = make_zip(tmp_path / "b.zip", GOOD, extra={bad: "x"})
    res = apply(root, tmp_path, data)
    assert not res["success"] and "unsafe path" in res["error"]
    assert (root / "stale.py").exists() and not (tmp_path.parent / "evil.py").exists()


def test_tar_with_absolute_path_and_outside_link_rejected(root, tmp_path):
    for kind in ("abs", "link"):
        path = tmp_path / f"{kind}.tar.gz"
        with tarfile.open(path, "w:gz") as tf:
            for name, body in GOOD.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tf.addfile(info, io.BytesIO(body.encode()))
            if kind == "abs":
                info = tarfile.TarInfo("/etc/evil")
                tf.addfile(info, io.BytesIO(b""))
            else:
                info = tarfile.TarInfo("virtualpytest/link")
                info.type, info.linkname = tarfile.SYMTYPE, "../../../etc/passwd"
                tf.addfile(info)
        res = apply(root, tmp_path, path.read_bytes())
        assert not res["success"], kind
        assert (root / "stale.py").exists()


@pytest.mark.parametrize("files,msg", [
    ({"virtualpytest/app.py": "x"}, "BUNDLE_MANIFEST"),
    ({**GOOD, "virtualpytest/.git/config": "x"}, ".git"),
    ({**GOOD, "other/x": "x"}, "top level"),
])
def test_not_a_bundle_rejected(root, tmp_path, files, msg):
    res = apply(root, tmp_path, make_zip(tmp_path / "b.zip", files))
    assert not res["success"] and msg in res["error"]
    assert (root / "stale.py").exists()


def test_download_other_origin_refused_and_key_not_sent(root, tmp_path):
    sent = []
    res = ba.apply_bundle(
        project_root=str(root), backup_root=str(tmp_path / "b"), url="https://evil.example.com/x", sha256="a" * 64,
        host_name="h1", server_url=SERVER, headers={"X-API-Key": "k"}, backup_fn=backup_fn, prune_fn=lambda *_: None,
        restart_fn=lambda: None, get=lambda *a, **k: sent.append(1))
    assert not res["success"] and "not on this host" in res["error"] and sent == []


def test_download_http_error_and_size_cap(root, tmp_path):
    res = ba.apply_bundle(
        project_root=str(root), backup_root=str(tmp_path / "b"), url=URL, sha256="a" * 64, host_name="h1",
        server_url=SERVER, headers={}, backup_fn=backup_fn, prune_fn=lambda *_: None, restart_fn=lambda: None,
        get=lambda *a, **k: FakeResp(b"", 401))
    assert "HTTP 401" in res["error"]
    data = make_zip(tmp_path / "b.zip", GOOD)
    res = apply(root, tmp_path, data, max_bytes=10)
    assert not res["success"] and "larger than" in res["error"]


def test_backup_failure_stops_before_sync(root, tmp_path):
    data = make_zip(tmp_path / "b.zip", GOOD)

    def boom(*a):
        raise RuntimeError("disk full")
    res = ba.apply_bundle(
        project_root=str(root), backup_root=str(tmp_path / "b"), url=URL, sha256=hashlib.sha256(data).hexdigest(),
        host_name="h1", server_url=SERVER, headers={}, backup_fn=boom, prune_fn=lambda *_: None,
        restart_fn=lambda: None, work_root=str(tmp_path), get=lambda *a, **k: FakeResp(data))
    assert not res["success"] and "backup failed" in res["error"]
    assert (root / "stale.py").exists()


def test_bad_sha_format_rejected(root, tmp_path):
    res = apply(root, tmp_path, b"x", sha="nothex")
    assert not res["success"] and "64 hex" in res["error"]


# -- updatePrereqs -------------------------------------------------------------------------------
def ping_get(ok=True, status=200):
    body = "vpt-update-ping"

    class R:
        status_code = status

        def json(self):
            return {"success": True, "body": body, "sha256": hashlib.sha256(body.encode()).hexdigest() if ok else "0" * 64}
    return lambda url, **kw: R()


def check(tmp_path, run, get=None, which=lambda n: "/usr/bin/" + n):
    (tmp_path / "root").mkdir(exist_ok=True)
    (tmp_path / "root" / "VERSION.txt").write_text("2.0\n")
    return ba.self_check(project_root=str(tmp_path / "root"), backup_root=str(tmp_path / "bk"), host_name="h1",
                         server_url=SERVER, headers={}, get=get or ping_get(), run=run, which=which)


def fake_run(sudo_ok=True, du="1024 x"):
    def run(cmd, timeout):
        if cmd[0] == "du":
            return subprocess.CompletedProcess(cmd, 0, du, "")
        if cmd[:3] == ["sudo", "-n", "-l"]:
            return subprocess.CompletedProcess(cmd, 0 if sudo_ok else 1, "", "" if sudo_ok else "sudo: a password is required\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def test_self_check_all_ok(tmp_path):
    out = check(tmp_path, fake_run())
    assert out["ok"] and out["version"] == "2.0" and out["supports_apply_bundle"]
    assert out["sudo"]["ok"] and out["download"]["ok"] and out["tools"]["ok"] and out["disk"]["ok"]


def test_self_check_reports_each_failure(tmp_path):
    out = check(tmp_path, fake_run(sudo_ok=False), get=ping_get(ok=False), which=lambda n: None if n == "rsync" else "/x")
    assert not out["ok"]
    assert out["tools"]["missing"] == ["rsync"]
    assert "password" in out["sudo"]["restart"]["detail"]
    assert not out["download"]["ok"]
    out = check(tmp_path, fake_run(), get=ping_get(status=401))
    assert "HTTP 401" in out["download"]["detail"]


def test_self_check_disk_low(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "_free", lambda p: 10)
    assert not check(tmp_path, fake_run())["disk"]["ok"]


def test_resolve_url():
    assert ba.resolve_download_url("/a/b", "https://s.x/") == "https://s.x/a/b"
    assert ba.resolve_download_url("https://s.x/a", "https://s.x") == "https://s.x/a"
    with pytest.raises(ba.ApplyError):
        ba.resolve_download_url("//evil.com/a", "https://s.x")
    with pytest.raises(ba.ApplyError):
        ba.resolve_download_url("http://s.x/a", "https://s.x")


# -- TASK-128 G12: rollbackBundle ---------------------------------------------------------------------
def meta_backup_fn(counter=[0]):
    """Like the host's snapshot: a copy of the tree + the meta file with the reason. Ids look like the real ones."""
    def fn(target, backup_root, reason):
        counter[0] += 1
        bid = f"20261018_10000{counter[0]}_000001"
        dest = os.path.join(backup_root, bid)
        shutil.copytree(target, dest, ignore=shutil.ignore_patterns(".env", "venv"))
        with open(os.path.join(dest, ba.BACKUP_META_FILENAME), "w") as fh:
            json.dump({"backup_id": bid, "reason": reason}, fh)
        return dest, {"backup_id": bid}
    return fn


def rollback(root, tmp_path, backup_id, run=None, restart=None):
    restarts = []
    result = ba.rollback_bundle(
        project_root=str(root), backup_root=str(tmp_path / "backups"), backup_id=backup_id, host_name="h1",
        backup_fn=meta_backup_fn(), restart_fn=restart or (lambda: restarts.append(1)),
        run=run or run_real_rsync_fake_sudo())
    result["_restarts"] = restarts
    return result


@needs_rsync
def test_rollback_restores_the_pre_update_tree_keeps_env_and_local_state(root, tmp_path):
    data = make_zip(tmp_path / "b.zip", GOOD)
    restarts = []
    applied = ba.apply_bundle(
        project_root=str(root), backup_root=str(tmp_path / "backups"), url=URL, sha256=hashlib.sha256(data).hexdigest(),
        host_name="h1", server_url=SERVER, headers={}, backup_fn=meta_backup_fn(), prune_fn=lambda *_: None,
        restart_fn=lambda: restarts.append(1), work_root=str(tmp_path), get=lambda u, **kw: FakeResp(data),
        run=run_real_rsync_fake_sudo())
    assert applied["success"] and (root / "VERSION.txt").read_text() == "9.9.9\n"
    (root / ".env").write_text("SECRET=changed-after\n")
    res = rollback(root, tmp_path, applied["backup_id"])
    assert res["success"], res
    assert (root / "VERSION.txt").read_text() == "1.0.0\n" and (root / "stale.py").read_text() == "old"
    assert not (root / "app.py").exists()                                   # the new file is gone
    assert (root / ".env").read_text() == "SECRET=changed-after\n"         # .env never touched
    assert (root / "venv" / "keep.txt").exists() and (root / "backend_host/config/user_data/profile").read_text() == "local"
    assert res["version_before"] == "9.9.9" and res["version_after"] == "1.0.0" and res["_restarts"] == [1]
    assert res["pre_rollback_backup_id"] != applied["backup_id"]           # the new tree is saved first: the roll back can be undone
    assert [json.loads(l.split("VPT_PROGRESS ", 1)[1])["state"] for l in res["progress"]] == ["ok"]


@pytest.mark.parametrize("bad", ["../etc", "b1", "20261018_100001_000001/../x", "", "/var/tmp/x"])
def test_rollback_only_takes_a_backup_id_under_the_backup_root(root, tmp_path, bad):
    (tmp_path / "backups").mkdir()
    res = rollback(root, tmp_path, bad)
    assert not res["success"] and res["_restarts"] == [] and (root / "stale.py").exists()


def test_rollback_refuses_a_backup_that_is_not_a_pre_update_one(root, tmp_path):
    fn = meta_backup_fn()
    _dest, meta = fn(str(root), str(tmp_path / "backups"), "baseline")
    res = rollback(root, tmp_path, meta["backup_id"])
    assert not res["success"] and "not a pre-update backup" in res["error"] and res["_restarts"] == []


@needs_rsync
def test_rollback_changes_nothing_when_the_snapshot_fails(root, tmp_path):
    _dest, meta = meta_backup_fn()(str(root), str(tmp_path / "backups"), "pre_bundle")
    (root / "VERSION.txt").write_text("9.9.9\n")

    def broken(*_a):
        raise OSError("disk full")
    res = ba.rollback_bundle(project_root=str(root), backup_root=str(tmp_path / "backups"), backup_id=meta["backup_id"],
                             host_name="h1", backup_fn=broken, restart_fn=lambda: None, run=run_real_rsync_fake_sudo())
    assert not res["success"] and "nothing was changed" in res["error"] and (root / "VERSION.txt").read_text() == "9.9.9\n"
