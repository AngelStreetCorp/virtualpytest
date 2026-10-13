"""
tests/backend_host/test_web_input_text_settle.py — how long web input_text waits after the fill.

execute_command passes params.timeout to input_text as its post-fill settle, and the action's
own wait_time is slept afterwards by ActionExecutor. The implicit settle was 3000 ms: 3 s per
typed field for a fill that takes ~30 ms, on every one of the 152 stored web input_text
actions (none sets timeout). It is now INPUT_TEXT_SETTLE_MS; an explicit params.timeout is
still honoured.
"""
import asyncio
import importlib

import pytest

playwright_mod = importlib.import_module('backend_host.src.controllers.web.playwright')
PlaywrightWebController = playwright_mod.PlaywrightWebController


class _Page:
    def __init__(self):
        self.filled = []

    async def fill(self, selector, text):
        self.filled.append((selector, text))


@pytest.fixture
def controller(monkeypatch):
    ctl = PlaywrightWebController(browser_engine='chromium')
    page = _Page()

    async def persistent_page(*_a, **_k):
        return page

    monkeypatch.setattr(ctl, '_get_persistent_page', persistent_page)
    ctl._test_page = page
    return ctl


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        recorded.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    return recorded


def run(coro):
    return asyncio.run(coro)


def test_the_implicit_settle_is_short(controller, sleeps):
    result = run(controller.execute_command('input_text', {'selector': '.new-todo', 'text': 'Buy milk',
                                                           'wait_time': 500}))

    assert result['success'] is True
    assert controller._test_page.filled == [('.new-todo', 'Buy milk')]
    assert playwright_mod.INPUT_TEXT_SETTLE_MS == 500
    assert sleeps == [0.5], 'one settle of INPUT_TEXT_SETTLE_MS; wait_time is not slept here'


def test_an_explicit_timeout_is_still_honoured(controller, sleeps):
    run(controller.execute_command('input_text', {'selector': '#q', 'text': 'x', 'timeout': 3000}))

    assert sleeps == [3.0]


def test_the_method_default_matches_the_command_default(controller, sleeps):
    run(controller.input_text('#q', 'x'))

    assert sleeps == [playwright_mod.INPUT_TEXT_SETTLE_MS / 1000]
