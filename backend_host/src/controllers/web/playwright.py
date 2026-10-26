"""
Playwright Web Controller Implementation

This controller provides web browser automation functionality using Playwright SYNC API.
Key features: Chrome remote debugging, sync Playwright for thread safety (no async complexity).
Uses playwright_utils for Chrome management.
"""

# =============================================================================
# GLOBAL BROWSER ENGINE CONFIGURATION
# =============================================================================
# Change this to switch between browsers easily:
# - "chromium" = Full Chrome browser (default, ~170MB, high memory)
# - "webkit"   = Safari/WebKit engine (lightweight, ~50MB, low memory)
BROWSER_ENGINE = "chromium"  # chromium is default — better session/cookie handling, login support
# =============================================================================

# WebKit only: the fixed settle delays after a launch. A launched Chromium is waited on by
# readiness instead (a page target on its debug port, see _await_chromium_page).
BROWSER_CONNECT_INIT_WAIT_SECONDS = 2

import os
import json
import time
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from shared.src.lib.utils.phase_timing import (
    t0 as _phase_t0,
    log_duration as _log_duration,
    log_phase as _log_phase,
)

# A browser already serving the debug port when a script takes the device is an orphan:
# the server-side device lock guarantees no other run is driving it (BUG-0179). connect()
# attaches to it when it still answers CDP within this budget, otherwise kills it and
# launches fresh. It never waits for it to go away.
BROWSER_ATTACH_TIMEOUT_SECONDS = float(os.getenv('VPT_WEB_ATTACH_TIMEOUT', '15'))
# Budget for the graceful `Browser.close` sent over CDP at teardown, before the process kill.
BROWSER_CDP_CLOSE_TIMEOUT_SECONDS = 3.0
# input_text settles this long after the fill when the action sets no params.timeout. It was
# 3000 ms, on top of the action's own wait_time that ActionExecutor sleeps afterwards: 3 s per
# typed field for a fill that takes ~30 ms (all 152 stored web input_text actions rely on the
# default, 2026-09-29). 500 ms still covers the usual 250-300 ms debounce of search-as-you-type.
INPUT_TEXT_SETTLE_MS = 500

# Commands agents invent on a web device, and what to use instead (TASK-135 turn-waste analysis)
UNKNOWN_COMMAND_HINTS = {
    'click_element_by_id': "Use click_element with params {'element_id': '#<id>'}. ",
    'type_text': "Use input_text with params {'selector': ..., 'text': ...}. ",
    'execute_pyautogui': "execute_pyautogui_* is a desktop command: send it with action_type 'desktop', "
                         "or on the page use press_key, input_text or tap_x_y. ",
}


def unknown_command_hint(command: str) -> str:
    return next((h for k, h in UNKNOWN_COMMAND_HINTS.items() if command.startswith(k)), '')

# =============================================================
# Single decorator to guarantee execution on controller loop
# =============================================================
# How long a caller waits for the controller loop to answer. The loop is one thread for
# every Playwright op of this host, so when it wedges an unbounded wait left the run and
# its browser alive for ever (BUG-0842). The wait is bounded and the failure says so.
CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS = float(os.getenv('VPT_CONTROLLER_LOOP_TIMEOUT', '120'))


def _controller_loop_result(fut, timeout: Optional[float] = None):
    """The controller loop's answer, waited for with a bound.

    ``fut.result()`` without a timeout blocked for ever when the loop never completed the
    coroutine: the run never reported and its browser never came down (BUG-0842).
    """
    import concurrent.futures
    budget = CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return fut.result(timeout=budget)
    except concurrent.futures.TimeoutError:
        fut.cancel()
        raise TimeoutError(
            f'The Playwright controller loop did not answer within {budget:g}s') from None


def ensure_controller_loop(func):
    async def wrapper(self, *args, **kwargs):
        import asyncio
        # Ensure controller loop exists
        self._ensure_loop()
        controller_loop = self.__class__._loop
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is controller_loop:
            return await func(self, *args, **kwargs)
        fut = self._submit_to_controller_loop(func(self, *args, **kwargs))
        if current_loop is None:
            return _controller_loop_result(fut)
        # Bounded, and the bound really bounds: `asyncio.wait` leaves the pending work
        # alone on timeout, where `wait_for` waits for a cancellation that a running
        # coroutine never grants.
        wrapped = asyncio.wrap_future(fut)
        done, _pending = await asyncio.wait(
            {wrapped}, timeout=CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS)
        if not done:
            wrapped.cancel()
            raise TimeoutError(
                f'The Playwright controller loop did not answer within '
                f'{CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS:g}s')
        return wrapped.result()
    return wrapper
from ..base_controller import WebControllerInterface

# Use absolute import for utils from shared library
import sys
import os
# Get path to shared/lib/utils
shared_utils_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'shared', 'lib', 'utils')
if shared_utils_path not in sys.path:
    sys.path.insert(0, shared_utils_path)

from  backend_host.src.lib.utils.playwright_utils import (
    PlaywrightUtils,
    stop_playwright,
    CHROME_READY_POLL_S,
    CHROME_PAGE_READY_MAX_WAIT_S,
)
from  backend_host.src.lib.utils.webkit_utils import WebKitUtils
# Import browseruse_utils only when needed to avoid browser_use dependency at module load
# from  backend_host.src.lib.utils.browseruse_utils import BrowserUseManager

# Import verification mixin
from .playwright_verifications import PlaywrightVerificationsMixin


GOTO_TIMEOUT_MIN_MS = int(os.environ.get('VPT_WEB_GOTO_TIMEOUT_MIN_MS', '15000'))
GOTO_TIMEOUT_DEFAULT_MS = int(os.environ.get('VPT_WEB_GOTO_TIMEOUT_MS', '30000'))


def resolve_goto_timeout(params: Dict[str, Any]) -> int:
    """Page-load timeout (ms) of navigate_to_url: `page_load_timeout` or legacy `timeout`, never `wait_time`.
    Never below VPT_WEB_GOTO_TIMEOUT_MIN_MS (15 s), so a short edge pause cannot make a slow page fail."""
    asked = params.get('page_load_timeout') or params.get('timeout') or GOTO_TIMEOUT_DEFAULT_MS
    try:
        asked = int(asked)
    except (TypeError, ValueError):
        asked = GOTO_TIMEOUT_DEFAULT_MS
    return max(asked, GOTO_TIMEOUT_MIN_MS)


class PlaywrightWebController(PlaywrightVerificationsMixin, WebControllerInterface):
    """Playwright web controller using async Playwright with sync wrappers for browser-use compatibility."""
    
    # Class-level Chrome process management
    _chrome_process = None
    _chrome_running = False
    
    # Class-level persistent Playwright browser and context (reuse)
    _playwright = None
    _browser = None
    _context = None
    _browser_connected = False
    
    # Dedicated controller event loop (single place for all Playwright ops)
    _loop = None
    _loop_thread = None
    _connect_fallback_in_progress = False
    
    def __init__(self, browser_engine: str = None, **kwargs):
        """
        Initialize the Playwright web controller.
        
        Args:
            browser_engine: "chromium" or "webkit" (uses BROWSER_ENGINE global if None)
        """
        super().__init__("Playwright Web", "playwright")
        #import os
        #os.environ['DEBUG'] = 'pw:api'  # Enable Playwright API debug logs
        #os.environ['PLAYWRIGHT_DEBUG'] = '1'  # Enable additional debug info
        
        # Choose browser engine (use global default if not specified)
        self.browser_engine = browser_engine if browser_engine is not None else BROWSER_ENGINE
        
        if self.browser_engine == "webkit":
            self.utils = WebKitUtils()
            print(f"[@controller:PlaywrightWeb] Initialized with lightweight WebKit browser (global setting, SYNC API)")
        else:
            self.utils = PlaywrightUtils(auto_accept_cookies=True, use_cgroup=False)
            print(f"[@controller:PlaywrightWeb] Initialized with Chromium browser (global setting, cgroup disabled, SYNC API)")
        
        # Command execution state
        self.last_command_output = ""
        self.last_command_error = ""
        self.current_url = ""
        self.page_title = ""

        # Flutter semantics tracking (lazy activation on first dump)
        self._flutter_app_detected = None  # None = unknown, True = Flutter, False = not Flutter

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[PLAYWRIGHT {timestamp}]: {message}")

    def _summarize_script(self, script: str) -> str:
        compact = " ".join((script or "").split())
        if not compact:
            return "js:empty"
        digest = hashlib.sha1(compact.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        return f"js:{digest} {compact[:80]}"

    # =============================================================
    # Controller loop management (single long-lived asyncio loop)
    # =============================================================
    def _ensure_loop(self):
        """Ensure a dedicated event loop thread exists for Playwright ops."""
        if self.__class__._loop and self.__class__._loop_thread and self.__class__._loop_thread.is_alive():
            return
        import threading, asyncio
        def _loop_worker():
            loop = asyncio.new_event_loop()
            self.__class__._loop = loop
            asyncio.set_event_loop(loop)
            loop.run_forever()
        t = threading.Thread(target=_loop_worker, name="PlaywrightControllerLoop", daemon=True)
        t.start()
        self.__class__._loop_thread = t
        # Give the loop a brief moment to start
        import time as _time
        start = _time.time()
        while self.__class__._loop is None and (_time.time() - start) < 1.0:
            _time.sleep(0.01)
    
    def _submit_to_controller_loop(self, coro):
        """Submit a coroutine to the controller loop and return a concurrent.futures.Future."""
        self._ensure_loop()
        import asyncio
        return asyncio.run_coroutine_threadsafe(coro, self.__class__._loop)

    # _redirect_if_needed removed; unified with @ensure_controller_loop

    def _reset_state(self):
        """Reset class-level persistent browser state flags and references."""
        self.__class__._playwright = None
        self.__class__._browser = None
        self.__class__._context = None
        self.__class__._browser_connected = False

    async def _drop_playwright_handles(self):
        """Forget the Playwright handles, stopping the driver first. Clearing `_playwright`
        without `stop()` leaves its Node driver running for the life of vpt-host (BUG-0191)."""
        playwright = self.__class__._playwright
        self._reset_state()
        await stop_playwright(playwright)

    @property
    def is_connected(self):
        """Always connected once Chrome is running."""
        # Check if Chrome process is actually still alive
        if self.__class__._chrome_process and self.__class__._chrome_running:
            if self.__class__._chrome_process.poll() is not None:
                # Chrome process has died
                print(f"[PLAYWRIGHT]: Chrome process {self.__class__._chrome_process.pid} has died (exit code: {self.__class__._chrome_process.returncode})")
                self.__class__._chrome_running = False
                self.__class__._browser_connected = False
                self.__class__._chrome_process = None
        
        result = self.__class__._chrome_running
        print(f"[PLAYWRIGHT]: is_connected check - _chrome_running={self._chrome_running}, returning {result}")
        return result
    
    @is_connected.setter
    def is_connected(self, value):
        """Setter for base controller compatibility - only sets True when Chrome launches."""
        if value:
            self.__class__._chrome_running = True
        # Ignore False values - once connected, always connected
    
    @ensure_controller_loop
    async def _get_persistent_page(self, target_url: str = None):
        """Get the persistent page from browser+context, creating/connecting if needed."""
        # Ensure we have a connected browser/context
        # Prefer concrete browser/context objects over boolean flags to avoid stale state
        if not self.__class__._browser or not self.__class__._context:
            # Try to establish a connection (does NOT kill Chrome)
            connect_result = await self.connect_browser()
            if not connect_result or not connect_result.get('success'):
                raise RuntimeError(f"Unable to get persistent page: connect_browser failed: {connect_result.get('error') if isinstance(connect_result, dict) else 'unknown error'}")

        context = self.__class__._context
        if context is None:
            raise RuntimeError("Unable to get persistent page: browser context is not available")

        # Reuse first page if any, else create a new page
        try:
            return await self._page_from_context(context)
        except Exception as e:
            # The cached context is dead (Chrome exited, the window was closed, the CDP
            # session dropped): Playwright raises TargetClosedError from BrowserContext.new_page
            # and every later call would too, because the class-level handles were never
            # reset. Seen 2026-09-27 (agent session 39d2c4e2): 360 execute_device_action
            # calls over 26 minutes, all failing on the same closed context. Drop the dead
            # handles and connect once more before giving up.
            print(f"[PLAYWRIGHT]: Page acquisition failed ({type(e).__name__}: {e}) — dropping dead browser handles and reconnecting")
            await self._drop_playwright_handles()
            connect_result = await self.connect_browser()
            if not connect_result or not connect_result.get('success'):
                raise RuntimeError(
                    f"Failed to acquire page from context: {type(e).__name__}: {e}; "
                    f"reconnect failed: {connect_result.get('error') if isinstance(connect_result, dict) else 'unknown error'}"
                )
            context = self.__class__._context
            if context is None:
                raise RuntimeError("Failed to acquire page: browser context is not available after reconnect")
            try:
                return await self._page_from_context(context)
            except Exception as retry_error:
                raise RuntimeError(f"Failed to acquire page from context after reconnect: {type(retry_error).__name__}: {retry_error}")

    @staticmethod
    async def _page_from_context(context):
        pages = context.pages
        if pages and len(pages) > 0:
            return pages[0]
        return await context.new_page()
    
    def _kill_browser_process(self) -> bool:
        """Kill the browser process this controller drove. No loop, no CDP, no waiting.

        The graceful close is a nicety, the process kill is the guarantee, and the
        guarantee must not depend on the graceful step: when the close hung, the kill
        that sat behind it never ran and the browser outlived the run (BUG-0760).
        """
        used_a_browser = (self.__class__._chrome_process is not None or self.__class__._browser is not None
                          or self.__class__._chrome_running)
        if not used_a_browser:
            # Only when this run used a browser at all: a script that never touched the
            # web controller has no business taking down a browser somebody opened by hand.
            print(f"[PLAYWRIGHT]: No browser was launched or attached by this run; leaving the debug port alone")
            return False
        try:
            return bool(self.utils.kill_chrome(chrome_process=self.__class__._chrome_process))
        except Exception as e:
            print(f"[PLAYWRIGHT]: Chrome kill error ignored: {type(e).__name__}: {str(e)}")
            return False

    async def _cleanup_persistent_browser(self):
        """Close the browser this run used, whether it launched it or attached to one.

        Graceful first: `Browser.close` over the CDP connection we already hold (the
        only real CDP shutdown; there is no HTTP endpoint for it). Then the hard
        guarantee: terminate the launched process group, and whatever still listens
        on the debug port. The next run must find the port free (BUG-0179).
        """
        print(f"[PLAYWRIGHT]: Cleaning up persistent browser+context...")
        browser = self.__class__._browser
        _t = _phase_t0()
        if browser is not None and self.browser_engine != "webkit":
            try:
                session = await browser.new_browser_cdp_session()
                await asyncio.wait_for(session.send('Browser.close'), timeout=BROWSER_CDP_CLOSE_TIMEOUT_SECONDS)
                print(f"[PLAYWRIGHT]: Browser.close sent over CDP")
            except Exception as e:
                # The browser usually drops the connection while answering; the kill below covers it.
                print(f"[PLAYWRIGHT]: CDP Browser.close did not complete ({type(e).__name__}: {e}); falling back to process kill")
        _log_phase('web.cleanup.cdp_browser_close', _t)
        _t = _phase_t0()
        try:
            if browser is not None:
                await asyncio.wait_for(browser.close(), timeout=BROWSER_CDP_CLOSE_TIMEOUT_SECONDS)
        except Exception as e:
            print(f"[PLAYWRIGHT]: Browser close error ignored: {type(e).__name__}: {str(e)}")
        _log_phase('web.cleanup.playwright_browser_close', _t)

        # Hard guarantee: the launched process group (if any) and then any listener still
        # on the port - a browser this run only attached to has no Popen to terminate.
        _t = _phase_t0()
        self._kill_browser_process()
        _log_phase('web.cleanup.kill_chrome', _t)
        _t = _phase_t0()
        await stop_playwright(self.__class__._playwright)
        _log_phase('web.cleanup.stop_playwright', _t)

        # Reset flags/state
        self.__class__._playwright = None
        self.__class__._browser = None
        self.__class__._context = None
        self.__class__._browser_connected = False
        self.__class__._chrome_process = None
        self.__class__._chrome_running = False
        print(f"[PLAYWRIGHT]: Persistent browser+context cleaned up and Chrome process terminated")

    async def _cleanup_persistent_browser_with_timeout(self, timeout_seconds: int = 15):
        """Cleanup wrapper that enforces a timeout so it never blocks navigation."""
        import asyncio
        try:
            await asyncio.wait_for(self._cleanup_persistent_browser(), timeout=timeout_seconds)
        except Exception as e:
            print(f"[PLAYWRIGHT]: Cleanup timed out or failed: {type(e).__name__}: {str(e)}")
            # The graceful close hung, so the browser is still alive: kill it here.
            # The kill used to sit only INSIDE the routine, behind the graceful close,
            # so a hang there left the browser running while the controller believed
            # there was none - and nothing else ever came back for it (BUG-0760).
            self._kill_browser_process()
            # Cut off before (or while) stopping Playwright: its driver must not outlive the
            # run (BUG-0191). A browser left on the port is an orphan the next connect handles.
            await self._drop_playwright_handles()
            self.__class__._chrome_process = None
            self.__class__._chrome_running = False
    
    async def _attach_to_chromium(self) -> None:
        """Attach over CDP to the Chromium already on the debug port and adopt its first
        context/page as this run's persistent handles. Raises when it does not answer
        within BROWSER_ATTACH_TIMEOUT_SECONDS; the Playwright instance is stopped on failure."""
        playwright = browser = None
        try:
            playwright, browser, context, page = await asyncio.wait_for(
                self.utils.connect_to_chrome(), timeout=BROWSER_ATTACH_TIMEOUT_SECONDS)
            # A browser whose page no longer executes anything is not worth keeping.
            await asyncio.wait_for(page.evaluate('1'), timeout=BROWSER_ATTACH_TIMEOUT_SECONDS)
        except BaseException:
            for closer in ((browser.close if browser else None), (playwright.stop if playwright else None)):
                if closer is None:
                    continue
                try:
                    await closer()
                except Exception:
                    pass
            raise
        self.__class__._playwright = playwright
        self.__class__._browser = browser
        self.__class__._context = context
        self.__class__._browser_connected = True
        self.current_url = page.url

    async def _claim_chromium(self) -> str:
        """The connect decision for Chromium. Returns 'launched' or 'reused'. Never waits.

        Port free  -> launch.
        Port busy  -> the browser there is an orphan (the device lock is what keeps two runs
                      off one browser, so nobody else can be driving it): attach to it and
                      reuse it; if it does not answer, kill its process group and launch fresh.
        """
        chrome_manager = self.utils.chrome_manager
        if chrome_manager.cdp_healthy(self.utils.debug_port):
            self._log(f"A CHROMIUM is already on debug port {self.utils.debug_port} (orphan of a previous run) - attaching to it")
            try:
                await self._attach_to_chromium()
                self.__class__._chrome_process = None
                self._log(f"Reusing the CHROMIUM on port {self.utils.debug_port} (url={self.current_url})")
                return 'reused'
            except Exception as e:
                self._log(f"Attach failed ({type(e).__name__}: {e}) - killing that CHROMIUM and launching fresh")
                chrome_manager.shutdown_chrome(self.utils.debug_port)
        self._log("CHROMIUM not running, launching new process...")
        self.__class__._chrome_process = self.utils.launch_chrome()
        return 'launched'

    async def _await_chromium_page(self, phase: str) -> bool:
        """Wait until the Chromium on the debug port lists a page target: what the fixed 2 s
        sleeps after a launch were standing in for. Returns at once when the launcher already
        saw it; gives up after CHROME_PAGE_READY_MAX_WAIT_S (the sleeps' own total) and lets
        the caller carry on as the sleeps did."""
        chrome_manager = self.utils.chrome_manager
        max_polls = max(1, int(CHROME_PAGE_READY_MAX_WAIT_S / CHROME_READY_POLL_S))
        deadline = time.monotonic() + CHROME_PAGE_READY_MAX_WAIT_S
        _t = _phase_t0()
        polls, ready = 0, False
        while True:
            polls += 1
            ready = await asyncio.to_thread(chrome_manager.cdp_page_ready, self.utils.debug_port)
            if ready or polls >= max_polls or time.monotonic() >= deadline:
                break
            await asyncio.sleep(CHROME_READY_POLL_S)
        _log_phase(phase, _t, f"ready={ready} polls={polls}")
        return ready

    def _debug_port_has_listener(self) -> bool:
        """Whether anything listens on the Chromium debug port. When nothing does, attaching is
        pointless: each attempt starts a Playwright driver (~1.6 s) to be refused."""
        if self.browser_engine == "webkit":
            return True  # unchanged: WebKit always tries its attach first
        return self.utils.chrome_manager.port_listening(self.utils.debug_port)

    @ensure_controller_loop
    async def connect(self) -> bool:
        """Give this process a browser on the debug port: launch one, or adopt the one there."""
        browser_name = self.browser_engine.upper()
        self._log(f"connect() called - _{self.browser_engine}_running={self._chrome_running}, _process={self._chrome_process}")

        if not self._chrome_running:
            try:
                _t = _phase_t0()
                if self.browser_engine == "webkit":
                    self._log(f"{browser_name} not running, launching new process...")
                    self.__class__._chrome_process = self.utils.launch_webkit()
                    outcome = 'launched'
                else:
                    outcome = await self._claim_chromium()
                _log_phase('web.claim_or_launch_browser', _t, f"outcome={outcome}")
                self.__class__._chrome_running = True
                if outcome == 'launched':
                    self._log(f"{browser_name} launched with remote debugging successfully (PID: {self._chrome_process.pid})")
                    if self.browser_engine == "webkit":
                        _t = _phase_t0()
                        await asyncio.sleep(2)
                        _log_phase('web.post_launch_fixed_sleep', _t, 'connect() startup delay')
                    else:
                        await self._await_chromium_page('web.post_launch_ready')
                    self._log(f"{browser_name} startup delay completed")

            except Exception as e:
                error_type = type(e).__name__
                self._log(f"Failed to launch {browser_name} - {error_type}: {str(e)}")
                return False
        else:
            self._log(f"{browser_name} process already running (PID: {self._chrome_process.pid if self._chrome_process else 'attached'})")

        self._log(f"connect() completed - running={self._chrome_running}, is_connected={self.is_connected}")
        return True
    

    
    @ensure_controller_loop
    async def open_browser(self) -> Dict[str, Any]:
        """Open/launch the browser window with a single launch/connect attempt."""
        try:
            self._log("Opening browser - single launch/connect attempt")
            start_time = time.time()

            if not self.is_connected:
                self._log("Chrome not running, launching...")
            await self.connect()

            page = await self._get_persistent_page()

            if page.url in ['about:blank', '', 'chrome://newtab/']:
                await page.goto('https://google.fr')

            self.current_url = page.url
            self.page_title = await page.title()

            execution_time = int((time.time() - start_time) * 1000)
            self._log(f"Browser opened and ready in {execution_time}ms")
            return {
                'success': True,
                'error': '',
                'execution_time': execution_time,
                'connected': True
            }
            
        except Exception as e:
            error_msg = f"Browser open error: {e}"
            self._log(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0,
                'connected': False
            }
        
    @ensure_controller_loop
    async def connect_browser(self) -> Dict[str, Any]:
        """Connect to existing Chrome debug session without killing Chrome first.
        OPTIMIZED: Skip reconnection if already connected, skip sleep if Chrome already running.
        """
        import asyncio  # ✅ Import asyncio at the start of the method
        try:
            start_time = time.time()
            
            # ✅ OPTIMIZATION 1: Check if already connected - skip reconnection
            if self.__class__._chrome_running and self.__class__._browser_connected and self.__class__._browser and self.__class__._context:
                print(f"[PLAYWRIGHT]: Already connected to Chrome (PID: {self.__class__._chrome_process.pid if self.__class__._chrome_process else 'unknown'}), reusing connection")
                
                # Verify by accessing context/pages directly (avoid circular _get_persistent_page call)
                try:
                    context = self.__class__._context
                    pages = context.pages
                    page = pages[0] if pages and len(pages) > 0 else await context.new_page()
                    self.current_url = page.url
                    
                    # Get page title with timeout (heavy pages like YouTube might be slow)
                    try:
                        self.page_title = await asyncio.wait_for(page.title(), timeout=2.0) if page.url != 'about:blank' else ''
                    except asyncio.TimeoutError:
                        print(f"[PLAYWRIGHT]: Page title timeout (page busy), using empty title")
                        self.page_title = ''
                    
                    execution_time = int((time.time() - start_time) * 1000)
                    print(f"[PLAYWRIGHT]: Reused existing connection (verified via context/pages)")
                    return {
                        'success': True,
                        'error': '',
                        'execution_time': execution_time,
                        'connected': True,
                        'current_url': self.current_url,
                        'page_title': self.page_title,
                        'reused_connection': True
                    }
                except Exception as verify_error:
                    print(f"[PLAYWRIGHT]: Connection verification failed ({verify_error}), will reconnect...")
                    # Fall through to reconnection logic
            
            print(f"[PLAYWRIGHT]: Connecting to Chrome debug session")
            # A connection that failed verification above is replaced below: stop its driver.
            if self.__class__._playwright is not None:
                await self._drop_playwright_handles()

            # ✅ OPTIMIZATION 2: Track if Chrome was already running before connect()
            chrome_was_already_running = self.__class__._chrome_running
            
            # Try to connect to existing Chrome debug session (no killing Chrome first)
            _t_first_attach = _phase_t0()
            try:
                if not self._debug_port_has_listener():
                    # Nothing to attach to: go straight to the launch below.
                    raise ConnectionRefusedError(f"nothing listens on debug port {self.utils.debug_port}")
                # For existing Chrome, just connect without creating new context
                self.__class__._playwright, self.__class__._browser, self.__class__._context, page = await self.utils.connect_to_chrome()
                _log_phase('web.connect_to_existing_chrome', _t_first_attach, 'ok=True')
                self.__class__._browser_connected = True
                # This run now owns that browser: a later connect() must not attach to it a
                # second time, and teardown must close it even though no Popen was launched.
                self.__class__._chrome_running = True

                # Get current page info from persistent page
                self.current_url = page.url
                self.page_title = await page.title() if page.url != 'about:blank' else ''

                execution_time = int((time.time() - start_time) * 1000)

                print(f"[PLAYWRIGHT]: Connected to existing Chrome debug session")
                return {
                    'success': True,
                    'error': '',
                    'execution_time': execution_time,
                    'connected': True,
                    'current_url': self.current_url,
                    'page_title': self.page_title
                }
                
            except Exception as e:
                # Chrome debug session not available - try to launch Chrome instead
                _log_phase('web.connect_to_existing_chrome', _t_first_attach, f"ok=False ({type(e).__name__})")
                print(f"[PLAYWRIGHT]: No existing Chrome found ({e}), launching new Chrome...")
                try:
                    # Launch Chrome and connect
                    _t = _phase_t0()
                    connect_result = await self.connect()
                    _log_phase('web.connect_launch', _t, f"ok={connect_result}")
                    if not connect_result:
                        raise Exception("Failed to launch Chrome")
                    
                    if self.__class__._browser is not None and self.__class__._context is not None:
                        # connect() adopted the browser that was already on the port: the
                        # handles are live, a second attach would only leak a Playwright instance.
                        print(f"[PLAYWRIGHT]: connect() attached to the existing Chrome, reusing its handles")
                        page = await self._page_from_context(self.__class__._context)
                    else:
                        # Avoid long startup delays; launch readiness should already be handled by the launcher.
                        if not chrome_was_already_running and self.browser_engine == "webkit":
                            print(f"[PLAYWRIGHT]: Chrome was just launched, waiting {BROWSER_CONNECT_INIT_WAIT_SECONDS}s for initialization...")
                            _t = _phase_t0()
                            await asyncio.sleep(BROWSER_CONNECT_INIT_WAIT_SECONDS)
                            _log_phase('web.connect_init_fixed_sleep', _t, 'BROWSER_CONNECT_INIT_WAIT_SECONDS')
                        elif not chrome_was_already_running:
                            print(f"[PLAYWRIGHT]: Chrome was just launched, waiting for its page target...")
                            await self._await_chromium_page('web.connect_init_ready')
                        else:
                            print(f"[PLAYWRIGHT]: Chrome was already running, skipping initialization delay")

                        # Now connect to the Chrome debug session to get browser/context/page
                        _t = _phase_t0()
                        if self.__class__._playwright is not None:
                            await self._drop_playwright_handles()
                        self.__class__._playwright, self.__class__._browser, self.__class__._context, page = await self.utils.connect_to_chrome()
                        self.__class__._browser_connected = True
                        _log_phase('web.connect_to_launched_chrome', _t)
                    
                    # Update page state
                    self.current_url = page.url
                    self.page_title = await page.title()
                    
                    execution_time = int((time.time() - start_time) * 1000)
                    print(f"[PLAYWRIGHT]: Launched new Chrome and connected successfully")
                    return {
                        'success': True,
                        'error': '',
                        'execution_time': execution_time,
                        'connected': True,
                        'current_url': self.current_url,
                        'page_title': self.page_title,
                        'launched_new': not chrome_was_already_running
                    }
                except Exception as launch_error:
                    error_msg = f"Could not connect to existing Chrome and failed to launch new Chrome: {launch_error}"
                    print(f"[PLAYWRIGHT]: {error_msg}")
                    return {
                        'success': False,
                        'error': error_msg,
                        'execution_time': 0,
                        'connected': False
                    }
            
        except Exception as e:
            error_msg = f"Browser connection error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0,
                'connected': False
            }
    
    def _browser_still_running(self) -> Optional[int]:
        """The pid of the browser that still holds our debug port, or None.

        This is what tells "the browser is closed" from "the close was only asked for".
        A close that cannot answer that question must not report success (BUG-0760).
        """
        from shared.src.lib.utils.leaked_browser_reaper import browser_pid_for_port, pid_is_running
        port = getattr(self.utils, 'debug_port', None)
        if not port:
            return None
        try:
            pid = browser_pid_for_port(int(port))
        except (TypeError, ValueError):
            return None
        if pid and pid_is_running(pid):
            return pid
        return None

    def close_browser(self, wait: bool = False, wait_timeout: float = 22.0) -> Dict[str, Any]:
        """Clean up the persistent browser/Chrome process.

        By default this only schedules the cleanup on the controller loop and
        returns immediately (non-blocking, safe to call from the navigation
        thread). Pass wait=True to block until the cleanup actually finishes
        (browser.close() + playwright.stop() + Chrome process killed) - the
        loop thread is a daemon thread, so a caller that's about to exit the
        process (e.g. end-of-script teardown) MUST wait=True or the cleanup
        can be cut off mid-flight and leave Chrome running.

        The result says what really happened: with wait=True, ``success`` means the
        browser is gone; without it, the close is only scheduled, so ``confirmed`` is
        False and ``browser_still_running`` names the pid that is still there.
        """
        print(f"[PLAYWRIGHT]: {'Waiting for' if wait else 'Scheduling non-blocking'} browser cleanup")
        # Pre-emptively mark disconnected so next actions reconnect if needed
        self.__class__._browser_connected = False
        scheduled = False
        waited = False
        error = ''
        try:
            # Ensure cleanup runs on the controller loop where Playwright objects live
            fut = self._submit_to_controller_loop(self._cleanup_persistent_browser_with_timeout(15))
            scheduled = True
            if wait:
                try:
                    fut.result(timeout=wait_timeout)
                    waited = True
                except Exception as e:
                    error = f'{type(e).__name__}: {e}'
                    print(f"[PLAYWRIGHT]: Timed out waiting for browser cleanup ({error}); continuing")
        except RuntimeError as e:
            error = f'{type(e).__name__}: {e}'
            # No running loop (unlikely since execute_command is async) - best effort fallback: do nothing blocking
            print(f"[PLAYWRIGHT]: No running asyncio loop; skipping async cleanup scheduling")
        still_running = self._browser_still_running()
        confirmed = still_running is None
        if not confirmed:
            print(f"[PLAYWRIGHT]: Browser {still_running} is still running after the close")
        return {
            # success means the browser is gone. A close that was only scheduled says
            # so: it never reports a close that did not happen (BUG-0760).
            'success': confirmed,
            'error': '' if confirmed else (error or f'the browser is still running (pid {still_running})'),
            'execution_time': 0,
            'connected': False,
            'scheduled_async_cleanup': scheduled,
            'waited_for_cleanup': waited,
            'confirmed': confirmed,
            'browser_still_running': still_running,
        }

    async def close_browser_confirmed(self, wait_timeout: float = 22.0) -> Dict[str, Any]:
        """Close the browser and wait for the result, so the answer is a confirmation.

        The cleanup runs on the controller loop; awaiting its future leaves the
        caller's event loop free while the browser really goes away. A caller that
        trusts this result is told the truth: success means the browser is gone.
        """
        print(f"[PLAYWRIGHT]: Waiting for browser cleanup")
        # Pre-emptively mark disconnected so next actions reconnect if needed
        self.__class__._browser_connected = False
        scheduled = False
        waited = False
        error = ''
        try:
            fut = self._submit_to_controller_loop(self._cleanup_persistent_browser_with_timeout(15))
            scheduled = True
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(fut, loop=asyncio.get_running_loop()),
                    timeout=wait_timeout)
                waited = True
            except asyncio.TimeoutError:
                error = f'The browser cleanup did not finish within {wait_timeout}s'
                print(f"[PLAYWRIGHT]: {error}")
            except Exception as e:
                error = f'{type(e).__name__}: {e}'
                print(f"[PLAYWRIGHT]: Browser cleanup failed ({error})")
        except RuntimeError as e:
            error = f'{type(e).__name__}: {e}'
            # No running loop (unlikely since execute_command is async) - best effort fallback: do nothing blocking
            print(f"[PLAYWRIGHT]: No running asyncio loop; skipping async cleanup scheduling")
        still_running = self._browser_still_running()
        confirmed = still_running is None
        if not confirmed:
            print(f"[PLAYWRIGHT]: Browser {still_running} is still running after the close")
        return {
            'success': confirmed,
            'error': '' if confirmed else (error or f'the browser is still running (pid {still_running})'),
            'execution_time': 0,
            'connected': False,
            'scheduled_async_cleanup': scheduled,
            'waited_for_cleanup': waited,
            'confirmed': confirmed,
            'browser_still_running': still_running,
        }
    
    async def _inject_consent_cookies_if_needed(self, url: str) -> bool:
        """Inject consent cookies for YouTube/Google domains before navigation.
        
        Returns True if cookies were injected, False otherwise.
        """
        # Check if URL is YouTube or Google domain
        consent_domains = [
            ('.youtube.com', 'YouTube'),
            ('.google.com', 'Google'),
            ('.google.fr', 'Google FR'),
            ('.google.de', 'Google DE'),
            ('.google.co.uk', 'Google UK'),
            ('.googlevideo.com', 'Google Video'),
        ]
        
        target_domain = None
        domain_name = None
        
        for domain, name in consent_domains:
            if domain in url or domain.lstrip('.') in url:
                target_domain = domain
                domain_name = name
                break
        
        if not target_domain:
            return False
        
        try:
            context = self.__class__._context
            if not context:
                print(f"[PLAYWRIGHT]: No context available for cookie injection")
                return False
            
            # Generate consent cookie value (format: YES+cb.{date}-17-p0.en+FX+{random})
            import random
            from datetime import datetime
            date_str = datetime.now().strftime('%Y%m%d')
            random_suffix = random.randint(100, 999)
            consent_value = f'YES+cb.{date_str}-17-p0.en+FX+{random_suffix}'
            
            # Inject consent cookies for all Google/YouTube domains
            cookies_to_inject = [
                {'name': 'CONSENT', 'value': consent_value, 'domain': '.youtube.com', 'path': '/'},
                {'name': 'CONSENT', 'value': consent_value, 'domain': '.google.com', 'path': '/'},
                {'name': 'CONSENT', 'value': consent_value, 'domain': '.google.fr', 'path': '/'},
                {'name': 'CONSENT', 'value': consent_value, 'domain': '.google.de', 'path': '/'},
                {'name': 'CONSENT', 'value': consent_value, 'domain': '.google.co.uk', 'path': '/'},
                # SOCS cookie (newer Google consent format)
                {'name': 'SOCS', 'value': 'CAISHAgBEhJnd3NfMjAyMzEyMTUtMF9SQzEaAmVuIAEaBgiA_LCrBg', 'domain': '.youtube.com', 'path': '/'},
                {'name': 'SOCS', 'value': 'CAISHAgBEhJnd3NfMjAyMzEyMTUtMF9SQzEaAmVuIAEaBgiA_LCrBg', 'domain': '.google.com', 'path': '/'},
            ]
            
            await context.add_cookies(cookies_to_inject)
            print(f"[PLAYWRIGHT]: Injected consent cookies for {domain_name} ({target_domain})")
            return True
            
        except Exception as e:
            print(f"[PLAYWRIGHT]: Failed to inject consent cookies: {e}")
            return False
    
    async def _capture_dom_snapshot(self, page) -> None:
        """Record page DOM for the execution report; deduped per page in dom_capture."""
        try:
            from shared.src.lib.utils.dom_capture import capture_page_dom, page_name_from_url
            await capture_page_dom(page=page, name=page_name_from_url(page.url))
        except Exception as e:
            self._log(f"DOM capture skipped: {e}")

    async def _photo_page(self, path: str, timeout: float = 5.0) -> Optional[str]:
        """The half of `capture_page_screenshot` that has to run on the controller loop."""
        context = self.__class__._context
        if context is None:
            return None
        try:
            pages = context.pages
        except Exception as e:
            self._log(f"Page screenshot skipped (no pages): {type(e).__name__}: {e}")
            return None
        if not pages:
            return None
        page = pages[0]
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            # The timeout belongs to Playwright, not only to our wait for the future: a
            # screenshot of a page that never settles has no timeout of its own, so it
            # holds the controller loop — and every request queued behind it — until
            # something else gives up. In the TASK-161 web smoke that was three minutes
            # per hop: the hop's own screenshot blocked the loop, the navigation behind
            # it waited, and the walker's 180 s navigation timeout was what finally
            # released it. The walk then failed every screen of the second pass.
            await page.screenshot(path=path, full_page=False, timeout=max(1, int(timeout * 1000)))
        except Exception as e:
            self._log(f"Page screenshot skipped: {type(e).__name__}: {e}")
            return None
        return path

    def capture_page_screenshot(self, path: str, timeout: float = 5.0) -> Optional[str]:
        """Write a screenshot of THIS run's own page to `path`, and return the path.

        Every browser run on a host shares one X display (`DISPLAY=:1`), so the
        screen capture the report used to fall back on (VNC / x11grab, the newest
        file of the host's capture folder) shows whichever Chrome window happens to
        be on top — with parallel runs that is regularly the *other* run's browser
        (TASK-146). A page screenshot belongs to the run that took it.

        Returns None when there is no live page to photograph, or when the
        screenshot fails; the caller then falls back to the screen capture. It
        never opens a new page: a screenshot must not change what the run is doing.

        Deliberately **not** `@ensure_controller_loop`. That decorator answers two
        different ways: `fut.result()` from a plain thread, but an *awaitable* when
        the caller already has a running loop — so a caller that asked for a path
        received a coroutine and failed on `os.path.exists()` with `stat: path should
        be string, bytes, os.PathLike or integer, not coroutine`, which the caller
        swallowed and fell back to the screen capture (seen live 2026-10-21, twice).
        Submitting to the controller loop and blocking on the future gives the same
        answer to either kind of caller, and the timeout stops a wedged driver from
        stalling the run.

        The default timeout is **5 s, not 20**: the capture is queued on the same
        controller loop as the navigation, so a busy loop (a page still loading, a
        browser that was restarted under the run) makes it wait its whole budget and
        then produce nothing. A viewport screenshot takes ~100 ms when the loop is
        free — measured 79-107 ms on the TASK-161 web smokes — so 5 s is fifty times
        the real cost, and the difference is pure waiting. At 20 s, one web tree walk
        spent 21.7 of its 30 minutes in screenshot timeouts (TASK-161, 2026-10-23):
        the hop-start frame and the verification probe each paid the full budget,
        and the walk blew past the point where it could finish.
        """
        import concurrent.futures

        try:
            fut = self._submit_to_controller_loop(self._photo_page(path, timeout))
        except Exception as e:
            self._log(f"Page screenshot skipped (no controller loop): {type(e).__name__}: {e}")
            return None
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            self._log(f"Page screenshot timed out after {timeout:g}s")
            return None
        except Exception as e:
            self._log(f"Page screenshot failed: {type(e).__name__}: {e}")
            return None

    async def _bounded_title(self, page, timeout: float = 5.0) -> str:
        """The page title, but never longer than `timeout` seconds.

        `page.title()` is a protocol call with no timeout of its own: on a renderer that
        is busy or blocked (a donation modal's script, a JS dialog) it never returns.
        Measured on `web-internetarchive` (TASK-161, 2026-10-23): the page had loaded,
        the renderer stopped answering, and every later hop of the walk died inside the
        title read — the navigation never returned, so the walk burned its 180 s budget
        per hop and the second pass failed on all of them. An empty title is the honest
        answer there: the URL is what says the page loaded.
        """
        try:
            return await asyncio.wait_for(page.title(), timeout=timeout)
        except asyncio.TimeoutError:
            self._log(f"Page title read timed out after {timeout:g}s (renderer busy)")
            return ''
        except Exception as e:
            self._log(f"Page title read failed: {type(e).__name__}: {e}")
            return ''

    @ensure_controller_loop
    async def navigate_to_url(self, url: str, timeout: int = 60000, follow_redirects: bool = True) -> Dict[str, Any]:
        """Navigate to a URL."""
        start_time = time.time()
        try:
            # `/settings` or `/{lang}/settings` = same page in the language the app shows now (BUG-0703)
            from shared.src.lib.utils.localize_identity import resolve_app_url
            url = resolve_app_url(url, self.current_url)
            normalized_url = self.utils.normalize_url(url)
            self._log(f"Navigating to {url} (normalized: {normalized_url}) with timeout {timeout}ms")

            _t = _phase_t0()
            _had_browser = bool(self.__class__._browser and self.__class__._context)
            page = await self._get_persistent_page(target_url=normalized_url)
            _log_phase('web.get_persistent_page', _t, f"browser_was_connected={_had_browser}")

            # Inject consent cookies for YouTube/Google before navigation
            await self._inject_consent_cookies_if_needed(normalized_url)

            # Wait for basic page load only - verifications will check readiness
            _t = _phase_t0()
            await page.goto(normalized_url, timeout=timeout, wait_until='load')
            _log_phase('web.goto_until_load', _t, f"url={normalized_url}")

            # Reset Flutter detection flags on new page load
            # (semantics state doesn't persist across pages)
            self._flutter_app_detected = None

            self.current_url = page.url
            self.page_title = await self._bounded_title(page)

            _t = _phase_t0()
            await self._capture_dom_snapshot(page)
            _log_phase('web.dom_snapshot', _t)

            execution_time = int((time.time() - start_time) * 1000)
            
            result = {
                'success': True,
                'url': self.current_url,
                'title': self.page_title,
                'execution_time': execution_time,
                'error': '',
                'normalized_url': normalized_url,
                'redirected': self.current_url != normalized_url,
                'follow_redirects': follow_redirects
            }
            
            if result['redirected']:
                self._log(f"Navigation completed with redirect in {execution_time}ms: {normalized_url} -> {self.current_url}")
            else:
                self._log(f"Navigation successful in {execution_time}ms - {self.page_title}")
            return result
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_type = type(e).__name__
            error_msg = str(e)
            
            # Check if navigation actually succeeded despite timeout
            # (page loaded but took longer than expected)
            page_loaded = False
            current_url = self.current_url
            current_title = self.page_title
            
            try:
                if 'page' in locals():
                    current_url = page.url
                    # The title is a nicety here, not the verdict: the URL is what says the
                    # page loaded. A renderer that stopped answering (a modal script, a JS
                    # dialog) must not turn a loaded page into a failed navigation, and
                    # `page.title()` has no timeout of its own.
                    current_title = await self._bounded_title(page)
                    # If we got a valid URL and title, page loaded successfully
                    page_loaded = current_url and current_url != 'about:blank'
                    print(f"[PLAYWRIGHT]: Current page state - URL: {current_url}, Title: {current_title[:50]}...")
            except Exception as state_error:
                print(f"[PLAYWRIGHT]: Could not get page state: {type(state_error).__name__}: {str(state_error)}")
            
            # If timeout but page loaded, treat as success
            # Verifications will check if page is actually ready
            if error_type == 'TimeoutError' and page_loaded:
                print(f"[PLAYWRIGHT]: ⚠️ Navigation timed out but page loaded successfully")
                print(f"[PLAYWRIGHT]: Treating as success - verifications will check readiness")
                
                self.current_url = current_url
                self.page_title = current_title

                await self._capture_dom_snapshot(page)

                return {
                    'success': True,
                    'url': current_url,
                    'title': current_title,
                    'execution_time': execution_time,
                    'error': '',
                    'warning': f'Navigation completed but exceeded timeout ({execution_time}ms > {timeout}ms)',
                    'normalized_url': normalized_url if 'normalized_url' in locals() else url,
                    'redirected': current_url != normalized_url if 'normalized_url' in locals() else False,
                    'follow_redirects': follow_redirects
                }
            
            # Real failure - page didn't load
            print(f"[PLAYWRIGHT]: ❌ NAVIGATION FAILED after {execution_time}ms")
            print(f"[PLAYWRIGHT]: Error Type: {error_type}")
            print(f"[PLAYWRIGHT]: Error Message: {error_msg}")
            print(f"[PLAYWRIGHT]: Target URL: {normalized_url if 'normalized_url' in locals() else url}")
            
            return {
                'success': False,
                'error': f"{error_type}: {error_msg}",
                'error_type': error_type,
                'url': current_url,
                'title': current_title,
                'execution_time': execution_time,
                'original_url': url,
                'normalized_url': normalized_url if 'normalized_url' in locals() else url,
                'follow_redirects': follow_redirects
            }
        
    def _is_css_selector(self, text: str) -> bool:
        """Detect if text is a CSS selector or XPath that Playwright can use directly.
        
        Args:
            text: Input string to check
            
        Returns:
            True if it's a CSS selector or XPath, False if it's plain text
        """
        if not text or not text.strip():
            return False
        
        text = text.strip()

        # Explicit Playwright engine prefix: css=input.search, xpath=//input
        # (the agent's web dump hands out css= selectors so they are never read as text)
        if text.startswith(('css=', 'xpath=')):
            return True

        # XPath selector: //div or (//div)
        if text.startswith('//') or text.startswith('(//'):
            return True
        
        # CSS ID selector: #my-id
        if text.startswith('#'):
            return True
        
        # CSS class selector: .my-class
        if text.startswith('.'):
            return True
        
        # Attribute selector: [aria-label="..."] or [id="..."]
        if text.startswith('[') and ']' in text:
            return True
        
        # Complex CSS with > or + or ~ combinators: div > span, button + input
        if any(combinator in text for combinator in [' > ', ' + ', ' ~ ']):
            return True
        
        # CSS pseudo-selectors: :nth-child, :first-child, :hover, etc.
        if ':' in text and not text.startswith('http'):
            return True
        
        # Tag with attribute: button[type="submit"]
        if '[' in text and ']' in text:
            return True
        
        return False
    
    @ensure_controller_loop
    async def click_element(self, element_id: str) -> Dict[str, Any]:
        """Click an element - uses direct click for CSS selectors, dump-first for text search.
        Supports pipe-separated fallback: "Settings|Preferences|Options"
        
        Args:
            element_id: CSS selector (#id, .class, [attr]) OR plain text to search for
                        Can use pipe "|" to specify multiple options (tries each until one succeeds)
        """
        try:
            start_time = time.time()
            
            # Parse pipe-separated terms for fallback support
            terms = [t.strip() for t in element_id.split('|')] if '|' in element_id else [element_id]
            
            if len(terms) > 1:
                print(f"[PLAYWRIGHT]: Using fallback strategy with {len(terms)} terms: {terms}")
            
            # Try each term until one succeeds
            last_error = None
            for i, term in enumerate(terms):
                if len(terms) > 1:
                    print(f"[PLAYWRIGHT]: Attempt {i+1}/{len(terms)}: Searching for '{term}'")
                
                # OPTIMIZATION: Detect CSS selectors and use direct click (skip dump)
                if self._is_css_selector(term):
                    print(f"[PLAYWRIGHT]: Detected CSS selector, using direct click (skip dump): {term}")
                    
                    try:
                        page = await self._get_persistent_page()
                        
                        # Try direct click with Playwright's native selector
                        await page.click(term, timeout=5000)
                        
                        execution_time = int((time.time() - start_time) * 1000)
                        print(f"[PLAYWRIGHT]: Direct CSS click successful: {term}")
                        return {
                            'success': True,
                            'error': '',
                            'execution_time': execution_time,
                            'method': 'direct_css_click',
                            'selector': term
                        }
                    except Exception as css_error:
                        last_error = f"CSS selector click failed: {css_error}"
                        print(f"[PLAYWRIGHT]: {last_error}")
                        if len(terms) > 1:
                            print(f"[PLAYWRIGHT]: CSS selector '{term}' failed, trying next...")
                        continue
                
                # Plain text search - try Playwright's native text matching FIRST
                # This is what a real user does: find visible text and click it
                print(f"[PLAYWRIGHT]: Plain text detected, trying native text selectors first: {term}")

                try:
                    page = await self._get_persistent_page()

                    # Try multiple Playwright-native strategies in order of specificity
                    native_selectors = [
                        f'text="{term}"',                    # Exact text match
                        f'[id="{term}"]',                    # A bare element id (kc-login)
                        f'input[value="{term}" i]',          # Input buttons (submit/button with value)
                        f'button:has-text("{term}")',         # Button containing text
                        f'a:has-text("{term}")',              # Link containing text
                        f'[role="button"]:has-text("{term}")', # ARIA button role
                    ]

                    for sel in native_selectors:
                        try:
                            # Count first (no wait): clicking an absent selector waits out its 3 s timeout,
                            # 15 s per click on a Flutter page where none match (TASK-135).
                            if not await page.locator(sel).count():
                                continue
                            await page.click(sel, timeout=3000)
                            execution_time = int((time.time() - start_time) * 1000)
                            print(f"[PLAYWRIGHT]: Native text click successful: {sel}")
                            return {
                                'success': True,
                                'error': '',
                                'execution_time': execution_time,
                                'method': 'native_text_click',
                                'selector': sel
                            }
                        except Exception:
                            continue

                    print(f"[PLAYWRIGHT]: Native text selectors exhausted, falling back to dump-first approach")
                except Exception as native_error:
                    print(f"[PLAYWRIGHT]: Native text click error: {native_error}, falling back to dump-first")

                # Fallback: dump-first approach (Android mobile style)
                # Step 1: Find element using dump-first (same as Android mobile)
                find_result = await self.find_element(term)
                
                if not find_result.get('success'):
                    last_error = f"Element not found: {find_result.get('error', 'Unknown error')}"
                    if len(terms) > 1:
                        print(f"[PLAYWRIGHT]: Term '{term}' not found, trying next...")
                    continue
                
                # Step 2: Click the found element using coordinates (like Android mobile)
                element_info = find_result.get('element_info', {})
                position = element_info.get('position', {})
                
                if not position or 'x' not in position:
                    last_error = f"Element found but no coordinates available"
                    if len(terms) > 1:
                        print(f"[PLAYWRIGHT]: Term '{term}' found but no coordinates, trying next...")
                    continue
                
                # Calculate center coordinates
                center_x = position['x'] + (position.get('width', 0) / 2)
                center_y = position['y'] + (position.get('height', 0) / 2)
                
                # Log with element_id for consistency
                found_element_id = element_info.get('element_id', 'unknown')
                matched_value = element_info.get('matched_value', '')
                print(f"[PLAYWRIGHT]: Found element (ID={found_element_id}, value='{matched_value}'), clicking at coordinates ({center_x:.0f}, {center_y:.0f})")
                
                # Step 3: Click using coordinates (reuse tap_x_y logic)
                tap_result = await self.tap_x_y(int(center_x), int(center_y))
                
                if tap_result.get('success'):
                    execution_time = int((time.time() - start_time) * 1000)
                    if len(terms) > 1:
                        print(f"[PLAYWRIGHT]: Click successful using term '{term}'")
                    else:
                        print(f"[PLAYWRIGHT]: Click successful using dump-first approach")
                    return {
                        'success': True,
                        'error': '',
                        'execution_time': execution_time,
                        'method': 'dump_search_click',
                        'coordinates': {'x': int(center_x), 'y': int(center_y)},
                        'element_info': element_info
                    }
                else:
                    last_error = f"Element found but click failed: {tap_result.get('error', 'Unknown error')}"
                    if len(terms) > 1:
                        print(f"[PLAYWRIGHT]: Term '{term}' click failed, trying next...")
                    continue
            
            # All terms failed
            execution_time = int((time.time() - start_time) * 1000)
            print(f"[PLAYWRIGHT]: All terms failed. Last error: {last_error}")
            return {
                'success': False,
                'error': last_error or 'Element not found',
                'execution_time': execution_time
            }
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"Click error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': execution_time,
                'selector_attempted': element_id
            }
    
    @ensure_controller_loop
    async def hover_element(self, selector: str) -> Dict[str, Any]:
        """Hover over an element to trigger rollover effects.
        
        Args:
            selector: CSS selector, or text content to search for
        """
        try:
            print(f"[PLAYWRIGHT]: Hovering over element: {selector}")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            
            # Try same selectors as click
            selectors_to_try = [
                selector,
                f"[aria-label='{selector}']",
                f"[flt-semantics[aria-label='{selector}']",
            ]
            
            for i, sel in enumerate(selectors_to_try):
                try:
                    await page.hover(sel, timeout=2000)
                    execution_time = int((time.time() - start_time) * 1000)
                    print(f"[PLAYWRIGHT]: Hover successful using selector {i+1}: {sel}")
                    return {
                        'success': True,
                        'error': '',
                        'execution_time': execution_time
                    }
                except Exception as e:
                    print(f"[PLAYWRIGHT]: Hover selector {i+1} failed: {sel} - {str(e)}")
                    continue
            
            # All selectors failed
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"Hover failed - element not found with any selector"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': execution_time
            }
            
        except Exception as e:
            error_msg = f"Hover error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0
            }
        
    @ensure_controller_loop
    async def find_element(self, selector: str) -> Dict[str, Any]:
        """Find an element using Playwright native selectors first, then dump fallback.

        Priority order (mirrors click_element strategy):
        1. CSS selectors → Playwright direct locator
        2. Plain text → Playwright native text matching (works inside web components/shadow DOM)
        3. Fallback → dump_elements + text search (original Android-mobile approach)

        Args:
            selector: CSS selector, text content, or aria-label to search for
        """
        try:
            start_time = time.time()

            # ── Phase 1: Try Playwright native selectors (fast, works with shadow DOM) ──
            page = None
            try:
                page = await self._get_persistent_page()
            except Exception:
                pass  # Fall through to dump approach if page unavailable

            if page is not None:
                # CSS selector → direct locator
                if self._is_css_selector(selector):
                    try:
                        locator = page.locator(selector)
                        box = await locator.first.bounding_box(timeout=300)
                        if box:
                            execution_time = int((time.time() - start_time) * 1000)
                            print(f"[PLAYWRIGHT]: Element found via CSS locator: {selector}")
                            return {
                                'success': True, 'error': '', 'execution_time': execution_time,
                                'result': {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2,
                                           'width': box['width'], 'height': box['height']},
                                'element_info': {'matched_value': selector, 'match_reason': 'css_locator'},
                                'method': 'playwright_css'
                            }
                    except Exception:
                        pass  # Fall through

                # Plain text → try multiple Playwright-native strategies
                if not self._is_css_selector(selector):
                    native_selectors = [
                        f'text="{selector}"',                       # Exact text match
                        f'input[value="{selector}" i]',             # Input buttons
                        f'button:has-text("{selector}")',            # Button containing text
                        f'a:has-text("{selector}")',                 # Link containing text
                        f'[role="button"]:has-text("{selector}")',   # ARIA button
                    ]
                    for sel in native_selectors:
                        try:
                            locator = page.locator(sel)
                            box = await locator.first.bounding_box(timeout=300)
                            if box:
                                execution_time = int((time.time() - start_time) * 1000)
                                print(f"[PLAYWRIGHT]: Element found via native selector: {sel}")
                                return {
                                    'success': True, 'error': '', 'execution_time': execution_time,
                                    'result': {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2,
                                               'width': box['width'], 'height': box['height']},
                                    'element_info': {'matched_value': selector, 'match_reason': f'native:{sel}'},
                                    'method': 'playwright_native'
                                }
                        except Exception:
                            continue

                    print(f"[PLAYWRIGHT]: Native selectors exhausted for '{selector}', falling back to dump approach")

            # ── Phase 2: Fallback to dump-first approach (original behavior) ──
            print(f"[PLAYWRIGHT]: Finding element using dump-first approach: {selector}")

            # Step 1: Dump all elements first (like Android mobile)
            dump_result = await self.dump_elements()

            if not dump_result.get('success'):
                execution_time = int((time.time() - start_time) * 1000)
                error_msg = f"Failed to dump elements: {dump_result.get('error', 'Unknown error')}"
                print(f"[PLAYWRIGHT]: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'execution_time': execution_time
                }
            
            elements = dump_result.get('elements', [])
            print(f"[PLAYWRIGHT]: Searching within {len(elements)} dumped elements")
            
            # DEBUG: Log ALL elements for verification (not just first 20)
            print(f"[PLAYWRIGHT]: === DUMPED ELEMENTS (ALL {len(elements)}) ===")
            for i, el in enumerate(elements):  # Show ALL, not just [:20]
                # Clean up text: remove extra whitespace/newlines and limit to 50 chars
                raw_text = el.get('textContent', '').strip()
                clean_text = ' '.join(raw_text.split())  # Remove all extra whitespace
                display_text = clean_text[:50] + '...' if len(clean_text) > 50 else clean_text
                
                aria = el.get('attributes', {}).get('aria-label', '').strip()
                element_selector = el.get('selector', '')
                href = el.get('attributes', {}).get('href', '')
                
                # Include href in output for debugging
                href_display = f" - href: '{href}'" if href else ""
                print(f"[PLAYWRIGHT]:   {i+1}. {el.get('tagName', 'unknown')} - text: '{display_text}' - aria: '{aria}' - selector: '{element_selector}'{href_display}")
            print(f"[PLAYWRIGHT]: === END DUMPED ELEMENTS ===")
            
            # Step 2: Search within dumped elements (same logic as Android mobile)
            matches = self._search_dumped_elements(selector, elements)
            
            if matches:
                # Found element - return coordinates like Android mobile does.
                # Skip matches without a usable box (off-screen / zero-size flt-semantics nodes):
                # a later match in the same dump often has one (BUG-0701).
                usable = [m for m in matches if self._has_usable_box(m.get('position'))]
                if not usable:
                    execution_time = int((time.time() - start_time) * 1000)
                    error_msg = f"Element found but no coordinates available ({len(matches)} match(es) for '{selector}' have no usable bounding box)"
                    print(f"[PLAYWRIGHT]: {error_msg}")
                    return {'success': False, 'error': error_msg, 'execution_time': execution_time}
                first_match = usable[0]
                execution_time = int((time.time() - start_time) * 1000)
                
                # Log with element_id like click_element does
                element_id = first_match.get('element_id', 'unknown')
                matched_value = first_match.get('matched_value', '')
                print(f"[PLAYWRIGHT]: Element found in dump: {first_match['match_reason']} (ID={element_id}, value='{matched_value}')")
                return {
                    'success': True,
                    'error': '',
                    'execution_time': execution_time,
                    'result': {  # Use 'result' key like clicks do for frontend compatibility
                        'x': first_match['position']['x'],
                        'y': first_match['position']['y'], 
                        'width': first_match['position']['width'],
                        'height': first_match['position']['height']
                    },
                    'element_info': first_match,
                    'method': 'dump_search'
                }
            else:
                execution_time = int((time.time() - start_time) * 1000)
                error_msg = f"Element '{selector}' not found in {len(elements)} dumped elements"
                print(f"[PLAYWRIGHT]: {error_msg}")
                
                # Log available elements for debugging (like Android mobile does)
                print(f"[PLAYWRIGHT]: Available elements:")
                for i, el in enumerate(elements[:10]):  # Show first 10
                    # Clean up text: remove extra whitespace/newlines and limit to 40 chars
                    raw_text = el.get('textContent', '').strip()
                    clean_text = ' '.join(raw_text.split())
                    display_text = clean_text[:40] + '...' if len(clean_text) > 40 else clean_text
                    aria = el.get('attributes', {}).get('aria-label', '').strip()
                    print(f"[PLAYWRIGHT]:   {i+1}. {el.get('tagName', 'unknown')} - text: '{display_text}' - aria: '{aria}'")
                
                return {
                    'success': False,
                    'error': error_msg,
                    'execution_time': execution_time
                }
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"Find error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': execution_time,
                'selector_attempted': selector
            }
    
    @staticmethod
    def _has_usable_box(position: Any) -> bool:
        """True when a dumped element's position can be clicked: has x/y and a non-zero size."""
        if not isinstance(position, dict) or position.get('x') is None or position.get('y') is None:
            return False
        return (position.get('width') or 0) > 0 and (position.get('height') or 0) > 0

    def _calculate_match_score(self, search_term: str, matched_value: str, element: Dict[str, Any] = None) -> tuple:
        """
        Calculate match quality score for prioritization.
        
        Returns tuple of (exact_match, starts_with, widget_priority, case_match_score, length) where:
        - exact_match: 1 if exact match, 0 otherwise (highest priority)
        - starts_with: 1 if matched value starts with search term (2nd priority)
        - widget_priority: 2 for Button/Tab/Input, 1 for Clickable class, 0 otherwise (3rd priority)
        - case_match_score: number of matching case characters (higher is better)
        - length: length of matched value (lower is better, so we negate for sorting)
        
        Args:
            search_term: The search term to compare
            matched_value: The value that was matched
            element: Optional element dictionary for widget type checking
        
        Returns:
            Tuple[int, int, int, int, int]: (exact_match, starts_with, widget_priority, case_match_score, -length)
        """
        search_stripped = search_term.strip()
        value_stripped = matched_value.strip()
        search_lower = search_stripped.lower()
        value_lower = value_stripped.lower()
        
        # 1. Check for exact match (highest priority)
        exact_match = 1 if search_stripped == value_stripped else 0
        
        # 2. Check if starts with search term (2nd priority)
        starts_with = 1 if value_lower.startswith(search_lower) else 0
        
        # 3. Widget Priority (Tab/Button/Input preference)
        widget_priority = 0
        if element:
            tag_name = element.get('tagName', '').upper()
            attributes = element.get('attributes', {})
            role = attributes.get('role', '').lower()
            class_name = element.get('className', '').lower()
            
            # High priority: Semantic interactive elements
            if (tag_name in ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'A'] or 
                role in ['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch', 'combobox', 'textbox']):
                widget_priority = 2
            # Medium priority: Class indicating interactivity
            elif any(x in class_name for x in ['btn', 'button', 'clickable', 'tab', 'menu', 'nav']):
                widget_priority = 1
        
        # 4. Calculate case match score (character-by-character case matching)
        # For each character position where both have the same case, add 1 point
        case_match_score = 0
        
        # Find where the search term appears in the value (case-insensitive)
        if search_lower in value_lower:
            start_idx = value_lower.index(search_lower)
            # Compare case character by character
            for i in range(len(search_stripped)):
                if i + start_idx < len(value_stripped):
                    search_char = search_stripped[i]
                    value_char = value_stripped[i + start_idx]
                    # Check if both are same case (both upper or both lower)
                    if search_char.isupper() == value_char.isupper():
                        case_match_score += 1
        
        # 5. Get length (we'll negate it for sorting so shorter is better)
        length = len(value_stripped)
        
        return (exact_match, starts_with, widget_priority, case_match_score, -length)
    
    def _search_dumped_elements(self, search_term: str, elements: list) -> list:
        """Search within dumped elements with smart prioritization (exact match, starts with, widget type, case match, shortest length)."""
        search_lower = search_term.strip().lower()
        matches = []
        
        for element in elements:
            element_matches = []
            
            # Check textContent (like Android mobile text attribute)
            text_content = element.get('textContent', '').strip()
            if text_content and search_lower in text_content.lower():
                element_matches.append({
                    "attribute": "textContent",
                    "value": text_content,
                    "reason": f"Contains '{search_term}' in text content"
                })
            
            # Check aria-label (like Android mobile content_desc)
            aria_label = element.get('attributes', {}).get('aria-label', '').strip()
            if aria_label and search_lower in aria_label.lower():
                element_matches.append({
                    "attribute": "aria-label", 
                    "value": aria_label,
                    "reason": f"Contains '{search_term}' in aria-label"
                })
            
            # Check selector/id (like Android mobile resource_id)
            selector = element.get('selector', '').strip()
            if selector and search_lower in selector.lower():
                element_matches.append({
                    "attribute": "selector",
                    "value": selector,
                    "reason": f"Contains '{search_term}' in selector"
                })
            
            # Check className (like Android mobile class_name)
            class_name = element.get('className', '').strip()
            if class_name and search_lower in class_name.lower():
                element_matches.append({
                    "attribute": "className",
                    "value": class_name,
                    "reason": f"Contains '{search_term}' in class name"
                })
            
            # If matches found, calculate score and add to results
            if element_matches:
                primary_match = element_matches[0]
                element_index = element.get('index', 0)
                
                # Calculate match score for prioritization
                match_score = self._calculate_match_score(search_term, primary_match["value"], element)
                
                match_info = {
                    "element_id": f"element_{element_index}",  # Add element_id like Android does
                    "element_index": element_index,
                    "matched_attribute": primary_match["attribute"],
                    "matched_value": primary_match["value"],
                    "match_reason": primary_match["reason"],
                    "search_term": search_term,
                    "position": element.get('position', {}),
                    "selector": element.get('selector', ''),
                    "full_element": element,
                    "match_score": match_score  # For sorting/debugging
                }
                
                matches.append(match_info)
        
        # Sort matches by priority: 1) Exact match, 2) Starts with, 3) Widget Type, 4) Case match score, 5) Shortest length
        if matches:
            matches.sort(key=lambda m: m["match_score"], reverse=True)
            print(f"[PLAYWRIGHT]: Prioritized {len(matches)} matches for '{search_term}':")
            for i, match in enumerate(matches[:5]):  # Show top 5
                score = match["match_score"]
                print(f"[PLAYWRIGHT]:   {i+1}. '{match['matched_value'][:50]}' (exact={score[0]}, start={score[1]}, widget={score[2]}, case={score[3]}, len={-score[4]}) - {match['match_reason']}")
        
        return matches
    
    @ensure_controller_loop
    async def input_text(self, selector: Optional[str], text: str, wait_time: int = INPUT_TEXT_SETTLE_MS,
                         press_enter: bool = False) -> Dict[str, Any]:
        """Input text into an element.

        selector: CSS (css=...), XPath (//... or xpath=...) or any Playwright selector.
        None types into the focused field, e.g. the search box a click just focused.
        press_enter submits afterwards, as a user would.
        """
        try:
            print(f"[PLAYWRIGHT]: Inputting text to: {selector or '<focused field>'}")
            start_time = time.time()

            # Get persistent page from browser+context
            page = await self._get_persistent_page()

            if selector:
                await page.fill(selector, text)
            else:
                focused_is_editable = await page.evaluate(
                    "() => { const el = document.activeElement;"
                    " return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA'].includes(el.tagName)); }"
                )
                if not focused_is_editable:
                    return {
                        'success': False,
                        'error': ("No field to type into: pass params.selector (from dump_ui_elements, "
                                  "e.g. css=input[name='q']) or click the field first"),
                        'execution_time': int((time.time() - start_time) * 1000)
                    }
                await page.locator('*:focus').fill(text)

            if press_enter:
                await page.keyboard.press('Enter')
            _log_duration('web.input_text.fill', (time.time() - start_time) * 1000,
                          f"selector={selector!r} press_enter={press_enter}")

            # execute_command passes params.timeout here (default INPUT_TEXT_SETTLE_MS) -- not
            # the action's wait_time, which ActionExecutor sleeps separately afterwards.
            _t = _phase_t0()
            await asyncio.sleep(wait_time / 1000)
            _log_phase('web.input_text.post_fill_sleep', _t,
                       f"sleep_ms={wait_time} (params.timeout, default {INPUT_TEXT_SETTLE_MS})")

            result = {
                'success': True,
                'error': '',
            'execution_time': int((time.time() - start_time) * 1000)
            }
            
            print(f"[PLAYWRIGHT]: Text input successful")
            return result
            
        except Exception as e:
            error_msg = f"Input error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0
            }
        
    @ensure_controller_loop
    async def tap_x_y(self, x: int, y: int) -> Dict[str, Any]:
        """Tap/click at specific coordinates."""
        try:
            print(f"[PLAYWRIGHT]: Tapping at coordinates: ({x}, {y})")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            
            # Show click animation and coordinates (like Android mobile)
            await self._show_click_animation(page, x, y)
            
            # Click at coordinates
            await page.mouse.click(x, y)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            result = {
                'success': True,
                'error': '',
                'execution_time': execution_time,
                'coordinates': {'x': x, 'y': y}
            }
            
            print(f"[PLAYWRIGHT]: Tap successful at ({x}, {y})")
            return result
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = f"Tap error ({error_type}): {str(e)}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            print(f"[PLAYWRIGHT]: Exception details - Type: {error_type}, Args: {e.args}")
            
            # Log connection state for debugging
            print(f"[PLAYWRIGHT]: Connection state - is_connected: {self.is_connected}, _chrome_running: {self.__class__._chrome_running}, _browser_connected: {self.__class__._browser_connected}")
            
            return {
                'success': False,
                'error': error_msg,
                'error_type': error_type,
                'error_details': str(e),
                'connection_state': {
                    'is_connected': self.is_connected,
                    'chrome_running': self.__class__._chrome_running,
                    'browser_connected': self.__class__._browser_connected
                },
                'execution_time': 0
            }
        
    @ensure_controller_loop
    async def execute_javascript(self, script: str, timeout: float = 15.0) -> Dict[str, Any]:
        """Execute JavaScript code in the page.

        page.evaluate() does NOT honor set_default_timeout and has no built-in
        timeout — if the page is mid-navigation (execution context destroyed) or
        the renderer is busy, it blocks forever. Guard it with asyncio.wait_for so
        callers in polling loops can never hang indefinitely.
        """
        try:
            start_time = time.time()
            script_summary = self._summarize_script(script)
            self._log(f"JS start {script_summary}")

            # Get persistent page from browser+context
            page = await self._get_persistent_page()

            # Execute JavaScript with a hard timeout. A top-level `return` is a SyntaxError for evaluate: run the
            # script as a function body instead (agents write it that way, TASK-135).
            try:
                result = await asyncio.wait_for(page.evaluate(script), timeout=timeout)
            except Exception as e:
                if 'Illegal return statement' not in str(e):
                    raise
                result = await asyncio.wait_for(page.evaluate(f"(() => {{\n{script}\n}})()"), timeout=timeout)

            execution_time = int((time.time() - start_time) * 1000)
            self._log(f"JS done {script_summary} in {execution_time}ms")

            return {
                'success': True,
                'result': result,
                # The action executor forwards only output_data, so the value
                # the script returned must travel there to reach the caller.
                'output_data': {'result': result},
                'error': '',
                'execution_time': execution_time
            }

        except asyncio.TimeoutError:
            error_msg = f"JavaScript execution timed out after {timeout}s (page unresponsive or mid-navigation)"
            self._log(error_msg)
            return {
                'success': False,
                'result': None,
                'error': error_msg,
                'execution_time': int((time.time() - start_time) * 1000)
            }
        except Exception as e:
            error_msg = f"JavaScript execution error: {e}"
            self._log(error_msg)
            return {
                'success': False,
                'result': None,
                'error': error_msg,
                'execution_time': 0
            }
    
    async def _show_click_animation(self, page, x: int, y: int):
        """Show click animation and coordinates like Android mobile overlay."""
        try:
            js_code = f"""
            (() => {{
                // Create click animation styles if not exists
                const styleId = 'playwright-click-animation-styles';
                if (!document.getElementById(styleId)) {{
                    const style = document.createElement('style');
                    style.id = styleId;
                    style.textContent = `
                        @keyframes playwrightClickPulse {{
                            0% {{
                                transform: scale(0.3);
                                opacity: 1;
                            }}
                            100% {{
                                transform: scale(1.5);
                                opacity: 0;
                            }}
                        }}
                    `;
                    document.head.appendChild(style);
                }}
                
                // Create click animation circle
                const clickAnimation = document.createElement('div');
                clickAnimation.style.cssText = `
                    position: fixed;
                    left: {x - 15}px;
                    top: {y - 15}px;
                    width: 30px;
                    height: 30px;
                    border-radius: 50%;
                    background-color: rgba(255, 255, 255, 0.8);
                    border: 2px solid rgba(0, 123, 255, 0.8);
                    z-index: 999999;
                    pointer-events: none;
                    animation: playwrightClickPulse 0.3s ease-out forwards;
                `;
                document.body.appendChild(clickAnimation);
                
                // Create coordinate display
                const coordDisplay = document.createElement('div');
                coordDisplay.style.cssText = `
                    position: fixed;
                    left: {x + 20}px;
                    top: {y - 15}px;
                    background-color: rgba(0, 0, 0, 0.8);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-family: monospace;
                    font-weight: bold;
                    z-index: 999999;
                    pointer-events: none;
                    white-space: nowrap;
                `;
                coordDisplay.textContent = '{x}, {y}';
                document.body.appendChild(coordDisplay);
                
                // Remove animation after 300ms
                setTimeout(() => {{
                    if (clickAnimation.parentNode) {{
                        clickAnimation.parentNode.removeChild(clickAnimation);
                    }}
                }}, 300);
                
                // Remove coordinate display after 2 seconds
                setTimeout(() => {{
                    if (coordDisplay.parentNode) {{
                        coordDisplay.parentNode.removeChild(coordDisplay);
                    }}
                }}, 2000);
                
                return true;
            }})()
            """
            
            await page.evaluate(js_code)
            print(f"[PLAYWRIGHT]: Click animation shown at ({x}, {y})")
        except Exception as e:
            print(f"[PLAYWRIGHT]: Click animation failed: {e}")
            # Don't fail the tap if animation fails
    
    @ensure_controller_loop
    async def get_page_info(self) -> Dict[str, Any]:
        """Get current page information."""
        try:
            print(f"[PLAYWRIGHT]: Getting page info")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            
            # Get page info
            self.current_url = page.url
            self.page_title = await page.title()
            
            execution_time = int((time.time() - start_time) * 1000)
            
            result = {
                'success': True,
                'url': self.current_url,
                'title': self.page_title,
                'error': '',
                'execution_time': execution_time,
                'output_data': {
                    'url': self.current_url,
                    'title': self.page_title,
                }
            }
            
            print(f"[PLAYWRIGHT]: Page info retrieved - {self.page_title}")
            return result
            
        except Exception as e:
            error_msg = f"Get page info error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'url': '',
                'title': '',
                'execution_time': 0
            }
        
    @ensure_controller_loop
    async def activate_semantic(self) -> Dict[str, Any]:
        """Activate semantic placeholder for Flutter web apps."""
        script = """
        (() => {
            // Try new structure first (Flutter 3.x+): direct DOM element
            let element = document.querySelector('flt-semantics-placeholder');
            if (element) {
                console.log('[Flutter] Found flt-semantics-placeholder in direct DOM (new structure)');
                element.click();
                return {success: true, structure: 'direct-dom'};
            }
            
            // Try old structure: inside shadow DOM
            const shadowHost = document.querySelector('body > flutter-view > flt-glass-pane');
            if (shadowHost && shadowHost.shadowRoot) {
                element = shadowHost.shadowRoot.querySelector('flt-semantics-placeholder');
                if (element) {
                    console.log('[Flutter] Found flt-semantics-placeholder in shadow DOM (old structure)');
                    element.click();
                    return {success: true, structure: 'shadow-dom'};
                }
            }
            
            // Try alternative direct selector
            element = document.querySelector('body > flt-semantics-placeholder');
            if (element) {
                console.log('[Flutter] Found flt-semantics-placeholder as body child');
                element.click();
                return {success: true, structure: 'body-child'};
            }
            
            console.log('[Flutter] flt-semantics-placeholder not found in any structure');
            return {success: false, structure: 'not-found'};
        })()
        """
        
        # Try once, if fails wait 1s and retry with connection check
        result = await self.execute_javascript(script)
        if not result.get('success'):
            print(f"[PLAYWRIGHT]: First activate_semantic failed ({result.get('error', 'unknown')}), retrying in 1s...")
            import asyncio
            await asyncio.sleep(1)
            # Check if connection issue and try to recover
            if 'Connection closed' in str(result.get('error', '')):
                print(f"[PLAYWRIGHT]: Connection issue detected, attempting recovery...")
                self.__class__._browser_connected = False  # Force reconnection
            result = await self.execute_javascript(script)
        
        # Log the structure found
        if result.get('success') and result.get('result'):
            js_result = result.get('result', {})
            if isinstance(js_result, dict):
                structure = js_result.get('structure', 'unknown')
                print(f"[PLAYWRIGHT]: Semantic activated using {structure} structure")
        
        # The placeholder click only turns the engine's semantics on. Apps that gate their
        # widget semantics behind keyboard navigation (common Flutter a11y pattern) still
        # expose an empty tree until Tab is pressed, so wait for real labels.
        try:
            page = await self._get_persistent_page()
            result['semantics_populated'] = await self._ensure_flutter_semantics_populated(page)
        except Exception as e:
            print(f"[PLAYWRIGHT]: Semantics population check failed (non-fatal): {e}")

        result['success'] = True  # Always succeed since this is optional
        return result

    @ensure_controller_loop
    async def override_page_meta(self, name: str, content: str) -> Dict[str, Any]:
        """Force the content of a <meta name=...> tag on every document this browser loads.

        Web apps read runtime config from meta tags at boot (e.g. a flag that disables
        accessibility semantics). The override is an init script on the browser context,
        so it must run before navigate_to_url and lasts until the browser disconnects.
        """
        start_time = time.time()
        script = """
        (() => {
            const name = %s, content = %s;
            const apply = (el) => {
                if (el && el.tagName === 'META' && el.getAttribute('name') === name) {
                    el.setAttribute('content', content);
                }
            };
            document.querySelectorAll('meta').forEach(apply);
            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) m.addedNodes.forEach(apply);
            });
            observer.observe(document, {childList: true, subtree: true});
            document.addEventListener('DOMContentLoaded', () => observer.disconnect(), {once: true});
        })();
        """ % (json.dumps(name), json.dumps(content))
        try:
            await self._get_persistent_page()
            await self.__class__._context.add_init_script(script)
            self._log(f"Meta override registered: {name}={content!r} (applies from the next page load)")
            return {'success': True, 'error': '', 'execution_time': int((time.time() - start_time) * 1000)}
        except Exception as e:
            return {
                'success': False,
                'error': f'override_page_meta failed: {type(e).__name__}: {e}',
                'execution_time': int((time.time() - start_time) * 1000)
            }

    async def _flutter_semantics_populated(self, page) -> bool:
        """True when the Flutter semantics tree carries at least one label, not just empty nodes."""
        return await page.evaluate("""
        () => [...document.querySelectorAll('flt-semantics')].some(
            (n) => (n.getAttribute('aria-label') || '').trim() || (n.textContent || '').trim())
        """)

    async def _ensure_flutter_semantics_populated(self, page, timeout_s: float = 6.0) -> bool:
        """Wait for a labelled Flutter semantics tree, pressing Tab once if the tree stays empty.

        Returns True when populated, False for a non-Flutter page or when it never populates.
        """
        if not await page.evaluate("() => !!document.querySelector('flutter-view, flt-glass-pane')"):
            return False
        deadline = time.time() + timeout_s
        tab_at = time.time() + min(2.0, timeout_s / 2)
        tab_pressed = False
        while True:
            if await self._flutter_semantics_populated(page):
                print(f"[PLAYWRIGHT:FLUTTER] ✅ Semantics tree populated{' after Tab' if tab_pressed else ''}")
                return True
            now = time.time()
            if now >= deadline:
                print(f"[PLAYWRIGHT:FLUTTER] ⚠️ Semantics tree still empty after {timeout_s}s"
                      f" — the app may exclude its semantics (check its config/meta tags)")
                return False
            if not tab_pressed and now >= tab_at:
                print(f"[PLAYWRIGHT:FLUTTER] ⌨️ Semantics tree empty — pressing Tab (keyboard-gated semantics)")
                await page.keyboard.press('Tab')
                tab_pressed = True
            await asyncio.sleep(0.5)

    @ensure_controller_loop
    async def wait_for_iframe_painted(self, selector: str, max_total_ms: int = 12000,
                                       poll_interval_ms: int = 500) -> Dict[str, Any]:
        """Wait until a (cross-origin) iframe's contentDocument actually has elements.

        Why it exists:
          `grecaptcha` (and other widget APIs) loads on the top document and is
          `typeof === 'function'` very quickly — but the iframe's contentDocument
          renders separately and asynchronously. `page.screenshot()` taken before
          the iframe paints shows a blank rectangle in the iframe's area, which
          breaks any image-matching verification downstream (TASK-37 §3 — the
          reCAPTCHA demo page is the canonical case; any cross-origin widget with
          a late-painting iframe hits the same issue).

        Behavior:
          - Resolves `selector` against the top document (CSS selector string).
          - Polls `iframe.contentDocument.body.querySelectorAll('*').length` and
            returns when it is > 0 (i.e. the iframe has rendered some content).
          - Same-origin iframes only: cross-origin iframes return null for
            `contentDocument` and this method will time out, which is the right
            answer (the caller should use a different observation strategy).

        Args:
            selector: CSS selector for the iframe on the top document.
            max_total_ms: Total time to wait before giving up.
            poll_interval_ms: How often to re-check the contentDocument.

        Returns:
            dict with keys: success (bool), painted (bool), element_count (int),
            elapsed_ms (int), error (str, on failure).
        """
        try:
            page = await self._get_persistent_page()
            start_ms = int(time.time() * 1000)
            deadline_ms = start_ms + max_total_ms
            last = {"painted": False, "element_count": 0}
            while True:
                last = await asyncio.wait_for(
                    page.evaluate(
                        """(sel) => {
                            const el = document.querySelector(sel);
                            if (!el || !el.contentDocument || !el.contentDocument.body) {
                                return {painted: false, element_count: 0};
                            }
                            const n = el.contentDocument.body.querySelectorAll('*').length;
                            return {painted: n > 0, element_count: n};
                        }""",
                        selector,
                    ),
                    timeout=5.0,
                )
                if last.get("painted"):
                    return {
                        "success": True,
                        "painted": True,
                        "element_count": last["element_count"],
                        "elapsed_ms": int(time.time() * 1000) - start_ms,
                    }
                if int(time.time() * 1000) >= deadline_ms:
                    return {
                        "success": False,
                        "painted": False,
                        "element_count": last.get("element_count", 0),
                        "elapsed_ms": int(time.time() * 1000) - start_ms,
                        "error": f"iframe '{selector}' did not paint within {max_total_ms}ms "
                                 f"(final element_count={last.get('element_count', 0)})",
                    }
                await asyncio.sleep(poll_interval_ms / 1000.0)
        except Exception as e:
            return {
                "success": False,
                "painted": False,
                "element_count": 0,
                "elapsed_ms": 0,
                "error": f"{type(e).__name__}: {e}",
            }

    @ensure_controller_loop
    async def press_key(self, key: str) -> Dict[str, Any]:
        """Press keyboard key.

        Args:
            key: Key to press ('BACK', 'ESCAPE', 'ENTER', 'OK', etc.)
        """
        try:
            self._log(f"Pressing key: {key}")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            
            # Handle BACK specially - use browser history navigation
            if key.upper() == 'BACK':
                await page.go_back()
                execution_time = int((time.time() - start_time) * 1000)
                result = {
                    'success': True,
                    'error': '',
                    'execution_time': execution_time,
                    'key_pressed': key,
                    'action': 'browser_back'
                }
                print(f"[PLAYWRIGHT]: Browser back navigation successful")
                return result
            
            # Map web-specific keys to Playwright key names
            key_mapping = {
                'ESC': 'Escape', 
                'ESCAPE': 'Escape',
                'OK': 'Enter',
                'ENTER': 'Enter',
                'HOME': 'Home',
                'END': 'End',
                'UP': 'ArrowUp',
                'DOWN': 'ArrowDown', 
                'LEFT': 'ArrowLeft',
                'RIGHT': 'ArrowRight',
                'TAB': 'Tab',
                'SPACE': 'Space',
                'DELETE': 'Delete',
                'BACKSPACE': 'Backspace',
                'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4',
                'F5': 'F5', 'F6': 'F6', 'F7': 'F7', 'F8': 'F8',
                'F9': 'F9', 'F10': 'F10', 'F11': 'F11', 'F12': 'F12'
            }
            
            playwright_key = key_mapping.get(key.upper(), key)
            
            # Press the key
            await page.keyboard.press(playwright_key)
            
            # Page remains persistent for next actions
            
            execution_time = int((time.time() - start_time) * 1000)
            
            result = {
                'success': True,
                'error': '',
                'execution_time': execution_time,
                'key_pressed': key,
                'playwright_key': playwright_key
            }
            
            print(f"[PLAYWRIGHT]: Key press successful: {key} -> {playwright_key}")
            return result
            
        except Exception as e:
            error_msg = f"Key press error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0,
                'key_attempted': key
            }
        
    @ensure_controller_loop
    async def scroll(self, direction: str, amount: int = 300) -> Dict[str, Any]:
        """Scroll the page in a specific direction.
        
        Args:
            direction: Direction to scroll ('up', 'down', 'left', 'right')
            amount: Number of pixels to scroll (default 300)
        """
        try:
            print(f"[PLAYWRIGHT]: Scrolling {direction} by {amount}px")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            
            # Map direction to scroll deltas
            direction_map = {
                'up': (0, -amount),
                'down': (0, amount),
                'left': (-amount, 0),
                'right': (amount, 0)
            }
            
            if direction.lower() not in direction_map:
                return {
                    'success': False,
                    'error': f"Invalid direction '{direction}'. Use 'up', 'down', 'left', or 'right'",
                    'execution_time': 0
                }
            
            delta_x, delta_y = direction_map[direction.lower()]
            
            # Execute scroll using mouse wheel
            await page.mouse.wheel(delta_x, delta_y)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            result = {
                'success': True,
                'error': '',
                'execution_time': execution_time,
                'direction': direction,
                'amount': amount,
                'delta_x': delta_x,
                'delta_y': delta_y
            }
            
            print(f"[PLAYWRIGHT]: Scroll successful: {direction} {amount}px")
            return result
            
        except Exception as e:
            error_msg = f"Scroll error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'execution_time': 0,
                'direction': direction,
                'amount': amount
            }
    
    def get_status(self) -> Dict[str, Any]:
        """Get controller status."""
        try:
            if self.is_connected and self._chrome_running:
                return {
                    'success': True,
                    'current_url': self.current_url,
                    'page_title': self.page_title,
                    'connected': True,
                    'chrome_running': True
                }
            else:
                return {
                    'success': False,
                    'error': 'Chrome not running or not connected',
                    'connected': False,
                    'chrome_running': self._chrome_running
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to check status: {str(e)}',
                'connected': False,
                'chrome_running': False
            }
    
    @ensure_controller_loop
    async def browser_use_task(self, task: str, max_steps: int = 20) -> Dict[str, Any]:
        """Execute browser-use task using existing Chrome instance on controller loop.
        
        Args:
            task: Task description for browser-use
            max_steps: Maximum steps for browser-use agent (default: 20)
        """
        try:
            print(f"[PLAYWRIGHT]: Executing browser-use task: {task} (max_steps={max_steps})")
            start_time = time.time()
            
            # Import browseruse_utils only when needed
            try:
                from backend_host.src.lib.utils.browseruse_utils import BrowserUseManager
            except ImportError as e:
                return {
                    'success': False,
                    'error': f'Browser-use not available: {e}',
                    'task': task,
                    'execution_time': 0
                }
            
            # Create browser-use manager with our utils
            manager = BrowserUseManager(self.utils)
            
            # Execute task (already runs on controller loop via @ensure_controller_loop)
            result = await manager.execute_task(task, max_steps=max_steps)
            
            execution_time = int((time.time() - start_time) * 1000)
            print(f"[PLAYWRIGHT]: Browser-use task completed in {execution_time}ms")
            
            return result
            
        except Exception as e:
            error_msg = f"Browser-use task error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': error_msg,
                'task': task,
                'execution_time': int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
            }
        
    async def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute web automation command with JSON parameters.
        
        Args:
            command: Command to execute
            params: JSON parameters for the command
            
        Returns:
            Dict: Command execution result
        """
        # Thread ownership no longer needed with sync API!

        if params is None:
            params = {}
        
        import threading, asyncio
        print(f"[PLAYWRIGHT]: Executing command '{command}' with params: {params} (thread={threading.current_thread().name})")

        # Ensure we always execute Playwright ops on the controller loop to avoid loop-affinity issues
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        controller_loop = self.__class__._loop
        if controller_loop is None:
            # Initialize loop lazily
            self._ensure_loop()
            controller_loop = self.__class__._loop
        
        # If we're NOT on the controller loop, resubmit this call onto the controller loop and await its result
        if current_loop is None or current_loop is not controller_loop:
            fut = self._submit_to_controller_loop(self.execute_command(command, params))
            if current_loop is None:
                # If no running loop (unlikely inside async), block and return result.
                # Bounded: a wedged controller loop must fail the command, not hang the run.
                try:
                    return _controller_loop_result(fut)
                except TimeoutError as exc:
                    return {'success': False, 'error': str(exc), 'execution_time': 0}
            else:
                # Bridge concurrent.futures.Future to awaitable in current loop, bounded:
                # `asyncio.wait` leaves the pending work alone on timeout, where
                # `wait_for` waits for a cancellation a running coroutine never grants.
                wrapped = asyncio.wrap_future(fut)
                done, _pending = await asyncio.wait(
                    {wrapped}, timeout=CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS)
                if not done:
                    wrapped.cancel()
                    return {
                        'success': False,
                        'error': (f'The Playwright controller loop did not answer within '
                                  f'{CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS:g}s'),
                        'execution_time': 0,
                    }
                return wrapped.result()
        
        # ============== From here on, we are on the controller loop ==============
        if command in ('navigate_to_url', 'navigate'):
            url = params.get('url')
            # The goto has its own timeout (BUG-0714): `wait_time` is the pause AFTER the action, never the load limit
            timeout = resolve_goto_timeout(params)
            follow_redirects = params.get('follow_redirects', True)
            
            if not url:
                return {
                    'success': False,
                    'error': 'URL parameter is required',
                    'execution_time': 0
                }

            # Pre-check: resolve hostname and verify reachability before navigation
            import socket
            from urllib.parse import urlparse
            parsed = urlparse(url if '://' in url else f'http://{url}')
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)

            if host:
                # Step 1: DNS resolution
                try:
                    socket.getaddrinfo(host, port)
                except socket.gaierror:
                    print(f"[PLAYWRIGHT]: DNS resolution failed for '{host}' - check /etc/hosts or DNS")
                    return {
                        'success': False,
                        'error': f"Cannot resolve hostname '{host}' - check /etc/hosts or DNS configuration",
                        'execution_time': 0
                    }

                # Step 2: TCP reachability (3s timeout)
                try:
                    sock = socket.create_connection((host, port), timeout=3)
                    sock.close()
                except (socket.timeout, ConnectionRefusedError, OSError) as e:
                    print(f"[PLAYWRIGHT]: Host unreachable {host}:{port} - {e}")
                    return {
                        'success': False,
                        'error': f"Host unreachable: {host}:{port} - {e}",
                        'execution_time': 0
                    }

            return await self.navigate_to_url(url, timeout=timeout, follow_redirects=follow_redirects)
        
        elif command == 'click_element':
            # Standardize parameter names: convert 'text', 'selector', 'xpath' to 'element_id'
            element_id = params.get('element_id') or params.get('selector') or params.get('text')
            if not element_id and params.get('xpath'):
                element_id = params['xpath'] if params['xpath'].startswith('xpath=') else f"xpath={params['xpath']}"
            
            if not element_id:
                return {
                    'success': False,
                    'error': 'element_id parameter is required (an id like #login, CSS, XPath or the visible text)',
                    'execution_time': 0
                }
                
            return await self.click_element(element_id)
        
        elif command == 'find_element':
            # Standardize parameter names: convert 'element_id', 'text' to 'selector'
            selector = params.get('selector') or params.get('element_id') or params.get('text')
            
            if not selector:
                return {
                    'success': False,
                    'error': 'selector parameter is required',
                    'execution_time': 0
                }
                
            return await self.find_element(selector)
        
        elif command == 'hover_element':
            # Standardize parameter names: convert 'element_id', 'text' to 'selector'
            selector = params.get('selector') or params.get('element_id') or params.get('text')
            
            if not selector:
                return {
                    'success': False,
                    'error': 'selector parameter is required',
                    'execution_time': 0
                }
                
            return await self.hover_element(selector)
        
        elif command == 'input_text':
            # The field may come as selector, element_id or xpath (Playwright reads
            # //... as XPath); none at all types into the focused field.
            selector = params.get('selector') or params.get('element_id') or params.get('xpath')
            text = params.get('text', '')
            timeout = params.get('timeout', INPUT_TEXT_SETTLE_MS)
            press_enter = bool(params.get('press_enter', False))

            return await self.input_text(selector, text, wait_time=timeout, press_enter=press_enter)
        
        elif command == 'tap_x_y':
            x = params.get('x')
            y = params.get('y')
            
            if x is None or y is None:
                return {
                    'success': False,
                    'error': 'X and Y coordinates are required',
                    'execution_time': 0
                }
                
            return await self.tap_x_y(x, y)
        
        elif command == 'execute_javascript':
            script = params.get('script')
            
            if not script:
                return {
                    'success': False,
                    'error': 'Script parameter is required',
                    'execution_time': 0
                }
                
            return await self.execute_javascript(script)
        
        elif command == 'get_page_info':
            return await self.get_page_info()
        
        elif command == 'activate_semantic':
            return await self.activate_semantic()

        elif command == 'override_page_meta':
            name = params.get('name')
            if not name:
                return {
                    'success': False,
                    'error': 'name parameter is required',
                    'execution_time': 0
                }
            return await self.override_page_meta(name, str(params.get('content', '')))
        
        elif command == 'open_browser':
            return await self.open_browser()
        
        elif command == 'close_browser':
            # Wait for the cleanup and report its real outcome: a caller that trusts
            # this result must not be told a browser died that is still running
            # (BUG-0760). The browser closed is the same one as before.
            return await self.close_browser_confirmed()
        
        elif command == 'connect_browser':
            return await self.connect_browser()
        
        elif command == 'dump_elements':
            element_types = params.get('element_types', 'all')
            include_hidden = params.get('include_hidden', False)
            return await self.dump_elements(element_types=element_types, include_hidden=include_hidden)
        
        elif command == 'browser_use_task':
            task = params.get('task', '')
            max_steps = params.get('max_steps', 20)
            
            if not task:
                return {
                    'success': False,
                    'error': 'Task parameter is required',
                    'execution_time': 0
                }
            
            return await self.browser_use_task(task, max_steps=max_steps)
        
        elif command == 'press_key':
            key = params.get('key')

            if not key:
                return {
                    'success': False,
                    'error': 'Key parameter is required',
                    'execution_time': 0
                }

            return await self.press_key(key)

        elif command == 'wait_for_iframe_painted':
            selector = params.get('selector')
            if not selector:
                return {
                    'success': False,
                    'error': 'selector parameter is required',
                    'execution_time': 0,
                }
            max_total_ms = int(params.get('max_total_ms', 12000))
            poll_interval_ms = int(params.get('poll_interval_ms', 500))
            return await self.wait_for_iframe_painted(
                selector, max_total_ms=max_total_ms, poll_interval_ms=poll_interval_ms
            )
        
        elif command == 'scroll':
            direction = params.get('direction')
            amount = params.get('amount', 300)
            
            if not direction:
                return {
                    'success': False,
                    'error': 'Direction parameter is required (up, down, left, right)',
                    'execution_time': 0
                }
            
            return await self.scroll(direction, amount)
        
        elif command == 'set_viewport_size':
            width = params.get('width')
            height = params.get('height')
            
            if not width or not height:
                return {
                    'success': False,
                    'error': 'Width and height parameters are required',
                    'execution_time': 0
                }
            
            self.set_viewport_size(width, height)
            return {
                'success': True,
                'message': f'Viewport size set to {width}x{height}',
                'execution_time': 0
            }
        
        else:
            print(f"[PLAYWRIGHT]: Unknown command: {command}")
            return {
                'success': False,
                'error': f'Unknown command: {command}. {unknown_command_hint(command)}'
                         f'Call list_actions for the web commands.',
                'execution_time': 0
            }
    
    async def _try_activate_flutter_semantics(self) -> bool:
        """
        Helper method to try activating Flutter semantics (both standard and shadow DOM).
        
        Returns:
            True if activation attempted, False if not a Flutter app
        """
        try:
            page = await self._get_persistent_page()
            
            flutter_check_js = """
            () => {
                // Method 1: Standard DOM (most common)
                let placeholder = document.querySelector('flt-semantics-placeholder');
                if (placeholder) {
                    placeholder.click();
                    return 'standard';
                }
                
                // Method 2: Shadow DOM (less common)
                const flutterView = document.querySelector('body>flutter-view > flt-glass-pane');
                if (flutterView && flutterView.shadowRoot) {
                    placeholder = flutterView.shadowRoot.querySelector('flt-semantics-placeholder');
                    if (placeholder) {
                        placeholder.click();
                        return 'shadow-dom';
                    }
                }
                
                return null; // Not a Flutter app
            }
            """
            flutter_type = await page.evaluate(flutter_check_js)
            if flutter_type:
                print(f"[PLAYWRIGHT]: 🦋 Flutter semantics activation attempted ({flutter_type})")
                return True
            return False
        except Exception as e:
            print(f"[PLAYWRIGHT]: Flutter activation error (non-fatal): {e}")
            return False
    
    @ensure_controller_loop
    async def dump_elements(self, element_types: str = "all", include_hidden: bool = False) -> Dict[str, Any]:
        """
        Dump all visible elements from the page for debugging and inspection.
        
        Args:
            element_types: Types of elements to include ('all', 'interactive', 'text', 'links')
            include_hidden: Whether to include hidden elements
        """
        try:
            print(f"[PLAYWRIGHT]: Dumping elements (type: {element_types}, include_hidden: {include_hidden})")
            start_time = time.time()
            
            # Get persistent page from browser+context
            page = await self._get_persistent_page()
            print(f"[PLAYWRIGHT]: Got persistent page (url={page.url}), preparing to dump elements")
            
            # JavaScript code to extract visible elements
            js_code = f"""
            () => {{
                const elementTypes = '{element_types}';
                const includeHidden = {str(include_hidden).lower()};
                
                // Define element selectors based on type
                let selectors = [];
                
                if (elementTypes === 'all' || elementTypes === 'interactive') {{
                    selectors.push(
                        'button', 'input', 'select', 'textarea', 'a[href]', 
                        '[onclick]', '[role="button"]', '[tabindex]'
                    );
                }}
                
                if (elementTypes === 'all' || elementTypes === 'text') {{
                    selectors.push('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'div');
                }}
                
                if (elementTypes === 'all' || elementTypes === 'links') {{
                    selectors.push('a[href]');
                }}
                
                if (elementTypes === 'all') {{
                    // Add form elements, media, etc.
                    selectors.push('img', 'video', 'iframe', 'form', 'label');
                    // Add Flutter semantic elements
                    selectors.push('flt-semantics', 'flt-semantic-node', '[id^="flt-semantic-node"]');
                }}
                
                // Get all elements matching selectors
                const allElements = document.querySelectorAll(selectors.join(', '));
                const elements = [];
                
                allElements.forEach((el, index) => {{
                    // Check if element is visible
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const isVisible = rect.width > 0 && rect.height > 0 && 
                                    style.visibility !== 'hidden' && 
                                    style.display !== 'none' &&
                                    rect.top < window.innerHeight && 
                                    rect.bottom > 0;
                    
                    if (isVisible || includeHidden) {{
                        // Generate selector for this element
                        let selector = el.tagName.toLowerCase();
                        
                        // Add ID if available
                        if (el.id) {{
                            selector = '#' + el.id;
                        }} else {{
                            // Add class if available
                            if (el.className && typeof el.className === 'string') {{
                                const classes = el.className.trim().split(/\\s+/).slice(0, 2);
                                if (classes.length > 0) {{
                                    selector += '.' + classes.join('.');
                                }}
                            }}
                            
                            // Add nth-child if no unique identifier
                            if (!el.id && (!el.className || el.className === '')) {{
                                const parent = el.parentNode;
                                if (parent) {{
                                    const siblings = Array.from(parent.children).filter(child => 
                                        child.tagName === el.tagName
                                    );
                                    if (siblings.length > 1) {{
                                        const index = siblings.indexOf(el) + 1;
                                        selector += `:nth-child(${{index}})`;
                                    }}
                                }}
                            }}
                        }}
                        
                        // Get text content (limited to first 100 chars)
                        let textContent = '';
                        if (el.textContent) {{
                            textContent = el.textContent.trim().substring(0, 100);
                            if (el.textContent.trim().length > 100) {{
                                textContent += '...';
                            }}
                        }}
                        
                        // Get attributes of interest including aria labels
                        const attributes = {{}};
                        if (el.href) attributes.href = el.href;
                        if (el.value) attributes.value = el.value;
                        if (el.placeholder) attributes.placeholder = el.placeholder;
                        if (el.title) attributes.title = el.title;
                        if (el.alt) attributes.alt = el.alt;
                        if (el.type) attributes.type = el.type;
                        if (el.name) attributes.name = el.name;
                        
                        // Aria attributes for accessibility and Flutter semantics
                        if (el.getAttribute('aria-label')) attributes['aria-label'] = el.getAttribute('aria-label');
                        if (el.getAttribute('aria-labelledby')) attributes['aria-labelledby'] = el.getAttribute('aria-labelledby');
                        if (el.getAttribute('aria-describedby')) attributes['aria-describedby'] = el.getAttribute('aria-describedby');
                        if (el.getAttribute('aria-role')) attributes['aria-role'] = el.getAttribute('aria-role');
                        if (el.getAttribute('role')) attributes.role = el.getAttribute('role');
                        if (el.getAttribute('data-semantics-role')) attributes['data-semantics-role'] = el.getAttribute('data-semantics-role');
                        if (el.getAttribute('flt-semantic-role')) attributes['flt-semantic-role'] = el.getAttribute('flt-semantic-role');
                        
                        elements.push({{
                            index: index,
                            tagName: el.tagName.toLowerCase(),
                            selector: selector,
                            textContent: textContent,
                            attributes: attributes,
                            position: {{
                                x: Math.round(rect.left),
                                y: Math.round(rect.top),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            }},
                            isVisible: isVisible,
                            className: el.className,
                            id: el.id || null
                        }});
                    }}
                }});
                
                return {{
                    elements: elements,
                    totalCount: elements.length,
                    visibleCount: elements.filter(el => el.isVisible).length,
                    pageTitle: document.title,
                    pageUrl: window.location.href,
                    viewport: {{
                        width: window.innerWidth,
                        height: window.innerHeight
                    }}
                }};
            }}
            """
            
            # Execute the JavaScript with proper timeout and error handling
            try:
                print(f"[PLAYWRIGHT]: Starting page.evaluate() with 5s timeout")
                import asyncio as _asyncio
                result = await _asyncio.wait_for(page.evaluate(js_code), timeout=5.0)
                print(f"[PLAYWRIGHT]: page.evaluate() completed successfully")
            except _asyncio.TimeoutError:
                error_msg = "Element dump timed out after 5 seconds - page may be unresponsive"
                print(f"[PLAYWRIGHT]: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'elements': [],
                    'summary': {},
                    'execution_time': int((time.time() - start_time) * 1000)
                }
            except Exception as eval_error:
                error_msg = f"Element dump evaluation error: {type(eval_error).__name__}: {str(eval_error)}"
                print(f"[PLAYWRIGHT]: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'elements': [],
                    'summary': {},
                    'execution_time': int((time.time() - start_time) * 1000)
                }
            
            # Page remains persistent for next actions
            
            execution_time = int((time.time() - start_time) * 1000)
            
            print(f"[PLAYWRIGHT]: Found {result['totalCount']} elements ({result['visibleCount']} visible)")
            
            # -------------------------------------------------------
            # FLUTTER SEMANTICS (lazy activation, re-checked on every dump)
            # -------------------------------------------------------
            # Checking the dump is free, and an app can drop its semantics tree at any time
            # (e.g. a pointer click leaving keyboard/a11y mode), so readiness is never cached.
            if self._flutter_app_detected is None:
                self._flutter_app_detected = any(el.get('tagName') == 'flutter-view' for el in result['elements'])
                print(f"[PLAYWRIGHT:FLUTTER] 📱 Flutter view detection: {self._flutter_app_detected}")

            def _has_labelled_semantics(elements) -> bool:
                # An excluded/collapsed tree still renders empty flt-semantic-node-* ids
                return any(
                    el.get('id') and 'flt-semantic-node' in el.get('id')
                    and ((el.get('textContent') or '').strip() or el.get('attributes', {}).get('aria-label'))
                    for el in elements
                )

            if self._flutter_app_detected and not _has_labelled_semantics(result['elements']):
                print(f"[PLAYWRIGHT:FLUTTER] ⚠️ Flutter semantics tree empty - re-activating...")
                activation_result = await self._try_activate_flutter_semantics()
                print(f"[PLAYWRIGHT:FLUTTER] 🔧 Placeholder activation attempted: {activation_result}")
                await self._ensure_flutter_semantics_populated(page)

                result = await _asyncio.wait_for(page.evaluate(js_code), timeout=5.0)
                execution_time = int((time.time() - start_time) * 1000)
                print(f"[PLAYWRIGHT:FLUTTER] 📊 Re-dump found {result['totalCount']} elements ({result['visibleCount']} visible),"
                      f" labelled semantics: {_has_labelled_semantics(result['elements'])}")
            # -------------------------------------------------------
            
            summary = {
                'total_count': result['totalCount'],
                'visible_count': result['visibleCount'],
                'page_title': result['pageTitle'],
                'page_url': result['pageUrl'],
                'viewport': result['viewport'],
                'element_types': element_types,
                'include_hidden': include_hidden
            }
            return {
                'success': True,
                'elements': result['elements'],
                'summary': summary,
                'execution_time': execution_time,
                'error': '',
                'output_data': {
                    'page_title': result['pageTitle'],
                    'page_url': result['pageUrl'],
                    'total_elements': result['totalCount'],
                    'visible_elements': result['visibleCount'],
                    'elements': [
                        {k: v for k, v in el.items() if k in ('tagName', 'textContent', 'id', 'attributes', 'isVisible')}
                        for el in result['elements'][:50]  # Limit to 50 elements to avoid token bloat
                    ]
                }
            }
                
        except Exception as e:
            error_msg = f"Dump elements error: {e}"
            print(f"[PLAYWRIGHT]: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'elements': [],
                'summary': {}
            }
        
    async def getMenuInfo(self, area: dict = None, context = None) -> Dict[str, Any]:
        """
        Extract menu info from web elements (Playwright-based alternative to OCR getMenuInfo)
        Same interface as text.getMenuInfo but uses dump_elements instead of OCR
        
        Args:
            area: Optional area to filter elements (x, y, width, height)
            context: Execution context for metadata storage
            
        Returns:
            Same format as text.getMenuInfo:
            {
                success: bool,
                output_data: {
                    parsed_data: dict,
                    raw_output: str
                },
                message: str
            }
        """
        print(f"[@controller:PlaywrightWeb:getMenuInfo] Params: area={area}, context={context is not None}")
        
        try:
            # 1. Dump web elements (already exists)
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Dumping web elements...")
            dump_result = await self.dump_elements(element_types='all', include_hidden=False)
            
            if not dump_result.get('success'):
                error = dump_result.get('error', 'Unknown error')
                print(f"[@controller:PlaywrightWeb:getMenuInfo] FAIL: Element dump failed: {error}")
                return {
                    'success': False,
                    'output_data': {},
                    'message': f'Failed to dump elements: {error}'
                }
            
            elements = dump_result.get('elements', [])
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Dumped {len(elements)} web elements")
            
            # 2. Filter by area if specified
            filtered_elements = elements
            if area:
                filtered_elements = []
                for elem in elements:
                    pos = elem.get('position', {})
                    elem_x = pos.get('x', 0)
                    elem_y = pos.get('y', 0)
                    elem_width = pos.get('width', 0)
                    elem_height = pos.get('height', 0)
                    
                    # Check if element overlaps with area
                    area_x = area.get('x', 0)
                    area_y = area.get('y', 0)
                    area_width = area.get('width', 99999)
                    area_height = area.get('height', 99999)
                    
                    # Element is in area if it overlaps
                    if (elem_x < area_x + area_width and
                        elem_x + elem_width > area_x and
                        elem_y < area_y + area_height and
                        elem_y + elem_height > area_y):
                        filtered_elements.append(elem)
                
                print(f"[@controller:PlaywrightWeb:getMenuInfo] Filtered to {len(filtered_elements)} elements in area")
            
            # 3. Parse key-value pairs from element text
            parsed_data = {}
            for elem in filtered_elements:
                text = elem.get('textContent', '').strip()
                
                # Skip empty text
                if not text or len(text) < 2:
                    continue
                
                # Parse key-value pairs
                # Pattern 1: "Key: Value" (colon separator)
                if ':' in text and len(text) < 100:  # Reasonable length for key-value
                    parts = text.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().replace(' ', '_').replace('-', '_')
                        value = parts[1].strip()
                        if key and value:  # Both must be non-empty
                            parsed_data[key] = value
                            print(f"  • {key} = {value}")
                
                # Pattern 2: "Key\nValue" (newline separator)
                elif '\n' in text:
                    lines = text.split('\n')
                    if len(lines) >= 2:
                        key = lines[0].strip().replace(' ', '_').replace('-', '_')
                        value = '\n'.join(lines[1:]).strip()
                        if key and value:  # Both must be non-empty
                            parsed_data[key] = value
                            print(f"  • {key} = {value}")
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Parsed {len(parsed_data)} key-value pairs")
            
            if not parsed_data:
                print(f"[@controller:PlaywrightWeb:getMenuInfo] WARNING: No key-value pairs found in web elements")
            
            # 4. Auto-store to context.metadata (same as OCR version)
            if context:
                from datetime import datetime
                
                # Initialize metadata if not exists
                if not hasattr(context, 'metadata'):
                    context.metadata = {}
                
                # Append parsed data directly to metadata (flat structure)
                for key, value in parsed_data.items():
                    context.metadata[key] = value
                
                # Add extraction metadata
                context.metadata['extraction_method'] = 'web_elements'
                context.metadata['extraction_timestamp'] = datetime.now().isoformat()
                context.metadata['element_count'] = len(filtered_elements)
                
                # Add page info
                summary = dump_result.get('summary', {})
                context.metadata['page_title'] = summary.get('page_title', '')
                context.metadata['page_url'] = summary.get('page_url', '')
                
                if area:
                    context.metadata['extraction_area'] = str(area)
                
                print(f"[@controller:PlaywrightWeb:getMenuInfo] ✅ AUTO-APPENDED to context.metadata (FLAT)")
                print(f"[@controller:PlaywrightWeb:getMenuInfo] Metadata keys: {list(context.metadata.keys())}")
                print(f"[@controller:PlaywrightWeb:getMenuInfo] New fields added: {list(parsed_data.keys())}")
            else:
                print(f"[@controller:PlaywrightWeb:getMenuInfo] WARNING: No context provided, metadata not stored")
            
            # 5. Prepare output data with FULL raw dump for debugging
            raw_dump = []
            for elem in filtered_elements:
                raw_dump.append({
                    'index': elem.get('index'),
                    'tagName': elem.get('tagName'),
                    'selector': elem.get('selector'),
                    'textContent': elem.get('textContent'),
                    'className': elem.get('className'),
                    'id': elem.get('id'),
                    'attributes': elem.get('attributes', {}),
                    'position': elem.get('position', {}),
                    'isVisible': elem.get('isVisible'),
                    'aria-label': elem.get('attributes', {}).get('aria-label'),
                    'role': elem.get('attributes', {}).get('role'),
                    'href': elem.get('attributes', {}).get('href'),
                    'title': elem.get('attributes', {}).get('title')
                })
            
            output_data = {
                'parsed_data': parsed_data,
                'raw_dump': raw_dump,  # Full structured dump for debugging
                'element_count': len(filtered_elements)
            }
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] 📤 RETURNING output_data with {len(parsed_data)} parsed_data entries")
            print(f"[@controller:PlaywrightWeb:getMenuInfo] 📤 output_data keys: {list(output_data.keys())}")
            
            # 6. Return same format as text.getMenuInfo
            message = f'Parsed {len(parsed_data)} fields from {len(filtered_elements)} web elements'
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] ✅ SUCCESS: {message}")
            
            return {
                'success': True,
                'output_data': output_data,
                'message': message
            }
            
        except Exception as e:
            error_msg = f"Error extracting menu info from web elements: {str(e)}"
            print(f"[@controller:PlaywrightWeb:getMenuInfo] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'output_data': {},
                'message': error_msg
            }
    
    # Note: get_available_verifications is defined below with ALL verifications combined
    
    # Note: execute_verification is defined below with ALL commands combined
    
    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for Playwright web controller."""
        return {
            'Web': [
                # Browser management
                {
                    'id': 'open_browser',
                    'label': 'Open Browser',
                    'command': 'open_browser',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Open the browser window',
                    'requiresInput': False
                },
                {
                    'id': 'close_browser',
                    'label': 'Close Browser',
                    'command': 'close_browser',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Close the browser window',
                    'requiresInput': False
                },
                {
                    'id': 'connect_browser',
                    'label': 'Connect Browser',
                    'command': 'connect_browser',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Connect to existing Chrome debug session',
                    'requiresInput': False
                },
                # Navigation
                {
                    'id': 'navigate_to_url',
                    'label': 'Navigate to URL',
                    'command': 'navigate_to_url',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Navigate to a specific URL',
                    'requiresInput': True,
                    'inputLabel': 'URL',
                    'inputPlaceholder': 'https://google.com'
                },
                # Element interaction
                {
                    'id': 'click_element',
                    'label': 'Click Element by Text',
                    'command': 'click_element',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Click an element by text/ID (same as Android - dump UI first, then click)',
                    'requiresInput': True,
                    'inputLabel': 'Element Text/ID',
                    'inputPlaceholder': 'Submit Button'
                },
                {
                    'id': 'find_element',
                    'label': 'Find Element',
                    'command': 'find_element',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Find an element by text/selector/aria-label (returns element ID and position like click_element)',
                    'requiresInput': True,
                    'inputLabel': 'Selector or text',
                    'inputPlaceholder': 'TV Guide or #flt-semantic-node-6'
                },
                {
                    'id': 'hover_element',
                    'label': 'Hover Element',
                    'command': 'hover_element',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Hover over an element to trigger rollover effects',
                    'requiresInput': True,
                    'inputLabel': 'Selector or text',
                    'inputPlaceholder': '#player-controls or Play Button'
                },
                {
                    'id': 'input_text',
                    'label': 'Input Text',
                    'command': 'input_text',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Type text into an input field (params: selector, text, optional press_enter; no selector types into the focused field)',
                    'requiresInput': True,
                    'inputLabel': 'CSS selector and text (comma separated)',
                    'inputPlaceholder': '#username,myusername'
                },
                {
                    'id': 'tap_x_y',
                    'label': 'Click Coordinates',
                    'command': 'tap_x_y',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Click at specific coordinates',
                    'requiresInput': True,
                    'inputLabel': 'Coordinates (x,y)',
                    'inputPlaceholder': '100,200'
                },
                {
                    'id': 'wait_for_iframe_painted',
                    'label': 'Wait For Iframe Painted',
                    'command': 'wait_for_iframe_painted',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Wait until an iframe\'s contentDocument has rendered elements '
                                   '(polls contentDocument.body.querySelectorAll length). Same-origin iframes only.',
                    'requiresInput': True,
                    'inputLabel': 'iframe CSS selector',
                    'inputPlaceholder': 'iframe[src*="recaptcha"]'
                },
                # JavaScript execution
                {
                    'id': 'execute_javascript',
                    'label': 'Execute JavaScript',
                    'command': 'execute_javascript',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Execute custom JavaScript code',
                    'requiresInput': True,
                    'inputLabel': 'JavaScript code',
                    'inputPlaceholder': 'alert("Hello World")'
                },
                # Page information
                {
                    'id': 'get_page_info',
                    'label': 'Get Page Info',
                    'command': 'get_page_info',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Get current page URL and title',
                    'requiresInput': False
                },
                # Flutter web specific
                {
                    'id': 'activate_semantic',
                    'label': 'Activate Semantic',
                    'command': 'activate_semantic',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Activate semantic for Flutter web apps',
                    'requiresInput': False
                },
                {
                    'id': 'override_page_meta',
                    'label': 'Override Page Meta',
                    'command': 'override_page_meta',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Force a <meta name> content on every page load (params: name, content); run before navigate_to_url',
                    'requiresInput': True,
                    'inputLabel': 'Meta name and content',
                    'inputPlaceholder': 'DISABLE_WEB_SEMANTICS,false'
                },
                # Element inspection
                {
                    'id': 'dump_elements',
                    'label': 'Dump Page Elements',
                    'command': 'dump_elements',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Get all visible elements on the page',
                    'requiresInput': False
                },
                # AI-powered browser automation
                {
                    'id': 'browser_use_task',
                    'label': 'AI Browser Task',
                    'command': 'browser_use_task',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Execute a complex browser task using AI',
                    'requiresInput': True,
                    'inputLabel': 'Task description',
                    'inputPlaceholder': 'Search for Python tutorials on Google'
                },
                # Keyboard controls
                {
                    'id': 'press_key',
                    'label': 'Press Key',
                    'command': 'press_key',
                    'action_type': 'web',
                    'params': {},
                    'description': 'Press keyboard key',
                    'requiresInput': True,
                    'inputLabel': 'Key',
                    'inputPlaceholder': 'UP',
                    'options': ['BACK', 'ESC', 'ESCAPE', 'OK', 'ENTER', 'HOME', 'END', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'TAB', 'SPACE', 'DELETE', 'BACKSPACE', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12']
                },
                {
                    'id': 'press_key_back',
                    'label': 'Back',
                    'command': 'press_key',
                    'action_type': 'web',
                    'params': {'key': 'BACK'},
                    'description': 'Press Escape key (browser back)',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_ok',
                    'label': 'OK',
                    'command': 'press_key',
                    'action_type': 'web',
                    'params': {'key': 'OK'},
                    'description': 'Press Enter key (confirm)',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_esc',
                    'label': 'Esc',
                    'command': 'press_key',
                    'action_type': 'web',
                    'params': {'key': 'ESCAPE'},
                    'description': 'Press Escape key (cancel)',
                    'requiresInput': False
                },
                # Scroll controls
                {
                    'id': 'scroll_up',
                    'label': 'Scroll Up',
                    'command': 'scroll',
                    'action_type': 'web',
                    'params': {'direction': 'up', 'amount': 300},
                    'description': 'Scroll page up by 300 pixels',
                    'requiresInput': False
                },
                {
                    'id': 'scroll_down',
                    'label': 'Scroll Down',
                    'command': 'scroll',
                    'action_type': 'web',
                    'params': {'direction': 'down', 'amount': 300},
                    'description': 'Scroll page down by 300 pixels',
                    'requiresInput': False
                },
                {
                    'id': 'scroll_left',
                    'label': 'Scroll Left',
                    'command': 'scroll',
                    'action_type': 'web',
                    'params': {'direction': 'left', 'amount': 300},
                    'description': 'Scroll page left by 300 pixels',
                    'requiresInput': False
                },
                {
                    'id': 'scroll_right',
                    'label': 'Scroll Right',
                    'command': 'scroll',
                    'action_type': 'web',
                    'params': {'direction': 'right', 'amount': 300},
                    'description': 'Scroll page right by 300 pixels',
                    'requiresInput': False
                }
            ]
        }
    
    # Note: All verification methods (waitForElementToAppear, waitForElementToDisappear, 
    # checkElementExists, getMenuInfo, execute_verification, get_available_verifications) 
    # are now in PlaywrightVerificationsMixin (playwright_verifications.py)
