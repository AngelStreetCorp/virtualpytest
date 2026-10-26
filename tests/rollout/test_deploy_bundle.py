"""
deploy_bundle.sh (TASK-99 G5): runs the real script in a tmp HOME with a stub update_core.sh that
ships inside the bundle and records what it was called with. Every refusal must leave REPO_DIR
byte-for-byte as it was.
"""
import hashlib
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "setup" / "proxmox" / "node" / "deploy_bundle.sh"

pytestmark = pytest.mark.unit

STUB = """#!/usr/bin/env bash
echo "STUB ran in $REPO_DIR agent=${VPT_LEASE_AGENT:-none} args=$*" > "$STUB_OUT"
exit "${STUB_RC:-0}"
"""

needs_unzip = pytest.mark.skipif(shutil.which("unzip") is None, reason="unzip not installed")


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "stub.out"
    return {"HOME": str(home), "PATH": os.environ["PATH"], "REPO_DIR": str(home / "virtualpytest"),
            "STUB_OUT": str(out), "VPT_LEASE_AGENT": "agent-7"}


def make_tree(root: Path, manifest=True, with_git=False, stub=True):
    top = root / "virtualpytest"
    (top / "setup/proxmox/node").mkdir(parents=True)
    if manifest:
        (top / "BUNDLE_MANIFEST.txt").write_text("bundle: vpt-test\nversion: v1\n")
    if stub:
        (top / "setup/proxmox/node/update_core.sh").write_text(STUB)
    (top / "marker.txt").write_text("new\n")
    if with_git:
        (top / ".git").mkdir()
        (top / ".git/HEAD").write_text("x")
    return top


def pack(tmp_path, kind="zip", sums=True, **tree_kw):
    src = tmp_path / f"src-{kind}"
    shutil.rmtree(src, ignore_errors=True)
    src.mkdir()
    make_tree(src, **tree_kw)
    arc = tmp_path / ("bundle." + ("zip" if kind == "zip" else "tar.gz"))
    if kind == "zip":
        with zipfile.ZipFile(arc, "w") as z:
            for f in sorted(src.rglob("*")):
                z.write(f, f.relative_to(src))
    else:
        with tarfile.open(arc, "w:gz") as t:
            t.add(src / "virtualpytest", arcname="virtualpytest")
    if sums:
        Path(str(arc) + ".sha256").write_text(f"{hashlib.sha256(arc.read_bytes()).hexdigest()}  {arc.name}\n")
    return arc


def run(env, *args, extra=None):
    return subprocess.run(["bash", str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          env={**env, **(extra or {})}, timeout=60)


def snapshot(path):
    return sorted((str(p.relative_to(path)), p.read_bytes() if p.is_file() else b"") for p in Path(path).rglob("*"))


def old_install(env, git=False):
    d = Path(env["REPO_DIR"])
    d.mkdir()
    (d / "marker.txt").write_text("old\n")
    if git:
        (d / ".git").mkdir()
    return d


def test_script_is_valid_bash():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


@pytest.mark.parametrize("kind", ["tar", pytest.param("zip", marks=needs_unzip)])
def test_deploys_backs_up_and_runs_update_core_with_the_lease_agent(tmp_path, env, kind):
    old = old_install(env)
    arc = pack(tmp_path, kind)
    r = run(env, arc, "--server", "--frontend")
    assert r.returncode == 0, r.stderr + r.stdout
    assert (old / "marker.txt").read_text() == "new\n"                       # the bundle is in place
    backups = list(old.parent.glob("virtualpytest.bak-*"))
    assert len(backups) == 1 and (backups[0] / "marker.txt").read_text() == "old\n"
    assert not list(old.parent.glob("virtualpytest.incoming.*"))
    assert "STUB ran in" in Path(env["STUB_OUT"]).read_text()
    out = Path(env["STUB_OUT"]).read_text()
    assert f"in {old} agent=agent-7 args=--server --frontend" in out
    assert "sha256 ok" in r.stdout and "version: v1" in r.stdout            # the manifest is shown


def test_a_fresh_machine_has_nothing_to_back_up(tmp_path, env):
    r = run(env, pack(tmp_path, "tar"))
    assert r.returncode == 0, r.stderr
    assert not list(Path(env["HOME"]).glob("virtualpytest.bak-*"))
    assert (Path(env["REPO_DIR"]) / "BUNDLE_MANIFEST.txt").is_file()


def test_the_node_update_core_is_preferred_and_keeps_its_exit_status(tmp_path, env):
    old_install(env)
    (Path(env["HOME"]) / "update_core.sh").write_text(
        '#!/bin/bash\necho "NODE copy $*" > "$STUB_OUT"\nexit 7\n')
    r = run(env, pack(tmp_path, "tar"), "feat/x")
    assert r.returncode == 7
    assert Path(env["STUB_OUT"]).read_text().startswith("NODE copy feat/x")


def test_missing_checksum_file_stops_before_touching_repo_dir(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    r = run(env, pack(tmp_path, "tar", sums=False))
    assert r.returncode != 0 and "no checksum file" in r.stderr
    assert snapshot(old) == before and not list(old.parent.glob("virtualpytest.*"))
    assert not Path(env["STUB_OUT"]).exists()


def test_wrong_checksum_stops_before_touching_repo_dir(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    arc = pack(tmp_path, "tar")
    Path(str(arc) + ".sha256").write_text("0" * 64 + f"  {arc.name}\n")
    r = run(env, arc)
    assert r.returncode != 0 and "sha256 mismatch" in r.stderr
    assert snapshot(old) == before and not Path(env["STUB_OUT"]).exists()


def test_a_tampered_archive_is_caught_by_the_original_checksum(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    arc = pack(tmp_path, "tar")
    with open(arc, "ab") as f:
        f.write(b"tamper")
    r = run(env, arc)
    assert r.returncode != 0 and "sha256 mismatch" in r.stderr
    assert snapshot(old) == before


def test_a_git_checkout_is_refused_without_replace_checkout(tmp_path, env):
    old = old_install(env, git=True)
    before = snapshot(old)
    r = run(env, pack(tmp_path, "tar"))
    assert r.returncode != 0 and "--replace-checkout" in r.stderr
    assert snapshot(old) == before and not Path(env["STUB_OUT"]).exists()
    r = run(env, pack(tmp_path, "tar"), "--replace-checkout")
    assert r.returncode == 0, r.stderr
    assert (old / "marker.txt").read_text() == "new\n" and not (old / ".git").exists()
    assert (list(old.parent.glob("virtualpytest.bak-*"))[0] / ".git").is_dir()      # the checkout is kept


def test_an_archive_without_a_manifest_is_refused(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    r = run(env, pack(tmp_path, "tar", manifest=False))
    assert r.returncode != 0 and "BUNDLE_MANIFEST.txt" in r.stderr
    assert snapshot(old) == before and not list(old.parent.glob("virtualpytest.*"))


def test_an_archive_carrying_git_is_refused(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    r = run(env, pack(tmp_path, "tar", with_git=True))
    assert r.returncode != 0 and ".git" in r.stderr
    assert snapshot(old) == before


def test_a_tar_with_a_path_escape_is_refused_before_extraction(tmp_path, env):
    old = old_install(env)
    before = snapshot(old)
    src = tmp_path / "evil"
    make_tree(src)
    (src / "x.txt").write_text("x")
    arc = tmp_path / "evil.tar.gz"
    with tarfile.open(arc, "w:gz") as t:
        t.add(src / "virtualpytest", arcname="virtualpytest")
        t.add(src / "x.txt", arcname="virtualpytest/../escaped.txt")
    Path(str(arc) + ".sha256").write_text(hashlib.sha256(arc.read_bytes()).hexdigest() + "  evil.tar.gz\n")
    r = run(env, arc)
    assert r.returncode != 0 and "'..'" in r.stderr
    assert snapshot(old) == before and not (tmp_path / "home" / "escaped.txt").exists()


def test_missing_archive_and_unknown_extension(tmp_path, env):
    assert run(env, tmp_path / "nope.zip").returncode != 0
    odd = tmp_path / "bundle.rar"
    odd.write_text("x")
    Path(str(odd) + ".sha256").write_text(hashlib.sha256(b"x").hexdigest() + "  bundle.rar\n")
    r = run(env, odd)
    assert r.returncode != 0 and "unsupported archive" in r.stderr


def test_no_arguments_prints_usage(env):
    r = run(env)
    assert r.returncode != 0 and "Usage:" in r.stderr
