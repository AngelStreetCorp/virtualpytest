"""The stall watcher clears the lock itself when its fixer ends (BUG-0947).

The chain that lets a locked save play again is: the run stalls -> the dispatcher writes the lock ->
the watcher starts a fixer -> the fixer fixes the stall, deploys it and clears the lock -> the lane
plays on. The last link was the fixer agent's own work (step 6 of its brief). An agent that ends
without doing it - it died, it went another way, it never reached step 6 - leaves the save locked for
ever: the dispatcher starts no run, and the watcher, whose retry window is 6 h, asks nobody.

On 2026-10-26 the second save was dark from 08:45 to 12:12 and the first from 11:17 to 12:11 for
exactly that reason. The watcher does the clear itself when the fixer it started is over.

The tests run the watcher script for real, in a sandbox: a fake canonical store, a fake tmux, a fake
ssh and a fake dispatcher that records the clear.

Run: pytest tests/scripts/test_stall_watch_clear.py -v
"""
import json
import os
import subprocess
import time

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
WATCHER = os.path.join(_root, "scripts", "agent", "pokemon_stall_watch.sh")

REPORT_DIR = "/var/lib/vpt-private/pokemon"
DISPATCH_STUB = '''import os
import sys

with open(os.environ["DISPATCH_LOG"], "a") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("DISPATCH_RC", "0")))
'''

TMUX_STUB = """#!/usr/bin/env bash
case "$1" in
  list-panes) printf '%s\\n' "${TMUX_PANES:-}" ;;
  kill-session) printf 'kill %s\\n' "$3" >> "${TMUX_KILL_LOG}" ;;
esac
exit 0
"""

SSH_STUB = """#!/usr/bin/env bash
exit 0
"""

PSTREE_STUB = """#!/usr/bin/env bash
printf '%s\\n' "${PSTREE_OUT:-}"
"""

CBSESSION_STUB = """#!/usr/bin/env bash
printf 'cbsession %s\\n' "$*" >> "${CBSESSION_LOG}"
exit 0
"""


def _write(path, text, mode=0o700):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)
    return str(path)


class Sandbox:
    """A home directory with a canonical store, a fake tmux and a fake dispatcher."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.canon = self.home / "vpt-private" / "pokemon" / "canonical"
        self.canon.mkdir(parents=True)
        self.state = self.home / ".cache" / "pokemon-stall-watch"
        self.state.mkdir(parents=True)
        self.handled = self.state / "handled"
        self.handled.write_text("")
        self.dispatch_log = tmp_path / "dispatch.log"
        self.kill_log = tmp_path / "kill.log"
        self.cbsession_log = tmp_path / "cbsession.log"

        # the tree the fixer works in: a dirty git repo, so the watcher neither clones nor syncs it
        fix_repo = self.home / ".local" / "share" / "vpt-stall-fix"
        fix_repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(fix_repo)], check=True)
        (fix_repo / "in-progress.txt").write_text("work")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write(bin_dir / "tmux", TMUX_STUB)
        _write(bin_dir / "ssh", SSH_STUB)
        _write(bin_dir / "pstree", PSTREE_STUB)
        local_bin = self.home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        _write(local_bin / "cbsession", CBSESSION_STUB)
        self.dispatch = _write(tmp_path / "dispatch_stub.py", DISPATCH_STUB, mode=0o600)

    def lock(self, save, report, run_id="20261026-084552"):
        """The canonical lock of a save: "this save is stuck on that report"."""
        path = self.canon / f"stall_{save}.lock.json"
        path.write_text(json.dumps({"report": f"{REPORT_DIR}/{report}", "run_id": run_id,
                                    "reason": "same_spot", "milestone": "hall_of_fame"}))
        return path

    def handled_entry(self, report):
        """A fixer worked on that report (the handled list keeps "<report>|<epoch>")."""
        with open(self.handled, "a", encoding="utf-8") as handle:
            handle.write(f"{REPORT_DIR}/{report}|{int(time.time())}\n")

    def run(self, panes="", pstree_out="", dispatch_rc=0):
        env = os.environ.copy()
        env.update({
            "HOME": str(self.home),
            "PATH": f"{self.root / 'bin'}:{env['PATH']}",
            "POKEMON_CANON": str(self.canon),
            "POKEMON_DISPATCH": self.dispatch,
            "DISPATCH_LOG": str(self.dispatch_log),
            "DISPATCH_RC": str(dispatch_rc),
            "TMUX_PANES": panes,
            "TMUX_KILL_LOG": str(self.kill_log),
            "PSTREE_OUT": pstree_out,
            "CBSESSION_LOG": str(self.cbsession_log),
        })
        return subprocess.run(["bash", WATCHER], capture_output=True, text=True, timeout=180, env=env, check=False)

    @property
    def clears(self):
        """What the watcher asked the dispatcher to clear."""
        if not self.dispatch_log.exists():
            return []
        return [line.strip() for line in self.dispatch_log.read_text().splitlines() if line.strip()]

    @property
    def killed(self):
        if not self.kill_log.exists():
            return []
        return [line.strip() for line in self.kill_log.read_text().splitlines() if line.strip()]


def _stale_panes(run_id="20261026-084552", pid=4242):
    """A tmux pane whose session is over (the watcher judges it by the pane's process tree)."""
    return f"pokestall-{run_id}|{int(time.time())}|{pid}"


def test_a_finished_fixer_clears_the_lock_of_its_own_save(tmp_path):
    """The chain's missing last link: the fixer ended without clearing, so the watcher clears."""
    box = Sandbox(tmp_path)
    box.lock("second", "stall_second_20261026-084552.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes())

    assert box.clears == ["clear-stall --save second"], out.stdout + out.stderr
    assert box.killed == ["kill pokestall-20261026-084552"]


def test_the_clear_names_the_save_of_the_main_lane_too(tmp_path):
    """The first lane's save is "latest": the clear has to name it, or it lands on the wrong lane."""
    box = Sandbox(tmp_path)
    box.lock("latest", "stall_latest_20261026-121745.json", run_id="20261026-121745")
    box.handled_entry("stall_latest_20261026-121745.json")

    out = box.run(panes=_stale_panes(run_id="20261026-121745"))

    assert box.clears == ["clear-stall --save latest"], out.stdout + out.stderr


def test_a_save_that_is_not_locked_is_not_cleared(tmp_path):
    """The fixer of a save that is not locked any more has nothing to clear."""
    box = Sandbox(tmp_path)
    box.lock("latest", "stall_latest_20261026-121745.json", run_id="20261026-121745")
    box.handled_entry("stall_latest_20261026-121745.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes())

    assert "second" not in " ".join(box.clears), out.stdout + out.stderr


def test_a_newer_stall_holding_the_lock_is_not_cleared(tmp_path):
    """The lock names another stall: that one is not ours to clear, its own fixer is armed for it."""
    box = Sandbox(tmp_path)
    box.lock("second", "stall_second_20261026-101010.json", run_id="20261026-101010")
    box.handled_entry("stall_second_20261026-101010.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes())

    assert box.clears == [], out.stdout + out.stderr


def test_a_fixer_that_is_still_working_keeps_the_lock(tmp_path):
    """A live fixer owns the lock: the watcher must not clear under it."""
    box = Sandbox(tmp_path)
    box.lock("second", "stall_second_20261026-084552.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes(), pstree_out="claude (4242)")

    assert box.clears == [], out.stdout + out.stderr
    assert box.killed == []


def test_a_failed_clear_keeps_the_fixer_session_for_the_next_minute(tmp_path):
    """The clear is retried: the session stays, so the next tick tries again."""
    box = Sandbox(tmp_path)
    box.lock("second", "stall_second_20261026-084552.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes(), dispatch_rc=1)

    assert box.clears == ["clear-stall --save second"], out.stdout + out.stderr
    assert box.killed == [], out.stdout + out.stderr
    assert "stays open" in out.stdout


def test_a_fixer_that_never_cleared_leaves_no_dark_save(tmp_path):
    """The whole point: a fixer that ends without clearing does not lock the save for ever."""
    box = Sandbox(tmp_path)
    box.lock("second", "stall_second_20261026-084552.json")
    box.handled_entry("stall_second_20261026-084552.json")

    box.run(panes=_stale_panes())

    assert box.clears, "the save stayed locked after its fixer ended"


@pytest.mark.parametrize("save", ["latest", "second"])
def test_the_watcher_never_touches_a_lock_it_did_not_start(tmp_path, save):
    """Only the lock of the save the finished fixer worked on is cleared."""
    box = Sandbox(tmp_path)
    box.lock("latest", "stall_latest_20261026-121745.json", run_id="20261026-121745")
    box.handled_entry("stall_latest_20261026-121745.json")
    box.handled_entry("stall_second_20261026-084552.json")

    out = box.run(panes=_stale_panes())

    assert save not in " ".join(box.clears), out.stdout + out.stderr
