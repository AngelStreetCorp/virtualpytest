"""Transient transport failures (BUG-0433).

The point of `call_with_retry` is that it retries the failures that are the PATH's fault
and nothing else. A dropped TLS session gets another go; a PostgREST JSON error, a 4xx
or a missing table is the caller's problem and must still surface on the first attempt —
otherwise a real bug hides behind a retry loop and nobody reads the trace.
"""

import ssl

import pytest

from shared.src.lib.database.transient_retry import (
    TRANSIENT_MARKERS,
    brief,
    call_with_retry,
    is_transient,
)


def _boom(exc):
    raise exc


# --------------------------------------------------------------------------- is_transient


def test_ssl_error_is_transient():
    assert is_transient(ssl.SSLError(1, "DECRYPTION_FAILED_OR_BAD_RECORD_MAC"))


def test_remote_disconnect_is_transient():
    import http.client

    assert is_transient(http.client.RemoteDisconnected("Remote end closed connection"))


def test_wrong_version_number_is_transient():
    # A TLS ClientHello answered on a plain-HTTP port — a path problem, not a query one.
    assert is_transient(Exception("SSL: WRONG_VERSION_NUMBER"))


def test_postgrest_html_error_is_transient():
    # supabase-py when the answer is not JSON at all: a proxy's HTML 500 page.
    assert is_transient(Exception("{'message': 'JSON could not be generated', 'code': 500}"))


def test_a_real_api_error_is_not_transient():
    assert not is_transient(Exception("{'code': '42P01', 'message': 'relation does not exist'}"))
    assert not is_transient(ValueError("invalid team_id"))


def test_a_4xx_is_not_transient():
    assert not is_transient(Exception("{'code': 42501, 'message': 'permission denied'}"))


def test_every_marker_is_a_real_substring_and_not_a_bare_type_name():
    # Guards against a marker that can never appear, which would silently disable the
    # retry for that failure mode.
    assert all(len(m) > 6 for m in TRANSIENT_MARKERS)
    assert not any(m in ("error", "exception") for m in TRANSIENT_MARKERS)


# ------------------------------------------------------------------------------- brief


def test_brief_truncates_a_postgrest_dump():
    exc = Exception("x" * 5000)
    out = brief(exc, limit=50)

    assert out.startswith("Exception: ")
    assert out.endswith("…")
    assert len(out) < 80


def test_brief_flattens_newlines_so_one_failure_is_one_line():
    assert "\n" not in brief(Exception("a\nb"))


def test_brief_of_a_bare_exception_has_no_trailing_space():
    assert brief(Exception("")) == "Exception"


# ------------------------------------------------------------------------- call_with_retry


def test_returns_the_value_on_first_success_without_sleeping():
    slept = []
    assert call_with_retry(lambda: "ok", label="t", sleep=slept.append) == "ok"
    assert slept == []


def test_retries_a_transient_failure_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ssl.SSLError(1, "DECRYPTION_FAILED_OR_BAD_RECORD_MAC")
        return "recovered"

    slept = []
    out = call_with_retry(flaky, label="t", sleep=slept.append, log=lambda _m: None)

    assert out == "recovered"
    assert len(calls) == 3
    # delays grow: 0.5s then 1.0s at the default base
    assert slept == [0.5, 1.0]


def test_gives_up_after_attempts_and_reraises():
    slept = []
    with pytest.raises(ssl.SSLError):
        call_with_retry(
            lambda: _boom(ssl.SSLError(1, "DECRYPTION_FAILED_OR_BAD_RECORD_MAC")),
            label="t",
            attempts=3,
            sleep=slept.append,
            log=lambda _m: None,
        )
    assert len(slept) == 2          # two waits between three attempts


def test_a_non_transient_error_is_never_retried():
    calls = []

    def broken():
        calls.append(1)
        raise ValueError("relation does not exist")

    with pytest.raises(ValueError):
        call_with_retry(broken, label="t", sleep=lambda _s: None, log=lambda _m: None)

    assert len(calls) == 1          # first attempt, straight to the caller


def test_logs_one_compact_line_per_retry():
    lines = []
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ssl.SSLError(1, "DECRYPTION_FAILED_OR_BAD_RECORD_MAC")
        return "ok"

    call_with_retry(flaky, label="[@x:y]", sleep=lambda _s: None, log=lines.append)

    assert len(lines) == 1
    assert "[@x:y]" in lines[0] and "transient" in lines[0] and "1/2" in lines[0]


def test_attempts_must_be_positive():
    with pytest.raises(ValueError):
        call_with_retry(lambda: None, label="t", attempts=0, sleep=lambda _s: None)
