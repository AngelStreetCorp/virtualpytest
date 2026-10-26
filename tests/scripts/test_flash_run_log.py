"""Per-run record of the free-Flash game runs (TASK-164): a run that is still in flight must not be
counted as a failure.

`record_script_execution_start` inserts the row with `completed_at = started_at` and leaves
`execution_time_ms` NULL; `update_script_execution_result` writes the real end time and the
duration when the script is over. The reader used to test `completed_at IS NULL`, which is never
true (the column is NOT NULL), so every run that had just started was printed as "failed".

Run: pytest tests/scripts/test_flash_run_log.py -v
"""
import importlib.util
import os

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "flash_run_log", os.path.join(_here, "..", "..", "scripts", "agent", "flash_run_log.py"))
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


def _run(**over):
    """One script_results row as the reader gets it from the database."""
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "game": "pokemon",
        "started": "2026-10-26 01:00:05.953755+00:00",
        "ended": "2026-10-26 01:00:05.953756+00:00",
        "duration_ms": None,
        "host": "host-clone-2",
        "success": False,
        "error": "",
        "meta": {},
        "calls": [],
    }
    row.update(over)
    return row


def test_a_just_started_run_is_running_not_failed():
    # The placeholder the platform writes: completed_at == started_at, no duration yet.
    assert L._in_flight(_run()) is True
    assert L._outcome(_run()) == "running"
    assert L._wall(_run()) == "running"


def test_a_finished_failure_stays_failed():
    row = _run(ended="2026-10-26 01:02:35.830180+00:00", duration_ms=149876,
               error="STALLED: the same map position for 300 ticks at hall_of_fame")
    assert L._in_flight(row) is False
    assert L._outcome(row).startswith("failed: STALLED")
    assert L._wall(row) == "2m29s"


def test_a_finished_success_stays_ok():
    row = _run(ended="2026-10-26 01:00:22.797060+00:00", duration_ms=16275, success=True)
    assert L._outcome(row) == "ok"
    assert L._wall(row) == "0m16s"


def test_a_finished_row_without_a_duration_is_not_running():
    # 14 rows of the save are like this: the run is over (the gap is real) but the platform never
    # wrote a duration. Only the placeholder -- a gap under a second -- means "still running".
    row = _run(ended="2026-10-26 05:45:00.000000+00:00", duration_ms=None)
    assert L._in_flight(row) is False
    assert L._outcome(row) == "failed"


def test_a_row_without_an_end_is_running():
    row = _run(ended=None)
    assert L._in_flight(row) is True
    assert L._outcome(row) == "running"


def test_the_table_says_running_for_the_run_in_flight():
    table = L.table([L.row_for(_run())])
    assert "running" in table
    assert "failed" not in table
