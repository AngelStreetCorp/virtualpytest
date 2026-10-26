"""
tests/backend_host/test_run_page_screenshot.py — a report's step image belongs to the run that
took it, not to whichever Chrome window happens to be on top of the shared display (TASK-146).

Since the browser isolation (BUG-0727) two runs can share one host, and a host has ONE X
display (`DISPLAY=:1`). The screen capture a report fell back on — the newest file of the host's
capture folder, written by the VNC / x11grab loop — photographs the whole screen, so with two
runs it regularly shows the other run's browser. `capture_run_page_screenshot` photographs the
run's OWN page instead.

What is checked here:
  - the run's own page is used, and the shared screen capture is not,
  - a device with no live page (no browser run, a TV, an Android box) keeps the screen capture,
  - a page screenshot that fails is a fallback miss, never an exception and never a wrong image,
  - two concurrent runs get two different files, so they cannot overwrite each other,
  - the controller method never opens a page it is only meant to photograph.
"""
import asyncio
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

device_utils = importlib.import_module('shared.src.lib.utils.device_utils')


class _FakePage:
    """A Playwright page that only knows how to be photographed."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.screenshots = []
        self.timeouts = []

    async def screenshot(self, path=None, full_page=False, timeout=None):
        # Playwright's own timeout is part of the call: a screenshot that never settles
        # must give up on its own instead of holding the controller loop (TASK-161).
        self.timeouts.append(timeout)
        if self.fail:
            raise RuntimeError("Target page, context or browser has been closed")
        with open(path, 'wb') as handle:
            handle.write(b'PNG-of-this-run')
        self.screenshots.append(path)
        return path


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages


class _FakeWebController:
    """The per-run web controller: it owns one browser context and one page."""

    def __init__(self, page=None, context=None, raises: bool = False):
        self.page = page
        self.context = context
        self.raises = raises
        self.requested = []

    def capture_page_screenshot(self, path):
        self.requested.append(path)
        if self.raises:
            raise RuntimeError("controller loop is down")
        if self.page is None:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(b'PNG-of-this-run')
        return path


class _FakeAVController:
    """The host's screen capture: one image of the whole display."""

    def __init__(self, path='/captures/capture_0001.jpg', capture_source='VNC'):
        self.path = path
        self.capture_source = capture_source
        self.calls = 0

    def take_screenshot(self):
        self.calls += 1
        return self.path


def _awaitable_answer(path):
    """Stand in for the awaitable `@ensure_controller_loop` used to hand back."""
    async def _coro():
        return path
    return _coro()


class _FakeDevice:
    def __init__(self, controllers=None):
        self._controllers = controllers or {}

    def _get_controller(self, kind):
        found = self._controllers.get(kind)
        return found[0] if found else None


class _FakeContext_Report:
    """The report context: it just collects the paths it is given."""

    def __init__(self):
        self.screenshot_paths = []

    def add_screenshot(self, path):
        self.screenshot_paths.append(path)

    def upload_screenshots_to_r2(self):
        pass


@pytest.fixture
def run_env(monkeypatch):
    monkeypatch.setenv('VPT_RUN_ID', 'run-under-test')
    return monkeypatch


# ── the run's own page wins over the shared screen ──────────────────────────────

def test_a_browser_run_screenshots_its_own_page(run_env):
    """The image in the report is the page this run drove."""
    av = _FakeAVController()
    device = _FakeDevice({'web': [_FakeWebController(page=object())], 'av': [av]})

    path = device_utils.capture_run_page_screenshot(device, 'step_1')

    assert path and os.path.exists(path)
    assert av.calls == 0, "the shared screen capture must not be used when the run has its own page"


def test_the_page_screenshot_reaches_the_report(run_env):
    """The per-run image is what the report gets, not a screen capture."""
    web = _FakeWebController(page=object())
    device = _FakeDevice({'web': [web], 'av': [_FakeAVController()]})
    context = _FakeContext_Report()

    screenshot_id = device_utils.capture_screenshot_for_script(device, context, 'step_1')

    assert screenshot_id == 'step_1'
    assert len(context.screenshot_paths) == 1
    assert 'run-under-test' in context.screenshot_paths[0]
    assert web.requested, "the run's own page is what should have been photographed"


def test_a_run_that_opens_no_page_still_reports_a_miss(run_env):
    """No page to photograph: a miss, whatever the device's screen is."""
    device = _FakeDevice({'web': [_FakeWebController(page=None)],
                          'av': [_FakeAVController(capture_source='HDMI')]})

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None


def test_a_device_without_a_web_controller_keeps_the_screen_capture(run_env):
    """No browser run on the device at all: the screen capture stays the source."""
    av = _FakeAVController()
    device = _FakeDevice({'av': [av]})
    context = _FakeContext_Report()

    device_utils.capture_screenshot_for_script(device, context, 'step_1')

    assert context.screenshot_paths == ['/captures/capture_0001.jpg']
    assert av.calls == 1


# ── a failure is a miss, never a wrong image and never an exception ──────────────

def test_a_failing_page_screenshot_falls_back_to_the_screen_it_owns(run_env):
    """A browser that died mid-run must not cost the report its image.

    The fallback only ever meant to cover a device whose screen belongs to it alone; on a
    shared screen there is no honest image left to fall back to (see the skip tests below).
    """
    av = _FakeAVController(path='/captures/hdmi_0001.jpg', capture_source='HDMI')
    device = _FakeDevice({'web': [_FakeWebController(raises=True)], 'av': [av]})
    context = _FakeContext_Report()

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None

    device_utils.capture_screenshot_for_script(device, context, 'step_1')

    assert context.screenshot_paths == ['/captures/hdmi_0001.jpg']
    assert av.calls == 1


def test_a_photo_of_a_dead_page_is_not_returned(run_env):
    """The path is only returned when an image really landed on disk."""
    web = _FakeWebController(page=None)
    device = _FakeDevice({'web': [web]})

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None


def test_a_broken_device_raises_nothing(run_env):
    """A device object that blows up on `_get_controller` must not break the report."""
    class _Exploding:
        def _get_controller(self, kind):
            raise RuntimeError("device registry is gone")

    assert device_utils.capture_run_page_screenshot(_Exploding(), 'step_1') is None


# ── two runs on one host do not overwrite each other ─────────────────────────────

def test_two_runs_get_two_different_files(run_env):
    """Run A's image must never be replaced by run B's."""
    device = _FakeDevice({'web': [_FakeWebController(page=object())]})

    first = device_utils.capture_run_page_screenshot(device, 'step_1')
    second = device_utils.capture_run_page_screenshot(device, 'step_1')

    assert first != second


def test_the_file_lives_in_the_runs_own_directory(run_env):
    """Every run writes under its own run id, so a cleanup of one run spares the other."""
    path = device_utils.capture_run_page_screenshot(
        _FakeDevice({'web': [_FakeWebController(page=object())]}), 'step_1')

    assert 'run-under-test' in path.split(os.sep)


def test_a_run_without_an_id_still_gets_a_private_file(monkeypatch):
    """A run with no VPT_RUN_ID (a developer, a one-off) is isolated by pid."""
    monkeypatch.delenv('VPT_RUN_ID', raising=False)
    device = _FakeDevice({'web': [_FakeWebController(page=object())]})

    path = device_utils.capture_run_page_screenshot(device, 'step_1')

    assert path and f"pid{os.getpid()}" in path


# ── the legacy path, which is what the executor actually calls ───────────────────
#
# The script executor takes the run's initial and final report artifacts through
# `capture_screenshot()`, NOT through `capture_screenshot_for_script()`. Fixing only the
# latter shipped a no-op: the first deploy (2026-10-21) left every report header falling
# back to `capture_000388253.jpg` from the shared capture folder. These tests exist so
# that gap cannot come back unnoticed.

def test_the_legacy_path_photographs_the_runs_page(run_env):
    """The executor's initial/final artifact is the run's own page."""
    av = _FakeAVController()
    web = _FakeWebController(page=object())
    device = _FakeDevice({'web': [web], 'av': [av]})
    context = _FakeContext_Report()

    path = device_utils.capture_screenshot(device, context, '[test_script]')

    assert path and os.path.exists(path)
    assert 'run-under-test' in path
    assert context.screenshot_paths == [path]
    assert av.calls == 0, "the shared screen capture must not be used when the run has its own page"
    assert web.requested, "the run's own page is what should have been photographed"


def test_the_legacy_path_keeps_the_screen_capture_for_a_tv(run_env):
    """A device that drives no page is unchanged, image and message alike."""
    av = _FakeAVController()
    device = _FakeDevice({'av': [av]})
    context = _FakeContext_Report()

    path = device_utils.capture_screenshot(device, context, '[test_script]')

    assert path == '/captures/capture_0001.jpg'
    assert context.screenshot_paths == [path]
    assert av.calls == 1


def test_the_legacy_path_falls_back_when_the_browser_died(run_env):
    """A browser that dies between the check and the shot costs the report nothing."""
    av = _FakeAVController(path='/captures/hdmi_0001.jpg', capture_source='HDMI')
    device = _FakeDevice({'web': [_FakeWebController(raises=True)], 'av': [av]})
    context = _FakeContext_Report()

    assert device_utils.capture_screenshot(device, context, '[test_script]') == '/captures/hdmi_0001.jpg'
    assert av.calls == 1


def test_a_miss_says_why_on_stdout(run_env, capsys):
    """A silent fallback is how the first version shipped while changing nothing."""
    device = _FakeDevice({'web': [_FakeWebController(raises=True)], 'av': [_FakeAVController()]})

    device_utils.capture_run_page_screenshot(device, 'step_1')

    assert 'No run page screenshot' in capsys.readouterr().out


def test_an_awaitable_answer_is_a_miss_not_a_crash(run_env, capsys):
    """`@ensure_controller_loop` hands back an awaitable to a caller that already has a loop.

    That is how the first two deploys failed: the caller got a coroutine, `os.path.exists`
    raised outside the try, and the run reported a capture failure instead of falling back.
    It must be a plain miss, said out loud.
    """
    web = _FakeWebController(page=object())
    web.capture_page_screenshot = _awaitable_answer
    device = _FakeDevice({'web': [web], 'av': [_FakeAVController()]})

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None
    assert 'No run page screenshot' in capsys.readouterr().out


def test_the_legacy_path_survives_an_awaitable_answer(run_env):
    """The report still gets its image: the screen capture answers a miss."""
    web = _FakeWebController(page=object())
    web.capture_page_screenshot = _awaitable_answer
    device = _FakeDevice({'web': [web], 'av': [_FakeAVController(capture_source='HDMI')]})
    context = _FakeContext_Report()

    assert device_utils.capture_screenshot(device, context, '[t]') == '/captures/capture_0001.jpg'
    assert context.screenshot_paths == ['/captures/capture_0001.jpg']


def test_a_path_with_no_image_behind_it_is_a_miss(run_env, capsys):
    """A controller that returns a path it never wrote to must not pass as a screenshot."""
    web = _FakeWebController(page=object())
    web.capture_page_screenshot = lambda path: '/tmp/never-written.png'
    device = _FakeDevice({'web': [web]})

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None
    assert 'No run page screenshot' in capsys.readouterr().out


def test_no_web_controller_is_not_reported_as_a_miss(run_env, capsys):
    """A device that drives no page has nothing to miss; it is not a browser run."""
    device = _FakeDevice({'av': [_FakeAVController()]})

    assert device_utils.capture_run_page_screenshot(device, 'step_1') is None
    assert capsys.readouterr().out == ''


# ── the controller method ────────────────────────────────────────────────────────

def _controller(context=None, loop_result=None, loop_raises=None):
    """A PlaywrightWebController carrying only what `capture_page_screenshot` touches.

    The method submits `_photo_page` to the controller loop itself, so the loop is
    replaced by a fake here and `context` decides what the photograph would find.
    """
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = context

    class _Future:
        def result(self, timeout=None):
            if loop_raises:
                raise loop_raises
            if callable(loop_result):
                return loop_result(controller)
            return loop_result

        def cancel(self):
            pass

    def _submit(coro):
        coro.close()
        return _Future()

    controller._submit_to_controller_loop = _submit
    return controller


def test_the_controller_answers_with_a_path_from_a_plain_caller(tmp_path):
    """The whole point: a plain caller gets a path, never an awaitable.

    `@ensure_controller_loop` used to answer an awaitable when the caller already
    had a running loop, which is what made the first two deploys fall back silently.
    """
    controller = _controller(loop_result=lambda c: str(tmp_path / 'shot.png'))

    taken = controller.capture_page_screenshot(str(tmp_path / 'shot.png'))

    assert isinstance(taken, str)
    assert taken == str(tmp_path / 'shot.png')


def test_the_controller_writes_the_image(tmp_path):
    """The real coroutine half creates the directory and photographs the first page."""
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = _FakeContext([_FakePage()])
    target = tmp_path / 'shots' / 'run.png'
    try:
        result = asyncio.run(controller._photo_page(str(target)))
    finally:
        PlaywrightWebController._context = None

    assert result == str(target)
    assert target.exists()


def test_the_controller_never_opens_a_page_to_photograph_it(tmp_path):
    """A screenshot must not change what the run is doing: no page is ever created."""
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    class _ExplodingContext:
        pages = []

        async def new_page(self):
            raise AssertionError("the screenshot opened a page")

    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = _ExplodingContext()
    try:
        result = asyncio.run(controller._photo_page(str(tmp_path / 'x.png')))
    finally:
        PlaywrightWebController._context = None

    assert result is None


def test_the_controller_returns_none_without_a_browser(tmp_path):
    controller = _controller(context=None, loop_result=None)
    assert controller.capture_page_screenshot(str(tmp_path / 'x.png')) is None


def test_a_dead_page_is_not_fatal(tmp_path):
    """The browser can die between the check and the shot; the caller falls back."""
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = _FakeContext([_FakePage(fail=True)])
    try:
        result = asyncio.run(controller._photo_page(str(tmp_path / 'x.png')))
    finally:
        PlaywrightWebController._context = None

    assert result is None


def test_a_wedged_driver_times_out_instead_of_stalling_the_run(tmp_path):
    """A screenshot may never hang a run: the timeout answers None."""
    import concurrent.futures

    controller = _controller(loop_raises=concurrent.futures.TimeoutError())

    assert controller.capture_page_screenshot(str(tmp_path / 'x.png'), timeout=0.01) is None


def test_no_controller_loop_is_a_miss_not_a_crash(tmp_path):
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None

    def _boom(coro):
        coro.close()
        raise RuntimeError("no controller loop")

    controller._submit_to_controller_loop = _boom
    assert controller.capture_page_screenshot(str(tmp_path / 'x.png')) is None


# ── the moments a browser run has no page: take nothing rather than the wrong image ─
#
# The executor asks for the run's "before" and "after" shots. A browser run has no page at
# either moment — the first before it launches Chrome, the last after it closes it — so both
# used to take the newest screen capture, which on a host running two tests is the OTHER run's
# browser. There is no honest image at those moments, so there is none.

def test_the_device_shot_is_skipped_when_the_screen_is_shared(run_env, capsys):
    """No page yet (or any more), shared screen: no image, said out loud."""
    av = _FakeAVController()
    device = _FakeDevice({'web': [_FakeWebController(page=None)], 'av': [av]})

    result = device_utils.capture_screenshot(device, _FakeContext_Report(), '[t]')

    assert result is None
    assert av.calls == 0, "a shared screen capture would show the other run's window"
    assert 'shared' in capsys.readouterr().out


def test_a_step_without_a_page_is_skipped_when_the_screen_is_shared(run_env, capsys):
    av = _FakeAVController()
    device = _FakeDevice({'web': [_FakeWebController(page=None)], 'av': [av]})
    context = _FakeContext_Report()

    assert device_utils.capture_screenshot_for_script(device, context, 'step_1') is None
    assert context.screenshot_paths == []
    assert av.calls == 0
    assert 'shared between' in capsys.readouterr().out


def test_an_hdmi_device_still_gets_its_screen_capture(run_env):
    """A set-top box's screen belongs to it alone: nothing about it changes."""
    av = _FakeAVController(path='/captures/hdmi_0001.jpg', capture_source='HDMI')
    device = _FakeDevice({'web': [_FakeWebController(page=None)], 'av': [av]})

    assert device_utils.capture_screenshot(device, _FakeContext_Report(), '[t]') == '/captures/hdmi_0001.jpg'
    assert av.calls == 1


def test_a_device_that_drives_no_browser_keeps_the_shared_capture(run_env):
    """No web controller at all: this is not a browser run, and the screen is the answer."""
    av = _FakeAVController()
    device = _FakeDevice({'av': [av]})

    assert device_utils.capture_screenshot(device, _FakeContext_Report(), '[t]') == '/captures/capture_0001.jpg'
    assert av.calls == 1


def test_a_live_page_still_wins_over_the_skip(run_env):
    """The skip is only for the no-page moments; a live page is photographed as always."""
    av = _FakeAVController()
    web = _FakeWebController(page=object())
    device = _FakeDevice({'web': [web], 'av': [av]})

    path = device_utils.capture_screenshot(device, _FakeContext_Report(), '[t]')

    assert path and os.path.exists(path)
    assert av.calls == 0


def test_the_controller_takes_the_first_page_of_the_context(tmp_path):
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    first, second = _FakePage(), _FakePage()
    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = _FakeContext([first, second])
    try:
        asyncio.run(controller._photo_page(str(tmp_path / 'shot.png')))
    finally:
        PlaywrightWebController._context = None

    assert first.screenshots, "the run's own page is the one to photograph"
    assert not second.screenshots

def test_the_default_page_screenshot_budget_is_five_seconds():
    """The capture must give up in 5 s, not 20 (TASK-161).

    The capture is queued on the Playwright controller loop, so a busy loop — a
    page still loading, a browser restarted under the run — makes it wait its
    whole budget and then produce nothing. At 20 s that wait was paid twice per
    hop (the hop-start frame and the verification probe): one web tree walk
    spent 21.7 of its 30 minutes in screenshot timeouts and could not finish.
    A viewport screenshot takes ~100 ms when the loop is free, so 5 s is fifty
    times the real cost and the difference is pure waiting.
    """
    import inspect

    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    default = inspect.signature(PlaywrightWebController.capture_page_screenshot)
    assert default.parameters['timeout'].default == 5.0


def test_the_screenshot_carries_its_own_timeout_to_playwright(tmp_path):
    """Playwright must get the budget, not only our wait for the future.

    A screenshot of a page that never settles has no timeout of its own, so it holds
    the Playwright controller loop — and every request queued behind it — until
    something else gives up. In the TASK-161 web smoke that was three minutes per
    hop: the hop's screenshot blocked the loop, the navigation behind it waited, and
    the walker's own 180 s timeout was what finally released it. The walk then failed
    every screen of its second pass.
    """
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    page = _FakePage()
    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller._log = lambda message: None
    controller.__class__._context = _FakeContext([page])
    try:
        result = asyncio.run(controller._photo_page(str(tmp_path / 'shot.png'), timeout=5.0))
    finally:
        PlaywrightWebController._context = None

    assert result is not None
    assert page.timeouts == [5000]
