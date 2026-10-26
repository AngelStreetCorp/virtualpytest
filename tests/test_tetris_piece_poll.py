"""The piece wait must be a poll, not a hot spin (BUG-0841).

While Tetris applies gravity and has not dropped the next piece, the runner re-reads the page
through the host's single Playwright controller loop. It did so with no sleep on the path, so
the poll rate was bounded only by that loop's latency: the runner competed with the very
after-action screenshot the same loop had to serve, and a run stopped fitting in its time
budget. It also meant `max_duration` was only ever checked between pieces, so a run waiting on
the game could sit past its cap.

These drive the real `TetrisRunner.run()` loop with a fake IO that reports a game refusing to
drop its next piece, and assert on wall-clock behaviour rather than on the source text.

Run: pytest tests/test_tetris_piece_poll.py -v
"""
import os
import sys
import time
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

pytestmark = pytest.mark.unit

runner_mod = pytest.importorskip('shared.src.lib.game.tetris.runner')


def _court():
    return [[0] * runner_mod.NY for _ in range(runner_mod.NX)]


class _StuckIO:
    """A game that never drops the next piece: state reads are cheap and instant."""

    def __init__(self):
        self.state_reads = 0

    def run_actions(self, actions):
        self.state_reads += 1
        if actions and actions[0].get("command") == "execute_javascript":
            # The runner unwraps the last execute_javascript result via _js_result.
            return {"success": True, "results": [{"output_data": {"result": {
                "court": "0" * (runner_mod.NX * runner_mod.NY),
                "piece": {"id": 0, "t": "T", "x": 0, "y": 0, "d": 0}, "rows": 0, "score": 0, "playing": True,
                "step": 0, "next": None,
            }}}]}
        return {"success": True, "results": []}

    def edge_actions(self, game, name):
        # The runner reads every key it may need once at start and refuses to run when the tree
        # has none. This run never presses any -- the game never offers a new piece -- so the
        # contents only need to be non-empty.
        return [{"command": "press_key", "action_type": "web", "params": {"key": name}}]

    def navigate(self, node):
        # The runner opens the game and the start node before its play loop; both succeed here.
        return {"success": True}

    def frame(self):
        # Only the vision perception path reads frames; this run is js.
        return None

    def evidence(self, name):
        # The run's own page screenshot; irrelevant to pacing, and the host returns None when
        # the run drives no live page.
        return None


def _runner(io, **kw):
    ctx = SimpleNamespace(
        error_message=None, overall_success=None, execution_summary=None,
        userinterface=None, tree_id="t1", metadata=None,
        record_step=lambda *a, **k: None,
        record_step_immediately=lambda *a, **k: None,
        log=lambda *a, **k: None,
    )
    opts = dict(max_pieces=1000, max_duration=5, min_rows=0,
                perception='js', rules=None, vision_profile=None, predict=False)
    opts.update(kw)
    return runner_mod.TetrisRunner(io, ctx, **opts), ctx


def test_waiting_for_a_piece_does_not_spin_the_browser(monkeypatch):
    """A poll loop must be paced by PIECE_POLL_S, not by controller latency.

    `state()` here answers instantly, so a spin would issue thousands of reads in a fraction of
    a second. Bounding the read count is what makes the pacing observable without asserting on
    the implementation.
    """
    monkeypatch.setattr(runner_mod, 'NEW_PIECE_TIMEOUT_S', 30.0)
    monkeypatch.setattr(runner_mod, 'PIECE_POLL_S', 0.05, raising=False)
    io = _StuckIO()
    runner, _ = _runner(io, max_duration=1)

    t0 = time.monotonic()
    runner.run()
    elapsed = time.monotonic() - t0

    # ~1 s of budget at a 50 ms poll is at most a few dozen reads, and each costs controller
    # time; a hot spin would be orders of magnitude more.
    assert io.state_reads < 400, f"hot spin: {io.state_reads} reads in {elapsed:.2f}s"
    assert elapsed >= 0.5, f"returned before the time cap was reachable ({elapsed:.2f}s)"


def test_a_run_waiting_on_the_game_still_honours_max_duration(monkeypatch):
    """The cap was only checked between pieces, so a stuck game outlasted it."""
    monkeypatch.setattr(runner_mod, 'NEW_PIECE_TIMEOUT_S', 300.0)
    monkeypatch.setattr(runner_mod, 'PIECE_POLL_S', 0.01, raising=False)
    io = _StuckIO()
    runner, _ = _runner(io, max_duration=1)

    t0 = time.monotonic()
    data = runner.run()
    elapsed = time.monotonic() - t0

    assert data.get("stop_reason") == "time_cap"
    assert elapsed < 10, f"waited {elapsed:.1f}s for a 1s cap -- the cap is not being checked while waiting"


def test_the_poll_interval_is_short_enough_to_not_change_the_gameplay(monkeypatch):
    """Pacing must not cost latency: gravity is about a second per piece."""
    assert 0 < runner_mod.PIECE_POLL_S <= 0.2
    assert runner_mod.PIECE_POLL_S < runner_mod.NEW_PIECE_TIMEOUT_S


def test_a_piece_that_never_lands_still_reports_piece_stuck(monkeypatch):
    """The pacing must not swallow the existing stuck-piece verdict."""
    monkeypatch.setattr(runner_mod, 'NEW_PIECE_TIMEOUT_S', 0.3)
    monkeypatch.setattr(runner_mod, 'PIECE_POLL_S', 0.01, raising=False)
    io = _StuckIO()
    runner, _ = _runner(io, max_duration=3600)

    data = runner.run()

    assert "never landed" in (data.get("error") or "")
    assert not data.get("success")