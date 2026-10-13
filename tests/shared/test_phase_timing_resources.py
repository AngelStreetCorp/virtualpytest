"""TASK-68: the host-resource probe in shared/src/lib/utils/phase_timing.py and the decision
stamp in shared/src/lib/ai/decisions.py.

Pure: no /proc on macOS is a supported case (the probe returns None, never raises), so the CPU
tests run against a fake /proc/stat file, and one test runs against a real process only when a
real one is available.

Run: pytest tests/shared/test_phase_timing_resources.py -v
"""
import os
import sys
import time

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from shared.src.lib.ai import decisions  # noqa: E402
from shared.src.lib.utils import phase_timing as pt  # noqa: E402

pytestmark = pytest.mark.unit

ON_LINUX = os.path.isdir('/proc/self')


def _fake_stat(tmp_path, utime, stime, name="phase timing test"):
    """A /proc/<pid>/stat lookalike: comm is the parenthesised 2nd field, then the 52 after it.

    Fields 1..15 -- pid, comm, state, ppid..cmajflt, utime, stime -- is all the probe reads.
    """
    path = tmp_path / "stat"
    middle = " ".join(["S"] + [str(i) for i in range(4, 14)])
    path.write_text(f"1 ({name}) {middle} {utime} {stime} " + " ".join(["0"] * 40) + "\n")
    return str(path)


# ---------------------------------------------------------------- cpu delta

def test_cpu_ms_between_measures_a_burned_loop(tmp_path, monkeypatch):
    """A process that burns measurable CPU: the delta is positive and inside a plausible bound."""
    path = _fake_stat(tmp_path, 100, 50)
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: path)
    before = pt.process_cpu_ticks(999)
    assert before == 150
    _fake_stat(tmp_path, 118, 55)  # 13 user + 5 sys ticks => 23 ticks => 230 ms at HZ=100
    assert pt.cpu_ms_between(999, before) == pytest.approx(230.0, abs=0.01)


def test_cpu_ms_between_is_zero_when_nothing_was_burned(tmp_path, monkeypatch):
    path = _fake_stat(tmp_path, 42, 8)
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: path)
    before = pt.process_cpu_ticks(1)
    assert pt.cpu_ms_between(1, before) == 0.0


def test_comm_with_spaces_and_paren_does_not_break_the_parse(tmp_path, monkeypatch):
    """A comm like "(my proc) x" -- the split must be after the LAST ')', not the first."""
    path = tmp_path / "stat"
    path.write_text("7 (my proc) x) S " + " ".join(["0"] * 10) + " 900 100 " + " ".join(["0"] * 40) + "\n")
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: str(path))
    assert pt.process_cpu_ticks(1) == 1000


@pytest.mark.skipif(not ON_LINUX, reason="no /proc on this host")
def test_real_process_cpu_delta_is_positive_and_bounded():
    """The real thing: burn ~200 ms of CPU, expect roughly that back and well under the wall time."""
    before = pt.process_cpu_ticks(os.getpid())
    assert before is not None
    deadline = time.time() + 0.2
    x = 0
    while time.time() < deadline:
        x += 1
    cpu_ms = pt.cpu_ms_between(os.getpid(), before)
    assert x > 0
    assert cpu_ms is not None and cpu_ms > 0
    assert cpu_ms < 5000  # never more than the wall time plus the sampling overhead


@pytest.mark.skipif(not ON_LINUX, reason="no /proc on this host")
def test_measure_cpu_ms_returns_the_call_result_and_its_cost():
    def burn():
        deadline = time.time() + 0.15
        n = 0
        while time.time() < deadline:
            n += 1
        return n

    n, cpu_ms = pt.measure_cpu_ms(os.getpid(), burn)
    assert n > 0 and cpu_ms is not None and cpu_ms > 0


@pytest.mark.skipif(not ON_LINUX, reason="no /proc on this host")
def test_measure_cpu_ms_lets_the_calls_own_exception_through():
    def boom():
        raise ValueError("caller's error, not the probe's")

    with pytest.raises(ValueError):
        pt.measure_cpu_ms(os.getpid(), boom)


# ---------------------------------------------------------------- failure modes

@pytest.mark.parametrize("pid", [None, 0, -1, "", "abc", 2 ** 62])
def test_a_pid_that_cannot_exist_reads_as_none(pid):
    assert pt.proc_stat_path(pid) is None or isinstance(pt.proc_stat_path(pid), str)
    assert pt.process_cpu_ticks(pid) is None


@pytest.mark.skipif(not ON_LINUX, reason="no /proc on this host")
def test_a_dead_pid_is_none_not_an_error():
    """A pid that exited between the two reads: the after-read fails, so there is no number."""
    before = pt.process_cpu_ticks(os.getpid())
    assert before is not None  # the before-read is real
    assert pt.cpu_ms_between(999_999_999, before) is None  # the after-read is gone


def test_a_dead_pid_is_none_not_an_error_without_proc():
    """Same degradation where there is no /proc at all: no before-read, no exception."""
    assert pt.cpu_ms_between(os.getpid(), None) is None
    assert pt.cpu_ms_between(999_999_999, 1234) is None


def test_unreadable_proc_degrades_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: str(tmp_path / "missing" / "stat"))
    assert pt.process_cpu_ticks(1) is None
    assert pt.cpu_ms_between(1, 0) is None


def test_permission_denied_degrades_to_none(tmp_path, monkeypatch):
    def denied(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: "/proc/1/stat")
    monkeypatch.setattr(pt, "open", denied, raising=False)
    monkeypatch.setattr("builtins.open", denied)
    assert pt.process_cpu_ticks(1) is None
    assert pt.cpu_ms_between(1, 0) is None


def test_truncated_or_garbage_proc_degrades_to_none(tmp_path, monkeypatch):
    path = tmp_path / "stat"
    path.write_text("this is not /proc\n")
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: str(path))
    assert pt.process_cpu_ticks(1) is None


def test_a_broken_loader_does_not_stop_the_trace(tmp_path, monkeypatch):
    """os.getloadavg() gone / raising: the tick still lands, with no load on the line."""
    def boom():
        raise OSError("no loadavg here")

    monkeypatch.setattr(os, "getloadavg", boom)
    trace = pt.LoadTrace(capacity=4, pid=1)
    assert trace.sample() is True
    assert trace.samples()[0][1] is None
    assert pt.load_context().get("cpu_count", 0) >= 0


# ---------------------------------------------------------------- ring buffer

def test_the_ring_rolls_over_without_growing():
    trace = pt.LoadTrace(capacity=5, pid=1)
    for _ in range(23):
        trace.sample()
    samples = trace.samples()
    assert len(samples) == 5                      # bounded
    assert trace.sampled == 23                    # and it says how many it kept of
    assert trace.dropped == 18
    assert [s[0] for s in samples] == sorted(s[0] for s in samples)  # oldest first


def test_a_capacity_that_is_not_a_number_falls_back():
    assert pt.LoadTrace(capacity="nope", pid=1).capacity == pt.LOAD_TRACE_CAPACITY
    assert pt.LoadTrace(capacity=0, pid=1).capacity == 1


def test_flush_prints_the_samples_and_a_summary_line():
    trace = pt.LoadTrace(capacity=8, pid=os.getpid())
    trace.sample()
    trace.sample()
    lines = []
    summary = trace.flush(print_line=lambda text, **kw: lines.append(text))
    assert summary["sampled"] == 2 and summary["kept"] == 2 and summary["dropped"] == 0
    assert lines[-1].startswith(pt.MARKER) and "resource.trace" in lines[-1]
    samples = [line for line in lines if line.startswith(pt.RESOURCE_MARKER)]
    assert len(samples) == 2
    # every sample line carries its own wall_clock_prefix -- that is the join key
    assert all("Z +" in line for line in samples)


def test_a_dropped_ring_says_so_in_the_summary():
    trace = pt.LoadTrace(capacity=2, pid=1)
    for _ in range(6):
        trace.sample()
    lines = []
    summary = trace.flush(print_line=lambda text, **kw: lines.append(text))
    assert summary["dropped"] == 4 and "dropped=4" in lines[-1]


def test_a_flush_with_no_samples_is_quiet_but_prints_the_summary():
    lines = []
    summary = pt.LoadTrace(capacity=4, pid=1).flush(print_line=lambda text, **kw: lines.append(text))
    assert summary["sampled"] == 0 and len(lines) == 1


# ---------------------------------------------------------------- start / stop

def test_start_and_stop_a_trace_flushes_once_and_is_idempotent(tmp_path, monkeypatch, capsys):
    path = _fake_stat(tmp_path, 10, 10)
    monkeypatch.setattr(pt, "proc_stat_path", lambda pid: path)
    trace = pt.start_resource_trace(pid=os.getpid(), interval_s=0.02, capacity=64)
    assert trace is not None
    time.sleep(0.12)
    summary = pt.stop_resource_trace(flush=True)
    assert summary["sampled"] >= 1 and pt.active_resource_trace() is None
    assert pt.stop_resource_trace() == {}   # second stop is a no-op, not an error
    out = capsys.readouterr().out
    assert "resource.trace" in out
    assert out.count(f"{pt.MARKER} resource.trace") == 1  # flushed once, not twice
    assert pt.RESOURCE_MARKER in out


def test_the_probe_writes_no_file_and_no_db_row(tmp_path, monkeypatch):
    """The BUG-0093 constraint, as a test: a whole trace is memory plus stdout."""
    monkeypatch.chdir(tmp_path)
    trace = pt.start_resource_trace(pid=os.getpid(), interval_s=0.02, capacity=64)
    assert trace is not None
    time.sleep(0.08)
    pt.stop_resource_trace(flush=False)
    assert list(tmp_path.iterdir()) == []


def test_a_start_failure_returns_none_instead_of_raising(monkeypatch):
    monkeypatch.setattr(pt, "LoadTrace", lambda *a, **k: (_ for _ in ()).throw(OSError("no mem")))
    assert pt.start_resource_trace() is None


# ---------------------------------------------------------------- decisions stamp

def test_the_stamp_carries_tier_load_and_cpu_count():
    stamped = decisions.stamp_refs({"alert_id": "a-1"})
    assert stamped["alert_id"] == "a-1"
    assert stamped["tier"] == decisions.TIER_MODEL          # unset -> a model ran
    assert set(pt.load_context()) <= set(stamped)
    assert stamped["cpu_count"] >= 1


def test_tier_is_recorded_and_the_callers_own_keys_win():
    for tier in decisions.TIERS:
        assert decisions.stamp_refs({"tier": tier})["tier"] == tier
        assert decisions.stamp_refs(None, tier)["tier"] == tier
    assert decisions.stamp_refs({"tier": "rule"}, "cv")["tier"] == "cv"
    assert decisions.stamp_refs({"tier": "cv"}, "cv")["tier"] == "cv"


def test_an_unknown_or_missing_tier_falls_back_to_model():
    assert decisions.stamp_refs(None)["tier"] == "model"
    assert decisions.stamp_refs({"tier": "llm"})["tier"] == "model"
    assert decisions.stamp_refs({"tier": None})["tier"] == "model"
    assert decisions.host_context("nonsense")["tier"] == "model"


def test_the_stamp_never_raises_on_a_host_without_load_numbers(monkeypatch):
    def boom():
        raise OSError("no getloadavg here")

    monkeypatch.setattr(os, "getloadavg", boom)
    monkeypatch.setattr(os, "cpu_count", boom)
    assert decisions.host_context() == {"tier": "model"}


def test_a_broken_phase_timing_leaves_the_caller_refs_intact(monkeypatch):
    monkeypatch.setattr(pt, "load_context", lambda: (_ for _ in ()).throw(OSError("probe down")))
    assert decisions.stamp_refs({"alert_id": "a-1"})["alert_id"] == "a-1"