"""TASK-128 G6: free disk space - newest five of each kind kept, dry run changes nothing, nothing outside the known folders."""
import os
import sys
import time

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import cleanup  # noqa: E402
from backend_server.src.lib.platform_update.runs import RunStore  # noqa: E402


def make(parent, names, size=100):
    """Create folders named ``names`` (oldest first) with a file of ``size`` bytes and rising mtimes."""
    parent.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        d = parent / name
        d.mkdir()
        (d / "f").write_bytes(b"x" * size)
        os.utime(d, (1_000_000 + i, 1_000_000 + i))


@pytest.fixture
def tree(tmp_path):
    state, root = tmp_path / "pu", tmp_path / "opt" / "virtualpytest"
    root.mkdir(parents=True)
    make(state / "backups", [f"2026100{i}-120000" for i in range(1, 9)])             # 8 backups
    make(state / "bundles", [f"run{i}" for i in range(7)])                           # 7 bundles
    make(root.parent, [f"virtualpytest.bak-2026100{i}-120000" for i in range(1, 7)])  # 6 trees
    make(root.parent, ["other-project", "virtualpytest.bak-notes"])                  # never touched
    return state, root


def names(group):
    return sorted(i["name"] for i in group)


def test_keeps_newest_five_of_each_kind_and_dry_run_deletes_nothing(tree):
    state, root = tree
    out = cleanup.run(state, str(root), dry_run=True)
    g = {x["kind"]: x for x in out["groups"]}
    assert names(g["backups"]["delete"]) == ["20261001-120000", "20261002-120000", "20261003-120000"]
    assert names(g["bundles"]["delete"]) == ["run0", "run1"]
    assert names(g["bak"]["delete"]) == ["virtualpytest.bak-20261001-120000"]
    assert len(g["backups"]["keep"]) == 5 and out["dry_run"] is True
    assert out["total_bytes"] > 0 and out["count"] == 6 and out["freed_bytes"] == 0
    assert (state / "backups" / "20261001-120000").exists()          # nothing was deleted


def test_real_run_deletes_the_listed_folders_and_reports_the_freed_bytes(tree):
    state, root = tree
    planned = cleanup.run(state, str(root), dry_run=True)["total_bytes"]
    out = cleanup.run(state, str(root), dry_run=False)
    assert out["freed_bytes"] == planned and out["deleted"] == 6 and out["errors"] == []
    assert not (state / "backups" / "20261001-120000").exists() and (state / "backups" / "20261004-120000").exists()
    assert not (state / "bundles" / "run0").exists() and (state / "bundles" / "run6").exists()
    assert not (root.parent / "virtualpytest.bak-20261001-120000").exists()
    assert (root.parent / "other-project").exists() and (root.parent / "virtualpytest.bak-notes").exists()
    assert root.exists()                                              # the live tree is never a candidate
    assert cleanup.run(state, str(root), dry_run=False)["deleted"] == 0     # idempotent


def test_symlinks_are_refused_and_their_target_survives(tree, tmp_path):
    state, root = tree
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("data")
    os.symlink(outside, state / "backups" / "20260901-000000")        # oldest by name, matches the pattern
    os.symlink(outside, root.parent / "virtualpytest.bak-20260901-000000")
    out = cleanup.run(state, str(root), dry_run=False)
    assert (outside / "keep.txt").read_text() == "data"
    refused = [(g["kind"], r["name"], r["reason"]) for g in out["groups"] for r in g["refused"]]
    assert ("backups", "20260901-000000", "symlink") in refused and ("bak", "virtualpytest.bak-20260901-000000", "symlink") in refused
    assert os.path.islink(state / "backups" / "20260901-000000")      # the link itself is left as it was


def test_a_folder_swapped_for_a_symlink_after_the_plan_is_not_followed(tree, tmp_path):
    state, root = tree
    plan = cleanup.plan(state, str(root))
    victim = plan["groups"][0]["delete"][0]
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x").write_text("1")
    import shutil
    shutil.rmtree(victim["path"])
    os.symlink(outside, victim["path"])
    assert cleanup._delete(victim, plan["groups"][0]["dir"]) == "is no longer a plain folder"
    assert (outside / "x").exists()


def test_a_missing_directory_is_an_empty_group_and_nothing_is_created(tmp_path):
    out = cleanup.run(tmp_path / "none", str(tmp_path / "opt" / "virtualpytest"), dry_run=False)
    assert out["count"] == 0 and out["freed_bytes"] == 0 and not (tmp_path / "none").exists()


def test_files_in_the_folders_are_never_listed(tmp_path):
    state, root = tmp_path / "pu", tmp_path / "opt" / "virtualpytest"
    make(state / "backups", [f"2026100{i}-120000" for i in range(1, 8)])
    (state / "backups" / "20260901-000000").write_text("a file, not a folder")
    out = cleanup.run(state, str(root), dry_run=False)
    assert (state / "backups" / "20260901-000000").exists() and out["deleted"] == 2


def test_busy_job_blocks_a_real_run_but_not_the_dry_run(tree):
    state, root = tree
    assert cleanup.run(state, str(root), dry_run=True, busy=lambda: True)["count"] == 6
    with pytest.raises(cleanup.Busy):
        cleanup.run(state, str(root), dry_run=False, busy=lambda: True)
    assert (state / "backups" / "20261001-120000").exists()


def test_the_bundle_of_the_active_run_is_kept_even_when_old(tree):
    state, root = tree
    out = cleanup.run(state, str(root), dry_run=False, protected_bundles={"run0"})
    assert (state / "bundles" / "run0").exists() and not (state / "bundles" / "run1").exists()
    assert out["deleted"] == 5


# -- the route ---------------------------------------------------------------------------------------
@pytest.fixture
def client(tree, monkeypatch):
    from tests.backend_server import _task42_services_common as common
    from backend_server.src.routes import server_platform_update_routes as r
    state, root = tree
    monkeypatch.setattr(r, "_store", lambda: RunStore(state))
    monkeypatch.setattr(r, "PROJECT_ROOT", str(root))
    return lambda role="admin": common.make_app(r.server_platform_update_bp, role=role).test_client()


def test_route_is_admin_only(client):
    assert client("tester").post("/server/platform-update/cleanup", json={}).status_code == 403
    assert client("viewer").post("/server/platform-update/cleanup", json={"dry_run": False}).status_code == 403


def test_route_defaults_to_a_dry_run_and_only_a_literal_false_deletes(client, tree):
    state, _ = tree
    for body in ({}, {"dry_run": True}, {"dry_run": "false"}, {"dry_run": 0}):
        r = client().post("/server/platform-update/cleanup", json=body)
        assert r.status_code == 200 and r.get_json()["dry_run"] is True
    assert (state / "backups" / "20261001-120000").exists()
    r = client().post("/server/platform-update/cleanup", json={"dry_run": False})
    body = r.get_json()
    assert body["success"] and body["dry_run"] is False and body["deleted"] == 6 and body["freed_bytes"] > 0
    assert not (state / "backups" / "20261001-120000").exists()


def test_route_answers_409_while_a_job_runs(client, monkeypatch):
    from backend_server.src.lib.platform_update import bundle_jobs
    monkeypatch.setattr(bundle_jobs, "is_running", lambda kind: kind == "deploy")
    assert client().post("/server/platform-update/cleanup", json={"dry_run": False}).status_code == 409
    assert client().post("/server/platform-update/cleanup", json={}).status_code == 200
