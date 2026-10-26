"""The Pokémon stall fixer must work from the current main, not from the shared checkout (BUG-0923).

`scripts/agent/pokemon_stall_watch.sh` starts one fixer session per stall. That session used to start
in `~/virtualpytest` — the shared checkout of every Claude Code session on codebox, whose HEAD is
whatever the last session left behind. On 2026-10-26 that tree was a day old, so the fixer read a
runner that main had already fixed and reproduced the recursion of BUG-0919 instead of the stall it
was sent to fix.

The guard is on the text of the two files: the watcher must give the fixer a tree of its own, put it
on origin/main before the session starts, and hand that tree to the session; the brief must name it.

Run: pytest tests/scripts/test_stall_watch_script.py -v
"""
import os
import re
import subprocess
import sys

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
WATCHER = os.path.join(_root, "scripts", "agent", "pokemon_stall_watch.sh")
REVIEW = os.path.join(_root, "scripts", "pokemon_stall_review.py")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def watcher():
    return _read(WATCHER)


def test_the_fixer_is_not_started_in_the_shared_checkout(watcher):
    # The shared checkout is still named as the source of the fixer's clone, but the session itself
    # must not run in it: `cbsession -d` decides where the agent works.
    assert '-d "${REPO}"' not in watcher
    assert 'cbsession" -n "${name}" -d "${FIX_REPO}"' in watcher


def test_the_fixer_gets_a_tree_of_its_own(watcher):
    assert re.search(r'FIX_REPO="\$\{HOME\}/\S+"', watcher)
    assert "vpt-stall-fix" in watcher


def test_the_fixer_tree_is_synced_before_the_session_starts(watcher):
    # The sync has to happen before cbsession, and it must not throw away a tree that is dirty
    # (the previous fixer may still be at work in it).
    assert "sync_lane_clone.sh" in watcher
    assert 'status --porcelain' in watcher
    assert watcher.index('SYNC="${HERE}/scripts/agent/sync_lane_clone.sh"') < \
        watcher.index('"${HOME}/.local/bin/cbsession"')


def test_the_brief_names_the_tree(watcher):
    assert '--repo "${FIX_REPO}"' in watcher


def test_the_brief_names_the_save_the_stall_is_about(watcher):
    """The clear command in the brief must name the save: the plain one only clears the first lane's save
    (the second lane waited 5 h 30 for its lock, 2026-10-26)."""
    assert '--save "${lock_save}"' in watcher
    assert 'lock_save=$(basename "${lock_file}" .lock.json' in watcher
    source = _read(REVIEW)
    assert "{clear_cmd}" in source
    assert 'clear_cmd += f" --save {a.save}"' in source


def test_the_brief_template_has_the_repo_placeholder():
    text = _read(REVIEW)
    assert "--repo" in text
    assert "{repo}" in text
    # The template must not hold a brace the formatter would choke on: every placeholder is one of
    # the six the script fills.
    placeholders = set(re.findall(r"\{(\w+)\}", text.split('FIX_BRIEF = """')[1].split('"""')[0]))
    assert placeholders <= {"out", "hosts", "host", "report", "repo", "clear_cmd"}


def test_the_review_script_takes_the_repo_option():
    out = subprocess.run([sys.executable, REVIEW, "--help"], capture_output=True, text=True, timeout=60)
    assert "--repo" in out.stdout
