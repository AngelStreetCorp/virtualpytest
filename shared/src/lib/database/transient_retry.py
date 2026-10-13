"""Retry for transport-level failures when talking to Supabase.

On this platform the Supabase REST API is reached over the public hostname of the main
server, so a request can fail for reasons that have nothing to do with the query:

- a TLS session dropped mid-flight — `SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC`,
- the peer answering on the wrong port — `SSL: WRONG_VERSION_NUMBER`,
- a proxy in the path returning an HTML 500 while the far end is still coming up, which
  supabase-py reports as `JSON could not be generated`.

The same call a second later succeeds. Nothing is lost, but background loops pay twice:
one blip costs a whole cycle, and the log line is a PostgREST error dict with a raw HTML
body in it, which nobody can read.

So this retries *those*, a small number of times, and says so in one line. Anything that
is a real API answer — a PostgREST JSON error, a 4xx, a missing table — is re-raised
untouched: retrying that would only hide a bug behind a slower stack trace.

`is_transient()` is deliberately conservative. When in doubt it says "not transient", so a
real error still surfaces on the first attempt.
"""

from __future__ import annotations

import http.client
import ssl
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

# Substrings that mark a failure as "the path broke", not "the query is wrong". Kept
# explicit rather than pattern-matching on numbers, because the wording is what shows up
# in the journal and is what an operator greps for.
TRANSIENT_MARKERS = (
    "DECRYPTION_FAILED_OR_BAD_RECORD_MAC",
    "WRONG_VERSION_NUMBER",
    "SSLError",
    "SSL error",
    "ConnectionResetError",
    "Connection aborted",
    "RemoteDisconnected",
    "IncompleteRead",
    "ReadTimeout",
    "ConnectTimeout",
    "TimeoutError",
    # supabase-py when the response is not JSON at all — typically a proxy's HTML error page
    "JSON could not be generated",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Time-out",
)


def brief(exc: BaseException, limit: int = 200) -> str:
    """One readable line for an exception, so a PostgREST dict or an HTML body in a log
    line does not swallow the rest of the journal."""
    text = str(exc).replace("\n", " ").strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def is_transient(exc: BaseException) -> bool:
    """True when `exc` is a transport failure worth retrying straight away."""
    if isinstance(
        exc,
        (
            ssl.SSLError,
            ConnectionResetError,
            ConnectionAbortedError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            TimeoutError,
        ),
    ):
        return True
    text = f"{type(exc).__name__}: {exc}"
    return any(marker in text for marker in TRANSIENT_MARKERS)


def call_with_retry(
    fn: Callable[[], T],
    *,
    label: str,
    attempts: int = 3,
    base_delay: float = 0.5,
    sleep: Optional[Callable[[float], None]] = None,
    log: Callable[[str], None] = print,
) -> T:
    """Call `fn`, retrying only transport-level failures up to `attempts` times.

    `sleep` is injectable for a reason: this runs inside gevent greenlets as well as
    plain threads, and `time.sleep` in a greenlet blocks the whole hub. Pass the caller's
    cooperative sleep (section_cache passes its own `_sleep`) when running under gevent.

    Re-raises the last error once the attempts are spent, or immediately when the failure
    is not transient — callers keep their existing error handling either way.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    nap = sleep or time.sleep

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - classified immediately below
            if attempt >= attempts or not is_transient(e):
                raise
            delay = base_delay * attempt
            log(
                f"[@db:transient] {label}: {brief(e)} — transient, "
                f"retry {attempt}/{attempts - 1} in {delay:.1f}s"
            )
            nap(delay)

    raise AssertionError("unreachable: the loop either returns or raises")
