"""BLE wake-on-press aims at the bond the STB actually uses (regression guard, 2026-10).

With two bonds on one adapter that both carry the HID CCC (an STB re-paired
under a new identity without the stale bond being removed), _bonded_peer_mac
returned the D-Bus-first one; wake_on_press sent ADV_DIRECT_IND to that stale
identity and the box never woke.

hid_remote.py is a BlueZ daemon (dbus, gi). Those are stubbed here; only the
pure ranking and the status file are exercised. No adapter, no device.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]

STALE = '0C:7F:00:00:00:01'   # sorts first, D-Bus enumerates it first
LIVE = 'A0:E7:00:00:00:02'
OTHER = 'F0:00:00:00:00:03'


@pytest.fixture(scope='module')
def hid(tmp_path_factory):
    dbus = types.ModuleType('dbus')

    class _DBusException(Exception):
        pass

    class _Object:
        def __init__(self, *a, **k):
            pass

    def _decorator(*a, **k):
        return lambda fn: fn

    dbus.exceptions = types.SimpleNamespace(DBusException=_DBusException)
    dbus.service = types.ModuleType('dbus.service')
    dbus.service.Object = _Object
    dbus.service.method = _decorator
    dbus.service.signal = _decorator
    dbus.mainloop = types.ModuleType('dbus.mainloop')
    dbus.mainloop.glib = types.ModuleType('dbus.mainloop.glib')
    for name in ('Interface', 'ObjectPath', 'Boolean', 'String', 'Array', 'Byte',
                 'Dictionary', 'UInt16', 'Int16', 'SystemBus'):
        setattr(dbus, name, mock.MagicMock(name=name))
    gi = types.ModuleType('gi')
    gi.repository = types.ModuleType('gi.repository')
    gi.repository.GLib = mock.MagicMock(name='GLib')

    stubs = {'dbus': dbus, 'dbus.service': dbus.service, 'dbus.mainloop': dbus.mainloop,
             'dbus.mainloop.glib': dbus.mainloop.glib, 'gi': gi, 'gi.repository': gi.repository}
    # Loaded by path: bluetooth/ (the daemon dir, no __init__) sits next to
    # bluetooth.py (the controller), so a dotted import resolves to the latter.
    path = REPO / 'backend_host/src/controllers/remote/bluetooth/hid_remote.py'
    spec = importlib.util.spec_from_file_location('vpt_test_hid_remote', path)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, stubs):
        spec.loader.exec_module(mod)
    mod.STATUS_PATH = str(tmp_path_factory.mktemp('ble') / 'status.json')
    return mod


def test_positive_control_two_hid_bonds_used_to_pick_dbus_first(hid):
    # No last-connected and no mtimes: falls back to enumeration order, which is
    # exactly the old behaviour — the stale bond.
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False)], {STALE, LIVE})
    assert ranked[0] == STALE


def test_last_connected_mac_breaks_a_hid_tie(hid):
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False)], {STALE, LIVE},
                             last_connected_mac=LIVE.lower())
    assert ranked == [LIVE, STALE]


def test_newest_bond_breaks_a_tie_without_last_connected(hid):
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False)], {STALE, LIVE},
                             bond_mtimes={STALE: 100.0, LIVE: 200.0})
    assert ranked == [LIVE, STALE]


def test_last_connected_beats_mtime(hid):
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False)], {STALE, LIVE},
                             last_connected_mac=STALE, bond_mtimes={STALE: 100.0, LIVE: 200.0})
    assert ranked[0] == STALE


def test_connected_bond_always_wins(hid):
    ranked = hid._rank_bonds([(STALE, False), (LIVE, True)], {STALE},
                             last_connected_mac=STALE, bond_mtimes={STALE: 999.0})
    assert ranked[0] == LIVE


def test_hid_ready_beats_last_connected_battery_only_bond(hid):
    # A battery-only bond cannot carry keys (§6.7.29), even if it connected last.
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False)], {LIVE},
                             last_connected_mac=STALE)
    assert ranked[0] == LIVE


def test_wake_targets_are_best_then_remaining_hid_ready(hid):
    ranked = hid._rank_bonds([(STALE, False), (LIVE, False), (OTHER, False)], {STALE, LIVE},
                             last_connected_mac=LIVE)
    assert ranked == [LIVE, STALE, OTHER]
    assert hid._wake_targets(ranked, {STALE, LIVE}) == [LIVE, STALE]
    assert hid._wake_targets([LIVE], set()) == [LIVE]
    assert hid._wake_targets([], set()) == []


def test_last_connected_mac_is_persisted_in_status(hid):
    hid._last_connected_mac = None
    hid._record_connected_peer(LIVE.lower())
    with open(hid.STATUS_PATH) as f:
        status = json.load(f)
    assert status['last_connected_mac'] == LIVE
    assert status['waking'] is False
    assert hid._read_status_file()['last_connected_mac'] == LIVE
    hid._set_waking(True)
    assert hid._read_status_file()['waking'] is True
    hid._set_waking(False)


def test_wake_on_press_tries_the_next_hid_bond_after_a_timeout(hid, monkeypatch):
    bus = object()
    monkeypatch.setitem(hid._WAKE_CTX, 'bus', bus)
    monkeypatch.setitem(hid._WAKE_CTX, 'adv_mgr', mock.MagicMock())
    monkeypatch.setitem(hid._WAKE_CTX, 'adv_path', '/adv')
    monkeypatch.setitem(hid._WAKE_CTX, 'adapter_hci', 'hci0')
    monkeypatch.setenv('HID_REMOTE_SKIP_ADV', '0')
    monkeypatch.setattr(hid, '_ranked_bonds', lambda b: ([STALE, LIVE], {STALE, LIVE}))
    monkeypatch.setattr(hid, 'count_connected_peers', lambda b: 0)
    monkeypatch.setattr(hid.time, 'sleep', lambda s: None)
    hid._peer_connected_event.clear()

    tried = []

    def fake_attempt(mac, adapter):
        tried.append(mac)
        return mac == LIVE

    monkeypatch.setattr(hid, '_directed_adv_until_connected', fake_attempt)
    assert hid.wake_on_press() is True
    assert tried == [STALE, LIVE]
    assert hid._read_status_file()['waking'] is False


def test_wake_on_press_gives_up_after_every_hid_bond(hid, monkeypatch):
    monkeypatch.setitem(hid._WAKE_CTX, 'bus', object())
    monkeypatch.setitem(hid._WAKE_CTX, 'adv_mgr', mock.MagicMock())
    monkeypatch.setitem(hid._WAKE_CTX, 'adv_path', '/adv')
    monkeypatch.setattr(hid, '_ranked_bonds', lambda b: ([LIVE, STALE, OTHER], {LIVE, STALE}))
    monkeypatch.setattr(hid, 'count_connected_peers', lambda b: 0)
    monkeypatch.setattr(hid.time, 'sleep', lambda s: None)
    hid._peer_connected_event.clear()
    tried = []
    monkeypatch.setattr(hid, '_directed_adv_until_connected',
                        lambda mac, adapter: tried.append(mac) or False)
    assert hid.wake_on_press() is False
    assert tried == [LIVE, STALE]  # OTHER is battery-only: not worth a timeout
