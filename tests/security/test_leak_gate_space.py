"""E71 — the leak gate must not park its scratch in the platform trash.

`scripts/security/leak_gate.sh --all` exports the whole tracked tree into a scratch directory
and scans that copy, so that gitleaks sees exactly the files git has (see the script's own
comment: `--no-git` walks the filesystem and does not honour .gitignore, so scanning a working
checkout also scans the developer's real .env and frontend/dist).

The scratch used to be removed with plain `rm`. On the platform an agent's `rm` is a
recoverable-delete shim: it RELOCATES the target into the platform trash instead of unlinking
it. So the gate did not clean up after itself — it parked a full copy of the repository
(212 MB measured) in the trash on every `--all` run, and one per-branch scan over 26 branches
parked 5.55 GB. The fleet refuses all new work at 90 % disk, so the leak ate the headroom.

The harness below reproduces that with a **trash double**: an executable `rm` placed first on
PATH that moves its targets into a fake trash directory instead of unlinking them. A fixed gate
must (1) leave no export tree behind and (2) hand the fake trash nothing.

Run against the pre-fix script the same harness fails, which is the point:

    git show a6b40721ea:scripts/security/leak_gate.sh > /tmp/pre/leak_gate.sh
    LEAK_GATE_SCRIPT=/tmp/pre/leak_gate.sh python3 -m pytest tests/security/test_leak_gate_space.py -q

`LEAK_GATE_SCRIPT` selects the script under test; it defaults to the one in this repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = Path(os.environ.get("LEAK_GATE_SCRIPT") or REPO_ROOT / "scripts/security/leak_gate.sh")

# The commit whose leak_gate.sh is the pre-fix script (the base of fix/e71-leak-gate-export-space).
PREFIX_COMMIT = "a6b40721ea"

# A trash-style `rm`: it MOVES its targets into a fake trash instead of unlinking them. This is
# what the platform's recoverable-delete shim does on an agent's PATH.
TRASH_DOUBLE = r"""#!/usr/bin/env bash
set -u
TRASH="${FAKE_TRASH:?FAKE_TRASH must be set}"
LOG="${FAKE_TRASH_LOG:?FAKE_TRASH_LOG must be set}"
mkdir -p "$TRASH"
for arg in "$@"; do
  case "$arg" in -*) continue ;; esac
  target="$arg"
  [ -e "$target" ] || [ -L "$target" ] || continue
  base="$(basename "$target")"
  dest="$TRASH/$base"
  n=1
  while [ -e "$dest" ]; do dest="$TRASH/$base.$n"; n=$((n+1)); done
  mv "$target" "$dest"
  printf '%s\n' "$target" >> "$LOG"
done
exit 0
"""

# A plain `rm`, for the "the double is not on PATH" case. It unlinks, like a normal rm, so the
# test itself never parks anything in the platform trash.
PLAIN_RM = r"""#!/usr/bin/env bash
exec /bin/rm "$@"
"""

# A gitleaks stand-in: it records the --source it was pointed at (that is the export tree) and
# writes an empty report, so the secrets half of the gate runs without gitleaks installed.
GITLEAKS_STUB = r"""#!/usr/bin/env bash
set -u
source_dir=""
report=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--source" ]; then source_dir="$arg"; fi
  if [ "$prev" = "--report-path" ]; then report="$arg"; fi
  prev="$arg"
done
if [ -n "${GITLEAKS_STUB_LOG:-}" ]; then printf '%s\n' "$source_dir" >> "$GITLEAKS_STUB_LOG"; fi
if [ -n "$report" ]; then printf '[]' > "$report"; fi
exit 0
"""


@dataclass
class GateRun:
    """What one gate run left behind."""

    returncode: int
    stdout: str
    export_dir: str = ""
    moved: list = field(default_factory=list)   # paths the double was asked to relocate
    trash: list = field(default_factory=list)   # what ended up in the fake trash
    tmp_left: list = field(default_factory=list)  # what survived in TMPDIR


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _make_fixture_repo(path: Path) -> None:
    """A tiny git repo: one commit, a couple of tracked files, nothing sensitive."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("# fixture repo\n\nNothing sensitive here.\n")
    (path / "app.py").write_text("def main():\n    return 0\n")
    (path / ".gitleaks.toml").write_text("[extend]\nuseDefault = true\n")
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    for cmd in (
        ["git", "init", "-q", str(path)],
        ["git", "-C", str(path), "config", "user.email", "gate-fixture@example.invalid"],
        ["git", "-C", str(path), "config", "user.name", "Gate Fixture"],
        ["git", "-C", str(path), "config", "commit.gpgsign", "false"],
        ["git", "-C", str(path), "add", "-A"],
        ["git", "-C", str(path), "commit", "-qm", "fixture"],
    ):
        subprocess.run(cmd, check=True, env=env, capture_output=True)


def run_gate_all(scratch: Path, repo: Path, *, trash_double: bool, script: Path = None) -> GateRun:
    """Run `leak_gate.sh --all` in `repo` with a controlled PATH and TMPDIR."""
    script = Path(script or GATE_SCRIPT)
    bindir = scratch / "bin"
    trash = scratch / "trash"
    tmpdir = scratch / "tmp"
    moved_log = scratch / "moved.log"
    stub_log = scratch / "gitleaks-source.log"
    for d in (bindir, trash, tmpdir):
        d.mkdir(parents=True, exist_ok=True)
    for f in (moved_log, stub_log):
        f.touch()

    _write_exec(bindir / "rm", TRASH_DOUBLE if trash_double else PLAIN_RM)
    _write_exec(bindir / "gitleaks", GITLEAKS_STUB)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["TMPDIR"] = str(tmpdir)
    env["FAKE_TRASH"] = str(trash)
    env["FAKE_TRASH_LOG"] = str(moved_log)
    env["GITLEAKS_STUB_LOG"] = str(stub_log)
    env["NO_COLOR"] = "1"
    env.pop("LEAK_TERMS", None)
    env.pop("LEAK_TERMS_FILE", None)

    proc = subprocess.run(
        ["/bin/bash", str(script), "--all"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    sources = [line for line in stub_log.read_text().splitlines() if line.strip()]
    moved = [line for line in moved_log.read_text().splitlines() if line.strip()]
    return GateRun(
        returncode=proc.returncode,
        stdout=proc.stdout + proc.stderr,
        export_dir=sources[-1] if sources else "",
        moved=moved,
        trash=sorted(p.name for p in trash.iterdir()),
        tmp_left=sorted(p.name for p in tmpdir.iterdir()),
    )


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    return tmp_path / "scratch"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    _make_fixture_repo(path)
    return path


def assert_no_residue(run: GateRun, run_label: str) -> None:
    """The behavioural assertions: nothing survived, and nothing was relocated."""
    assert run.export_dir, (
        f"{run_label}: the gate never exported a tree, so this run proves nothing. "
        f"Output was:\n{run.stdout}"
    )
    leaked = [p for p in run.moved if p == run.export_dir or p.startswith(run.export_dir + "/")]
    assert not leaked, (
        f"{run_label}: the gate's scratch was RELOCATED instead of being freed. "
        f"{len(leaked)} path(s) under the export tree {run.export_dir} were moved into the "
        f"platform trash rather than unlinked: {leaked[:5]}"
    )
    assert not run.trash, (
        f"{run_label}: the platform trash received {len(run.trash)} item(s) that this run "
        f"created and should have freed: {run.trash[:5]}"
    )
    assert not run.tmp_left, (
        f"{run_label}: the gate left {len(run.tmp_left)} scratch path(s) in TMPDIR: {run.tmp_left[:5]}"
    )
    assert not Path(run.export_dir).exists(), (
        f"{run_label}: the export tree {run.export_dir} still exists after the run"
    )


def test_all_mode_frees_its_scratch_with_a_trash_double_on_path(scratch: Path, repo: Path) -> None:
    """The decisive case: `rm` on PATH relocates into a trash. The gate must still free itself."""
    run = run_gate_all(scratch, repo, trash_double=True)
    assert run.returncode == 0, f"the gate failed on a clean tree:\n{run.stdout}"
    assert "secrets: clean" in run.stdout, f"the verdict changed:\n{run.stdout}"
    assert_no_residue(run, "trash double on PATH")


def test_all_mode_frees_its_scratch_with_a_plain_rm_on_path(scratch: Path, repo: Path) -> None:
    """The normal case: the double is NOT on PATH. The gate must still free itself."""
    run = run_gate_all(scratch, repo, trash_double=False)
    assert run.returncode == 0, f"the gate failed on a clean tree:\n{run.stdout}"
    assert "secrets: clean" in run.stdout, f"the verdict changed:\n{run.stdout}"
    assert_no_residue(run, "plain rm on PATH")


def test_range_and_staged_modes_are_untouched(scratch: Path, repo: Path) -> None:
    """R3: the modes that do not export a tree keep working exactly as before."""
    bindir = scratch / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    _write_exec(bindir / "gitleaks", GITLEAKS_STUB)
    # A plain `rm` for this one too: when the suite is pointed at the PRE-FIX script, that
    # script cleans up with `rm`, and a trash-style rm on PATH would park the gate's own
    # scratch in the platform trash -- the bug this branch fixes, reproduced by the control
    # run itself. A plain rm unlinks, so the control never litters.
    _write_exec(bindir / "rm", PLAIN_RM)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["NO_COLOR"] = "1"
    env["GITLEAKS_STUB_LOG"] = str(scratch / "gitleaks-source.log")
    (scratch / "gitleaks-source.log").touch()

    proc = subprocess.run(
        ["/bin/bash", str(GATE_SCRIPT), "--staged"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"--staged failed:\n{proc.stdout}{proc.stderr}"
    assert "Leak gate passed" in proc.stdout
    # --staged must not export a tree at all.
    assert not (scratch / "gitleaks-source.log").read_text().strip(), (
        "--staged exported a tree; it never used to"
    )


def test_planted_secret_is_still_found_with_a_repo_relative_path(scratch: Path, repo: Path) -> None:
    """R2: the verdict must not change — a planted secret is found, counted and repo-relative."""
    if shutil.which("gitleaks") is None:
        pytest.skip("gitleaks is not installed on this machine")

    gitleaks = shutil.which("gitleaks")
    bindir = scratch / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    tmpdir = scratch / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    # A plain `rm`, for the same reason as in the staged test: the control run against the
    # pre-fix script must not park the gate's scratch in the platform trash.
    _write_exec(bindir / "rm", PLAIN_RM)
    # The real gitleaks, and a real .gitleaks.toml from the repository.
    shutil.copy2(REPO_ROOT / ".gitleaks.toml", repo / ".gitleaks.toml")

    # Assembled at run time so this fixture never contains a credential-shaped literal itself
    # (the same house pattern scripts/release/publish_public.sh uses for its selftest). The
    # names matter: gitleaks' generic-api-key rule keys on the variable name, so `key_secret =`
    # here would make the gate flag its own test file.
    k_id = "AKIA" + "IOSFODNN7FIXTURE"
    k_sec = "wJalrXUtnFEMI/K7MDENG" + "/bPxRfiCYzxLPQMKEY1"
    (repo / "planted.py").write_text(
        f'AWS_SECRET_ACCESS_KEY = "{k_sec}"\naws_access_key_id = "{k_id}"\n'
    )
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["TMPDIR"] = str(tmpdir)
    env["NO_COLOR"] = "1"
    env.pop("LEAK_TERMS", None)
    env.pop("LEAK_TERMS_FILE", None)
    env["GITLEAKS_STUB_LOG"] = str(scratch / "gitleaks-source.log")
    (scratch / "gitleaks-source.log").touch()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "planted"], check=True, capture_output=True)

    proc = subprocess.run(
        ["/bin/bash", str(GATE_SCRIPT), "--all"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"the gate did not fail on a planted secret:\n{out}"
    assert "secrets:" in out and "finding(s)" in out, f"the finding count changed:\n{out}"
    # The path must be repo-relative: the export prefix is stripped before printing.
    finding_lines = [line for line in out.splitlines() if "planted.py:" in line]
    assert finding_lines, f"no finding line for the planted secret:\n{out}"
    for line in finding_lines:
        assert str(tmpdir) not in line, f"the finding still carries the export prefix:\n{line}"
        # The rule id gitleaks reports may change; what must not change is that the finding
        # names the repo-relative path a human can open.
        assert "planted.py:" in line, f"the finding is not reported with a repo-relative path:\n{line}"


def test_the_pre_fix_script_fails_this_harness(scratch: Path, repo: Path, tmp_path: Path) -> None:
    """The negative control, in the suite: the pre-fix script leaks, and the harness sees it.

    This is what makes the other tests meaningful — a harness that cannot fail is worthless.
    """
    pre = tmp_path / "pre" / "leak_gate.sh"
    pre.parent.mkdir(parents=True, exist_ok=True)
    got = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{PREFIX_COMMIT}:scripts/security/leak_gate.sh"],
        capture_output=True,
        text=True,
    )
    if got.returncode != 0:
        pytest.skip(f"{PREFIX_COMMIT} is not available in this clone")
    pre.write_text(got.stdout)
    pre.chmod(0o755)

    run = run_gate_all(scratch, repo, trash_double=True, script=pre)
    assert run.export_dir, f"the pre-fix run never exported a tree:\n{run.stdout}"
    leaked = [p for p in run.moved if p == run.export_dir or p.startswith(run.export_dir + "/")]
    assert leaked, (
        "the pre-fix script did not relocate its scratch, so this harness cannot detect the "
        f"leak it is supposed to detect. Output was:\n{run.stdout}"
    )


def main() -> int:
    """Allow the control to be run as a script: exit non-zero when the harness holds."""
    return pytest.main([__file__, "-q"])


if __name__ == "__main__":
    sys.exit(main())
