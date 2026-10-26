"""BUG-0903: the CI runner retention must never delete the workspace of a running job.

Run them with:

    timeout 300 python3 -m pytest tests/test_ci_runner_retention.py -q

Nothing here touches a runner VM, the network, a device or a database: every
case builds a temporary tree that mimics
``~/runners/<name>/{_work,_diag,bin.2.338.0}`` and runs the script against it.

The negative control is the point of this file. The old guard matched
``<runner>/bin/Runner.Worker`` while the runner really runs
``<runner>/bin.2.338.0/Runner.Worker``, so it never matched and every runner
looked idle: the cleanup then deleted the workspace of the job that was
running. ``test_old_guard_pattern_would_not_have_seen_the_worker`` asserts that
the old pattern still misses the live worker, so these tests fail on the
pre-fix tree instead of passing on it.

The file also covers the run lock: the daily pass and the 15-minute check are
two different systemd units, so the lock file is what keeps them from walking
the same workspaces at the same time.
"""
from __future__ import annotations

import fcntl
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "setup" / "proxmox" / "vm" / "runner" / "ci-runner-retention.sh"
RUNNER_DIR = SCRIPT.parent

# The units are shipped as templates and rendered into /etc/systemd/system by
# install_runner.sh. A file whose name ends in .service/.timer/.socket is
# classified as a systemd unit by the merge policy and can never reach main, so
# the repo carries the .tmpl files and the installer writes the real unit names.
UNIT_TEMPLATES = (
    "ci-runner-retention.service.tmpl",
    "ci-runner-retention.timer.tmpl",
    "ci-runner-retention-check.service.tmpl",
    "ci-runner-retention-check.timer.tmpl",
)
# The unit names the templates have to render to on the runner VM.
UNIT_NAMES = (
    "ci-runner-retention.service",
    "ci-runner-retention.timer",
    "ci-runner-retention-check.service",
    "ci-runner-retention-check.timer",
)

# The real path of the worker binary on a runner VM.
WORKER_VERSION = "2.338.0"


# --- fixtures ---------------------------------------------------------------


def make_runner(root: Path, name: str = "vpt-1") -> Path:
    """A runner directory that mimics the layout of a real one."""
    runner = root / name
    (runner / "_work").mkdir(parents=True, exist_ok=True)
    (runner / "_diag").mkdir(parents=True, exist_ok=True)
    (runner / f"bin.{WORKER_VERSION}").mkdir(parents=True, exist_ok=True)
    return runner


def make_workspace(runner: Path, repo: str, age_days: int, checkout_fresh: bool = False) -> Path:
    """A workspace tree, the way a checkout leaves it.

    ``age_days`` is the age of the tree and of the checkout inside it. With
    ``checkout_fresh`` the checkout is young while the tree is old: that is the
    case the top-level directory mtime gets wrong.
    """
    tree = runner / "_work" / repo
    checkout = tree / repo / ".git"
    (checkout / "logs").mkdir(parents=True, exist_ok=True)
    (checkout / "FETCH_HEAD").write_text("ref\n")
    (checkout / "index").write_text("index\n")
    (checkout / "logs" / "HEAD").write_text("log\n")

    stamp = time.gmtime(time.time() - age_days * 86400)
    (runner / "_diag" / f"Worker_{time.strftime('%Y%m%d-%H%M%S', stamp)}-utc.log").write_text("log\n")

    old = time.time() - age_days * 86400
    # Every entry of the tree carries the age of the job - the directories
    # included: a directory that was created now says the tree is in use.
    for path in tree.rglob("*"):
        os.utime(path, (old, old))
    os.utime(tree, (old, old))

    if checkout_fresh:
        # The job checked out again: its checkout is seconds old, while the
        # tree itself is still days old.
        fresh = time.time()
        for path in (checkout / "FETCH_HEAD", checkout / "index"):
            os.utime(path, (fresh, fresh))
    return tree


def spawn_versioned_worker(runner: Path) -> subprocess.Popen:
    """A live process whose command line looks like the real versioned worker."""
    binary = runner / f"bin.{WORKER_VERSION}" / "Runner.Worker"
    binary.write_text("#!/bin/sh\nexec sleep 300\n")
    binary.chmod(0o755)
    cmdline = f"{binary} spawnclient 157 160"
    return subprocess.Popen(["bash", "-c", 'exec -a "$0" sleep 300', cmdline])


def spawn_holder(path: Path) -> subprocess.Popen:
    """A live process whose working directory is the given path."""
    return subprocess.Popen(["sleep", "300"], cwd=str(path))


@pytest.fixture
def runner(tmp_path: Path) -> Path:
    root = tmp_path / "runners"
    root.mkdir()
    return make_runner(root)


@pytest.fixture
def live_worker():
    """A live versioned worker, killed at the end of the test."""
    started = []

    def _start(runner_dir: Path) -> subprocess.Popen:
        proc = spawn_versioned_worker(runner_dir)
        started.append(proc)
        return proc

    yield _start

    for proc in started:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# --- helpers ----------------------------------------------------------------


def run_retention(
    runners_root: Path, *args: str, lock_path: Path | None = None
) -> subprocess.CompletedProcess:
    # The hard pass is off unless a case asks for it: how full the disk of the
    # machine running the tests is must not decide what the script does.
    cmd = [
        "bash",
        str(SCRIPT),
        "--runners-root",
        str(runners_root),
        "--hard-threshold",
        "100",
        *args,
    ]
    # The script takes a lock (/run/ci-runner-retention.lock on a runner VM).
    # The tests point it at a file of their own, so no case ever touches the
    # real one and no case waits for another case's lock.
    if lock_path is None:
        lock_path = runners_root.parent / "ci-runner-retention.lock"
    env = dict(os.environ)
    env["CI_RETENTION_LOCK_FILE"] = str(lock_path)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)


def guard_exit_code(runner_dir: Path) -> int:
    """Exit code of the script's own guard: 0 means the runner is busy."""
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; runner_busy "$1"', "bash", str(runner_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode


def old_pattern_matches(runner_dir: Path) -> bool:
    """What the pre-fix guard did: pgrep -f "<runner>/bin/Runner.Worker"."""
    result = subprocess.run(
        ["pgrep", "-f", f"{runner_dir}/bin/Runner.Worker"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


# --- the guard ---------------------------------------------------------------


def test_the_guard_reports_the_versioned_worker_as_busy(runner: Path, live_worker):
    """The guard must match bin.<version>/Runner.Worker, the path the runner uses."""
    live_worker(runner)
    assert guard_exit_code(runner) == 0, "the guard did not see the live worker"


def test_old_guard_pattern_would_not_have_seen_the_worker(runner: Path, live_worker):
    """The negative control: the old pattern still misses the live worker.

    This is what makes the suite fail on the pre-fix tree: the old guard looked
    for <runner>/bin/Runner.Worker, a path the versioned worker never uses, so
    every runner looked idle.
    """
    live_worker(runner)
    assert old_pattern_matches(runner) is False, (
        "the old pattern matched the live worker: this control no longer proves anything"
    )


def test_an_idle_runner_is_not_busy(runner: Path):
    assert guard_exit_code(runner) != 0


def test_the_check_busy_helper_reports_the_versioned_worker(runner: Path, live_worker):
    live_worker(runner)
    result = subprocess.run(
        ["bash", str(SCRIPT), "--check-busy", str(runner)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "busy" in result.stdout


# --- the age predicate -------------------------------------------------------


def test_a_workspace_with_a_fresh_checkout_is_kept(runner: Path):
    """The tree is old, the job is young: the job wins, the tree stays.

    The top-level directory is 5 days old here, which is exactly what the old
    `-mtime +3` predicate deleted. The checkout inside it is seconds old, so
    the job that owns it is running now.
    """
    tree = make_workspace(runner, "repo", age_days=5, checkout_fresh=True)

    result = run_retention(runner.parent)

    assert result.returncode == 0, result.stderr
    assert tree.exists(), "the workspace of a running job was deleted"
    assert "tree vpt-1/repo: skip" in result.stdout, result.stdout


def test_an_idle_stale_workspace_is_reclaimed(runner: Path):
    """Nothing runs, the job activity is 5 days old: the space comes back."""
    tree = make_workspace(runner, "repo", age_days=5)

    result = run_retention(runner.parent)

    assert result.returncode == 0, result.stderr
    assert not tree.exists(), "a stale idle workspace was not reclaimed"
    assert "reclaimed" in result.stdout


def test_a_busy_runner_workspace_survives(runner: Path, live_worker):
    """The runner runs a job: its workspace is not touched, and the log says why."""
    tree = make_workspace(runner, "repo", age_days=5)
    live_worker(runner)

    result = run_retention(runner.parent)

    assert result.returncode == 0, result.stderr
    assert tree.exists(), "the workspace of a busy runner was deleted"
    assert "skip vpt-1: job running" in result.stdout


# --- the hard-disk pass ------------------------------------------------------


def test_the_hard_disk_pass_never_deletes_a_workspace_a_live_process_holds(runner: Path, tmp_path: Path):
    """Above the hard threshold the age filter is off, the safety rules are not.

    Two workspaces, both stale: one is held by a live process, the other is
    free. The held one must survive and the free one must go - otherwise the
    fix would have traded a CI red for a disk-full red.
    """
    held = make_workspace(runner, "held-repo", age_days=5)
    free = make_workspace(runner, "free-repo", age_days=5)
    holder = spawn_holder(held)
    try:
        result = run_retention(runner.parent, "--hard-threshold", "0")
    finally:
        holder.terminate()
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()

    assert result.returncode == 0, result.stderr
    assert held.exists(), "a workspace a live process holds was deleted"
    assert not free.exists(), "the hard pass reclaimed nothing: the disk would still fill up"
    assert "skip vpt-1: in use" in result.stdout


def test_the_hard_disk_pass_never_deletes_a_busy_runner_workspace(runner: Path, live_worker):
    """Above the hard threshold a busy runner is still left alone."""
    tree = make_workspace(runner, "repo", age_days=5)
    live_worker(runner)

    result = run_retention(runner.parent, "--hard-threshold", "0")

    assert result.returncode == 0, result.stderr
    assert tree.exists(), "the hard pass deleted the workspace of a running job"
    assert "skip vpt-1: job running" in result.stdout


# --- the log -----------------------------------------------------------------


def test_every_runner_gets_a_decision_line(runner: Path):
    """One line per runner, with the decision and the reclaimed bytes."""
    other = make_runner(runner.parent, "vpt-2")
    make_workspace(runner, "repo", age_days=5)
    make_workspace(other, "repo", age_days=5)

    result = run_retention(runner.parent)

    assert result.returncode == 0, result.stderr
    for name in ("vpt-1", "vpt-2"):
        assert f"{name}: " in result.stdout, f"no decision line for {name}"
    assert "reclaimed" in result.stdout


# --- the 15-minute check tick ------------------------------------------------


def test_the_timer_is_outside_the_night_gate_window():
    """The daily timer must not fire between 00:00 and 07:00 UTC."""
    text = (RUNNER_DIR / "ci-runner-retention.timer.tmpl").read_text()
    match = re.search(r"^OnCalendar=\S+\s+(\d\d):(\d\d):\d\d\s+UTC\s*$", text, re.M)
    assert match, "OnCalendar must name the time with UTC explicit"
    minutes = int(match.group(1)) * 60 + int(match.group(2))
    delay = re.search(r"^RandomizedDelaySec=(\d+)", text, re.M)
    end = minutes + (int(delay.group(1)) // 60 if delay else 0)
    assert minutes >= 7 * 60 and end < 24 * 60, "the timer fires inside the Night gate"


# --- the rendered units ------------------------------------------------------


def _render_units(tmp_path: Path) -> dict:
    """Run the installer's own render loop against a fake /etc/systemd/system.

    A fake ``sudo`` first on the PATH copies the unit where the real one would
    land, so the test sees exactly what a runner VM would get without a VM and
    without a single write outside the temporary directory.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_systemd = tmp_path / "etc" / "systemd" / "system"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        "# fake sudo: `install -m MODE SRC DEST` copies SRC to DEST, and a DEST\n"
        "# under /etc/systemd/system is redirected into the temporary directory.\n"
        "src=''\n"
        "dest=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    install) shift ;;\n"
        "    -m) shift 2 ;;\n"
        "    *) if [ -z \"$src\" ]; then src=\"$1\"; else dest=\"$1\"; fi; shift ;;\n"
        "  esac\n"
        "done\n"
        "dest=\"${dest//\\/etc\\/systemd\\/system/$FAKE_SYSTEMD}\"\n"
        "mkdir -p \"$(dirname \"$dest\")\"\n"
        "cp \"$src\" \"$dest\"\n"
        "chmod 0644 \"$dest\"\n"
    )
    fake_sudo.chmod(0o755)

    installer = (RUNNER_DIR / "install_runner.sh").read_text()
    loop = re.search(r"for tmpl in .*?\n\s*done\n", installer, re.S)
    assert loop, "install_runner.sh no longer renders the unit templates"

    script = f'RETENTION_DIR="{RUNNER_DIR}"\n' + loop.group(0)
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "FAKE_SYSTEMD": str(fake_systemd),
            "HOME": os.environ.get("HOME", "/root"),
        },
    )
    assert result.returncode == 0, result.stderr

    return {p.name: p.read_bytes() for p in sorted(fake_systemd.glob("*"))}


def test_the_units_are_shipped_as_templates_and_rendered_under_their_real_names(tmp_path: Path):
    """No .service/.timer/.socket file may live in the repo.

    Such a path is classified as a systemd unit by the merge policy and is
    refused whatever the approval says, so the units are versioned as
    templates.
    """
    for path in sorted(RUNNER_DIR.iterdir()):
        assert not path.name.endswith((".service", ".timer", ".socket")), (
            f"{path.name} would be refused by the merge policy: ship it as a .tmpl template"
        )

    for name in UNIT_TEMPLATES:
        assert (RUNNER_DIR / name).is_file(), f"{name} is missing"

    rendered = _render_units(tmp_path)
    assert sorted(rendered) == sorted(UNIT_NAMES), (
        f"the installer renders {sorted(rendered)}, not {sorted(UNIT_NAMES)}"
    )


def test_a_rendered_unit_is_byte_identical_to_its_template(tmp_path: Path):
    """The unit on the VM has to be the one this repo ships, unchanged."""
    rendered = _render_units(tmp_path)

    for name in UNIT_NAMES:
        template = (RUNNER_DIR / f"{name}.tmpl").read_bytes()
        assert rendered[name] == template, f"{name} differs from its template on the VM"


def test_the_check_tick_on_a_full_disk_never_touches_a_live_worker_tree(runner: Path, live_worker):
    """--check above the threshold runs the full cleanup: the guard protects the tree."""
    busy_tree = make_workspace(runner, "repo", age_days=5)
    live_worker(runner)
    other = make_runner(runner.parent, "vpt-2")
    idle_tree = make_workspace(other, "repo", age_days=5)

    result = run_retention(runner.parent, "--check", "--check-threshold", "0")

    assert result.returncode == 0, result.stderr
    assert busy_tree.exists(), "the check tick deleted the workspace of a running job"
    assert "skip vpt-1: job running" in result.stdout
    assert not idle_tree.exists(), "the check tick on a full disk reclaimed nothing"


# --- the run lock -----------------------------------------------------------


def test_a_run_that_does_not_hold_the_lock_deletes_nothing(runner: Path, tmp_path: Path):
    """The daily pass and the 15-minute check must never walk the tree at once.

    They are two different systemd units, so systemd does not serialise them.
    The lock file is what does: a run that finds it held says so and leaves
    every workspace alone - the workspace below is stale and idle, so nothing
    but the lock keeps it.
    """
    lock_path = tmp_path / "held.lock"
    tree = make_workspace(runner, "repo", age_days=5)

    holder = open(lock_path, "w")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_retention(runner.parent, lock_path=lock_path)
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert result.returncode == 0, result.stderr
    assert "another run in progress, skipping" in result.stdout, result.stdout
    assert tree.exists(), "a run that did not hold the lock deleted a workspace"
    assert "deleted" not in result.stdout, result.stdout
    assert "reclaimed" not in result.stdout, result.stdout


def test_a_hard_pass_run_that_does_not_hold_the_lock_deletes_nothing(runner: Path, tmp_path: Path):
    """The hard pass drops the age filter, so the lock matters most there.

    Even a fresh workspace (which only the hard pass would delete) must survive
    a run that finds the lock held.
    """
    lock_path = tmp_path / "held-hard.lock"
    fresh = make_workspace(runner, "fresh", age_days=0)
    stale = make_workspace(runner, "stale", age_days=5)

    holder = open(lock_path, "w")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_retention(runner.parent, "--hard-threshold", "0", lock_path=lock_path)
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert result.returncode == 0, result.stderr
    assert "another run in progress, skipping" in result.stdout, result.stdout
    assert fresh.exists(), "the hard pass without the lock deleted a fresh workspace"
    assert stale.exists(), "the hard pass without the lock deleted a stale workspace"
    assert "hard pass" not in result.stdout, result.stdout
    assert "deleted" not in result.stdout, result.stdout
