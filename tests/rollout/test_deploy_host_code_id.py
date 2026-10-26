"""The host code id must describe the tree the deploy PUSHES, not the one it had before the pull.

`compute_host_code_id` hashes the host-code tree (`backend_host/`, `shared/`, `features/`,
`requirements.txt`) at HEAD. The deploy compares that id with the marker on the host
(`~/.vpt_host_code_id`) to decide whether `vpt-host` has to be restarted.

Computed BEFORE the git pull, the id described the tree of the PREVIOUS deploy, and the marker
was written the same way - so the check compared "the deploy before last" with "the one before
it". A deploy that changed host code then pushed the new code but did NOT restart `vpt-host`,
and the host kept running the previous code until something else restarted it (2026-10-20,
TASK-146: the browser port/profile fix was on the host but the service still ran the old code).
"""
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEPLOY_SCRIPT = os.path.join(REPO_ROOT, "setup", "proxmox", "node", "update_core.sh")


@pytest.fixture(scope="module")
def deploy_script_text():
    if not os.path.exists(DEPLOY_SCRIPT):
        pytest.skip(f"{DEPLOY_SCRIPT} is not in this checkout")
    with open(DEPLOY_SCRIPT, "r", encoding="utf-8") as handle:
        return handle.read()


def _extract_function(script_text: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", script_text, re.S | re.M)
    assert match, f"{name}() not found in the deploy script"
    return match.group(0)


def _git(repo: str, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _make_repo(tmp_path) -> str:
    """A repo with the host-code paths, one commit per version of the host code."""
    repo = str(tmp_path / "repo")
    os.makedirs(os.path.join(repo, "backend_host", "src"), exist_ok=True)
    os.makedirs(os.path.join(repo, "shared", "src"), exist_ok=True)
    os.makedirs(os.path.join(repo, "features"), exist_ok=True)
    with open(os.path.join(repo, "backend_host", "src", "a.py"), "w", encoding="utf-8") as handle:
        handle.write("print('v1')\n")
    with open(os.path.join(repo, "shared", "src", "b.py"), "w", encoding="utf-8") as handle:
        handle.write("print('v1')\n")
    with open(os.path.join(repo, "features", "f.txt"), "w", encoding="utf-8") as handle:
        handle.write("v1\n")
    with open(os.path.join(repo, "requirements.txt"), "w", encoding="utf-8") as handle:
        handle.write("requests\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v1")
    return repo


def _compute_id(repo: str, script_text: str) -> str:
    """Run the deploy script's own compute_host_code_id against a repo."""
    script = f"""
set -u
REPO_DIR="{repo}"
HOST_CODE_PATHS=(backend_host shared features requirements.txt)
HOST_CODE_IGNORE=$'\\tshared/src/lib/game(2048)?/'
HOST_CODE_ID=""
{_extract_function(script_text, "compute_host_code_id")}
compute_host_code_id
printf '%s' "$HOST_CODE_ID"
"""
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_the_code_id_changes_when_the_host_code_changes(tmp_path, deploy_script_text):
    repo = _make_repo(tmp_path)
    before = _compute_id(repo, deploy_script_text)

    with open(os.path.join(repo, "shared", "src", "b.py"), "w", encoding="utf-8") as handle:
        handle.write("print('v2')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v2")

    assert _compute_id(repo, deploy_script_text) != before


def test_the_id_is_computed_after_the_git_pull(deploy_script_text):
    """The id must describe the tree that is pushed, so it is computed after the pull.

    Before the fix the call sat above the pull: the id described the previous deploy's tree,
    the marker matched it, and a deploy that changed host code pushed new code without
    restarting vpt-host.
    """
    pull = deploy_script_text.find('git reset --hard "origin/')
    assert pull > 0, "the git pull is not in the deploy script"
    compute = deploy_script_text.find("\ncompute_host_code_id\n", pull)
    assert compute > pull, (
        "compute_host_code_id is called before the git pull: the id would describe the "
        "previous deploy's tree and vpt-host would not restart for a host-code change"
    )


def test_a_deploy_that_changes_the_host_code_restarts_the_service(tmp_path, deploy_script_text):
    """The marker of the previous deploy against the tree being pushed: they must differ.

    This is the decision the deploy makes per host (`seen == id` -> skip the restart).
    """
    repo = _make_repo(tmp_path)
    marker = _compute_id(repo, deploy_script_text)  # what the previous deploy wrote

    # The deploy pulls a commit that changes the host code.
    with open(os.path.join(repo, "backend_host", "src", "a.py"), "w", encoding="utf-8") as handle:
        handle.write("print('v2')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v2")

    assert _compute_id(repo, deploy_script_text) != marker, (
        "the id of the tree being pushed equals the marker of the last restart: "
        "vpt-host would keep running the previous code"
    )


def test_a_deploy_that_does_not_change_the_host_code_keeps_the_service(tmp_path, deploy_script_text):
    """Only a docs/scripts change: the host code is the same, the service stays up."""
    repo = _make_repo(tmp_path)
    marker = _compute_id(repo, deploy_script_text)

    os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
    with open(os.path.join(repo, "docs", "note.md"), "w", encoding="utf-8") as handle:
        handle.write("docs only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs only")

    assert _compute_id(repo, deploy_script_text) == marker
