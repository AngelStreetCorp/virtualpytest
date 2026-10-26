"""Tests for shared/src/lib/utils/web_tree_smoke.py (TASK-161).

The walker is what proves a showcase tree is worth showing: entry → every screen
(forward + its own verifications) → back to home, twice in a row.

The bug this file exists for: the summary line used `len(passes)` where `passes`
is an `int`. The walk itself completed — every screen was navigated and verified —
and then the script raised `TypeError: object of type 'int' has no len()` on the
very last line, so the execution died with no verdict at all. Every smoke of the
series failed that way and it looked like the trees were broken.
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.utils import web_tree_smoke  # noqa: E402
from shared.src.lib.utils.web_tree_smoke import smoke_walk_web_tree  # noqa: E402


class _FakeExecutor:
    """Answers every navigation and every verification with success."""

    def __init__(self):
        self.navigations = []
        self.verifications = []

    async def execute_navigation(self, tree_id=None, target_node_id=None, **kwargs):
        self.navigations.append(target_node_id)
        return {"success": True, "node_id": target_node_id}

    async def execute_single_node_verification(self, tree_id=None, node_id=None, **kwargs):
        self.verifications.append(node_id)
        return {"success": True, "message": "verified"}


class _FakeDevice:
    def __init__(self):
        self.navigation_executor = _FakeExecutor()


class _FakeContext:
    def __init__(self):
        self.selected_device = _FakeDevice()
        self.team_id = "team-1"
        self.steps = []

    def record_step_immediately(self, step):
        self.steps.append(step)


CONTENT = [
    {"node_id": "home", "label": "Home", "verifications": [{"type": "waitForUrlToMatch"}]},
    {"node_id": "screen-a", "label": "Screen A", "verifications": [{"type": "waitForUrlToMatch"}]},
    {"node_id": "screen-b", "label": "Screen B", "verifications": [{"type": "waitForUrlToMatch"}]},
]


@pytest.fixture
def walker(monkeypatch):
    """The walker over a fake tree of three screens."""
    monkeypatch.setattr(web_tree_smoke, "resolve_tree",
                        lambda context, ui_name: ("tree-1", [dict(n) for n in CONTENT]))
    return smoke_walk_web_tree


def test_summary_line_renders_the_pass_count(walker):
    """The regression: the summary must print the number of passes, not len() of it.

    `passes` is an int; `len(passes)` raises TypeError and kills the execution
    after the walk — no verdict, no log, a silent failure that reads like a
    broken tree.
    """
    context = _FakeContext()
    result = walker(context, "web-test", passes=2)

    assert "2 pass(es)" in result["summary"]
    assert "TypeError" not in result["summary"]
    assert result["passes"] == 2


def test_a_clean_walk_succeeds(walker):
    """Every screen navigated and verified, both passes → the run is a success."""
    context = _FakeContext()
    result = walker(context, "web-test", passes=2)

    assert result["success"] is True
    assert result["failures"] == []
    assert result["nodes"] == 3
    # 2 passes × (home verify + 2 screens × (forward+verify, back)) = 2 × 5 checks
    assert result["checks"] == 10
    # each pass starts from the entry edge, then goes home
    assert context.selected_device.navigation_executor.navigations[0] == "home"


def test_a_failing_verification_fails_the_walk(walker, monkeypatch):
    """A screen that cannot be verified fails the walk — that is the whole point."""
    context = _FakeContext()
    executor = context.selected_device.navigation_executor

    async def _bad_verification(tree_id=None, node_id=None, **kwargs):
        executor.verifications.append(node_id)
        return {"success": False, "error": "url never matched"}

    monkeypatch.setattr(executor, "execute_single_node_verification", _bad_verification)
    result = walker(context, "web-test", passes=2)

    assert result["success"] is False
    assert result["failures"]
    assert "FAILED" in result["summary"]


def test_one_pass_is_accepted(walker):
    """`passes=1` is a valid single walk and must not crash the summary either."""
    context = _FakeContext()
    result = walker(context, "web-test", passes=1)

    assert "1 pass(es)" in result["summary"]
    assert result["success"] is True
    assert result["checks"] == 5


def test_verifications_are_read_in_either_shape():
    """A node's verifications are a list, or the older `{"item": [...]}` shape.

    `youtube-web` was built before the list convention: its nodes store
    `{"item": [...]}`, and one of them stores `{"item": {"item": [...]}}`. The
    verification executor reads `verifications[0]`, which raises on the object
    shape, so the walk must hand it a list either way.
    """
    from shared.src.lib.utils.web_tree_smoke import verification_list

    plain = [{"command": "waitForUrlToMatch"}]
    assert verification_list({"verifications": plain}) == plain

    wrapped = {"item": [{"command": "waitForUrlToMatch"}]}
    assert verification_list({"verifications": wrapped}) == [{"command": "waitForUrlToMatch"}]

    double = {"item": {"item": [{"command": "waitForUrlToMatch"}]}}
    assert verification_list({"verifications": double}) == [{"command": "waitForUrlToMatch"}]

    # Nothing usable is an empty list, never a crash.
    assert verification_list({}) == []
    assert verification_list({"verifications": None}) == []
    assert verification_list({"verifications": "nonsense"}) == []
