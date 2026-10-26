"""A rejected completion callback must be retried (E50).

The completion callback is what closes the deployment_executions row and releases the
device lock. The host used to set "callback sent" as soon as the POST returned, before
looking at the status code: a callback the server rejected - or one that timed out - was
counted as sent, was never retried, and the recovery callback in the `finally` was skipped
because the flag was already set. The row then stayed in 'running' until the server's
reaper, which was itself blocked by the per-device busy check.

What is checked here:
  - a callback the server rejects is sent again,
  - a callback that times out is sent again,
  - a callback the server never accepts reports failure instead of pretending it was sent,
  - the retries are bounded.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

callback_mod = pytest.importorskip('backend_host.src.lib.utils.completion_callback')

_ROUTE_SOURCE = (Path(__file__).resolve().parents[2]
                 / 'backend_host/src/routes/host_script_routes.py').read_text()


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = 'rejected'


class _Time:
    """A time module whose sleep does not sleep."""

    @staticmethod
    def sleep(_seconds):
        return None


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(callback_mod, 'time', _Time)


@pytest.fixture
def posts(monkeypatch):
    """The recorded POST calls; the fake answers with `responses` in order."""
    calls = []
    responses = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'payload': json})
        answer = responses.pop(0) if responses else _Response(200)
        if isinstance(answer, Exception):
            raise answer
        return answer

    import requests
    monkeypatch.setattr(requests, 'post', fake_post)
    return calls, responses


def test_a_rejected_callback_is_sent_again(posts, no_sleep):
    calls, responses = posts
    responses.extend([_Response(500), _Response(200)])

    assert callback_mod.post_completion_callback('http://server/cb', {'task_id': 't1'}) is True
    assert len(calls) == 2


def test_a_callback_that_timed_out_is_sent_again(posts, no_sleep):
    calls, responses = posts
    responses.extend([TimeoutError('timed out'), _Response(200)])

    assert callback_mod.post_completion_callback('http://server/cb', {'task_id': 't1'}) is True
    assert len(calls) == 2


def test_a_callback_the_server_never_accepts_reports_failure(posts, no_sleep):
    """A refused callback was never applied: the caller must keep the row open."""
    calls, responses = posts
    responses.extend([_Response(500), _Response(500), _Response(503)])

    assert callback_mod.post_completion_callback('http://server/cb', {'task_id': 't1'}) is False
    assert len(calls) == callback_mod.CALLBACK_RETRY_ATTEMPTS


def test_the_retries_are_bounded(posts, no_sleep):
    """No infinite loop: the callback gives up after a fixed number of attempts."""
    calls, responses = posts
    responses.extend([_Response(500)] * 10)

    assert callback_mod.post_completion_callback('http://server/cb', {'task_id': 't1'}) is False
    assert len(calls) == callback_mod.CALLBACK_RETRY_ATTEMPTS


def test_the_route_counts_a_callback_as_sent_only_when_it_was_applied():
    """The old bug: `callback_sent = True` before the status code was looked at."""
    assert 'callback_sent = True' not in _ROUTE_SOURCE
    assert 'callback_sent = post_completion_callback(' in _ROUTE_SOURCE
