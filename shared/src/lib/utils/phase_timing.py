"""
Phase timing for execution logs -- logging only, never raises, never changes a result.

Every timing line has one shape so a run's time can be rebuilt by grepping one marker:

    ⏱ <phase> <ms> ms[ <detail>]

It is printed when the phase ENDS, so the wall-clock prefix that StdoutCapture puts on each
line of the uploaded execution.txt (see stamp_lines) is the phase's end time and the start is
that minus <ms>.

Where the lines land:
  * execution.txt -- ScriptExecutionContext.start_stdout_capture() prefixes every captured line
    with its UTC wall clock and the seconds since the context started.
  * inside a testcase block -- TestCaseExecutor._execute_block redirects stdout into a per-block
    buffer (the step's `logs`); PhaseLinePassthrough keeps that buffer whole and passes the ⏱
    lines on to the run's capture, so they reach execution.txt and the vpt-host journal too.
  * the finalize tail -- generate_report_for_context stops the capture before the report/log
    uploads and the final DB write, so those phases only reach the vpt-host journal. A testcase
    whose report tail runs in the background (VPT_TESTCASE_BACKGROUND_REPORT) stops it earlier,
    before the video extract: all its tail phases are journal-only, under tc.report_tail.

The resource probe at the bottom of this module (TASK-68) answers the question a ⏱ line cannot:
what the host was doing while that phase ran. It holds an in-memory ring of `os.getloadavg()` plus
this process's CPU ticks (`/proc/<pid>/stat` utime+stime, the only signal that attributes CPU to
one operation -- load average is a ~60 s EWMA and cannot). Same contract as the rest of the file:
best-effort, never raises, never changes a result, and **no DB write and no per-operation file
write** -- the trace lives in memory and is printed once at the end of the run, into the same
execution.txt stream as the ⏱ lines. That is deliberate (BUG-0093, where per-cycle writes stalled
the control path for minutes on a 4-core Pi); the probe has to be free or it must not ship.
"""

import os
import threading
import time
from collections import deque
from typing import Any, List, Optional, Tuple

MARKER = '⏱'  # ⏱


def t0() -> float:
    """A start mark for log_phase."""
    return time.perf_counter()


def log_duration(phase: str, ms: float, detail: str = '') -> int:
    """Print one timing line for a duration measured elsewhere."""
    ms_int = int(round(ms))
    line = f"{MARKER} {phase} {ms_int} ms"
    if detail:
        line += f" {detail}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    return ms_int


def log_phase(phase: str, started: float, detail: str = '') -> int:
    """Print one timing line for the phase that began at `started` (a t0() value)."""
    return log_duration(phase, (time.perf_counter() - started) * 1000.0, detail)


def wall_clock_prefix(now: float, origin: Optional[float]) -> str:
    """'HH:MM:SS.mmmZ +SSS.sss ' -- UTC wall clock, then seconds since `origin`."""
    seconds, millis = divmod(int(round(now * 1000)), 1000)
    stamp = time.strftime('%H:%M:%S', time.gmtime(seconds)) + f".{millis:03d}Z"
    if origin is None:
        return stamp + ' '
    return f"{stamp} +{now - origin:7.3f} "


def stamp_lines(text: str, at_line_start: bool, prefix: str) -> Tuple[str, bool]:
    """Insert `prefix` at the start of every line that begins inside `text`.

    `at_line_start` says whether the previous write ended a line; print() writes its text and
    its '\\n' separately, so a line is stamped once, when its first character arrives. Returns
    the stamped text and whether `text` itself ended a line.
    """
    if not text:
        return text, at_line_start
    out: List[str] = []
    parts = text.split('\n')
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if part and at_line_start:
            out.append(prefix)
        out.append(part)
        if not is_last:
            out.append('\n')
            at_line_start = True
        elif part:
            at_line_start = False
    return ''.join(out), at_line_start


class TimestampedLineBuffer:
    """Appends stamped text to a list; one per StdoutCapture. Thread-safe."""

    def __init__(self, buffer: list, origin: Optional[float]):
        self._buffer = buffer
        self._origin = origin
        self._at_line_start = True
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            stamped, self._at_line_start = stamp_lines(
                text, self._at_line_start, wall_clock_prefix(time.time(), self._origin))
            self._buffer.append(stamped)


class PhaseLinePassthrough:
    """File-like stand-in for a block's stdout buffer.

    Everything written goes to `buffer`, unchanged. Complete lines whose first non-blank
    character is the ⏱ marker are also written to `passthrough` (the stream that was active
    before the block redirected stdout), so timing lines reach the run's execution log while
    the rest of the block's output stays in the step's own logs.
    """

    def __init__(self, buffer, passthrough):
        self._buffer = buffer
        self._passthrough = passthrough
        self._pending = ''
        self._is_phase_line: Optional[bool] = None  # None = not decided yet for this line

    def write(self, text):
        from shared.src.lib.utils.detached_output import is_detached
        if is_detached():
            # Another run's background report tail: not this block's output.
            try:
                self._passthrough.write(text)
            except Exception:
                pass
            return len(text or '')
        self._buffer.write(text)
        if not text:
            return 0
        parts = text.split('\n')
        for i, part in enumerate(parts):
            if self._is_phase_line is None:
                self._pending += part
                stripped = self._pending.lstrip()
                if stripped:
                    self._is_phase_line = stripped.startswith(MARKER)
                    if not self._is_phase_line:
                        self._pending = ''
            elif self._is_phase_line:
                self._pending += part
            if i < len(parts) - 1:  # this part ended a line
                if self._is_phase_line:
                    try:
                        self._passthrough.write(self._pending + '\n')
                    except Exception:
                        pass
                self._pending = ''
                self._is_phase_line = None
        return len(text)

    def flush(self):
        for stream in (self._buffer, self._passthrough):
            try:
                stream.flush()
            except Exception:
                pass

    def getvalue(self):
        return self._buffer.getvalue()

    def __getattr__(self, name):
        return getattr(self._buffer, name)


# --------------------------------------------------------------------------
# Resource probe (TASK-68). In memory, flushed once per run. Never raises.
# --------------------------------------------------------------------------

RESOURCE_MARKER = '📈'  # 📈 -- a sample, not a duration: never grepped as a phase
LOAD_SAMPLE_INTERVAL_S = 0.25   # 4 fps: one getloadavg() + one /proc read per tick
LOAD_TRACE_CAPACITY = 2048      # ring: ~8.5 min at 4 fps, then it rolls over (counted, not silent)
_HZ_FALLBACK = 100              # clock ticks per second, the near-universal Linux value


def clock_ticks_per_second() -> int:
    """HZ -- clock ticks /proc/<pid>/stat counts in. Never raises."""
    try:
        hz = int(os.sysconf('SC_CLK_TCK'))
        return hz if hz > 0 else _HZ_FALLBACK
    except Exception:
        return _HZ_FALLBACK


def proc_stat_path(pid) -> Optional[str]:
    """/proc/<pid>/stat, or None for a pid that cannot have one. Never raises."""
    try:
        pid = int(pid)
    except Exception:
        return None
    return f'/proc/{pid}/stat' if pid > 0 else None


def process_cpu_ticks(pid) -> Optional[int]:
    """``utime + stime`` for `pid` in clock ticks, or None if it cannot be read.

    Two reasons for None, and both mean "no trace", never an error the caller sees: this host has
    no /proc (macOS, dev boxes), or the pid is gone / unreadable / not ours to read.
    """
    path = proc_stat_path(pid)
    if not path:
        return None
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except Exception:
        return None
    try:
        # comm is "(name)" and may itself contain spaces and ')': split after the LAST ')'.
        # After it, index 0 is state, so utime is field 14 and stime field 15 -> 11 and 12.
        fields = data[data.rindex(b')') + 1:].split()
        return int(fields[11]) + int(fields[12])
    except Exception:
        return None


def cpu_ms_between(pid, before_ticks, hz: Optional[int] = None) -> Optional[float]:
    """CPU ms `pid` consumed since `before_ticks` (a process_cpu_ticks() read), or None.

    None also covers the case that matters most: the pid exited between the two reads, so the
    after-read is None and there is no number to report. Callers keep their result either way.
    """
    after = process_cpu_ticks(pid)
    if after is None or before_ticks is None:
        return None
    try:
        delta = after - int(before_ticks)
        return (delta if delta > 0 else 0) / (hz or clock_ticks_per_second()) * 1000.0
    except Exception:
        return None


def measure_cpu_ms(pid, fn, *args, **kwargs) -> Tuple[Any, Optional[float]]:
    """Run ``fn`` and return ``(its result, CPU ms it cost)``. Never raises for the probe.

    An exception from ``fn`` is the caller's, not the probe's: it propagates untouched and the
    CPU number is dropped rather than changing what the call returns.
    """
    before = process_cpu_ticks(pid)
    out = fn(*args, **kwargs)
    return out, cpu_ms_between(pid, before)


def load_context() -> dict:
    """{'load_1m', 'load_5m', 'load_15m', 'cpu_count'} for a decision row, best-effort."""
    out: dict = {}
    try:
        load = os.getloadavg()
        for name, value in zip(('load_1m', 'load_5m', 'load_15m'), load):
            out[name] = round(float(value), 2)
    except Exception:
        pass
    try:
        count = os.cpu_count()
        if count:
            out['cpu_count'] = int(count)
    except Exception:
        pass
    return out


def _getloadavg() -> Optional[tuple]:
    try:
        return os.getloadavg()
    except Exception:
        return None


def _print(print_line, line: str) -> None:
    """One line out through `print_line` (print by default), flush preferred, never raises."""
    try:
        print_line(line, flush=True)
    except TypeError:
        try:
            print_line(line)
        except Exception:
            pass
    except Exception:
        pass


class LoadTrace:
    """Ring buffer of (wall clock, load 1/5/15, cpu ticks) samples. Memory only, thread-safe.

    Fixed capacity: a long run drops the oldest samples instead of growing. `dropped` counts them,
    so a truncated trace says so on the summary line rather than looking complete.
    """

    def __init__(self, capacity: int = LOAD_TRACE_CAPACITY, pid=None, origin: Optional[float] = None):
        try:
            capacity = max(1, int(capacity))
        except Exception:
            capacity = LOAD_TRACE_CAPACITY
        self.capacity = capacity
        self.pid = pid
        self.origin = time.time() if origin is None else origin
        self.sampled = 0
        self.dropped = 0
        self._samples = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._first_cpu: Optional[int] = None
        self._cpu_ms = 0.0

    def sample(self) -> bool:
        """One tick: getloadavg() + one /proc read. Never raises; returns False if unusable."""
        try:
            now = time.time()
            load = _getloadavg()
            ticks = process_cpu_ticks(self.pid)
            cpu_ms = 0.0
            with self._lock:
                if self._first_cpu is None and ticks is not None:
                    self._first_cpu = ticks
                elif ticks is not None:
                    hz = clock_ticks_per_second()
                    cpu_ms = max(0, ticks - self._first_cpu) / hz * 1000.0
                self._cpu_ms = max(self._cpu_ms, cpu_ms)
                if len(self._samples) == self.capacity:
                    self.dropped += 1
                self._samples.append((now, load, ticks, cpu_ms))
                self.sampled += 1
            return True
        except Exception:
            return False

    def samples(self) -> list:
        """The kept samples, oldest first."""
        try:
            with self._lock:
                return list(self._samples)
        except Exception:
            return []

    def cpu_ms(self) -> float:
        try:
            with self._lock:
                return self._cpu_ms
        except Exception:
            return 0.0

    def max_load(self) -> float:
        loads = [s[1][0] for s in self.samples() if s[1]]
        return max(loads) if loads else 0.0

    def format_line(self, sample: tuple) -> str:
        """One sample as a line, carrying its OWN wall_clock_prefix -- the join key.

        The prefix StdoutCapture adds at flush time says when the trace was written; the one
        inside the line says when the sample was taken, in the same format, so grep joins the two.
        """
        now, load, ticks, cpu_ms = sample
        line = f"{RESOURCE_MARKER} {wall_clock_prefix(now, self.origin)}"
        if load:
            line += f" 1m={load[0]:.2f} 5m={load[1]:.2f} 15m={load[2]:.2f}"
        if cpu_ms:
            line += f" cpu_ms={cpu_ms:.0f}"
        if ticks is not None:
            line += f" ticks={ticks}"
        return line

    def stats(self) -> dict:
        """What the trace holds, as numbers: sampled / kept / dropped / cpu_ms / load_1m_max."""
        kept = len(self.samples())
        summary = {'sampled': self.sampled, 'dropped': self.dropped, 'kept': kept,
                   'cpu_ms': self.cpu_ms(), 'load_1m_max': self.max_load(), 'pid': self.pid}
        summary['ms'] = int(round((time.time() - self.origin) * 1000.0))
        summary['detail'] = (f"pid={self.pid} samples={summary['sampled']} kept={kept} "
                             f"cpu_ms={summary['cpu_ms']:.0f} load_1m_max={summary['load_1m_max']:.2f}"
                             + (f" dropped={summary['dropped']} oldest (ring capacity)"
                                if summary['dropped'] else ""))
        summary['summary_line'] = f"{MARKER} resource.trace {summary['ms']} ms {summary['detail']}"
        return summary

    def flush(self, print_line=print) -> dict:
        """Print the kept samples plus one ⏱ summary, through `print_line`. Never raises.

        Returns the summary numbers. The summary is a ⏱ line like any other phase, so the run's
        cost of *being measured* sits in the same grep as everything else.
        """
        try:
            for sample in self.samples():
                _print(print_line, self.format_line(sample))
        except Exception:
            pass
        summary = self.stats()
        try:
            _print(print_line, summary['summary_line'])
        except Exception:
            pass
        return summary


class ResourceTrace:
    """A running LoadTrace plus its sampler thread. `stop()` flushes once, then it is dead."""

    def __init__(self, trace: LoadTrace, interval_s: float, pid):
        self.trace = trace
        self.interval_s = interval_s
        self.pid = pid
        self.stopped = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name='vpt-resource-trace', daemon=True)

    def start(self) -> 'ResourceTrace':
        try:
            self._thread.start()
        except Exception:
            self.stopped = True
        return self

    def _loop(self) -> None:
        try:
            self.trace.sample()  # at t=0, so the trace starts with the run
            while not self._stop.is_set():
                self._stop.wait(self.interval_s)
                if self._stop.is_set():
                    break
                self.trace.sample()
        except Exception:
            pass

    def stop(self, flush: bool = True) -> dict:
        """Stop sampling. Flushes the trace to stdout once (so it lands in execution.txt).

        Returns the trace's numbers either way: `flush=False` skips the printing, not the count.
        """
        if self.stopped:
            return {}
        self.stopped = True
        try:
            self._stop.set()
        except Exception:
            pass
        try:
            return self.trace.flush() if flush else self.trace.stats()
        except Exception:
            return {}


_trace_lock = threading.Lock()
_active_trace: Optional[ResourceTrace] = None


def start_resource_trace(pid=None, interval_s: float = LOAD_SAMPLE_INTERVAL_S,
                         capacity: int = LOAD_TRACE_CAPACITY) -> Optional[ResourceTrace]:
    """Sample load + this process's CPU in the background. One active trace; starts None on failure."""
    global _active_trace
    try:
        if pid is None:
            pid = os.getpid()
        trace = LoadTrace(capacity=capacity, pid=pid)
        try:
            interval_s = max(0.01, float(interval_s))
        except Exception:
            interval_s = LOAD_SAMPLE_INTERVAL_S
        handle = ResourceTrace(trace, interval_s, pid).start()
        with _trace_lock:
            _active_trace = handle if not handle.stopped else None
        return _active_trace
    except Exception:
        return None


def active_resource_trace() -> Optional[ResourceTrace]:
    try:
        with _trace_lock:
            return _active_trace
    except Exception:
        return None


def stop_resource_trace(flush: bool = True) -> dict:
    """Stop and flush the active trace. Safe to call twice, safe with no trace running."""
    global _active_trace
    try:
        with _trace_lock:
            handle, _active_trace = _active_trace, None
        return handle.stop(flush=flush) if handle else {}
    except Exception:
        return {}
