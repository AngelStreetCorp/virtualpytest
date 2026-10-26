"""The installer must not push an OLDER script onto a node because the checkout is behind.

`install_update_core.py` reads the script from the checkout it runs in. A checkout that is
behind origin/main holds the OLD script, so installing from it rolls the node BACK - undoing
the fixes main already carries, on the very node the fixes are for. That is the same failure
the installer exists to prevent (BUG-0728), coming from the other side: the node is behind
the repo while the installer says "installed" (2026-10-25: a checkout 113 commits behind would
have reinstalled the script that was missing the mirror fix and the stale-service report).

So the installer compares the local copy with origin/main's copy of the same file and refuses
to install the stale one. Work in progress - a branch with its own changes to the script - is
not stale and installs as it is.
"""
import importlib.util
import os
import subprocess

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
INSTALLER = os.path.join(REPO_ROOT, "setup", "proxmox", "node", "install_update_core.py")
SCRIPT_REL = os.path.join("setup", "proxmox", "node", "update_core.sh")


def _load_installer():
    spec = importlib.util.spec_from_file_location("install_update_core_stale", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer():
    if not os.path.exists(INSTALLER):
        pytest.skip(f"{INSTALLER} is not in this checkout")
    return _load_installer()


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=False
    )


def _make_repo(tmp_path, script_text):
    """A git checkout with one commit holding the deploy script."""
    repo = tmp_path / "repo"
    (repo / "setup" / "proxmox" / "node").mkdir(parents=True)
    script = repo / SCRIPT_REL
    script.write_text(script_text, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    return repo, script


def _publish_main(repo, script_text):
    """origin/main gets a newer version of the script than the checkout has."""
    script = repo / SCRIPT_REL
    script.write_text(script_text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "newer script")
    # origin/main is the commit that is not on this branch.
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "branch", "other", head)
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    return script


# The scripts below carry deploy logic AFTER the config block: the drift check compares the
# logic, not the fleet targets, so a fixture that is nothing but config would never drift.
OLD_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "\n"
    "SERVER_IP=\"${SERVER_IP:-192.0.2.10}\"\n"
    "\n"
    "deploy_logic() {\n"
    "  echo OLD_LOGIC\n"
    "}\n"
)
NEW_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "\n"
    "SERVER_IP=\"${SERVER_IP:-192.0.2.10}\"\n"
    "\n"
    "deploy_logic() {\n"
    "  echo NEW_LOGIC\n"
    "}\n"
)
BRANCH_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "\n"
    "SERVER_IP=\"${SERVER_IP:-192.0.2.10}\"\n"
    "\n"
    "deploy_logic() {\n"
    "  echo BRANCH_LOGIC\n"
    "}\n"
)
LOCAL_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "\n"
    "SERVER_IP=\"${SERVER_IP:-192.0.2.10}\"\n"
    "\n"
    "deploy_logic() {\n"
    "  echo LOCAL_LOGIC\n"
    "}\n"
)


def test_a_checkout_behind_origin_main_is_stale(installer, tmp_path):
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    local_text = script.read_text(encoding="utf-8")
    stale, why, origin_text = installer.local_is_stale(str(script), local_text)

    assert stale, "a checkout that misses origin/main's commit for the file is stale"
    assert "commit" in why
    assert origin_text == NEW_SCRIPT


def test_a_checkout_that_is_origin_main_is_not_stale(installer, tmp_path):
    repo, script = _make_repo(tmp_path, NEW_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    local_text = script.read_text(encoding="utf-8")
    stale, why, _ = installer.local_is_stale(str(script), local_text)

    assert not stale, why


def test_work_in_progress_is_not_stale(installer, tmp_path):
    """A branch with its own changes to the script installs as it is."""
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)
    # The branch changes the script itself and commits it.
    script.write_text(BRANCH_SCRIPT, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "branch change")

    local_text = script.read_text(encoding="utf-8")
    stale, why, _ = installer.local_is_stale(str(script), local_text)

    assert not stale, why


def test_uncommitted_changes_are_not_stale(installer, tmp_path):
    """An edit in the working tree is the operator's intent, not a stale checkout."""
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)
    script.write_text(LOCAL_SCRIPT, encoding="utf-8")

    local_text = script.read_text(encoding="utf-8")
    stale, why, _ = installer.local_is_stale(str(script), local_text)

    assert not stale, why


def test_a_file_outside_a_checkout_is_not_stale(installer, tmp_path):
    """Without a git checkout there is nothing to compare against: install as it is."""
    script = tmp_path / "update_core.sh"
    script.write_text(OLD_SCRIPT, encoding="utf-8")

    stale, why, origin_text = installer.local_is_stale(str(script), OLD_SCRIPT)

    assert not stale, why
    assert origin_text is None


def test_the_installer_refuses_to_install_a_stale_script(installer, tmp_path, monkeypatch, capsys):
    """--install must not roll the node back to an older script."""
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    installed = []

    def fake_install(node, remote_path, content):
        installed.append(content)
        return "BACKUP=/tmp/bak"

    monkeypatch.setattr(installer, "read_remote", lambda node, path: OLD_SCRIPT)
    monkeypatch.setattr(installer, "install_remote", fake_install)

    code = installer.main([
        "--node", "fake-node",
        "--install",
        "--repo-script", str(script),
    ])

    assert code == 1, "a stale install must be refused"
    assert installed == [], "nothing may be written to the node"
    err = capsys.readouterr().err
    assert "STALE" in err
    assert "--force" in err, "the refusal must say how to override it"


def test_force_installs_a_stale_script(installer, tmp_path, monkeypatch):
    """--force is the deliberate override: it installs the stale copy."""
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    installed = []

    def fake_install(node, remote_path, content):
        installed.append(content)
        return "BACKUP=/tmp/bak"

    monkeypatch.setattr(installer, "read_remote", lambda node, path: OLD_SCRIPT)
    monkeypatch.setattr(installer, "install_remote", fake_install)

    code = installer.main([
        "--node", "fake-node",
        "--install",
        "--force",
        "--repo-script", str(script),
    ])

    assert code == 0
    assert len(installed) == 1
    assert "OLD_LOGIC" in installed[0], "the forced install writes the stale local copy"


def test_check_compares_the_node_against_origin_main(installer, tmp_path, monkeypatch, capsys):
    """--check must judge the node against main's script, not against the stale local copy."""
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    # The node already has main's script: it is in sync with the repo.
    monkeypatch.setattr(installer, "read_remote", lambda node, path: NEW_SCRIPT)

    code = installer.main([
        "--node", "fake-node",
        "--check",
        "--repo-script", str(script),
    ])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "STALE" in out, "the check must say the local copy is stale"
    assert "in sync" in out


def test_check_reports_drift_when_the_node_differs_from_origin_main(installer, tmp_path, monkeypatch, capsys):
    repo, script = _make_repo(tmp_path, OLD_SCRIPT)
    _publish_main(repo, NEW_SCRIPT)

    # The node still has the OLD script: it does not have main's.
    monkeypatch.setattr(installer, "read_remote", lambda node, path: OLD_SCRIPT)

    code = installer.main([
        "--node", "fake-node",
        "--check",
        "--repo-script", str(script),
    ])

    out = capsys.readouterr().out
    assert code == 1, out
    assert "drift found" in out
