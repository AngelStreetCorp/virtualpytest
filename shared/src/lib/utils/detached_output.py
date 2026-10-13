"""
Detached output: keep a background thread's prints out of the NEXT run's execution log.

A run's log capture (ScriptExecutionContext.start_stdout_capture) and each testcase block's
log buffer (phase_timing.PhaseLinePassthrough) work by swapping the process-global sys.stdout,
so they record whatever ANY thread prints while they are installed. That is harmless while one
run owns the process. It is not once a finished testcase's report tail (video, uploads, HTML,
DB) runs in the background while the next testcase is already executing: without this, the
tail's few hundred lines would land in the next run's execution.txt and step logs.

A thread inside `detached_output()` is written straight through to the journal by every
capture layer, never into a capture buffer. Threads the tail starts itself (the R2 upload
pool) log through `logging`, not print, so they do not need it.
"""

import threading
from contextlib import contextmanager

_detached = set()
_lock = threading.Lock()


@contextmanager
def detached_output():
    """Mark the calling thread as detached from any run's log capture while inside."""
    ident = threading.get_ident()
    with _lock:
        _detached.add(ident)
    try:
        yield
    finally:
        with _lock:
            _detached.discard(ident)


def is_detached() -> bool:
    """True when the calling thread's output must bypass every capture buffer."""
    return threading.get_ident() in _detached
