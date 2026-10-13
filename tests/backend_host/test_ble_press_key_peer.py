"""BLE press_key reports a key that reached no peer as a failure (regression guard, 2026-10).

press_key returned True as soon as the key name was written to the daemon's FIFO.
With the STB asleep and the wake aimed at a stale bond, every key went nowhere and
every step "passed". Now, when no peer is connected, press_key waits for the wake
(WAKE_TIMEOUT_S + 2 s) and fails with 'no BLE peer connected after wake'.

No adapter, no daemon: the FIFO is a plain file, the status file is written by the
test, D-Bus is replaced, and the clock is simulated.
"""
import importlib
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = 0

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps += 1
        self.now += s


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    mod = importlib.import_module('backend_host.src.controllers.remote.bluetooth')
    c = object.__new__(mod.BluetoothRemoteController)
    c.device_type = 'bluetooth'
    c.adapter_hci = 'hci9'
    c.ble_type = 'arris'
    c.is_connected = True
    c.supported_keys = {'OK', 'HOME'}
    c.fifo_path = str(tmp_path / 'fifo')
    c.status_path = str(tmp_path / 'status.json')
    c.last_press_error = None
    clock = Clock()
    monkeypatch.setattr(mod.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(mod.time, 'sleep', clock.sleep)
    c.dbus_calls = 0
    c.peer = {'connected': False, 'stb_mac': 'A0:E7:00:00:00:02'}

    def fake_query():
        c.dbus_calls += 1
        return dict(c.peer) if c.peer is not None else None

    c._query_dbus_peer_state = fake_query
    c.clock = clock
    return c


def _status(c, **fields):
    with open(c.status_path, 'w') as f:
        json.dump(fields, f)


def test_connected_with_hid_subscription_costs_one_file_read(ctl):
    _status(ctl, hid_ready=True)
    assert ctl.press_key('ok') is True
    assert ctl.dbus_calls == 0
    assert ctl.clock.sleeps == 0
    assert Path(ctl.fifo_path).read_text() == 'OK\n'


def test_connected_without_status_needs_one_dbus_read_and_no_wait(ctl):
    ctl.peer['connected'] = True
    assert ctl.press_key('OK') is True
    assert ctl.dbus_calls == 1
    assert ctl.clock.sleeps == 0


def test_no_peer_after_wake_is_a_failure(ctl):
    _status(ctl, hid_ready=False, waking=False)
    assert ctl.press_key('OK') is False
    assert ctl.last_press_error == 'no BLE peer connected after wake'
    waited = ctl.clock.now - 1000.0
    assert ctl.WAKE_TIMEOUT_S + 2 <= waited < ctl.WAKE_TIMEOUT_S + 3
    result = ctl.execute_command('press_key', {'key': 'OK'})
    assert result == {'success': False, 'error': 'no BLE peer connected after wake'}


def test_peer_reconnecting_during_wake_is_a_success(ctl, monkeypatch):
    real_sleep = ctl.clock.sleep

    def sleep(s):
        real_sleep(s)
        if ctl.clock.now - 1000.0 >= 6:
            ctl.peer['connected'] = True

    import backend_host.src.controllers.remote.bluetooth as mod
    monkeypatch.setattr(mod.time, 'sleep', sleep)
    assert ctl.press_key('OK') is True
    assert ctl.last_press_error is None
    assert 6 <= ctl.clock.now - 1000.0 < 7


def test_wait_is_extended_while_daemon_reports_waking(ctl):
    _status(ctl, hid_ready=False, waking=True)
    assert ctl.press_key('OK') is False
    waited = ctl.clock.now - 1000.0
    # Capped at _MAX_WAKE_TARGETS directed adverts, never unbounded.
    assert waited >= ctl.WAKE_TIMEOUT_S * ctl._MAX_WAKE_TARGETS + 2
    assert waited < ctl.WAKE_TIMEOUT_S * ctl._MAX_WAKE_TARGETS + 3


def test_no_bond_fails_at_once(ctl):
    ctl.peer = None
    assert ctl.press_key('OK') is False
    assert ctl.last_press_error == 'no BLE peer bonded'
    assert ctl.clock.sleeps == 0


def test_wake_timeout_mirrors_the_daemon():
    import backend_host.src.controllers.remote.bluetooth as mod
    daemon = (REPO / 'backend_host/src/controllers/remote/bluetooth/hid_remote.py').read_text()
    value = int(re.search(r'^WAKE_TIMEOUT_S = (\d+)', daemon, re.M).group(1))
    assert mod.BluetoothRemoteController.WAKE_TIMEOUT_S == value
