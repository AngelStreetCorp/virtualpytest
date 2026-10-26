"""
tests/backend_host/test_playwright_connect_decision.py — what a web script does when it takes the
device and finds the Chromium debug port free, or already served by a browser (BUG-0179).

The rule: port free → launch; port busy → the browser there is an orphan (the server-side device
lock is what keeps two runs off one browser), so attach to it and reuse it, or — if it does not
answer — kill its process group and launch fresh. Never wait for it to leave. The old code slept
up to 300 s here, which turned every goto after an un-closed browser into a six-minute run.

And the other half: teardown must close the browser whether the run launched it or only attached
to it, so the next run finds the port free. The observed orphan chain started with a run that
attached through a verification probe, owned no process handle, and therefore killed nothing.
"""
import asyncio
import importlib
import signal

import pytest

playwright_mod = importlib.import_module('backend_host.src.controllers.web.playwright')
PlaywrightWebController = playwright_mod.PlaywrightWebController
utils_mod = importlib.import_module('backend_host.src.lib.utils.playwright_utils')
ChromeManager = utils_mod.ChromeManager

SIGKILL = utils_mod._SIGKILL


# ---------------------------------------------------------------------------
# Fakes: a browser process, a Playwright connection, and the utils facade
# ---------------------------------------------------------------------------

class FakePopen:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode


class FakePage:
    url = 'chrome://new-tab-page/'

    def __init__(self, hang=False):
        self.hang = hang

    async def evaluate(self, _expression):
        if self.hang:
            await asyncio.Event().wait()  # never set: a wedged renderer
        return 1

    async def title(self):
        return 'tab'


class FakeContext:
    def __init__(self, page):
        self.pages = [page]

    async def new_page(self):
        return self.pages[0]


class FakeCdpSession:
    def __init__(self, browser, fail=False):
        self.browser = browser
        self.fail = fail

    async def send(self, method, params=None):
        if self.fail:
            raise RuntimeError('Target closed')
        self.browser.cdp_commands.append(method)
        return {}


class FakeBrowser:
    def __init__(self, context, cdp_fails=False):
        self.contexts = [context]
        self.cdp_commands = []
        self.cdp_fails = cdp_fails
        self.closed = False

    async def new_browser_cdp_session(self):
        return FakeCdpSession(self, fail=self.cdp_fails)

    async def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakeChromeManager:
    """`page_after` = how many cdp_page_ready polls a browser takes to list its startup tab
    (None: never)."""

    def __init__(self, port_busy, page_after=1):
        self.port_busy = port_busy
        self.shutdowns = []
        self.page_after = page_after
        self.page_polls = 0

    def cdp_healthy(self, debug_port=9222, timeout=2.0):
        return self.port_busy

    def port_listening(self, debug_port=9222, timeout=0.25):
        return self.port_busy

    def cdp_page_ready(self, debug_port=9222, timeout=1.0):
        self.page_polls += 1
        return self.port_busy and self.page_after is not None and self.page_polls >= self.page_after

    def shutdown_chrome(self, debug_port=9222, chrome_process=None, timeout=5.0):
        self.shutdowns.append(debug_port)
        self.port_busy = False
        return True


class FakeUtils:
    """Stands in for PlaywrightUtils. `attach` is what the browser on the port does when a
    Playwright connects: 'ok', 'refuse' (connection error) or 'hang' (answers CDP, page dead)."""

    def __init__(self, port_busy=False, attach='ok'):
        self.debug_port = 9222
        self.chrome_manager = FakeChromeManager(port_busy)
        self.attach = attach
        self.calls = []
        self.playwrights = []

    def launch_chrome(self):
        self.calls.append('launch')
        self.chrome_manager.port_busy = True
        return FakePopen()

    async def connect_to_chrome(self, cdp_url=None, target_url=None):
        self.calls.append('attach')
        if self.attach == 'refuse':
            raise Exception('CDP connection failed (ECONNREFUSED)')
        page = FakePage(hang=(self.attach == 'hang'))
        context = FakeContext(page)
        playwright = FakePlaywright()
        self.playwrights.append(playwright)
        return playwright, FakeBrowser(context), context, page

    def kill_chrome(self, chrome_process=None):
        self.calls.append(('kill_chrome', chrome_process))
        self.chrome_manager.port_busy = False
        return True


def _reset_class_state():
    PlaywrightWebController._chrome_process = None
    PlaywrightWebController._chrome_running = False
    PlaywrightWebController._playwright = None
    PlaywrightWebController._browser = None
    PlaywrightWebController._context = None
    PlaywrightWebController._browser_connected = False


@pytest.fixture(autouse=True)
def private_port_registry(tmp_path, monkeypatch):
    """The port registry is per host and shared: a test must not read the host's one.

    A live entry for the debug port would make the cleanup believe another run owns
    the browser on it (TASK-146) - and that is exactly the decision these tests check.
    """
    from shared.src.lib.utils import browser_port_allocator
    registry_dir = tmp_path / 'registry'
    registry_dir.mkdir(exist_ok=True)
    monkeypatch.setenv(browser_port_allocator.REGISTRY_ENV, str(registry_dir))
    yield


@pytest.fixture
def controller():
    _reset_class_state()
    ctl = PlaywrightWebController(browser_engine='chromium')
    yield ctl
    _reset_class_state()


@pytest.fixture
def sleeps(monkeypatch):
    """Record every asyncio.sleep the controller asks for, without actually sleeping."""
    recorded = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        recorded.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    return recorded


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# The connect decision
# ---------------------------------------------------------------------------

def test_port_free_launches(controller, sleeps):
    controller.utils = FakeUtils(port_busy=False)

    assert run(controller.connect()) is True

    assert controller.utils.calls == ['launch']
    assert controller.utils.chrome_manager.shutdowns == []
    assert isinstance(PlaywrightWebController._chrome_process, FakePopen)
    assert PlaywrightWebController._chrome_running is True
    assert sleeps == [], 'the launched browser listed its tab on the first poll: no settle delay'


def test_port_busy_reuses_the_browser_without_waiting(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')

    assert run(controller.connect()) is True

    assert controller.utils.calls == ['attach']
    assert controller.utils.chrome_manager.shutdowns == []
    assert PlaywrightWebController._chrome_process is None, 'attached, nothing launched'
    assert PlaywrightWebController._chrome_running is True
    assert PlaywrightWebController._browser_connected is True
    assert isinstance(PlaywrightWebController._browser, FakeBrowser)
    assert isinstance(PlaywrightWebController._context, FakeContext)
    assert sleeps == [], 'no busy-wait, no settle delay for a browser that is already up'


def test_port_busy_but_browser_refuses_cdp_kills_it_and_launches(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='refuse')

    assert run(controller.connect()) is True

    assert controller.utils.calls == ['attach', 'launch']
    assert controller.utils.chrome_manager.shutdowns == [9222], 'the orphan was killed first'
    assert isinstance(PlaywrightWebController._chrome_process, FakePopen)
    assert sleeps == []


def test_port_busy_but_page_is_wedged_times_out_then_kills_and_launches(controller, sleeps, monkeypatch):
    """A browser that answers /json/version but whose page never executes anything: the
    attach is bounded by BROWSER_ATTACH_TIMEOUT_SECONDS, not by a 300 s wait."""
    monkeypatch.setattr(playwright_mod, 'BROWSER_ATTACH_TIMEOUT_SECONDS', 0.2)
    controller.utils = FakeUtils(port_busy=True, attach='hang')

    assert run(controller.connect()) is True

    assert controller.utils.calls == ['attach', 'launch']
    assert controller.utils.chrome_manager.shutdowns == [9222]
    assert controller.utils.playwrights[0].stopped is True, 'the failed attach did not leak a Playwright'
    assert sleeps == []


def test_the_busy_wait_is_gone():
    assert not hasattr(playwright_mod, 'BROWSER_BUSY_WAIT_SECONDS')


# ---------------------------------------------------------------------------
# Launch readiness instead of fixed sleeps (2026-09-29: ~7 s of an ~8.5 s start on host-clone-3)
#
# The launcher slept 2 s after the port opened, connect() 2 s more, connect_browser() 2 s more,
# and connect_browser() first tried to attach to a port nothing listened on (a Playwright driver
# start, ~1.6 s, to be refused). Now: skip that attach, wait for a page target, poll 0.1 s.
# ---------------------------------------------------------------------------

def test_nothing_listening_skips_the_first_attach_and_launches(controller, sleeps):
    controller.utils = FakeUtils(port_busy=False, attach='ok')

    result = run(controller.connect_browser())

    assert result['success'] is True and result.get('launched_new') is True
    assert controller.utils.calls == ['launch', 'attach'], 'no attach before the launch'
    assert len(controller.utils.playwrights) == 1, 'one Playwright driver, not two'
    assert sleeps == []


def test_something_listening_is_still_attached_to_first(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')

    assert run(controller.connect_browser())['success'] is True

    assert controller.utils.calls == ['attach']


def test_launch_waits_for_the_page_target_polling_briefly(controller, sleeps):
    controller.utils = FakeUtils(port_busy=False)
    controller.utils.chrome_manager.page_after = 4  # the startup tab shows up on the 4th poll

    assert run(controller.connect()) is True

    assert sleeps == [utils_mod.CHROME_READY_POLL_S] * 3
    assert controller.utils.chrome_manager.page_polls == 4


def test_a_browser_that_never_lists_a_page_is_waited_on_no_longer_than_the_old_sleeps(controller, sleeps):
    controller.utils = FakeUtils(port_busy=False)
    controller.utils.chrome_manager.page_after = None

    assert run(controller.connect()) is True, 'it carries on, as the fixed sleeps did'

    assert sum(sleeps) <= utils_mod.CHROME_PAGE_READY_MAX_WAIT_S + 1e-9
    assert utils_mod.CHROME_PAGE_READY_MAX_WAIT_S == 6.0, 'the three 2 s sleeps it replaces'


def test_webkit_keeps_its_fixed_startup_delay(sleeps):
    _reset_class_state()
    try:
        ctl = PlaywrightWebController(browser_engine='webkit')
        launched = []

        class _WebKitUtils:
            def launch_webkit(self):
                launched.append(1)
                return FakePopen()

        ctl.utils = _WebKitUtils()
        assert run(ctl.connect()) is True
        assert launched == [1]
        assert sleeps == [2]
    finally:
        _reset_class_state()


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.parametrize('payload,expected', [
    ([{'type': 'page', 'url': 'chrome://newtab/'}], True),
    ([{'type': 'service_worker'}, {'type': 'page'}], True),
    ([{'type': 'service_worker'}], False),
    ([], False),
])
def test_cdp_page_ready_needs_a_page_target(monkeypatch, payload, expected):
    import requests
    monkeypatch.setattr(requests, 'get', lambda url, timeout=None: _Response(200, payload))
    assert ChromeManager.cdp_page_ready(9222) is expected


def test_cdp_page_ready_is_false_when_nothing_answers(monkeypatch):
    import requests

    def refuse(url, timeout=None):
        raise requests.ConnectionError('refused')

    monkeypatch.setattr(requests, 'get', refuse)
    assert ChromeManager.cdp_page_ready(9222) is False


def test_port_listening_connects_instead_of_binding():
    import socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert ChromeManager.port_listening(port) is True
    finally:
        server.close()
    assert ChromeManager.port_listening(port) is False


def test_launcher_polls_the_port_then_the_page_not_a_clock(monkeypatch):
    """_wait_for_chrome_ready: port poll every CHROME_READY_POLL_S, then wait_for_cdp_page."""
    naps, attempts = [], []

    class _Socket:
        def __init__(self, *a, **k):
            pass

        def settimeout(self, _t):
            pass

        def connect(self, _addr):
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionRefusedError()

        def close(self):
            pass

    monkeypatch.setattr(utils_mod.socket, 'socket', _Socket)
    monkeypatch.setattr(utils_mod.time, 'sleep', lambda s: naps.append(s))
    page_polls = []
    monkeypatch.setattr(ChromeManager, 'cdp_page_ready',
                        staticmethod(lambda port, timeout=1.0: page_polls.append(1) or len(page_polls) >= 2))

    ChromeManager._wait_for_chrome_ready(9222, process=None, max_wait=5)

    assert len(attempts) == 3
    assert naps == [utils_mod.CHROME_READY_POLL_S] * 3, 'two port polls + one page poll, no 2 s sleep'
    assert len(page_polls) == 2


# ---------------------------------------------------------------------------
# The two entry points agree: a browser adopted by one is not attached again by the other
# ---------------------------------------------------------------------------

def test_connect_browser_after_connect_reuses_the_adopted_handles(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    run(controller.connect())

    result = run(controller.connect_browser())

    assert result['success'] is True
    assert result.get('reused_connection') is True
    assert controller.utils.calls == ['attach'], 'one attach, no second Playwright, no launch'


def test_verification_first_then_open_browser_does_not_relaunch(controller, sleeps):
    """The observed chain: a verification probe attached through connect_browser() before any
    open_browser action ran. The old connect() then saw a busy port, waited 300 s and killed the
    very browser this run was using. Now the attach marks the browser as this run's."""
    controller.utils = FakeUtils(port_busy=True, attach='ok')

    assert run(controller.connect_browser())['success'] is True
    assert PlaywrightWebController._chrome_running is True
    assert run(controller.connect()) is True

    assert controller.utils.calls == ['attach']
    assert controller.utils.chrome_manager.shutdowns == []
    assert sleeps == []


# ---------------------------------------------------------------------------
# Teardown closes the browser this run used, launched or attached
# ---------------------------------------------------------------------------

def test_teardown_closes_an_attached_browser_it_never_launched(controller):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    run(controller.connect())
    browser = PlaywrightWebController._browser
    playwright = PlaywrightWebController._playwright

    result = controller.close_browser(wait=True)

    assert result['waited_for_cleanup'] is True
    assert browser.cdp_commands == ['Browser.close'], 'graceful CDP close first'
    assert browser.closed is True and playwright.stopped is True
    assert ('kill_chrome', None) in controller.utils.calls, 'then the port listener, even with no Popen'
    assert PlaywrightWebController._chrome_running is False
    assert PlaywrightWebController._browser is None


def test_teardown_kills_the_launched_process_when_cdp_close_fails(controller, sleeps):
    controller.utils = FakeUtils(port_busy=False)
    run(controller.connect())
    launched = PlaywrightWebController._chrome_process
    context = FakeContext(FakePage())
    PlaywrightWebController._browser = FakeBrowser(context, cdp_fails=True)
    PlaywrightWebController._context = context
    PlaywrightWebController._playwright = FakePlaywright()

    controller.close_browser(wait=True)

    assert ('kill_chrome', launched) in controller.utils.calls
    assert PlaywrightWebController._chrome_process is None


# ---------------------------------------------------------------------------
# ChromeManager.shutdown_chrome: process group vs lone process, TERM then KILL
# ---------------------------------------------------------------------------

@pytest.fixture
def chrome_manager_sandbox(monkeypatch):
    """Route the kill primitives through recorders. `world` describes the host: which pid
    leads its own process group, who listens on the port, and what each signal does."""
    world = {
        'pgid': {},           # pid -> pgid
        'listener': None,     # pid listening on the port, or None
        'signals': [],        # (pid, signal, whole_group)
        'dies_on': {},        # pid -> signal that actually ends it
        'popen': None,
    }

    def pgid(pid):
        return world['pgid'].get(pid)

    def sig(pid, s, whole_group):
        world['signals'].append((pid, s, whole_group))
        if world['dies_on'].get(pid) == s:
            if world['listener'] == pid:
                world['listener'] = None
            if world['popen'] is not None and world['popen'].pid == pid:
                world['popen'].returncode = -s

    monkeypatch.setattr(ChromeManager, '_pgid', staticmethod(pgid))
    monkeypatch.setattr(ChromeManager, '_signal', staticmethod(sig))
    monkeypatch.setattr(ChromeManager, 'listener_pid', staticmethod(lambda port: world['listener']))
    monkeypatch.setattr(utils_mod.time, 'sleep', lambda _s: None)
    return world


def test_launched_leader_gets_its_whole_group_terminated(chrome_manager_sandbox):
    world = chrome_manager_sandbox
    popen = FakePopen(pid=500)
    world.update(popen=popen, pgid={500: 500}, listener=500, dies_on={500: signal.SIGTERM})

    assert ChromeManager.shutdown_chrome(9222, chrome_process=popen, timeout=0.05) is True

    assert world['signals'] == [(500, signal.SIGTERM, True)]
    assert world['listener'] is None


def test_a_browser_that_ignores_sigterm_is_sigkilled(chrome_manager_sandbox):
    world = chrome_manager_sandbox
    popen = FakePopen(pid=500)
    world.update(popen=popen, pgid={500: 500}, listener=500, dies_on={500: SIGKILL})

    assert ChromeManager.shutdown_chrome(9222, chrome_process=popen, timeout=0.05) is True

    assert world['signals'] == [(500, signal.SIGTERM, True), (500, SIGKILL, True)]


def test_an_attached_orphan_with_no_popen_is_killed_through_the_port(chrome_manager_sandbox):
    world = chrome_manager_sandbox
    world.update(pgid={777: 777}, listener=777, dies_on={777: signal.SIGTERM})

    assert ChromeManager.shutdown_chrome(9222, chrome_process=None, timeout=0.05) is True

    assert world['signals'] == [(777, signal.SIGTERM, True)]


def test_a_listener_in_someone_elses_group_is_signalled_alone(chrome_manager_sandbox):
    """A browser opened by the vpt-host service lives in the service's process group:
    killpg there would take the host down with it."""
    world = chrome_manager_sandbox
    world.update(pgid={777: 1}, listener=777, dies_on={777: signal.SIGTERM})

    assert ChromeManager.shutdown_chrome(9222, chrome_process=None, timeout=0.05) is True

    assert world['signals'] == [(777, signal.SIGTERM, False)]
    assert not any(whole for _, _, whole in world['signals'])


def test_a_free_port_needs_no_signal(chrome_manager_sandbox):
    world = chrome_manager_sandbox
    assert ChromeManager.shutdown_chrome(9222, chrome_process=None, timeout=0.05) is True
    assert world['signals'] == []


# ---------------------------------------------------------------------------
# Every Playwright started is stopped (BUG-0191)
#
# Each `async_playwright().start()` spawns a Node driver (`MainThread` in ps) that lives until
# `stop()`. Dropped handles leaked ~20 drivers an hour into vpt-host until the VM ran out of RAM.
# ---------------------------------------------------------------------------

class HangingPlaywright(FakePlaywright):
    """A Playwright whose stop() never returns, with the driver process behind it."""

    class _Proc:
        returncode = None
        killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

    def __init__(self):
        super().__init__()
        self.proc = self._Proc()
        transport = type('T', (), {'_proc': self.proc})()
        connection = type('C', (), {'_transport': transport})()
        self._impl_obj = type('I', (), {'_connection': connection})()

    async def stop(self):
        await asyncio.Event().wait()


def _fake_async_playwright(monkeypatch, started):
    import playwright.async_api as pw_api

    class _Chromium:
        async def connect_over_cdp(self, _url):
            raise Exception('connect ECONNREFUSED 127.0.0.1:9222')

    class _Starter:
        async def start(self):
            p = FakePlaywright()
            p.chromium = _Chromium()
            started.append(p)
            return p

    monkeypatch.setattr(pw_api, 'async_playwright', lambda: _Starter())


def test_a_failed_cdp_attach_stops_the_playwright_it_started(monkeypatch):
    """The common path: connect_browser() probes the port before Chrome is launched."""
    started = []
    _fake_async_playwright(monkeypatch, started)

    with pytest.raises(Exception, match='CDP connection failed'):
        run(utils_mod.PlaywrightConnection.connect_to_chrome('http://127.0.0.1:9222'))

    assert len(started) == 1 and started[0].stopped is True


def test_a_playwright_that_will_not_stop_has_its_driver_killed():
    playwright = HangingPlaywright()

    run(utils_mod.stop_playwright(playwright, timeout=0.05))

    assert playwright.proc.killed is True


def test_reconnecting_after_a_failed_verification_stops_the_old_playwright(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    run(controller.connect())
    old = PlaywrightWebController._playwright
    PlaywrightWebController._context = type('Dead', (), {'pages': property(lambda self: 1 / 0)})()  # verification raises

    assert run(controller.connect_browser())['success'] is True

    assert old.stopped is True
    assert PlaywrightWebController._playwright is not old


def test_dropping_a_dead_context_stops_its_playwright(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    run(controller.connect())
    old = PlaywrightWebController._playwright

    class DeadContext:
        pages = []

        async def new_page(self):
            raise RuntimeError('Target page, context or browser has been closed')

    PlaywrightWebController._context = DeadContext()
    run(controller._get_persistent_page())

    assert old.stopped is True


def test_a_timed_out_cleanup_still_stops_the_playwright(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    run(controller.connect())
    playwright = HangingPlaywright()
    PlaywrightWebController._playwright = playwright

    async def go():
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(utils_mod, 'PLAYWRIGHT_STOP_TIMEOUT_SECONDS', 0.05)
            mp.setattr(playwright_mod, 'stop_playwright',
                       lambda p: utils_mod.stop_playwright(p, timeout=0.05))
            await controller._cleanup_persistent_browser_with_timeout(timeout_seconds=0.01)

    run(go())

    assert playwright.proc.killed is True
    assert PlaywrightWebController._playwright is None
    assert PlaywrightWebController._chrome_running is False


def test_connect_close_cycles_leave_no_playwright_running(controller, sleeps):
    controller.utils = FakeUtils(port_busy=True, attach='ok')
    for _ in range(5):
        assert run(controller.connect_browser())['success'] is True
        controller.close_browser(wait=True)
        controller.utils.chrome_manager.port_busy = True  # next run finds a browser again

    assert len(controller.utils.playwrights) == 5
    assert all(p.stopped for p in controller.utils.playwrights)
