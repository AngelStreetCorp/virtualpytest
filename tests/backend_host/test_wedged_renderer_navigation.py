"""A wedged renderer and a malformed edge must not kill a web navigation (TASK-161).

Two defects the `web-internetarchive` and `web-dailymotion` smokes found on 2026-10-23:

1. **`params` that are not a mapping.** The `web-dailymotion` entry edge carries
   `"params": ""` on its `activate_semantic` action (the model wrote it). The action
   executor did `raw_params.items()` on that string and raised
   `'str' object has no attribute 'items'`, which killed the navigation and the whole
   smoke with it — 0 checks, 1 failure. Params that are not a mapping mean "no params".

2. **A page title read that never returns.** `page.title()` is a protocol call with no
   timeout of its own. On `archive.org/details/nasa` the donation modal left the
   renderer busy: the page had loaded (`page.url` was the new URL) but the title read
   never came back, so `navigate_to_url` never returned and every later hop of the walk
   died on it — 180 s per hop, and the second pass failed on all of them.

The fix bounds the title read and lets the URL, not the title, decide that a page
loaded.
"""
import asyncio
import os
import sys
import threading

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


# ------------------------------------------------------------------ malformed params


class _FakeWebController:
    def __init__(self):
        self.calls = []

    def send_command(self, command, **params):
        self.calls.append({"command": command, "params": dict(params)})
        return {"success": True, "url": params.get("url")}

    async def execute_command(self, command, params=None):
        self.calls.append({"command": command, "params": dict(params or {})})
        return {"success": True, "url": (params or {}).get("url")}


class _FakeDevice:
    def __init__(self):
        self.host_name = "test-host"
        self.device_id = "host"
        self.device_model = "web"
        self.device_name = "host-test"
        self.navigation_context = {}
        self.get_capture_dir = lambda subfolder="": "/tmp"
        self.web = _FakeWebController()

    def _get_controller(self, name):
        return self.web if name == "web" else None


def _executor():
    from backend_host.src.services.actions.action_executor import ActionExecutor
    return ActionExecutor(_FakeDevice(), _from_device_init=True)


def test_action_with_string_params_runs_instead_of_crashing():
    """`"params": ""` means no params — the action still runs."""
    result = asyncio.run(_executor().execute_actions(actions=[
        {"command": "navigate_to_url", "action_type": "web", "params": ""},
    ]))
    assert result["success"] is True
    assert result["error"] is None


def test_action_with_none_params_runs_too():
    result = asyncio.run(_executor().execute_actions(actions=[
        {"command": "navigate_to_url", "action_type": "web", "params": None},
    ]))
    assert result["success"] is True


def test_real_params_still_reach_the_controller():
    """The fix does not swallow well-formed params."""
    device = _FakeDevice()
    from backend_host.src.services.actions.action_executor import ActionExecutor
    result = asyncio.run(ActionExecutor(device, _from_device_init=True).execute_actions(actions=[
        {"command": "navigate_to_url", "action_type": "web", "params": {"url": "https://example.org/x"}},
    ]))
    assert result["success"] is True
    assert any(c["params"].get("url") == "https://example.org/x" for c in device.web.calls)


# ------------------------------------------------------------------ wedged renderer


class _WedgedPage:
    """A page whose renderer stopped answering: `title()` never returns."""

    def __init__(self, url="https://archive.org/"):
        self.url = url

    async def goto(self, url, timeout=None, wait_until=None):
        raise asyncio.TimeoutError(f"page.goto: Timeout 30000ms exceeded")

    async def title(self):
        await asyncio.sleep(3600)          # a renderer that never answers
        return "never"


class _Utils:
    def normalize_url(self, url):
        return url


def _controller(page):
    from backend_host.src.controllers.web.playwright import PlaywrightWebController
    controller = PlaywrightWebController.__new__(PlaywrightWebController)
    controller.utils = _Utils()
    controller.current_url = ""
    controller.page_title = ""
    controller._flutter_app_detected = None

    async def _page(target_url=None):
        return page

    async def _consent(target_url):
        return None

    async def _dom(page_arg):
        return None

    controller._get_persistent_page = _page
    controller._inject_consent_cookies_if_needed = _consent
    controller._capture_dom_snapshot = _dom
    return controller


def _run_on_this_loop(coro_factory):
    """Run the controller's coroutine on the calling loop, so no controller loop is needed."""
    async def _main():
        controller = _controller(_WedgedPage())
        controller.__class__._loop = asyncio.get_running_loop()
        controller.__class__._loop_thread = threading.current_thread()
        return await coro_factory(controller)

    return asyncio.run(_main())


def test_bounded_title_returns_empty_instead_of_hanging():
    """The title read is bounded: a busy renderer gives an empty title, not a hang."""
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    async def _main():
        controller = PlaywrightWebController.__new__(PlaywrightWebController)
        controller._log = lambda *a, **kw: None
        return await controller._bounded_title(_WedgedPage(), timeout=0.2)

    assert asyncio.run(_main()) == ""


def test_navigation_reports_success_when_the_page_loaded_but_the_title_did_not():
    """The goto timed out, but the URL says the page loaded: that is a navigation."""
    from backend_host.src.controllers.web.playwright import PlaywrightWebController

    async def _main():
        controller = _controller(_WedgedPage())
        controller.__class__._loop = asyncio.get_running_loop()
        controller.__class__._loop_thread = threading.current_thread()
        controller._log = lambda *a, **kw: None
        return await controller.navigate_to_url("https://archive.org/", timeout=30000)

    result = asyncio.run(_main())
    assert result["success"] is True
    assert result["url"] == "https://archive.org/"
    assert "timeout" in (result.get("warning") or "").lower()


def test_dom_capture_skips_a_page_whose_content_never_arrives(monkeypatch):
    """The DOM capture is bounded too: no capture, no hang."""
    from shared.src.lib.utils import dom_capture

    monkeypatch.setattr(dom_capture, "DOM_CONTENT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(dom_capture, "DOM_TITLE_TIMEOUT_S", 0.2)

    class _Stuck:
        url = "https://archive.org/"

        async def content(self):
            await asyncio.sleep(3600)

        async def title(self):
            await asyncio.sleep(3600)

    async def _main():
        return await dom_capture.capture_page_dom(page=_Stuck())

    assert asyncio.run(_main()) == ""
