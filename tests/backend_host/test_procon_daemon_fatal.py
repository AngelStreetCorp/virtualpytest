"""vpt-procon exits (systemd restarts it) when nxbt's manager can no longer recover (BUG-0361)."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

DAEMON = Path(__file__).parents[2] / 'backend_host/src/controllers/switch/procon/procon_daemon.py'


@pytest.fixture
def daemon(monkeypatch):
    for name in ('dbus', 'dbus.mainloop', 'dbus.mainloop.glib', 'dbus.service', 'gi',
                 'gi.repository', 'nxbt', 'nxbt.nxbt', 'nxbt.controller', 'nxbt.controller.server'):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    sys.modules['dbus.service'].Object = object
    sys.modules['nxbt.controller'].server = sys.modules['nxbt.controller.server']
    spec = importlib.util.spec_from_file_location('procon_daemon_under_test', DAEMON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make(daemon):
    p = daemon.Procon()
    p.nx.controllers.is_alive.return_value = True
    p.nx.controllers.pid = 99999999  # no /proc entry -> 0 fds
    return p


def test_healthy_has_no_fatal_reason(daemon):
    assert make(daemon).fatal_reason() is None


def test_dead_manager_is_fatal(daemon):
    p = make(daemon)
    p.nx.controllers.is_alive.return_value = False
    assert 'dead' in p.fatal_reason()


def test_consecutive_create_failures_are_fatal(daemon):
    p = make(daemon)
    p.create_failures = daemon.MAX_CREATE_FAILURES
    assert 'create-controller failures' in p.fatal_reason()


def test_fd_leak_is_fatal(daemon, monkeypatch):
    p = make(daemon)
    monkeypatch.setattr(daemon.os, 'listdir', lambda _: [0] * (daemon.MAX_MANAGER_FDS + 1))
    assert 'file descriptors' in p.fatal_reason()


def test_tick_exits_nonzero(daemon, monkeypatch):
    p = make(daemon)
    p.nx.controllers.is_alive.return_value = False
    codes = []
    monkeypatch.setattr(daemon.os, '_exit', codes.append)
    p.tick()
    assert codes == [1]
