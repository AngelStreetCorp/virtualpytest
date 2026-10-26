"""The end of a run must leave no browser behind (BUG-0760 part 1).

Measured on a game host: an hourly run ended at 17:05:54 with
``Cleanup timed out or failed: TimeoutError:`` and its Chromium was still alive on port
9300 until the periodic reclaim pass took it four minutes later. The run's own cleanup
closes the browser over the Playwright controller loop, and a wedged loop - exactly what
made the run fail - means that close never runs.

These tests drive the real end of a run (the executor's subprocess path) with a real
process that looks like a browser in ``/proc``, so the assertions are about a process
being alive or dead, never about a mock having been called. Every one of them fails on
the pre-fix commit because the browser survived the run there.

The safety half matters as much: the host's persistent service browser (the profile
next door, outside ``user_data_runs/``) and the browser of another live run are never
signalled, and a browser nobody could signal is reported as NOT reaped - never as
reclaimed.
"""
import os
import socket
import subprocess
import sys
import time

import pytest

from shared.src.lib.executors import script_executor as executor_mod
from shared.src.lib.utils import browser_port_allocator
from shared.src.lib.utils import leaked_browser_reaper as reaper
from shared.src.lib.utils.browser_port_allocator import REGISTRY_ENV


# The browsers the fake runs launched, so a test that fails to have them reaped does
# not leave them on the host.
_BROWSERS_OF_THIS_TEST = []


# ---------------------------------------------------------------------------
# A process that looks like a browser in /proc
# ---------------------------------------------------------------------------

def _fake_browser_binary(tmp_path):
    """A program whose argv[0] basename is 'chromium'.

    The reaper only ever considers a process that looks like a browser, matched on the
    basename of argv[0] - a shell wrapper that merely mentions the flags is somebody
    else's process and must never be signalled.
    """
    binary = tmp_path / 'chromium'
    if not binary.exists():
        binary.symlink_to(sys.executable)
    return str(binary)


def _spawn_fake_browser(binary, profile_dir, port):
    """Start a process that looks like a browser on a profile and a debug port."""
    return subprocess.Popen(
        [binary, '-c', 'import time; time.sleep(300)',
         f'--user-data-dir={profile_dir}', f'--remote-debugging-port={port}'],
        start_new_session=True,
    )


def _alive(pid):
    """True when the process is still running.

    A process that died but was not waited for is a zombie: its /proc entry is still
    there, but it is not running any more.
    """
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            tail = fh.read().decode('utf-8', errors='replace').rsplit(')', 1)[-1].split()
    except OSError:
        return False
    return bool(tail) and tail[0] != 'Z'


def _run_profile_dir(run_id):
    """The profile directory the allocator gives this run.

    Built with the allocator's own function, so the test asks the same question the
    platform answers.
    """
    run_root = reaper.default_run_profile_root()
    parent = os.path.dirname(run_root)
    name = os.path.basename(run_root)
    base_name = name[:-len('_runs')] if name.endswith('_runs') else name
    return browser_port_allocator.run_profile_dir(os.path.join(parent, base_name), run_id)


def _service_profile_dir():
    """The host's persistent profile: the service browser's, next door to the run roots."""
    run_root = reaper.default_run_profile_root()
    return os.path.join(os.path.dirname(run_root), 'user_data')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def private_port_registry(tmp_path, monkeypatch):
    """The port registry is per host and shared: a test must not read the host's one.

    A live entry for the run's port would make the teardown believe another run owns
    the browser on it - and that is exactly the decision these tests check.
    """
    registry_dir = tmp_path / 'registry'
    registry_dir.mkdir(exist_ok=True)
    monkeypatch.setenv(REGISTRY_ENV, str(registry_dir))


@pytest.fixture
def run_id(request):
    """A run id of this test's own: two tests never share a profile directory."""
    return 'e68-' + ''.join(
        ch if ch.isalnum() else '-' for ch in request.node.name)[:48]


@pytest.fixture
def port():
    """A free port of this test's own, so one test's browser is never another's."""
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def kill_leftover_browsers():
    """A run that failed to kill its browser must not leave one on the host.

    On the pre-fix commit every one of these tests leaves the browser alive on purpose:
    that is the bug. The test still cleans up after itself.
    """
    yield
    for pid in _BROWSERS_OF_THIS_TEST:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    _BROWSERS_OF_THIS_TEST.clear()


@pytest.fixture
def browser_binary(tmp_path):
    return _fake_browser_binary(tmp_path)


@pytest.fixture
def python_on_path(tmp_path, monkeypatch):
    """The executor runs its script through `python`, so the test needs one on PATH."""
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)
    shim = bindir / 'python'
    if not shim.exists():
        shim.symlink_to(sys.executable)
    monkeypatch.setenv('PATH', f'{bindir}{os.pathsep}{os.environ.get("PATH", "")}')
    return str(shim)


@pytest.fixture
def no_browser_slot_scan(monkeypatch):
    """The slot pool counts the browsers the host carries; a test must not measure the host."""
    monkeypatch.setattr(
        'shared.src.lib.utils.browser_run_slots.leaked_browser_count', lambda: 0)


@pytest.fixture
def spawned():
    """Every fake browser this test started, so none of them outlives the test."""
    procs = []

    def _spawn(binary, profile_dir, port):
        proc = _spawn_fake_browser(binary, profile_dir, port)
        procs.append(proc)
        return proc

    yield _spawn

    for proc in procs:
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# The run itself: a script that launches a browser and ends
# ---------------------------------------------------------------------------

# The script stands in for a run whose Playwright controller loop wedged: it launches
# its browser and never closes it, exactly as the production journal shows.
FAKE_RUN_SCRIPT = '''
import os
import subprocess
import sys

browser = os.environ['E68_FAKE_BROWSER']
profile = os.environ['E68_FAKE_PROFILE']
port = os.environ['E68_FAKE_PORT']

proc = subprocess.Popen([browser, '-c', 'import time; time.sleep(300)',
                         '--user-data-dir=' + profile,
                         '--remote-debugging-port=' + port])
print('FAKE_BROWSER_PID:' + str(proc.pid))
sys.stdout.flush()

{extra}
'''

# A run that drives no browser of its own.
PLAIN_RUN_SCRIPT = '''
print("this run drives no browser")
sys.stdout.flush()
'''

# The same run, but its own cleanup worked: the browser is gone before the run ends.
CLOSE_OWN_BROWSER = '''
os.kill(proc.pid, 9)
proc.wait()
print('RUN_BROWSER_CLOSE:closed')
sys.stdout.flush()
'''


def _run_script(tmp_path, monkeypatch, browser_binary, run_id, port,
                extra='', browser_isolated=True, spawn_browser=True):
    """Run a fake script through the executor, the way a real run is run."""
    script_path = tmp_path / ('fake_run.py' if browser_isolated else 'plain_run.py')
    rules = '\n_target_rules = {"browser_isolated": True}\n' if browser_isolated else '\n'
    body = FAKE_RUN_SCRIPT.format(extra=extra) if spawn_browser else PLAIN_RUN_SCRIPT
    script_path.write_text(body + rules, encoding='utf-8')
    monkeypatch.setenv('E68_FAKE_BROWSER', browser_binary)
    monkeypatch.setenv('E68_FAKE_PROFILE', _run_profile_dir(run_id))
    monkeypatch.setenv('E68_FAKE_PORT', str(port))

    executor = executor_mod.ScriptExecutor(
        script_name='e68_fake_run', description='e68 fake run',
        device_id='e68-test-device', device_model='host')
    executor.current_task_id = run_id
    executor.current_trigger = {'type': 'host'}
    result = executor._execute_script_subprocess(str(script_path), '', 'e68_fake_run', time.time())
    for line in (result.get('stdout') or '').splitlines():
        if line.startswith('FAKE_BROWSER_PID:'):
            _BROWSERS_OF_THIS_TEST.append(int(line.split(':', 1)[1]))
    return result


def _browser_pid(result):
    for line in (result.get('stdout') or '').splitlines():
        if line.startswith('FAKE_BROWSER_PID:'):
            return int(line.split(':', 1)[1])
    raise AssertionError(f'the fake run never reported its browser pid: {result}')


# ---------------------------------------------------------------------------
# The run ends: the browser it launched must be dead
# ---------------------------------------------------------------------------

def test_a_run_whose_own_cleanup_failed_still_takes_its_browser_down(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """The production case: the run's own close never ran, the browser outlived it.

    On the pre-fix commit the browser was still alive when the run ended.
    """
    result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
    pid = _browser_pid(result)

    assert not _alive(pid), 'the browser outlived the run: it is still running'
    out = capsys.readouterr().out
    assert 'taken down by pid' in out, out
    assert str(pid) in out, out


def test_the_operator_can_ask_for_the_browser_to_live_and_the_run_says_so(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """VPT_KEEP_BROWSER_OPEN is a documented, host-level opt-out: leave the browser open.

    A fix must not silently remove an operator's explicit capability, so the run-scoped
    teardown leaves the browser alone when the switch is set - and says so, with the pid,
    instead of skipping it quietly.
    """
    monkeypatch.setenv('VPT_KEEP_BROWSER_OPEN', 'true')

    result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
    pid = _browser_pid(result)

    assert _alive(pid), 'the browser was taken down although the operator asked to keep it'
    out = capsys.readouterr().out
    assert 'left open' in out, out
    assert 'VPT_KEEP_BROWSER_OPEN' in out, out
    assert str(pid) in out, out
    assert 'taken down by pid' not in out, out


def test_a_browser_that_is_already_gone_is_reported_as_such_and_nothing_is_signalled(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """Benign: the run's own cleanup did close the browser. Nothing may be signalled."""
    signalled = []
    real_kill = os.kill

    def _record(pid, sig):
        signalled.append(pid)
        return real_kill(pid, sig)

    monkeypatch.setattr(os, 'kill', _record)
    result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port,
                         extra=CLOSE_OWN_BROWSER)
    pid = _browser_pid(result)

    assert not _alive(pid)
    assert pid not in signalled, 'the teardown signalled a browser that was already gone'
    out = capsys.readouterr().out
    assert 'closed normally' in out, out
    assert 'taken down by pid' not in out, out


def test_a_browser_that_cannot_be_signalled_is_reported_as_not_reaped(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """A signal nobody is allowed to send is a failure, and it says so.

    The report must never read as a reclaim that did not happen.
    """
    real_kill = os.kill

    def _refuse(pid, sig):
        raise PermissionError(13, 'Permission denied')

    pid = None
    try:
        monkeypatch.setattr(os, 'kill', _refuse)
        result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
        pid = _browser_pid(result)

        out = capsys.readouterr().out
        assert 'NOT reaped' in out, out
        assert 'permission denied' in out.lower(), out
        assert 'taken down by pid' not in out, out
        assert _alive(pid), 'the browser was signalled after all'
    finally:
        monkeypatch.undo()
        if pid:
            try:
                real_kill(pid, 9)
            except OSError:
                pass


def test_the_hosts_persistent_service_browser_is_never_signalled(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """The service browser lives on the profile next door, outside user_data_runs/.

    It is the browser the agent tree and the web worker attach to: the run's teardown
    must not even look at it.
    """
    service = _spawn_fake_browser(browser_binary, _service_profile_dir(), port + 1)
    try:
        result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
        pid = _browser_pid(result)

        assert not _alive(pid), 'the run left its own browser behind'
        assert _alive(service.pid), 'the persistent service browser was signalled'
    finally:
        if service.poll() is None:
            service.kill()


def test_the_browser_of_another_live_run_is_never_signalled(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """Another run's browser belongs to that run, not to this one."""
    other = _spawn_fake_browser(browser_binary, _run_profile_dir(run_id + '-other'),
                                port + 1)
    try:
        result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
        pid = _browser_pid(result)

        assert not _alive(pid), 'the run left its own browser behind'
        assert _alive(other.pid), "another run's browser was signalled"
    finally:
        if other.poll() is None:
            other.kill()


def test_a_run_that_never_took_a_browser_slot_grows_no_teardown(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """The teardown is the run's own: a run that drives no browser pays nothing for it.

    The second half is the same run that drives one: it gets the teardown, and its
    browser is dead when it ends.
    """
    calls = []
    real_teardown = getattr(executor_mod, '_teardown_run_browser_for_run', None)
    monkeypatch.setattr(executor_mod, '_teardown_run_browser_for_run',
                        lambda *args, **kwargs: calls.append(args) or {}, raising=False)

    _run_script(tmp_path, monkeypatch, browser_binary, run_id, port,
                browser_isolated=False, spawn_browser=False)
    assert calls == [], 'a run that took no browser slot must not pay for a teardown'

    # The same run, but one that drives a browser: it gets the real teardown.
    monkeypatch.setattr(executor_mod, '_teardown_run_browser_for_run', real_teardown)
    result = _run_script(tmp_path, monkeypatch, browser_binary, run_id, port)
    pid = _browser_pid(result)

    assert not _alive(pid), 'the run left its own browser behind'


# ---------------------------------------------------------------------------
# The abort: a run that is stopped on purpose leaves nothing behind either
# ---------------------------------------------------------------------------

def test_an_aborted_run_takes_its_browser_down(
        tmp_path, monkeypatch, capsys, browser_binary, python_on_path, spawned,
        no_browser_slot_scan, run_id, port):
    """Chrome is launched in its own session, so the abort's tree kill cannot reach it."""
    browser = _spawn_fake_browser(browser_binary, _run_profile_dir(run_id), port)
    victim = subprocess.Popen(['sleep', '300'], start_new_session=True)
    device_id = 'e68-test-device'
    try:
        executor_mod._running_processes_by_device[device_id] = [{
            'process': victim,
            'script_name': 'e68_fake_run',
            'started_at': time.time(),
            'task_id': run_id,
            'execution_id': None,
            'run_id': run_id,
            'browser_slot': True,
        }]

        outcome = executor_mod.abort_running_script(device_id)

        assert outcome.get('aborted') is True, outcome
        assert not _alive(browser.pid), 'the aborted run left its browser behind'
    finally:
        executor_mod._running_processes_by_device.pop(device_id, None)
        if victim.poll() is None:
            victim.kill()
        if browser.poll() is None:
            browser.kill()


# ---------------------------------------------------------------------------
# The close_browser command: it must stop reporting a close that did not happen
# ---------------------------------------------------------------------------

def test_the_close_browser_command_does_not_report_success_for_a_running_browser(
        tmp_path, monkeypatch, browser_binary, spawned, run_id, port):
    """A caller that trusts the result must not be told a browser died that is alive."""
    import asyncio

    controller_mod = __import__(
        'backend_host.src.controllers.web.playwright', fromlist=['PlaywrightWebController'])

    class _Utils:
        """The cleanup runs and kills nothing: the browser stays alive."""
        debug_port = port

        class _Manager:
            def cdp_healthy(self, port, timeout=2.0):
                return False

            def port_listening(self, port, timeout=0.25):
                return True

            def shutdown_chrome(self, port, chrome_process=None, timeout=5.0):
                return False

        def __init__(self):
            self.chrome_manager = self._Manager()

        def kill_chrome(self, chrome_process=None):
            return False

    browser = _spawn_fake_browser(browser_binary, _run_profile_dir(run_id), port)
    try:
        controller = controller_mod.PlaywrightWebController(browser_engine='chromium')
        controller.utils = _Utils()

        result = asyncio.run(controller.execute_command('close_browser'))

        assert result.get('success') is False, result
        assert result.get('browser_still_running') == browser.pid, result
        assert 'still running' in (result.get('error') or ''), result
        assert _alive(browser.pid), 'the browser was closed after all'
    finally:
        controller_mod.PlaywrightWebController._chrome_process = None
        controller_mod.PlaywrightWebController._chrome_running = False
        controller_mod.PlaywrightWebController._playwright = None
        controller_mod.PlaywrightWebController._browser = None
        controller_mod.PlaywrightWebController._context = None
        controller_mod.PlaywrightWebController._browser_connected = False
        if browser.poll() is None:
            browser.kill()
