#!/usr/bin/env python3
"""
Thread-local measurement-log capture.

Buffers every log record emitted on the current thread while a measurement is
being processed, so the resulting report (KPI, zapping, …) can embed a
collapsible "Measurement Log" section and be debugged after the fact without
trawling journalctl on the host.

Why thread-local: the zapping worker runs in a thread pool (capture_monitor's
`zapping_executor`) with several capture folders processed concurrently, all
sharing the same module loggers. A plain root-logger handler would interleave
every device's logs. A single handler that appends only to the *current
thread's* active buffer keeps each measurement's log clean with no add/remove
races (the handler is installed once and never detached).

Usage:
    from shared.src.lib.utils.measurement_log_capture import (
        begin_measurement_log, end_measurement_log, current_measurement_log)

    begin_measurement_log()
    try:
        ...  # do the work that logs
        report_log = current_measurement_log()  # snapshot whenever needed
    finally:
        end_measurement_log()
"""

import logging
import threading

_local = threading.local()


class _ThreadLocalCapture(logging.Handler):
    """Appends formatted records to the calling thread's active buffer (if any)."""

    def emit(self, record: logging.LogRecord) -> None:
        buf = getattr(_local, 'buffer', None)
        if buf is None:
            return
        try:
            buf.append(self.format(record))
        except Exception:
            # A logging handler must never raise back into the emitting code.
            pass


_handler = _ThreadLocalCapture()
_handler.setLevel(logging.INFO)
_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
_install_lock = threading.Lock()
_installed = False


def _ensure_installed() -> None:
    """Attach the capture handler to the root logger exactly once.

    Installed lazily (first begin_measurement_log call) and never removed, so
    no thread ever races an addHandler/removeHandler against another.
    """
    global _installed
    if _installed:
        return
    with _install_lock:
        if not _installed:
            logging.getLogger().addHandler(_handler)
            _installed = True


def begin_measurement_log() -> None:
    """Start capturing the current thread's log records into a fresh buffer."""
    _ensure_installed()
    _local.buffer = []


def end_measurement_log() -> None:
    """Stop capturing on the current thread and discard its buffer."""
    _local.buffer = None


def current_measurement_log() -> str:
    """Return the current thread's captured log text (empty if not capturing)."""
    buf = getattr(_local, 'buffer', None)
    return '\n'.join(buf) if buf else ''
