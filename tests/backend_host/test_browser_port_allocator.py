"""
tests/backend_host/test_browser_port_allocator.py — two browser runs on one host get their own
Chrome debug port and their own profile (TASK-146).

Before this, every browser on a host used port 9222 and the profile directory
backend_host/config/user_data. The second run killed the first one's browser ("ANOTHER BROWSER IS
ALREADY RUNNING on CDP port 9222 - killing it", BUG-0114) or attached to it and drove the same tab.

What is checked here:
  - the allocator never hands the same port to two live runs,
  - it never hands out the host service browser's reserved port 9222 to a script run,
  - a dead run's reservation is pruned, so the port comes back,
  - the orphan cleanup leaves a browser that belongs to a LIVE run alone, and reaps a leftover,
  - a script run gets its own Chrome profile; the host's service browser keeps the persistent one.
"""
import importlib
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

allocator = importlib.import_module('shared.src.lib.utils.browser_port_allocator')
utils_mod = importlib.import_module('backend_host.src.lib.utils.playwright_utils')
helpers_mod = importlib.import_module('shared.src.lib.utils.local_debug_browser_helpers')


@pytest.fixture(autouse=True)
def private_registry(tmp_path, monkeypatch):
    """Never touch the host's real port registry.

    The registry is per host and shared by every process on it: a test that reserved
    a port there would make the next run believe a live run owns it.
    """
    monkeypatch.setenv(allocator.REGISTRY_ENV, str(tmp_path / 'registry'))
    (tmp_path / 'registry').mkdir(exist_ok=True)
    yield


@pytest.fixture
def registry(tmp_path):
    """A private registry, so the tests never touch the host's real one."""
    return str(tmp_path / 'ports.json')


# ---------------------------------------------------------------------------
# The allocator
# ---------------------------------------------------------------------------

def test_two_runs_never_get_the_same_port(registry):
    first = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    second = allocator.allocate_run_debug_port(base=19300, registry_path=registry)

    assert first != second
    assert first == 19300
    assert second == 19301


def test_a_run_port_is_never_the_reserved_service_port(registry):
    port = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    assert port != allocator.RESERVED_DEBUG_PORT


def test_a_busy_port_is_skipped(registry):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]

        port = allocator.allocate_run_debug_port(base=busy_port, registry_path=registry)

    assert port != busy_port


def test_the_reservation_of_a_dead_run_is_pruned(registry):
    port = allocator.allocate_run_debug_port(base=19300, registry_path=registry, owner_pid=4242)
    # pid 4242 does not exist here: the entry must not keep the port.
    assert allocator.port_owner_pid(port, registry_path=registry) is None

    again = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    assert again == port


def test_the_owner_of_a_live_port_is_reported(registry):
    port = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    assert allocator.port_owner_pid(port, registry_path=registry) == os.getpid()


def test_releasing_the_port_frees_it(registry):
    port = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    allocator.release_debug_port(port, registry_path=registry)
    assert allocator.port_owner_pid(port, registry_path=registry) is None


def test_an_explicit_port_wins(registry, monkeypatch):
    monkeypatch.setenv(allocator.DEBUG_PORT_ENV, '19777')
    port = allocator.allocate_run_debug_port(base=19300, registry_path=registry)
    assert port == 19777
    assert allocator.port_owner_pid(19777, registry_path=registry) == os.getpid()


def test_no_free_port_raises(registry):
    with pytest.raises(RuntimeError):
        allocator.allocate_run_debug_port(base=19300, max_scan=1, registry_path=registry)
        # the first call reserves the only port, the second one has nowhere to go
        allocator.allocate_run_debug_port(base=19300, max_scan=1, registry_path=registry)


# ---------------------------------------------------------------------------
# The profile directory
# ---------------------------------------------------------------------------

def test_a_run_gets_its_own_profile_directory():
    base = '/opt/virtualpytest/backend_host/config/user_data'
    first = allocator.run_profile_dir(base, 'run-1')
    second = allocator.run_profile_dir(base, 'run-2')

    assert first != second
    assert first.startswith('/opt/virtualpytest/backend_host/config/user_data_runs/')
    # The persistent profile of the host service browser is untouched.
    assert not first.startswith(base + os.sep)


def test_the_run_profile_is_a_sibling_of_the_persistent_profile(tmp_path):
    base = str(tmp_path / 'user_data')
    run_dir = allocator.run_profile_dir(base, 'abc')
    assert os.path.dirname(run_dir) == str(tmp_path / 'user_data_runs')


# ---------------------------------------------------------------------------
# PlaywrightUtils: which port and which profile this process takes
# ---------------------------------------------------------------------------

def test_a_script_run_takes_a_run_port_and_a_run_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('VPT_RUN_ID', 'task-146')
    monkeypatch.delenv('VPT_CHROME_DEBUG_PORT', raising=False)
    monkeypatch.delenv('VPT_CHROME_PROFILE_DIR', raising=False)

    utils = utils_mod.PlaywrightUtils(
        auto_accept_cookies=False,
        user_data_dir=str(tmp_path / 'user_data'),
    )

    assert utils.debug_port != allocator.RESERVED_DEBUG_PORT
    assert utils.debug_port >= allocator.RUN_DEBUG_PORT_BASE
    assert 'task-146' in utils.user_data_dir


def test_the_host_service_browser_keeps_the_reserved_port_and_the_persistent_profile(monkeypatch, tmp_path):
    monkeypatch.delenv('VPT_RUN_ID', raising=False)
    monkeypatch.delenv('VPT_CHROME_DEBUG_PORT', raising=False)
    monkeypatch.delenv('VPT_CHROME_PROFILE_DIR', raising=False)
    # A private registry and a free port 9222: the service browser is the first one.
    monkeypatch.setenv(allocator.REGISTRY_ENV, str(tmp_path))
    monkeypatch.setattr(allocator, 'is_port_listening', lambda port, host='127.0.0.1', timeout=0.25: False)

    utils = utils_mod.PlaywrightUtils(
        auto_accept_cookies=False,
        user_data_dir=str(tmp_path / 'user_data'),
    )

    assert utils.debug_port == allocator.RESERVED_DEBUG_PORT
    assert utils.user_data_dir == str(tmp_path / 'user_data')


def test_a_process_that_is_neither_a_run_nor_the_service_takes_its_own_port(monkeypatch, tmp_path):
    """A script started by hand on a host must not fight the service browser for 9222."""
    monkeypatch.delenv('VPT_RUN_ID', raising=False)
    monkeypatch.delenv('VPT_CHROME_DEBUG_PORT', raising=False)
    monkeypatch.delenv('VPT_CHROME_PROFILE_DIR', raising=False)
    monkeypatch.setenv(allocator.REGISTRY_ENV, str(tmp_path))
    # The service browser already holds 9222.
    monkeypatch.setattr(allocator, 'is_port_listening', lambda port, host='127.0.0.1', timeout=0.25: False)
    allocator.reserve_debug_port(allocator.RESERVED_DEBUG_PORT, owner_pid=os.getpid())

    utils = utils_mod.PlaywrightUtils(
        auto_accept_cookies=False,
        user_data_dir=str(tmp_path / 'user_data'),
    )

    assert utils.debug_port != allocator.RESERVED_DEBUG_PORT


def test_an_explicit_profile_dir_wins(monkeypatch, tmp_path):
    monkeypatch.setenv('VPT_RUN_ID', 'task-146')
    monkeypatch.setenv('VPT_CHROME_PROFILE_DIR', str(tmp_path / 'pinned'))

    utils = utils_mod.PlaywrightUtils(
        auto_accept_cookies=False,
        user_data_dir=str(tmp_path / 'user_data'),
    )

    assert utils.user_data_dir == str(tmp_path / 'pinned')


# ---------------------------------------------------------------------------
# The orphan cleanup: only our own port, never another live run's browser
# ---------------------------------------------------------------------------

def test_the_cleanup_leaves_a_live_runs_browser_alone(monkeypatch):
    """A run that ends must not kill the browser of the run that shares the host."""
    monkeypatch.setattr(allocator, 'port_owner_pid', lambda port, registry_path=None: 4242)
    monkeypatch.setattr(utils_mod.ChromeManager, 'listener_pid', staticmethod(lambda port: 5150))
    killed = []
    monkeypatch.setattr(
        utils_mod.ChromeManager, '_terminate_pid',
        staticmethod(lambda pid, timeout, is_alive: killed.append(pid) or True),
    )

    assert utils_mod.ChromeManager.shutdown_chrome(9222) is False
    assert killed == []


def test_the_cleanup_reaps_a_leftover_browser(monkeypatch):
    """A browser nobody owns (the run died) is still taken back."""
    monkeypatch.setattr(allocator, 'port_owner_pid', lambda port, registry_path=None: None)
    monkeypatch.setattr(utils_mod.ChromeManager, 'listener_pid', staticmethod(lambda port: 5150))
    killed = []
    monkeypatch.setattr(
        utils_mod.ChromeManager, '_terminate_pid',
        staticmethod(lambda pid, timeout, is_alive: killed.append(pid) or True),
    )
    monkeypatch.setattr(utils_mod.ChromeManager, 'listener_pid', staticmethod(lambda port: None if killed else 5150))

    utils_mod.ChromeManager.shutdown_chrome(9222)

    assert killed == [5150]


def test_the_launch_refuses_to_take_over_a_live_runs_port(monkeypatch):
    """The launch must not kill the browser of a concurrent run (BUG-0114)."""
    monkeypatch.setattr(allocator, 'port_owner_pid', lambda port, registry_path=None: 4242)
    monkeypatch.setattr(utils_mod.ChromeManager, 'listener_pid', staticmethod(lambda port: 5150))

    with pytest.raises(RuntimeError, match='live run'):
        utils_mod.ChromeManager.launch_chrome_with_remote_debugging(9222, user_data_dir='/tmp/does-not-matter')


# ---------------------------------------------------------------------------
# The local-debug helper: one port per run, never taken by force
# ---------------------------------------------------------------------------

def test_the_local_debug_helper_keeps_a_free_port(monkeypatch, tmp_path):
    monkeypatch.delenv('VPT_RUN_ID', raising=False)
    monkeypatch.setenv(allocator.DEBUG_PORT_ENV, str(_free_port()))

    port = helpers_mod.reserve_cdp_port(19399)
    assert port == 19399


def test_the_local_debug_helper_moves_off_a_busy_port(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]

        port = helpers_mod.reserve_cdp_port(busy_port)

    assert port != busy_port
    assert port != allocator.RESERVED_DEBUG_PORT


def test_the_local_debug_helper_never_takes_the_reserved_port(monkeypatch):
    monkeypatch.delenv(allocator.DEBUG_PORT_ENV, raising=False)
    port = helpers_mod.reserve_cdp_port(allocator.RESERVED_DEBUG_PORT)
    assert port != allocator.RESERVED_DEBUG_PORT


def test_the_local_debug_profile_is_per_run(monkeypatch):
    monkeypatch.setenv('VPT_RUN_ID', 'task-146')
    assert 'task-146' in helpers_mod.resolve_local_debug_profile_dir('youtube_check')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]
