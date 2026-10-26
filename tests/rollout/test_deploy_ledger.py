"""The deploy ledger must never record an empty commit or an empty version.

A ledger row with `commit=""` and `version=""` cannot be audited: there is nothing to
compare a running build against, and an empty string reads like "not recorded" instead of
"not resolved" (TASK-170: the row `labox-mobile` carried from a deploy on 2026-10-20 had
both empty).

The test runs the real `record_deploy_ledger` out of `update_core.sh` with a stub
`lease_cmd` that captures the arguments. Nothing leaves this machine: no host is touched,
no ledger service is called.
"""
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UC = PROJECT_ROOT / "setup" / "proxmox" / "node" / "update_core.sh"

pytestmark = pytest.mark.unit


def _function_text(name: str) -> str:
    """The bash function `name`, verbatim, out of the deploy script."""
    lines = UC.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    out = []
    for line in lines[start:]:
        out.append(line)
        if line.startswith("}"):
            break
    return "".join(out)


def _run_ledger(repo_dir: Path, capture: Path) -> list[str]:
    """Call record_deploy_ledger with a stub lease_cmd; return the captured arguments."""
    harness = textwrap.dedent(f"""
        LEDGER_CAPTURE="{capture}"
        export LEDGER_CAPTURE
        REPO_DIR="{repo_dir}"
        LEASE_ENV="node1-vpt"
        LEASE_REGISTRY_HOST=""
        DEPLOY_AGENT="test-agent"
        DEPLOY_T0=1700000000
        DEPLOY_OK_ROLE=()
        DEPLOY_FAIL_ROLE=()
        DEPLOY_SERVER=false
        DEPLOY_FRONTEND=false
        DEPLOY_HOSTS=true
        DEPLOY_HOSTS_WINDOWS=false
        SKIPPED_HOSTS=()
        DEFERRED_RESTARTS=()
        DOWN_SKIPPED=()
        PINNED_SKIPPED=()
        UNREACHABLE_SKIPPED=()
        HOST_RESTART_SKIPPED=()
        lease_cmd() {{ printf '%s\\n' "$@" >> "$LEDGER_CAPTURE"; }}
        {textwrap.indent(_function_text("record_deploy_ledger"), "        ")}
        record_deploy_ledger 0
    """)
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return capture.read_text(encoding="utf-8").splitlines()


def _value_of(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


@pytest.fixture
def capture(tmp_path) -> Path:
    return tmp_path / "ledger-args.txt"


def test_a_missing_repo_records_unknown_not_an_empty_string(tmp_path, capture):
    """No git repo and no VERSION.txt: the row says `unknown` and says why."""
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    args = _run_ledger(empty, capture)

    assert _value_of(args, "--commit") == "unknown"
    assert _value_of(args, "--version") == "unknown"
    note = _value_of(args, "--note")
    assert "commit unresolved" in note
    assert "version unresolved" in note
    # The point of the guard: never an empty string.
    assert _value_of(args, "--commit") != ""
    assert _value_of(args, "--version") != ""


def test_a_resolvable_repo_records_the_real_commit_and_version(tmp_path, capture):
    """The normal case is untouched: the real commit and the real version."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "VERSION.txt").write_text("current:main-2026.10.23-89754\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t",
         "add", "VERSION.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t",
         "commit", "-q", "-m", "x"],
        check=True,
    )
    expected = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    args = _run_ledger(repo, capture)

    assert _value_of(args, "--commit") == expected
    assert _value_of(args, "--version") == "main-2026.10.23-89754"
    # Nothing was unresolved, so there is no note to carry.
    assert "--note" not in args


def test_an_empty_version_file_records_unknown_with_the_reason(tmp_path, capture):
    """VERSION.txt present but its first line carries no version: `unknown`, and the reason."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "VERSION.txt").write_text("current:\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    args = _run_ledger(repo, capture)

    assert _value_of(args, "--version") == "unknown"
    assert "version unresolved" in _value_of(args, "--note")
    # The repo has no commit yet, so `git rev-parse HEAD` prints "HEAD" and fails. That
    # is not a sha: the row says `unknown` rather than recording "HEAD" as a commit.
    assert _value_of(args, "--commit") == "unknown"
    assert "commit unresolved" in _value_of(args, "--note")
