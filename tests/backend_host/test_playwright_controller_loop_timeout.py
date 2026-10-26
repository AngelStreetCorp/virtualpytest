"""A wedged controller loop must fail in bounded time, not hang the run (BUG-0842).

The web controller runs every Playwright op of a host on one loop thread. When that thread
wedged, the two waits on it were unbounded:

  - ``ensure_controller_loop`` (playwright.py:78) called from a plain thread:
    ``fut = self._submit_to_controller_loop(...)`` … ``return fut.result()``
  - ``execute_command`` (playwright.py:2368) with no running loop: ``return fut.result()``

So the caller waited for ever: the run never reported a result and its browser never came
down. The fix is a bounded wait with a clear failure.

Every test here runs the wait in a thread and reports whether it **came back**: a wait that
never returns is the defect itself, so a test must fail on it rather than hang the suite.

What is checked here:
  - a controller loop that never answers produces a bounded error, not a hang,
  - the failure says what happened,
  - a loop that answers in time is untouched (a healthy run keeps its old verdict),
  - ``execute_command`` reports the failure as a command result, not as an exception.
"""

import asyncio
import concurrent.futures
import importlib
import threading
import time

import pytest

playwright_mod = importlib.import_module('backend_host.src.controllers.web.playwright')

ensure_controller_loop = playwright_mod.ensure_controller_loop
execute_command = playwright_mod.PlaywrightWebController.execute_command


# ---------------------------------------------------------------------------
# Helpers: resolve the new API without failing at import time, and never hang
# ---------------------------------------------------------------------------

def _new(name):
    """The new API, or None when this code does not have it yet."""
    return getattr(playwright_mod, name, None)


def _returns_within(call, seconds):
    """Run ``call`` in a thread and report whether it came back in time.

    Returns ``(came_back, box)``; the box holds ``value`` or ``error``.
    """
    box = {}

    def runner():
        try:
            box['value'] = call()
        except BaseException as exc:  # noqa: BLE001 - the test wants to see any failure
            box['error'] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive(), box


# ---------------------------------------------------------------------------
# Fakes: a controller whose loop never completes the coroutine
# ---------------------------------------------------------------------------

class _NeverAnswers:
    """A controller whose controller loop never completes what it is given."""

    _loop = None

    def _ensure_loop(self):
        type(self)._loop = object()

    def _submit_to_controller_loop(self, coro):
        coro.close()
        return concurrent.futures.Future()  # never completes


class _Answers:
    """A controller whose controller loop answers at once."""

    _loop = None

    def _ensure_loop(self):
        type(self)._loop = object()

    def _submit_to_controller_loop(self, coro):
        coro.close()
        future = concurrent.futures.Future()
        future.set_result('answered')
        return future


def _decorated_op():
    @ensure_controller_loop
    async def op(self):
        return 'answered'

    return op


# ---------------------------------------------------------------------------
# The bounded wait
# ---------------------------------------------------------------------------

def test_a_controller_loop_that_never_answers_fails_in_bounded_time(monkeypatch):
    """The wait is bounded: a wedged loop produces an error, not a run that lives for ever."""
    monkeypatch.setattr(playwright_mod, 'CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS', 0.25,
                        raising=False)

    controller = _NeverAnswers()
    started = time.time()
    came_back, box = _returns_within(lambda: asyncio.run(_decorated_op()(controller)), 15)
    elapsed = time.time() - started

    assert came_back, 'the wait did not return: the run hangs for ever'
    assert elapsed < 15, 'the wait was not bounded'
    assert isinstance(box.get('error'), TimeoutError), box


def test_the_failure_says_the_loop_did_not_answer(monkeypatch):
    monkeypatch.setattr(playwright_mod, 'CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS', 0.25,
                        raising=False)

    controller = _NeverAnswers()
    came_back, box = _returns_within(lambda: asyncio.run(_decorated_op()(controller)), 15)

    assert came_back, 'the wait did not return: the run hangs for ever'
    message = str(box.get('error'))
    assert 'controller loop' in message
    assert 'did not answer' in message


def test_a_loop_that_answers_in_time_is_untouched(monkeypatch):
    """A healthy run keeps its old behaviour: the answer comes back as it always did."""
    assert _new('_controller_loop_result') is not None, \
        'the controller loop has no bounded wait to answer with'
    monkeypatch.setattr(playwright_mod, 'CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS', 5.0,
                        raising=False)

    came_back, box = _returns_within(lambda: asyncio.run(_decorated_op()(_Answers())), 15)

    assert came_back, 'a controller loop that answers did not come back'
    assert box.get('value') == 'answered'


def test_the_wait_uses_the_configured_budget(monkeypatch):
    helper = _new('_controller_loop_result')
    assert helper is not None, 'there is no bounded wait to configure'
    monkeypatch.setattr(playwright_mod, 'CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS', 0.25,
                        raising=False)

    future = concurrent.futures.Future()
    started = time.time()
    with pytest.raises(TimeoutError):
        helper(future)
    elapsed = time.time() - started

    assert elapsed < 15, 'the wait was not bounded'
    assert future.cancelled(), 'the pending work was left queued on a wedged loop'


def test_the_default_budget_is_finite():
    """A bounded wait with no timeout is the defect itself."""
    budget = _new('CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS')
    assert budget is not None, 'the controller loop wait has no budget at all'
    assert 0 < budget < 3600


# ---------------------------------------------------------------------------
# execute_command: the same failure, reported as a command result
# ---------------------------------------------------------------------------

def test_execute_command_reports_a_wedged_loop_as_a_failed_command(monkeypatch):
    """The action path reads a dict, not an exception: the failure has to be in the dict."""
    monkeypatch.setattr(playwright_mod, 'CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS', 0.25,
                        raising=False)

    controller = _NeverAnswers()
    controller.execute_command = lambda command, params=None: execute_command(
        controller, command, params)

    came_back, box = _returns_within(lambda: asyncio.run(controller.execute_command('click', {})), 15)

    assert came_back, 'the command did not come back: the run hangs for ever'
    result = box.get('value')
    assert isinstance(result, dict), result
    assert result['success'] is False
    assert 'controller loop' in result['error']
    assert 'execution_time' in result
