#!/usr/bin/env python3
"""Arris STB remote-control peripheral emulator (LE).

Matches the real Universal Electronics "RemoteUnit" GATT layout that was
reverse-engineered from the reference remote (MAC 20:21:41:00:1F:91).

Services exposed:
  - Generic Attribute (0x1801) — implicit via BlueZ
  - Battery (0x180F)
  - Device Information (0x180A) — full 9-characteristic set
  - Arris vendor service 2141e100-213a-11e6-b67b-9e71128cae77 with 3 chars:
      2141e101 notify            (HID Consumer Page — nav/channel/transport)
      2141e102 write-w/o-resp    (STB -> remote commands)
      2141e103 notify            (HID Keyboard Page — numeric keypad)

Advertisement mirrors the real remote: name "RemoteUnit", appearance 0x0180,
ServiceUUIDs [0x1812, 0x180F], manufacturer data Universal Electronics
(0x0093) 00 80, flags 0x06 (General disc + BR/EDR N/S), 20-50 ms interval.

Note: the real HID service (0x1812) is NOT implemented. We still advertise
it in the 16-bit UUID list because the real remote does the same — it's a
decoy kept for the STB's discovery filter. The key events flow over the
Arris vendor characteristic.

Key injection:
  Write a keyname or raw 16-bit hex into /tmp/hid_remote.fifo. Named keys
  whose name starts with ``KEY_`` (the numeric keypad) route to the Arris
  keyboard channel (2141e103, HID Keyboard Page 0x07). Every other named
  key — and raw hex codes — routes to the Arris consumer channel
  (2141e101, HID Consumer Page 0x0C) plus, in parallel, the HID Input
  Report at characteristic 0x2a4d. All three carry the same payload
  shape: 4 bytes [code, 0x00, 0x00, 0x00] (Arris) or 2 bytes
  [code_lo, code_hi] (HID Input Report) on press, then all zeros 80 ms
  later for release.

Run via launcher:
  sudo ~/ble-remote/start.sh   # fresh pair (destructive)
  sudo ~/ble-remote/resume.sh  # preserve existing bond
"""
import os
import sys
import errno
import fcntl
import json
import stat
import struct
import subprocess
import threading
import time
import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


# ---------- Wake-on-press (directed advertising) ----------------------------
# The Arris STB drops idle BLE links after ~7 minutes and its LE scanner
# enters a low-power mode that only responds to ADV_DIRECT_IND from its
# bonded remotes. A real Universal Electronics RemoteUnit — which has no
# persistent state (removing batteries for a day and reinserting them
# immediately works) — must therefore emit directed advertising on the
# first button press after wake. We replicate this: when a key is injected
# via the FIFO and no peer is currently connected, we emit ADV_DIRECT_IND
# targeted at the bonded STB's public address for up to WAKE_TIMEOUT_S.
# The STB's low-power scanner picks it up, wakes, and initiates a fresh
# bonded reconnection which our v2-patched bluetoothd handles normally.
#
# BlueZ 5.66's D-Bus LEAdvertisement1 API does NOT expose directed
# advertising (SupportedIncludes is only tx-power/appearance/local-name),
# so we drop down to raw HCI commands via `hcitool cmd`. This requires
# temporarily unregistering BlueZ's own undirected advertisement so the
# two paths don't fight over the advertising hardware.

# Low-duty-cycle ADV_DIRECT_IND reconnects can take a hair over 8s on a
# deep-idle STB. Observed 2026-06-25 on host3: the STB's Connected=True
# landed the SAME second the 8s wait expired, so the wake reported failure on
# a connection that actually succeeded and the triggering key was dropped.
# 15s comfortably covers the measured reconnect latency; the boundary re-check
# in wake_on_press() below catches anything that still lands right on the edge.
WAKE_TIMEOUT_S = 15
_peer_connected_event = threading.Event()
_wake_lock = threading.Lock()
_WAKE_CTX = {}

# Adapter path under /org/bluez that this daemon instance owns. Set once
# in main() right after find_adapter() resolves it, and used by every
# `GetManagedObjects()` walk to filter peers by adapter (multi-instance
# requirement, §6.7.22-followup-9). Without this filter, every daemon
# sees every Device1 on the host — wake_on_press targets the wrong
# peer, count_connected_peers counts sibling adapters' STBs, and the
# initial enumeration log line reports peers that don't even belong to
# this controller. When None (early-startup race), filtering is bypassed
# so logs still surface useful information.
_ADAPTER_PATH = None

# ---------- Constants --------------------------------------------------------
BLUEZ = 'org.bluez'
ADAPTER_IFACE = BLUEZ + '.Adapter1'
GATT_MANAGER_IFACE = BLUEZ + '.GattManager1'
LE_ADV_MANAGER_IFACE = BLUEZ + '.LEAdvertisingManager1'
GATT_SERVICE_IFACE = BLUEZ + '.GattService1'
GATT_CHRC_IFACE = BLUEZ + '.GattCharacteristic1'
GATT_DESC_IFACE = BLUEZ + '.GattDescriptor1'
LE_ADV_IFACE = BLUEZ + '.LEAdvertisement1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

# FIFO and status file paths are scoped per adapter so multiple BLE
# peripheral instances (one per hciN) can run on the same host without
# colliding. The HID_REMOTE_ADAPTER env var is the same one start.sh /
# resume.sh set when launching the daemon — single source of truth.
# Default 'hci0' preserves the old singleton path for hosts that only
# ever run one adapter.
_ADAPTER = os.environ.get('HID_REMOTE_ADAPTER', 'hci0')
FIFO_PATH = f'/tmp/hid_remote-{_ADAPTER}.fifo'
STATUS_PATH = f'/tmp/hid_remote_status-{_ADAPTER}.json'
LOCAL_NAME = os.environ.get('HID_REMOTE_NAME', 'RemoteUnit')

# Exclusive per-adapter run lock. Two daemons on one adapter silently halve
# the key rate: both park in open(FIFO,'r'), every controller write wakes
# both, and the kernel hands the line to exactly ONE of them. Only the
# daemon holding the STB's GATT subscription actually delivers a report, so
# every line the other wins is swallowed with no error on either side — the
# controller logs a successful ~12ms write and the key never reaches the box
# (§6.7.27: stb4 landed 4/6 with a leftover second daemon, 6/6 after it was
# stopped). fuser/lsof on the FIFO does NOT reveal this: a reader parked
# inside a blocking open() holds no fd yet, so the FIFO shows zero openers
# even with two daemons attached. `ps` for hid_remote.py is the only
# reliable check — hence this lock, which makes the duplicate refuse to
# start instead of degrading the link.
#
# /run is root-owned and tmpfs-backed, so the lock cannot be squatted by
# another user and never survives a reboot. flock is released automatically
# when the process dies, including on SIGKILL.
LOCK_PATH = f'/run/vpt-ble/hid-remote-{_ADAPTER}.lock'
_lock_fh = None  # module-global: keeps the fd (and thus the flock) alive

# ---------- Subscription status tracking ------------------------------------
# Tracks which GATT characteristics have received StartNotify from the STB.
# Written to STATUS_PATH as JSON so the controller (bluetooth.py) can detect
# "connected but battery-only" without a subprocess or D-Bus call.
_subscribed_uuids: set = set()
_status_lock = threading.Lock()

# Key-carrying characteristic UUIDs — a StartNotify on ANY of these means
# the STB has accepted us as a working remote and will react to key presses.
# Different STB models subscribe to different channels:
#   - Arris vendor notify (2141e101): used by STBs with Arris-specific firmware
#   - HID Input Report (00002a4d): used by STBs using standard BLE HID
# Battery (00002a19) is NOT a key channel — it's always subscribed but
# doesn't carry button events.
HID_KEY_UUIDS = {
    '2141e101-213a-11e6-b67b-9e71128cae77',  # Arris vendor notify
    '00002a4d-0000-1000-8000-00805f9b34fb',  # HID Input Report
}

def _write_status():
    """Atomically write the current subscription state to STATUS_PATH."""
    with _status_lock:
        data = {
            'subscribed_uuids': sorted(_subscribed_uuids),
            'hid_ready': bool(_subscribed_uuids & HID_KEY_UUIDS),
            'ts': time.time(),
        }
    tmp = STATUS_PATH + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, STATUS_PATH)
    except Exception as e:
        print(f'_write_status: failed: {e}')

def _on_start_notify(uuid: str):
    """Record that a characteristic received StartNotify."""
    with _status_lock:
        _subscribed_uuids.add(uuid)
    _write_status()

def _on_stop_notify(uuid: str):
    """Record that a characteristic received StopNotify."""
    with _status_lock:
        _subscribed_uuids.discard(uuid)
    _write_status()

def _clear_subscriptions():
    """Reset subscription tracking (e.g. on peer disconnect)."""
    with _status_lock:
        _subscribed_uuids.clear()
    _write_status()


def _load_keymap():
    """Load the key-name → HID Consumer Control code map from a JSON profile.

    Path resolution:
      1. HID_REMOTE_KEYMAP env var (absolute path) if set
      2. Default: ble_conf/arris.json next to this script

    JSON schema: {"<KEY_NAME>": "<hex string>", ...}. Underscored keys
    (e.g. "_comment") are ignored. Values are parsed via int(value, 0)
    so "0x00E9" / "0xe9" / "233" are all accepted.

    Failures are fatal — without a keymap, the FIFO reader cannot map
    incoming key names to codes. We log to stderr and exit instead of
    silently running with an empty dict, which would look like every
    key press is "unknown".
    """
    default_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'ble_conf', 'arris.json',
    )
    path = os.environ.get('HID_REMOTE_KEYMAP', default_path)
    try:
        with open(path, 'r') as f:
            raw = json.load(f)
    except Exception as e:
        sys.stderr.write(f'_load_keymap: failed to read {path}: {e}\n')
        sys.exit(1)
    keymap = {}
    for name, value in raw.items():
        if name.startswith('_'):
            continue  # ignore comment fields like "_comment"
        try:
            keymap[name] = int(value, 0) if isinstance(value, str) else int(value)
        except (ValueError, TypeError) as e:
            sys.stderr.write(
                f'_load_keymap: bad value for {name!r} in {path}: '
                f'{value!r} ({e})\n')
            sys.exit(1)
    if not keymap:
        sys.stderr.write(f'_load_keymap: {path} contained zero usable keys\n')
        sys.exit(1)
    print(f'Loaded {len(keymap)} keys from {path}')
    return keymap


KEYS = _load_keymap()


# ---------- UUIDs ------------------------------------------------------------
# Standard SIG.
UUID_HID_SERVICE      = '00001812-0000-1000-8000-00805f9b34fb'
UUID_HID_INFO         = '00002a4a-0000-1000-8000-00805f9b34fb'
UUID_HID_REPORT_MAP   = '00002a4b-0000-1000-8000-00805f9b34fb'
UUID_HID_CTRL_POINT   = '00002a4c-0000-1000-8000-00805f9b34fb'
UUID_HID_REPORT       = '00002a4d-0000-1000-8000-00805f9b34fb'
UUID_HID_PROTO_MODE   = '00002a4e-0000-1000-8000-00805f9b34fb'
UUID_REPORT_REF       = '00002908-0000-1000-8000-00805f9b34fb'

# Battery
UUID_BATTERY_SERVICE  = '0000180f-0000-1000-8000-00805f9b34fb'
UUID_BATTERY_LEVEL    = '00002a19-0000-1000-8000-00805f9b34fb'

# Device Information — full 9-characteristic set
UUID_DIS_SERVICE      = '0000180a-0000-1000-8000-00805f9b34fb'
UUID_DIS_MANUF_NAME   = '00002a29-0000-1000-8000-00805f9b34fb'
UUID_DIS_MODEL_NUMBER = '00002a24-0000-1000-8000-00805f9b34fb'
UUID_DIS_SERIAL_NUM   = '00002a25-0000-1000-8000-00805f9b34fb'
UUID_DIS_HW_REV       = '00002a27-0000-1000-8000-00805f9b34fb'
UUID_DIS_FW_REV       = '00002a26-0000-1000-8000-00805f9b34fb'
UUID_DIS_SW_REV       = '00002a28-0000-1000-8000-00805f9b34fb'
UUID_DIS_SYSTEM_ID    = '00002a23-0000-1000-8000-00805f9b34fb'
UUID_DIS_IEEE_REG     = '00002a2a-0000-1000-8000-00805f9b34fb'
UUID_DIS_PNP_ID       = '00002a50-0000-1000-8000-00805f9b34fb'

# Arris/Universal Electronics proprietary service (dumped from real remote)
UUID_ARRIS_SERVICE    = '2141e100-213a-11e6-b67b-9e71128cae77'
UUID_ARRIS_NOTIFY     = '2141e101-213a-11e6-b67b-9e71128cae77'  # key events
UUID_ARRIS_WRITE      = '2141e102-213a-11e6-b67b-9e71128cae77'  # STB -> remote
UUID_ARRIS_KEYBOARD   = '2141e103-213a-11e6-b67b-9e71128cae77'  # HID Keyboard Page

# ---------- Stable GATT handles ---------------------------------------------
# Hard-coded service starting handles. BlueZ honours the optional `Handle`
# property on each org.bluez.GattService1 D-Bus object and inserts the
# service at exactly the requested handle via gatt_db_insert_service().
# Without this, BlueZ auto-allocates handles in registration order and they
# drift on every external-app re-registration, which silently invalidates
# the bonded peer's GATT cache (the peer keeps writing/reading at the OLD
# handles even though the server moved them).
#
# We start at 0x0020 to leave room for BlueZ's built-in services
# (GAP at 0x0001-0x0007, GATT at 0x0008-0x0011, built-in DIS at
# 0x0012-0x0014, built-in Battery at 0x0015-0x0018) and keep large
# gaps between our services so the auto-allocated child handles
# (characteristic value, CCCD descriptor, Report Reference descriptor)
# can fit even if we add more characteristics later.
HANDLE_BATTERY      = 0x0020   # ~4 handles used: 0x0020..0x0023
HANDLE_DIS          = 0x0030   # ~19 handles used: 0x0030..0x0042
HANDLE_HID          = 0x0050   # ~14 handles used: 0x0050..0x005D
HANDLE_ARRIS_VENDOR = 0x0070   # ~9 handles used:  0x0070..0x0078


# ---------- BlueZ object base classes ----------------------------------------
class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'


class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/com/vpt/remote'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def add_service(self, service):
        self.services.append(service)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for svc in self.services:
            response[svc.get_path()] = svc.get_properties()
            for ch in svc.characteristics:
                response[ch.get_path()] = ch.get_properties()
                for d in ch.descriptors:
                    response[d.get_path()] = d.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = '/com/vpt/remote/service'

    def __init__(self, bus, index, uuid, primary, handle=0):
        # `handle`: optional pinned GATT handle for the service
        # declaration. Zero = let BlueZ auto-allocate (drifts on
        # every register). Non-zero = BlueZ inserts at exactly that
        # handle via gatt_db_insert_service(), which keeps our GATT
        # layout stable across hid_remote.py / bluetoothd restarts so
        # the STB's cached handles stay valid.
        self.path = f'{self.PATH_BASE}{index}'
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.handle = handle
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def add_characteristic(self, ch):
        self.characteristics.append(ch)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        props = {
            'UUID': self.uuid,
            'Primary': self.primary,
            'Characteristics': dbus.Array(
                [c.get_path() for c in self.characteristics], signature='o'),
        }
        if self.handle:
            props['Handle'] = dbus.UInt16(self.handle)
        return {GATT_SERVICE_IFACE: props}

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


def _peer_address_from_path(path):
    """Extract 'AA:BB:CC:DD:EE:FF' from '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF'."""
    tail = path.rsplit('/', 1)[-1]
    if not tail.startswith('dev_'):
        return path
    return tail[4:].replace('_', ':')


def install_device_watcher(bus):
    """Subscribe to org.bluez.Device1 PropertiesChanged signals and log
    every connect / disconnect / paired / trusted / services-resolved
    transition. Without this hid_remote.py has no visibility on peer
    lifecycle — the only things that reach the journal are StartNotify and
    WriteValue, which happen only while the peer is already fully set up.
    """
    def on_props_changed(interface, changed, invalidated, path=None):
        if interface != 'org.bluez.Device1':
            return
        if not changed:
            return
        # Adapter-scoping: ignore PropertiesChanged events for peers
        # bonded under a SIBLING adapter (multi-instance §6.7.22-followup-9).
        # Without this filter, hid-remote-hci1 would log/wake events for
        # hci2's STB and vice versa.
        if _ADAPTER_PATH and path and not path.startswith(_ADAPTER_PATH + '/'):
            return
        # Only log the properties we actually care about. BlueZ emits lots
        # of RSSI / Alias chatter that would drown the useful events.
        interesting = {}
        for k in ('Connected', 'Paired', 'Trusted', 'ServicesResolved',
                  'Bonded'):
            if k in changed:
                interesting[k] = bool(changed[k])
        if not interesting:
            return
        peer = _peer_address_from_path(path or '')
        parts = ' '.join(f'{k}={v}' for k, v in interesting.items())
        print(f'[peer {peer}] {parts}')
        # §6.7.30: drop an unbonded intruder before it can hold the link.
        if interesting.get('Connected') is True and path:
            if _reject_unbonded_peer(bus, path, peer):
                return
        # §6.7.30: the moment a bond exists, close the pairing window
        # (start.sh opened it with no bond present) and shout if a
        # SECOND bond just appeared — the §6.7.29 duplicate-bond hazard.
        if interesting.get('Bonded') is True:
            bonded = _bonded_addresses(bus)
            if len(bonded) > 1:
                print(f'*** [peer {peer}] bonded while {_ADAPTER_PATH} already had a bond: '
                      f'{bonded} — duplicate bond (§6.7.29); remove the stale one ***')
            _set_pairing_window(bus, False, f'bond established with {peer}')
            # §6.7.31: the STB is connected right now (adv is off), so the
            # list edit is allowed; the next identity advert will be locked.
            if os.environ.get('HID_REMOTE_SKIP_ADV') == '1':
                _program_accept_list(_ADAPTER, bonded)
        # Signal waiters (wake_on_press) when a peer comes up.
        if interesting.get('Connected') is True:
            _peer_connected_event.set()
        # Clear subscription tracking on disconnect — the STB's CCCDs are
        # gone from our perspective. If it reconnects via bond, we need to
        # see fresh StartNotify calls to know keys will actually work.
        if interesting.get('Connected') is False:
            _clear_subscriptions()

    bus.add_signal_receiver(
        on_props_changed,
        dbus_interface='org.freedesktop.DBus.Properties',
        signal_name='PropertiesChanged',
        arg0='org.bluez.Device1',
        path_keyword='path',
    )

    # Also log the state of any peer that already exists at startup, so we
    # can see on a fresh launch whether a previously-bonded peer is loaded.
    # Filtered to THIS adapter only — see _ADAPTER_PATH docstring.
    try:
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
        for path, ifaces in om.GetManagedObjects().items():
            dev = ifaces.get('org.bluez.Device1')
            if not dev:
                continue
            if _ADAPTER_PATH and not path.startswith(_ADAPTER_PATH + '/'):
                continue
            peer = _peer_address_from_path(path)
            print(f'[peer {peer}] initial '
                  f'Connected={bool(dev.get("Connected", False))} '
                  f'Paired={bool(dev.get("Paired", False))} '
                  f'Trusted={bool(dev.get("Trusted", False))} '
                  f'ServicesResolved={bool(dev.get("ServicesResolved", False))}')
    except Exception as e:
        print(f'install_device_watcher initial scan failed: {e}')


def count_connected_peers(bus):
    """Return how many org.bluez.Device1 objects UNDER THIS DAEMON'S
    ADAPTER currently have Connected=True. Used by notify_value() to log
    when a key injection happens while nobody is listening.

    Adapter-scoping (§6.7.22-followup-9): without the _ADAPTER_PATH
    filter this would count peers bonded to sibling adapters, making
    notify_value think someone is listening when the STB is actually
    connected to a different chip — keys go to /dev/null with the daemon
    thinking everything's fine.
    """
    try:
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
        n = 0
        for path, ifaces in om.GetManagedObjects().items():
            if _ADAPTER_PATH and not path.startswith(_ADAPTER_PATH + '/'):
                continue
            dev = ifaces.get('org.bluez.Device1')
            if dev and dev.get('Connected', False):
                n += 1
        return n
    except Exception:
        return -1


def _bonded_addresses(bus):
    """Addresses of every bonded Device1 under THIS adapter (upper-case)."""
    out = []
    try:
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
        for path, ifaces in om.GetManagedObjects().items():
            if _ADAPTER_PATH and not path.startswith(_ADAPTER_PATH + '/'):
                continue
            dev = ifaces.get('org.bluez.Device1')
            if dev and dev.get('Bonded', False) and dev.get('Address'):
                out.append(str(dev['Address']).upper())
    except Exception as e:
        print(f'_bonded_addresses failed: {e}')
    return out


def _set_pairing_window(bus, open_window, why=''):
    """§6.7.30: adapter Pairable/Discoverable follow the bond state.

    No bond  -> open  (start.sh pairing window: the STB must be able to pair)
    Bond     -> closed (a bonded STB reconnects on connectable advertising
                alone — it needs neither Pairable nor Discoverable — and
                nothing else may pair). resume.sh already closes the window
                (`bondable off`, §6.7.29) but this daemon used to force
                Pairable=True on every start, silently re-opening it. On
                host1 a foreign central then paired Just-Works onto
                hci2 (bond A0:E7…, Authenticated=0, battery-only CCC) and,
                while it held the link, advertising stopped and the real STB
                could never reconnect: the customer's "STB04 lost pairing".
    Re-pairing the SAME STB after it lost its key goes through start.sh
    (operator clicks Pair), which wipes the bond first — the documented flow.
    """
    if not _ADAPTER_PATH:
        return
    try:
        props = dbus.Interface(bus.get_object(BLUEZ, _ADAPTER_PATH), DBUS_PROP_IFACE)
        # Pairable (= MGMT bondable) only gates SMP pairing, never advertising
        # or an LTK reconnect, so it is safe in every mode — and it MUST run
        # even with HID_REMOTE_SKIP_ADV=1 (the customer's Minisforum hosts):
        # bluetoothd re-enables bondable on every adapter power-on, which is
        # how the window stood open there despite resume.sh's `bondable off`.
        props.Set(ADAPTER_IFACE, 'Pairable', dbus.Boolean(bool(open_window)))
        # Discoverable only when THIS daemon owns the advert. With
        # HID_REMOTE_SKIP_ADV=1 start.sh/resume.sh drive raw-HCI advertising and
        # a MGMT discoverable change can rewrite the adv data underneath them.
        if os.environ.get('HID_REMOTE_SKIP_ADV') != '1':
            props.Set(ADAPTER_IFACE, 'Discoverable', dbus.Boolean(bool(open_window)))
        print(f'pairing window {"OPEN" if open_window else "CLOSED"} on '
              f'{_ADAPTER_PATH}{(" — " + why) if why else ""} (§6.7.30)')
    except Exception as e:
        print(f'_set_pairing_window({open_window}) failed: {e}')


def _reject_unbonded_peer(bus, path, peer):
    """§6.7.30: an UNBONDED central connected while this adapter already
    holds a bond. A connection alone (no pairing needed) is enough to stop
    our advertising and lock the real STB out, so drop it at once. Never
    fires during a legitimate first pairing (no bond yet) and never for the
    bonded STB itself."""
    try:
        dprops = dbus.Interface(bus.get_object(BLUEZ, path), DBUS_PROP_IFACE)
        if bool(dprops.Get('org.bluez.Device1', 'Bonded')):
            return False
        bonded = _bonded_addresses(bus)
        if not bonded:
            return False          # pairing window: first connection is the pair
        print(f'*** [peer {peer}] connected UNBONDED while {_ADAPTER_PATH} is '
              f'bonded to {bonded} — disconnecting intruder (§6.7.30) ***')
        dbus.Interface(bus.get_object(BLUEZ, path), 'org.bluez.Device1').Disconnect()
        return True
    except Exception as e:
        print(f'_reject_unbonded_peer {peer}: {e}')
        return False


def _adapter_address(bus):
    """Public address of this daemon's adapter (upper-case), or None.
    Used to locate the adapter's bond dir under /var/lib/bluetooth/."""
    if not _ADAPTER_PATH:
        return None
    try:
        props = dbus.Interface(bus.get_object(BLUEZ, _ADAPTER_PATH),
                               'org.freedesktop.DBus.Properties')
        return str(props.Get('org.bluez.Adapter1', 'Address')).upper()
    except Exception as e:
        print(f'_adapter_address failed: {e}')
        return None


def _bond_has_hid_ccc(adapter_mac, peer_mac):
    """True if the on-disk bond for peer_mac under adapter_mac has the HID
    Input Report CCC (0x2a4d) subscribed — i.e. the bond can actually carry
    key presses. A battery-only bond (§6.7.9 trap) or a stale §6.7.20
    duplicate lacks this line entirely. Reads the bond info file directly:
    the daemon runs as root, and org.bluez.Device1 exposes no CCC state
    over D-Bus."""
    info = f'/var/lib/bluetooth/{adapter_mac}/{peer_mac}/info'
    try:
        with open(info) as f:
            for line in f:
                line = line.rstrip()
                if UUID_HID_REPORT in line and (line.endswith('=0x0001')
                                                or line.endswith('=0x0003')):
                    return True
    except OSError:
        pass
    return False


def _priv(cmd):
    """Prefix `sudo` only when NOT already root.

    hid-remote@ runs as root (systemd unit), so `sudo btmgmt …` on every
    keypress was pure overhead: each call wrote 3 audit lines to the journal
    (sudo COMMAND= + pam session open/close) — 5 journal lines per press
    together with `Injecting` + the multi-bond warning. On host1 that
    chatter rotated the volatile journal down to ~1 h of history, which is
    why the 2026-08-26 / 08-31 "lost pairing" events left no trace.
    """
    return cmd if os.geteuid() == 0 else ['sudo'] + cmd


_LAST_MULTI_BOND_KEY = None   # last bond set we warned about (log once per change)


def _bonded_peer_mac(bus):
    """Return the public-address MAC of a bonded Device1 UNDER THIS
    DAEMON'S ADAPTER, preferring a Connected=true peer; None if no bond.
    Used to pick the ADV_DIRECT_IND / ghost-check target for wake-on-press.

    Adapter-scoping (§6.7.22-followup-9): in a multi-adapter host the
    previous unscoped walk picked whichever bonded device D-Bus iterated
    first — frequently the sibling adapter's STB. wake_on_press then
    emitted ADV_DIRECT_IND at a MAC the LOCAL chip has no bond with,
    silently failing.

    Connected-preference (§6.7.20) is mandatory and was the missing half
    of that fix: the controller's status pickers were taught to prefer
    Connected=true, but THIS picker still returned the first-iterated
    bond. When the adapter holds more than one bond — e.g. an STB-side
    factory reset re-pairing under a new MAC without re-running start.sh —
    returning a dead bond makes wake_on_press cross-check the WRONG peer,
    declare a ghost on the genuinely-live link, and `hciconfig reset` the
    working connection on EVERY keypress (then chase the dead MAC for 8s
    and drop the key). Prefer the connected bond so the cheap early-return
    fires instead. Fall back to the first only when none are connected.

    HID-CCC tiebreak (§6.7.29): when NO peer is connected, "first bond
    iterated" is the worst possible fallback — D-Bus enumerates lex order,
    so on a duplicate-bond adapter the wake advert chases whichever MAC
    sorts first, which is frequently the DEAD one (host2
    2026-07-24: an STB-initiated re-pair during Resume left a stale
    battery-only 0C:7F next to the live A0:E7; every ADV_DIRECT_IND
    targeted the stale bond for an hour). Now: among disconnected bonds,
    prefer one whose on-disk [Cccs] shows the HID Input Report subscribed
    — only that bond can carry keys, so it is the only one worth waking.
    """
    try:
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
        candidates = []  # (mac, connected)
        for path, ifaces in om.GetManagedObjects().items():
            if _ADAPTER_PATH and not path.startswith(_ADAPTER_PATH + '/'):
                continue
            dev = ifaces.get('org.bluez.Device1')
            if not dev or not dev.get('Bonded', False):
                continue
            addr = dev.get('Address')
            if addr:
                candidates.append((str(addr), bool(dev.get('Connected', False))))
        global _LAST_MULTI_BOND_KEY
        bond_key = tuple(sorted(c[0] for c in candidates)) if len(candidates) > 1 else None
        if bond_key != _LAST_MULTI_BOND_KEY:
            # Log once when the bond set changes, not on every keypress —
            # the per-press repeat flooded the journal (see _priv()).
            _LAST_MULTI_BOND_KEY = bond_key
            if bond_key:
                print(f'_bonded_peer_mac: {len(candidates)} bonds on {_ADAPTER_PATH} '
                      f'{[c[0] for c in candidates]} — preferring Connected; '
                      f'remove stale bonds (§6.7.20) [logged once per change]')
        if candidates:
            # 1. A live connection always wins (§6.7.20).
            for mac, conn in candidates:
                if conn:
                    return mac
            # 2. §6.7.29: none connected — prefer a bond whose on-disk
            #    [Cccs] has the HID Input Report subscribed over a
            #    battery-only / stale duplicate.
            if len(candidates) > 1:
                adapter_mac = _adapter_address(bus)
                if adapter_mac:
                    hid_ready = [mac for mac, _ in candidates
                                 if _bond_has_hid_ccc(adapter_mac, mac)]
                    if hid_ready:
                        if len(hid_ready) < len(candidates):
                            skipped = [m for m, _ in candidates
                                       if m not in hid_ready]
                            print(f'_bonded_peer_mac: preferring HID-subscribed '
                                  f'{hid_ready[0]} over non-HID {skipped} (§6.7.29)')
                        return hid_ready[0]
            return candidates[0][0]
    except Exception as e:
        print(f'_bonded_peer_mac failed: {e}')
    return None


def _hci_cmd(args, adapter='hci0'):
    """Run `sudo hcitool -i <adapter> cmd <args...>` and return (ok, stdout).
    Logs failures. Blocks up to 5s."""
    full = _priv(['hcitool', '-i', adapter, 'cmd'] + args)
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            print(f'_hci_cmd {args}: rc={r.returncode} err={r.stderr.strip()}')
            return False, r.stdout
        return True, r.stdout
    except Exception as e:
        print(f'_hci_cmd {args} exception: {e}')
        return False, ''


def _link_state_via_mgmt(peer_mac, adapter='hci0'):
    """Return 'connected' / 'not-connected' / 'unknown' for the given peer.

    btmgmt's conn-info reflects the kernel's actual LL state.
    org.bluez.Device1.Connected can hold a stale True for many seconds
    (sometimes minutes) after the peer drops the link silently — STB
    sleep, range loss, TV power-off. During that window keys are emitted
    into a dead handle and the user sees no response. This probe is the
    cheap way to spot the divergence so wake_on_press can fix it."""
    if not peer_mac:
        return 'unknown'
    index = adapter.lstrip('hci') or '0'
    try:
        # -t 1 = LE Public address type. CRITICAL: `btmgmt conn-info <mac>`
        # with no type defaults to BR/EDR and returns "Not Connected"
        # (status 0x02) for EVERY LE peer — even a perfectly live one
        # (verified 2026-06-01: a connected STB reads "(BR/EDR) … Not
        # Connected" without -t but "(LE Public) … RSSI -59" with -t 1). Our
        # STB bonds are all LE Public (AddressType=public in the bond info).
        # Without -t 1 this probe reported every healthy link as dead, so
        # wake_on_press declared a false ghost and `hciconfig reset` the
        # adapter on every key press → the STB flapped and keys never
        # landed. This bug was masked until the stdin fix below made
        # conn-info actually run. See BLUETOOTH.md §6.7.23-followup-4.
        #
        # input='\n' gives btmgmt a PIPE stdin. The daemon runs as a systemd
        # service (StandardInput=null = /dev/null), and on bluetoothd 5.82
        # btmgmt WEDGES (blocks until killed) when its stdin is /dev/null —
        # a pipe stdin returns immediately. See §6.7.23-followup (stdin wedge).
        r = subprocess.run(
            _priv(['btmgmt', '--index', index, 'conn-info', '-t', '1', peer_mac]),
            input='\n', capture_output=True, text=True, timeout=2)
        out = (r.stdout + r.stderr).lower()
        if 'not connected' in out:
            return 'not-connected'
        if r.returncode == 0:
            return 'connected'
        return 'unknown'
    except Exception as e:
        print(f'_link_state_via_mgmt {peer_mac}: {e}')
        return 'unknown'


_GHOST_RESET_MIN_INTERVAL_S = 60
_last_ghost_reset = 0.0


def _clear_ghost_connection(adapter='hci0'):
    """Reset the HCI adapter to drop bluetoothd's stale Connected=true.
    Heavy hammer — only called once we have positive confirmation that
    the link is dead at the mgmt layer but bluetoothd still advertises
    Connected on D-Bus. The daemon's GATT objects survive the reset
    (they're our D-Bus objects, not BlueZ's), so we don't need to
    re-register. BlueZ re-applies persisted Cccs from the bond file on
    the next reconnect via our patched bluetoothd.

    Rate-limited to one reset per _GHOST_RESET_MIN_INTERVAL_S (§6.7.29):
    an `hciconfig reset` tears down any LL link WITHOUT a clean
    LL_TERMINATE_IND, and a burst of them (multi-key press while a
    false-ghost is being diagnosed) can interrupt the STB's own reconnect
    attempts mid-handshake. Repeated failed re-encryptions are exactly
    what makes the STB drop its LTK locally (spec HoGPairResetBehaviour)
    — after which only a fresh pair recovers. One reset per minute is
    plenty for the genuine §6.7.21 ghost (self-heal is ~3 s)."""
    global _last_ghost_reset
    now = time.monotonic()
    since = now - _last_ghost_reset
    if since < _GHOST_RESET_MIN_INTERVAL_S:
        print(f'_clear_ghost_connection: skipped — last reset {since:.0f}s ago '
              f'(< {_GHOST_RESET_MIN_INTERVAL_S}s anti-churn, §6.7.29)')
        return
    _last_ghost_reset = now
    print(f'_clear_ghost_connection: resetting {adapter} to clear stale state')
    try:
        subprocess.run(_priv(['hciconfig', adapter, 'reset']),
                       capture_output=True, text=True, timeout=5)
    except Exception as e:
        print(f'  ! hciconfig {adapter} reset failed: {e}')


def wake_on_press():
    """Emit ADV_DIRECT_IND targeted at the bonded STB and block until it
    connects or WAKE_TIMEOUT_S expires. Returns True if a peer becomes
    connected, False otherwise. Idempotent: if a peer is already connected,
    returns True immediately without touching advertising. Serialized via
    _wake_lock so two overlapping keypresses don't fight over the HCI."""
    bus = _WAKE_CTX.get('bus')
    adv_mgr = _WAKE_CTX.get('adv_mgr')
    adv_path = _WAKE_CTX.get('adv_path')
    adapter = _WAKE_CTX.get('adapter_hci', 'hci0')
    if bus is None or adv_mgr is None or adv_path is None:
        print('wake_on_press: context not initialised, skipping')
        return False

    with _wake_lock:
        peer_mac = _bonded_peer_mac(bus)

        if count_connected_peers(bus) > 0:
            # D-Bus claims connected — but bluetoothd's Connected flag can
            # be stale long after the peer dropped the link silently. Cross-
            # check with the mgmt socket; if it disagrees, reset the adapter
            # so bluetoothd updates Connected=false and we can advertise
            # ADV_DIRECT_IND to wake the peer.
            if peer_mac and _link_state_via_mgmt(peer_mac, adapter) == 'not-connected':
                print(f'wake_on_press: ghost connection for {peer_mac}, clearing')
                _clear_ghost_connection(adapter)
                time.sleep(0.5)  # let bluetoothd see Connected=False
            else:
                return True  # genuinely connected, no wake needed

        if not peer_mac:
            print('wake_on_press: no bonded peer, skipping directed adv')
            return False

        print(f'wake_on_press: no peer connected, starting ADV_DIRECT_IND -> {peer_mac}')
        _peer_connected_event.clear()

        # 1. Unregister BlueZ's undirected advertisement so the advertising
        #    hardware is free for our raw HCI sequence. Failures are
        #    non-fatal — we attempt the HCI path regardless and rely on
        #    the re-register at the end.
        if os.environ.get('HID_REMOTE_SKIP_ADV') != '1':
            try:
                adv_mgr.UnregisterAdvertisement(dbus.ObjectPath(adv_path))
            except Exception as e:
                print(f'  ! UnregisterAdvertisement failed: {e}')
        time.sleep(0.15)

        # 2. Raw HCI: disable any current adv to free the parameters.
        _hci_cmd(['0x08', '0x000a', '00'], adapter=adapter)

        # 3. Raw HCI: LE Set Advertising Parameters (OGF 0x08, OCF 0x0006)
        #    Interval min/max:     0x00a0 / 0x00a0  = 100 ms
        #    Advertising type:     0x04  (ADV_DIRECT_IND, low duty cycle)
        #    Own address type:     0x00  (public)
        #    Peer address type:    0x00  (public; STB uses public MAC)
        #    Peer address:         STB MAC in little-endian (last byte first)
        #    Channel map:          0x07  (all 3 advertising channels)
        #    Filter policy:        0x00  (accept Scan/Connect from any)
        peer_le = peer_mac.split(':')
        if len(peer_le) != 6:
            print(f'  ! malformed peer mac: {peer_mac}')
            return False
        peer_le.reverse()
        peer_le = [b.lower() for b in peer_le]
        params = ['a0', '00', 'a0', '00', '04', '00', '00'] + peer_le + ['07', '00']
        ok, _ = _hci_cmd(['0x08', '0x0006'] + params, adapter=adapter)
        if not ok:
            print('  ! LE Set Advertising Parameters failed')

        # 4. Raw HCI: LE Set Advertise Enable = 1
        ok, _ = _hci_cmd(['0x08', '0x000a', '01'], adapter=adapter)
        if not ok:
            print('  ! LE Set Advertise Enable failed')

        # 5. Wait for the device watcher to signal Connected=True.
        print(f'wake_on_press: directed adv running, waiting up to {WAKE_TIMEOUT_S}s')
        got_connection = _peer_connected_event.wait(timeout=WAKE_TIMEOUT_S)

        # 6. Always disable the raw adv before re-registering BlueZ's.
        _hci_cmd(['0x08', '0x000a', '00'], adapter=adapter)

        # 7. Re-enable undirected advertising for the next idle cycle —
        #    locked to the bonded STB (§6.7.31), never the open ADV_IND.
        if os.environ.get('HID_REMOTE_SKIP_ADV') == '1':
            _enable_identity_adv(bus, adapter)
        else:
            try:
                adv_mgr.RegisterAdvertisement(
                    dbus.ObjectPath(adv_path), {},
                    reply_handler=lambda: None,
                    error_handler=lambda e: print(f'  ! re-register undirected adv failed: {e}'))
            except Exception as e:
                print(f'  ! RegisterAdvertisement re-call failed: {e}')

        # Boundary re-check: the STB's reconnect can complete in the brief
        # window between the wait() timing out and here (steps 6-7 above run
        # ~0.5s of HCI commands). Observed 2026-06-25 on host3 where
        # `Connected=True` was logged the SAME second as the timeout, so the
        # wake declared failure on a link that was actually up and the key
        # was dropped. Re-poll the connected-event AND the live peer count
        # before giving up — either being true means the wake succeeded.
        if not got_connection:
            got_connection = (_peer_connected_event.is_set()
                              or count_connected_peers(bus) > 0)
            if got_connection:
                print('wake_on_press: STB reconnected just after timeout '
                      '(boundary race)')

        if got_connection:
            print('wake_on_press: STB reconnected')
            # Give bluetoothd a moment to replay CCCDs and export services
            # before callers start emitting notifications on the new link.
            time.sleep(0.4)
            return True

        print('wake_on_press: STB did not reconnect within timeout')
        return False


# ---------------------------------------------------------------------------
# Cold-standby wake (Broadcom "Legacy Wake on BLE" / WoBLE)
# ---------------------------------------------------------------------------
# wake_on_press() above handles ACTIVE standby: the STB host is still running
# and passively scanning, so ADV_DIRECT_IND reconnects it. It CANNOT wake a
# box in deep/COLD standby (S2/S3) where the host CPU is off and only the
# Broadcom BT chip is alive — armed (via BRCM_BLE_META_VSC 0x00e9) with a
# packet-content filter that asserts BT_HOST_WAKE only when it sees an
# *undirected* ADV_IND carrying manufacturer-specific data: company 0x000F
# (Broadcom) + ASCII pattern "WAKEUP", from the bonded remote's address.
# That undirected broadcast is exactly what a real RCU emits when you press
# POWER on a sleeping box. Ref: Broadcom BSA Wake-on-BLE / LGI WoBLE appendix;
# BLUETOOTH.md §6.7.10.
#
# WoBLE wake AD payload (Flags + Manufacturer Specific Data):
#   02 01 06                          Flags (LE General Disc + no BR/EDR)
#   09 FF 0F 00 57 41 4B 45 55 50     len 9, MSD (0xFF), company 0x000F, "WAKEUP"
_WOBLE_ADV_PAYLOAD = ['02', '01', '06',
                      '09', 'ff', '0f', '00', '57', '41', '4b', '45', '55', '50']
# How long to broadcast the WoBLE pattern before switching back to the
# identity advert. The chip's filter matches within one scan window.
WOBLE_BROADCAST_S = 3
# Booting the host from S2/S3 then reconnecting is much slower than the
# active-standby reconnect, so allow a longer window than WAKE_TIMEOUT_S.
COLD_WAKE_TIMEOUT_S = 20

# Identity advertisement bytes — kept byte-for-byte identical to the raw-HCI
# advertising block in start.sh (§6.7.13). cold_wake_on_press temporarily
# overwrites adv data with the WoBLE pattern and must restore exactly this
# afterwards. If you change the advert in start.sh, change it here too.
_IDENTITY_ADV_DATA_ARGS = [
    '16', '02', '01', '06', '05', '03', '12', '18', '0f', '18',
    '03', '19', '80', '01', '05', 'ff', '93', '00', '00', '80',
    '02', '0a', '00', '00', '00', '00', '00', '00', '00', '00', '00', '00']
_IDENTITY_SCAN_RSP_ARGS = [
    '0c', '0b', '09', '52', '65', '6d', '6f', '74', '65', '55',
    '6e', '69', '74', '00', '00', '00', '00', '00', '00', '00',
    '00', '00', '00', '00', '00', '00', '00', '00', '00', '00', '00', '00']
# LE Set Advertising Parameters, ADV_IND 20-40 ms, all channels. The LAST byte
# is the advertising filter policy (§6.7.31):
#   0x00 = accept scan + connect from ANY device   (pairing window, no bond)
#   0x02 = scan from any, CONNECT only from the controller's filter accept list
# Policy 0x02 keeps the scan response ("RemoteUnit") visible to every STB's
# discovery filter but lets only the bonded STB establish a link — a foreign
# central can no longer grab the adapter and silence our advert.
_IDENTITY_ADV_PARAMS_OPEN = [
    '20', '00', '40', '00', '00', '00', '00', '00', '00', '00', '00', '00', '00', '07', '00']
_IDENTITY_ADV_PARAMS_LOCKED = _IDENTITY_ADV_PARAMS_OPEN[:-1] + ['02']
_IDENTITY_ADV_PARAMS_ARGS = _IDENTITY_ADV_PARAMS_OPEN   # legacy name (open)


def _hci_status(out):
    """Status byte of the last HCI event line printed by `hcitool cmd`, e.g.
    '> HCI Event: 0x0e plen 4 / 01 10 20 00' -> '00'. None if unparsable."""
    lines = [l for l in (out or '').strip().splitlines() if l.strip()]
    if not lines:
        return None
    toks = lines[-1].split()
    return toks[-1].lower() if toks else None


def _mac_le(mac):
    """'AA:BB:CC:DD:EE:03' -> ['03','ee','dd','cc','bb','aa'] (HCI little-endian)."""
    parts = mac.split(':')
    if len(parts) != 6:
        return None
    return [p.lower() for p in reversed(parts)]


def _program_accept_list(adapter, macs):
    """§6.7.31: load the controller's LE filter accept list with the bonded
    STB address(es). Advertising MUST be disabled first (the controller
    rejects list edits while a list-based adv filter policy is active).
    Our STB bonds are all public addresses (AddressType=public on disk)."""
    ok, out = _hci_cmd(['0x08', '0x0010'], adapter=adapter)          # LE Clear Filter Accept List
    if not ok or _hci_status(out) != '00':
        print(f'  ! accept list clear failed on {adapter}: status={_hci_status(out)}')
        return False
    loaded = []
    for mac in macs:
        le = _mac_le(mac)
        if not le:
            continue
        ok, out = _hci_cmd(['0x08', '0x0011', '00'] + le, adapter=adapter)   # LE Add Device (public)
        if ok and _hci_status(out) == '00':
            loaded.append(mac)
        else:
            print(f'  ! accept list add {mac} failed on {adapter}: status={_hci_status(out)}')
    print(f'accept list on {adapter}: {loaded or "EMPTY"} (§6.7.31)')
    return bool(loaded)


def _enable_identity_adv(bus, adapter, with_data=False):
    """Raw-HCI identity advert, locked to the bonded STB when a bond exists.

    disable adv -> [adv data + scan rsp] -> accept list <- bonds -> params
    (policy 0x02 when bonded, 0x00 when not) -> enable. Every path that
    (re)starts the undirected advert goes through here so the lock can never
    be forgotten: daemon start, after wake_on_press, after cold_wake.
    """
    bonded = _bonded_addresses(bus) if bus is not None else []
    _hci_cmd(['0x08', '0x000a', '00'], adapter=adapter)              # disable
    if with_data:
        _hci_cmd(['0x08', '0x0008'] + _IDENTITY_ADV_DATA_ARGS, adapter=adapter)
        _hci_cmd(['0x08', '0x0009'] + _IDENTITY_SCAN_RSP_ARGS, adapter=adapter)
    locked = bool(bonded) and _program_accept_list(adapter, bonded)
    params = _IDENTITY_ADV_PARAMS_LOCKED if locked else _IDENTITY_ADV_PARAMS_OPEN
    ok, out = _hci_cmd(['0x08', '0x0006'] + params, adapter=adapter)
    if not ok or _hci_status(out) != '00':
        print(f'  ! LE Set Advertising Parameters failed on {adapter}: status={_hci_status(out)}')
    ok, out = _hci_cmd(['0x08', '0x000a', '01'], adapter=adapter)    # enable
    print(f'identity adv on {adapter}: {"LOCKED to " + str(bonded) if locked else "OPEN (no bond)"}'
          f' enable-status={_hci_status(out)}')
    return locked


def _restore_identity_adv(adv_mgr, adv_path, adapter):
    """Restore our normal (identity) advertisement after a raw-HCI wake.

    In production the daemon runs with HID_REMOTE_SKIP_ADV=1 (advertising is
    raw-HCI, set up by start.sh/resume.sh), so we replay start.sh's exact
    adv-data / scan-response / params and re-enable. In the non-SKIP_ADV
    (local-dev) path we re-register BlueZ's managed advertisement instead."""
    if os.environ.get('HID_REMOTE_SKIP_ADV') == '1':
        _enable_identity_adv(_WAKE_CTX.get('bus'), adapter, with_data=True)   # §6.7.31 lock
    else:
        try:
            adv_mgr.RegisterAdvertisement(
                dbus.ObjectPath(adv_path), {},
                reply_handler=lambda: None,
                error_handler=lambda e: print(f'  ! re-register identity adv failed: {e}'))
        except Exception as e:
            print(f'  ! RegisterAdvertisement re-call failed: {e}')


def cold_wake_on_press():
    """Wake an STB from deep/COLD standby via Broadcom WoBLE (see the block
    comment above). Two phases: (1) broadcast the undirected WoBLE pattern to
    trip the sleeping chip's packet filter and boot the host; (2) restore our
    identity advert and wait up to COLD_WAKE_TIMEOUT_S for it to reconnect.
    Returns True if a peer becomes connected. Serialized via _wake_lock so it
    can't race the active-standby wake_on_press over the HCI."""
    bus = _WAKE_CTX.get('bus')
    adv_mgr = _WAKE_CTX.get('adv_mgr')
    adv_path = _WAKE_CTX.get('adv_path')
    adapter = _WAKE_CTX.get('adapter_hci', 'hci0')
    if bus is None:
        print('cold_wake_on_press: context not initialised, skipping')
        return False

    with _wake_lock:
        if count_connected_peers(bus) > 0:
            print('cold_wake_on_press: peer already connected, no-op')
            return True

        print('cold_wake_on_press: broadcasting WoBLE pattern (0x000F/"WAKEUP")')
        _peer_connected_event.clear()

        # Free the advertising hardware from BlueZ (no-op under SKIP_ADV).
        if os.environ.get('HID_REMOTE_SKIP_ADV') != '1':
            try:
                adv_mgr.UnregisterAdvertisement(dbus.ObjectPath(adv_path))
            except Exception as e:
                print(f'  ! UnregisterAdvertisement failed: {e}')
            time.sleep(0.15)

        # Program an undirected ADV_IND carrying ONLY Flags + the WoBLE
        # manufacturer pattern. It must fit in 31 bytes, so the identity
        # payload can't ride along — hence the two-phase approach.
        _hci_cmd(['0x08', '0x000a', '00'], adapter=adapter)  # disable
        wob = _WOBLE_ADV_PAYLOAD + ['00'] * (31 - len(_WOBLE_ADV_PAYLOAD))
        _hci_cmd(['0x08', '0x0008', format(len(_WOBLE_ADV_PAYLOAD), '02x')] + wob,
                 adapter=adapter)
        # ADV_IND (connectable undirected, type 0x00), 100ms, public, all chans.
        _hci_cmd(['0x08', '0x0006',
                  'a0', '00', 'a0', '00', '00', '00', '00',
                  '00', '00', '00', '00', '00', '00', '07', '00'], adapter=adapter)
        _hci_cmd(['0x08', '0x000a', '01'], adapter=adapter)  # enable

        # Blast the pattern. If the host wakes fast enough to connect during
        # the broadcast, stop early.
        print(f'cold_wake_on_press: WoBLE advertising for up to {WOBLE_BROADCAST_S}s')
        connected = _peer_connected_event.wait(timeout=WOBLE_BROADCAST_S)

        # Restore the identity advert so the now-booting host can find us.
        _restore_identity_adv(adv_mgr, adv_path, adapter)

        if not connected:
            print(f'cold_wake_on_press: identity adv restored, waiting up to '
                  f'{COLD_WAKE_TIMEOUT_S}s for reconnect')
            connected = _peer_connected_event.wait(timeout=COLD_WAKE_TIMEOUT_S)

        if connected:
            print('cold_wake_on_press: STB reconnected')
            time.sleep(0.4)  # let bluetoothd replay CCCDs / export services
            return True
        print('cold_wake_on_press: STB did not wake/reconnect within timeout')
        return False


def mark_connected_peers_trusted(bus):
    """Set Trusted=true on every currently-connected Device1.

    Called from StartNotify. At StartNotify time the STB has completed SMP,
    encrypted the link, and started subscribing to a characteristic — it is
    safely identified as our peer. Marking Trusted here makes BlueZ auto-
    accept the re-encryption request on the next reconnect after an STB or
    Pi reboot, without going through an agent round-trip. Trusted=true is
    persisted to the bond's info file, so it survives service restarts.
    """
    try:
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
        for path, ifaces in om.GetManagedObjects().items():
            # Adapter-scoped (§6.7.22-followup-9): only mark peers
            # under THIS daemon's adapter as Trusted. Marking a sibling
            # adapter's peer would race with that adapter's daemon
            # doing the same and could surface as a bluetoothd D-Bus
            # access error.
            if _ADAPTER_PATH and not path.startswith(_ADAPTER_PATH + '/'):
                continue
            dev = ifaces.get('org.bluez.Device1')
            if not dev or not dev.get('Connected', False):
                continue
            if dev.get('Trusted', False):
                continue
            props = dbus.Interface(bus.get_object(BLUEZ, path),
                                   'org.freedesktop.DBus.Properties')
            props.Set('org.bluez.Device1', 'Trusted', True)
            print(f'Marked {path} as Trusted')
    except Exception as e:
        print(f'mark_connected_peers_trusted failed: {e}')


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service, handle=0):
        # `handle`: optional pinned characteristic declaration handle.
        # Zero = let BlueZ auto-allocate within the parent service's
        # reserved range (deterministic if we always register chars in
        # the same order). Non-zero = BlueZ inserts at exactly that
        # handle. The value handle is then handle+1 by spec.
        self.path = f'{service.path}/char{index}'
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.handle = handle
        self.descriptors = []
        self.value = []
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def add_descriptor(self, d):
        self.descriptors.append(d)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        props = {
            'Service': self.service.get_path(),
            'UUID': self.uuid,
            'Flags': self.flags,
            'Descriptors': dbus.Array(
                [d.get_path() for d in self.descriptors], signature='o'),
        }
        if self.handle:
            props['Handle'] = dbus.UInt16(self.handle)
        return {GATT_CHRC_IFACE: props}

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = list(value)
        hex_str = ' '.join(f'{b:02x}' for b in self.value)
        print(f'WriteValue on {self.uuid}: [{hex_str}]')

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True
        print(f'StartNotify on {self.uuid}')
        _on_start_notify(self.uuid)
        mark_connected_peers_trusted(self.bus)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False
        print(f'StopNotify on {self.uuid}')
        _on_stop_notify(self.uuid)

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def notify_value(self, payload):
        # We always emit PropertiesChanged regardless of the cached
        # `self.notifying` flag. Reason: when the STB reconnects via its
        # cached bond it does NOT re-write the CCCD (per BLE spec, bonded
        # clients restore CCCD state on the host side), so our Python
        # wrapper never sees a StartNotify and `self.notifying` stays
        # False — even though the kernel still has the subscription
        # active. By always emitting, we let BlueZ + the kernel decide
        # whether to actually send the notification on the wire.
        self.value = list(payload)
        # Visibility hook: log if we're emitting while no peer is
        # connected. The signal itself will succeed (it's just a D-Bus
        # PropertiesChanged), but nothing goes on the wire — this is the
        # classic "hid-remote looks happy, STB shows nothing" symptom.
        n_peers = count_connected_peers(self.bus)
        if n_peers == 0:
            print(f'notify {self.uuid}: no connected peer, dropped')
        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {'Value': dbus.Array(self.value, signature='y')},
            [])


class Descriptor(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = f'{characteristic.path}/desc{index}'
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_DESC_IFACE: {
                'Characteristic': self.chrc.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_DESC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_DESC_IFACE]

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')


# ---------- Battery Service --------------------------------------------------
class BatteryLevelChrc(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_BATTERY_LEVEL,
                         ['read', 'notify'], service)
        self.value = [100]


class BatteryService(Service):
    def __init__(self, bus, index):
        super().__init__(bus, index, UUID_BATTERY_SERVICE, True,
                         handle=0x0015)
        self.add_characteristic(BatteryLevelChrc(bus, 0, self))


# ---------- Device Information Service (full 9 characteristics) --------------
class StaticReadChrc(Characteristic):
    def __init__(self, bus, index, uuid, value, service):
        super().__init__(bus, index, uuid, ['read'], service)
        self.value = list(value)


class DeviceInfoService(Service):
    def __init__(self, bus, index):
        super().__init__(bus, index, UUID_DIS_SERVICE, True,
                         handle=0x0019)

        # All values below were dumped from the real Universal Electronics
        # RemoteUnit (MAC 20:21:41:00:1F:91) over an authenticated GATT
        # session on 2026-04-13.

        # PnP ID — vendor source 0x02 (USB-IF),
        # vendor ID 0x06E7 (Universal Electronics in USB-IF),
        # product ID 0x8209 (LE bytes 09 82), version 0x0110.
        # Authoritative bytes captured 2026-04-22 via dump_remote.py with
        # the `hog` plugin disabled (direct D-Bus read of 0x2a50 on the
        # real remote). Earlier docs (§ 3.3) listed ProductID as 0x0982 —
        # that was a transcription error. Some STB firmwares (e.g. the
        # the BLE STB) key their "recognised HID remote → enable all
        # Report IDs" table on the full PnP ID; sending the wrong
        # ProductID drops the STB into a legacy-keypad-only mode where
        # Reports 2 and 3 are silently dropped.
        pnp = bytes([0x02, 0xE7, 0x06, 0x09, 0x82, 0x10, 0x01])

        # System ID — 8 bytes derived from the device MAC,
        # exactly as the real remote returns it.
        system_id = bytes([0x20, 0x21, 0x41, 0xFF, 0xFE, 0x00, 0x1F, 0x91])

        # IEEE regulatory certification data — exact bytes from the real
        # remote (structure is opaque, we mirror it).
        ieee = bytes([0xFF, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA])

        entries = [
            (UUID_DIS_MANUF_NAME,   b'Universal Electronics, Inc.'),
            (UUID_DIS_MODEL_NUMBER, b'RemoteUnit'),
            (UUID_DIS_SERIAL_NUM,   b'1.0.0.0'),
            (UUID_DIS_HW_REV,       b'01'),
            (UUID_DIS_FW_REV,       b'BL 1.8.0'),
            (UUID_DIS_SW_REV,       b'1509.05.50_0.0'),
            (UUID_DIS_SYSTEM_ID,    system_id),
            (UUID_DIS_IEEE_REG,     ieee),
            (UUID_DIS_PNP_ID,       pnp),
        ]
        for i, (uuid, value) in enumerate(entries):
            self.add_characteristic(StaticReadChrc(bus, i, uuid, value, self))


# ---------- Arris vendor service ---------------------------------------------
class ArrisNotifyChrc(Characteristic):
    """Primary notify channel — key events flow here. Flags match the real
    remote exactly: plain `notify` (no encrypt- prefix). The LL link is
    already encrypted once bonded, so ATT-layer encrypt flags are not
    needed and actually differ from what the real remote advertises.
    Payload format (confirmed by sniffing): 4 bytes
    [hid_consumer_code, 0x00, 0x00, 0x00], release = 4x 0x00."""

    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_ARRIS_NOTIFY,
                         ['notify'], service)
        self.value = [0x00, 0x00, 0x00, 0x00]


class ArrisWriteChrc(Characteristic):
    """STB -> remote command channel. STB writes here (no response).
    We log the bytes for protocol analysis; nothing else uses them."""

    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_ARRIS_WRITE,
                         ['write-without-response'], service)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = list(value)
        spaced = ' '.join(f'{b:02x}' for b in self.value)
        print(f'[stb -> arris-write] {spaced}')


class ArrisKeyboardChrc(Characteristic):
    """Second notify channel — HID Keyboard Page (0x07) codes for the
    numeric keypad (1=0x1E, 2=0x1F, …, 0=0x27). Sniffed from the real
    remote on 2026-04-13; see BLUETOOTH.md §3.4."""

    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_ARRIS_KEYBOARD,
                         ['notify'], service)
        self.value = []


class ArrisService(Service):
    def __init__(self, bus, index):
        # Pinned at 0x0048 — matches the real remote's Arris service handle
        # from the 2026-04-22 dump. Moved from 0x0040 to make room for the
        # THIRD HID Input Report (Report ID 3 / vendor page, for INFO) which
        # grows HID through 0x0040. Changing the pinned handle is a fresh-pair
        # event; subsequent reconnects restore the layout from cache.
        # History: 0x0039 (before 2026-04-21) → 0x0040 (2026-04-21, second
        # report added) → 0x0048 (2026-04-22, third report added).
        super().__init__(bus, index, UUID_ARRIS_SERVICE, True,
                         handle=0x0048)
        self.notify = ArrisNotifyChrc(bus, 0, self)
        self.add_characteristic(self.notify)
        self.add_characteristic(ArrisWriteChrc(bus, 1, self))
        self.keyboard = ArrisKeyboardChrc(bus, 2, self)
        self.add_characteristic(self.keyboard)


# ---------- HID service ------------------------------------------------------
# Multi-report HID descriptor. The Arris STB subscribes to the HID Input
# Report (0x2a4d) but not to the Arris vendor notify characteristics on
# our peripheral, so every key has to flow through HID. That requires
# Consumer Page (nav/channel/transport) and Keyboard Page (digit keypad),
# each as its own report with a distinct Report ID. **Every report is
# 4 bytes on the wire** — matches the byte-for-byte pattern sniffed from
# the real Universal Electronics RemoteUnit (dump_remote.py capture,
# 2026-04-22). Earlier 1-byte Keyboard / 2-byte Consumer payloads were
# accepted by host1's lenient STB but rejected by host3's stricter
# parser; 4-byte uniform payloads work on both.
#
# Wire format per report:
#   consumer (ID 1): [usage_lo, usage_hi, 0x00, 0x00]  on press
#                    [0x00, 0x00, 0x00, 0x00]          on release
#   keyboard (ID 2): [usage, 0x00, 0x00, 0x00]         on press
#                    [0x00, 0x00, 0x00, 0x00]          on release
#
# Descriptor shape per report:
#   consumer: 16-bit usage (Data) + 16-bit padding (Const)
#   keyboard:  8-bit usage (Data) + 24-bit padding (Const)
HID_REPORT_MAP_BYTES = bytes([
    # Single Input Report (Report ID 1) carrying THREE parallel usage-page
    # fields: Keyboard + Consumer + System Control. Six-byte payload.
    #
    # Why one report instead of mirroring the real remote's three:
    #   - host1's Arris STB (permissive parser) handles multi-report
    #     descriptors fine.
    #   - the BLE STB only dispatches from the FIRST Input Report
    #     characteristic — confirmed by isolation test 2026-04-22 where
    #     whichever usage page was on Report ID 1 worked and every
    #     subsequent Report ID was silently dropped. (§ 6.7.18)
    #   - Putting every usage page we care about inside Report ID 1 means
    #     both STBs work with the same descriptor.
    #
    # Wire format per press: [kbd_lo, kbd_hi, cons_lo, cons_hi, sys_lo, sys_hi]
    # where each 16-bit field holds either a usage value (key pressed) or
    # 0x0000 (no key on that page). Release is all six bytes zero.
    0x05, 0x01,              # Usage Page (Generic Desktop)
    0x09, 0x07,              # Usage (Keypad)                ← top-level device type
    0xA1, 0x01,              # Collection (Application)
    0x85, 0x01,              #   Report ID (1)
    # Field 1 — Keyboard Page (KEY_0..KEY_9)
    0x05, 0x07,              #   Usage Page (Keyboard)
    0x19, 0x00,              #   Usage Minimum (0)
    0x2A, 0x00, 0x01,        #   Usage Maximum (0x0100)
    0x15, 0x00,              #   Logical Minimum (0)
    0x26, 0x00, 0x01,        #   Logical Maximum (0x0100)
    0x75, 0x10,              #   Report Size (16)
    0x95, 0x01,              #   Report Count (1)
    0x81, 0x00,              #   Input (Data, Array, Abs)
    # Field 2 — Consumer Page (OK/UP/CH+/VOL/TV/VOICE/HOME/BACK/transport)
    0x05, 0x0C,              #   Usage Page (Consumer)
    0x19, 0x00,              #   Usage Minimum (0)
    0x2A, 0xFF, 0x03,        #   Usage Maximum (0x03FF)
    0x15, 0x00,              #   Logical Minimum (0)
    0x26, 0xFF, 0x03,        #   Logical Maximum (0x03FF)
    0x75, 0x10,              #   Report Size (16)
    0x95, 0x01,              #   Report Count (1)
    0x81, 0x00,              #   Input (Data, Array, Abs)
    # Field 3 — System Control (INFO = System Context Menu 0x0084)
    0x05, 0x01,              #   Usage Page (Generic Desktop)
    0x19, 0x00,              #   Usage Minimum (0)
    0x2A, 0x00, 0x01,        #   Usage Maximum (0x0100)
    0x15, 0x00,              #   Logical Minimum (0)
    0x26, 0x00, 0x01,        #   Logical Maximum (0x0100)
    0x75, 0x10,              #   Report Size (16)
    0x95, 0x01,              #   Report Count (1)
    0x81, 0x00,              #   Input (Data, Array, Abs)
    0xC0,                    # End Collection
])

# HID Information: bcdHID=0x0111, country=0, flags=0x03 (RemoteWake|NormallyConnectable)
HID_INFO_BYTES = bytes([0x11, 0x01, 0x00, 0x03])


class ReportMapChrc(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_HID_REPORT_MAP, ['read'], service)
        self.value = list(HID_REPORT_MAP_BYTES)


class HidInformationChrc(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_HID_INFO, ['read'], service)
        self.value = list(HID_INFO_BYTES)


class HidControlPointChrc(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_HID_CTRL_POINT,
                         ['write-without-response'], service)


class ProtocolModeChrc(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, UUID_HID_PROTO_MODE,
                         ['read', 'write-without-response'], service)
        self.value = [0x01]  # Report protocol mode


class ReportReferenceDesc(Descriptor):
    def __init__(self, bus, index, characteristic, report_id, report_type):
        super().__init__(bus, index, UUID_REPORT_REF, ['read'], characteristic)
        self.value = [report_id, report_type]


class HidInputReportChrc(Characteristic):
    """HID Input Report — receives key codes from sendkey.py via the FIFO.
    Encrypted because HID Report requires a paired/bonded link. ``report_id``
    and the initial ``value`` size must match the corresponding collection
    in ``HID_REPORT_MAP_BYTES``.
    """

    def __init__(self, bus, index, service, report_id=1, value_size=2):
        super().__init__(bus, index, UUID_HID_REPORT,
                         ['encrypt-read', 'encrypt-notify'], service)
        self.add_descriptor(ReportReferenceDesc(self.bus, 0, self,
                                                report_id=report_id,
                                                report_type=1))
        self.value = [0x00] * value_size


class HidService(Service):
    def __init__(self, bus, index):
        super().__init__(bus, index, UUID_HID_SERVICE, True,
                         handle=0x002c)
        # Match the real remote's characteristic order exactly — host3's
        # BLE STB dispatches HID reports by child-characteristic index
        # within the HID service (not by Report Reference descriptor), so
        # any deviation from the real remote's order silently breaks all
        # reports except the first one. Real remote layout captured
        # 2026-04-22 with hog-plugin disabled (§ 6.7.17):
        #   HID Info (0x2a4a)       ← first
        #   HID Control Point (0x2a4c)
        #   Report Map (0x2a4b)
        #   Input Report 1
        #   ...
        # (Real remote has NO Protocol Mode characteristic — STBs that
        # need it fall back to Report Protocol by default. Dropping it
        # from our emulation to match byte-for-byte.)
        self.add_characteristic(HidInformationChrc(bus, 0, self))
        self.add_characteristic(HidControlPointChrc(bus, 1, self))
        self.add_characteristic(ReportMapChrc(bus, 2, self))
        # Single Input Report (Report ID 1) carrying three usage-page
        # fields — Keyboard + Consumer + System Control — in a 6-byte
        # payload. This layout is mandated by the BLE STB which
        # only dispatches from the first Input Report characteristic (all
        # subsequent Report IDs silently drop). host1's Arris STB also
        # works with this layout because it parses Usage Pages correctly.
        # See HID_REPORT_MAP_BYTES docstring + BLUETOOTH.md § 6.7.18 for
        # the payload shape.
        self.input_report = HidInputReportChrc(bus, 3, self,
                                               report_id=1, value_size=6)
        self.add_characteristic(self.input_report)


# ---------- Advertisement ----------------------------------------------------
class Advertisement(dbus.service.Object):
    PATH = '/com/vpt/remote/advertisement0'

    def __init__(self, bus):
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.PATH)

    def get_properties(self):
        # Manufacturer data copied from the reference remote
        # (Universal Electronics, Inc. company id 0x0093, payload 00 80).
        msd = dbus.Dictionary(
            {dbus.UInt16(0x0093): dbus.Array([0x00, 0x80], signature='y')},
            signature='qv')
        return {
            LE_ADV_IFACE: {
                'Type': 'peripheral',
                # HID UUID kept in the list as a decoy — real remote does
                # the same even though its GATT tree has no HID service.
                'ServiceUUIDs': dbus.Array(
                    [UUID_HID_SERVICE, UUID_BATTERY_SERVICE], signature='s'),
                'LocalName': LOCAL_NAME,
                'Appearance': dbus.UInt16(0x0180),  # Generic Remote Control
                'ManufacturerData': msd,
                'Includes': dbus.Array(['tx-power'], signature='s'),
                'Discoverable': dbus.Boolean(True),
                'MinInterval': dbus.UInt32(20),
                'MaxInterval': dbus.UInt32(50),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.PATH)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADV_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADV_IFACE]

    @dbus.service.method(LE_ADV_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Advertisement released')


# ---------- Adapter lookup ---------------------------------------------------
def find_adapter(bus):
    # HID_REMOTE_ADAPTER is set by start.sh / resume.sh / the
    # vpt-ble-remote@hciN template — one daemon instance per adapter
    # (multi-instance, §6.7.22-followup-6/9). Default 'hci0' is just the
    # historical singleton-host behaviour. Walk the bluez object tree,
    # pick the adapter that has BOTH GattManager1 AND LEAdvertisingManager1
    # (i.e. a usable BLE peripheral controller), and prefer the one whose
    # path ends with the requested hciN.
    preferred = os.environ.get('HID_REMOTE_ADAPTER', 'hci0')
    om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
    fallback = None
    for path, ifaces in om.GetManagedObjects().items():
        if GATT_MANAGER_IFACE in ifaces and LE_ADV_MANAGER_IFACE in ifaces:
            if path.endswith('/' + preferred):
                return path
            if fallback is None:
                fallback = path
    return fallback


# ---------- FIFO key input ---------------------------------------------------
def ensure_fifo():
    # If anything already exists at FIFO_PATH, verify it's actually a FIFO.
    # A regular file at this path (accidentally created by e.g. a shell
    # redirection like `echo KEY > /tmp/hid_remote.fifo` that missed the
    # pipe) would cause fifo_reader_thread to open() it instantly, read
    # the stale contents in a tight while-True loop, and re-inject the
    # same key hundreds of times per second — which masquerades as an
    # external writer flooding the FIFO. Unlink and recreate if so.
    if os.path.exists(FIFO_PATH):
        try:
            if not stat.S_ISFIFO(os.stat(FIFO_PATH).st_mode):
                print(f'ensure_fifo: {FIFO_PATH} exists but is not a FIFO; '
                      f'unlinking and recreating')
                os.unlink(FIFO_PATH)
        except OSError as e:
            print(f'ensure_fifo: stat/unlink failed: {e}')
    # Permissions: this daemon may run as root (it needs raw HCI), while the
    # backend_host controller that writes key sentinels here (press_key / wake
    # / cold_wake) runs as vpt_user. A root-owned 0o600 FIFO blocks that
    # cross-user write — every controller open(FIFO,'w') fails with
    # PermissionError and the key/sentinel never reaches the daemon (this is
    # exactly what broke after the 0o666→0o600 B103 change: the controller
    # could no longer write). Use 0o660 + group-ownership by the controller's
    # group so the controller can write WITHOUT making the FIFO world-writable
    # (world-writable is what bandit B103 actually flags). The group name is
    # configurable via HID_REMOTE_FIFO_GROUP (default vpt_user, the platform
    # service user). chgrp is best-effort — if the group is missing or we lack
    # privilege we keep the FIFO usable rather than crashing the daemon.
    # 0o660, NOT 0o600: the controller writes as vpt_user via the GROUP bit.
    # 0o600 + chgrp grants the group nothing — that variant shipped on main
    # and broke every UI keypress on host2 (2026-09-02) while
    # `sudo tee` into the FIFO still worked. prod has always been 0o660.
    try:
        os.mkfifo(FIFO_PATH, 0o660)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    os.chmod(FIFO_PATH, 0o660)
    fifo_group = os.environ.get('HID_REMOTE_FIFO_GROUP', 'vpt_user')
    try:
        import grp
        os.chown(FIFO_PATH, -1, grp.getgrnam(fifo_group).gr_gid)
    except (KeyError, PermissionError, OSError) as e:
        print(f'ensure_fifo: could not chgrp {FIFO_PATH} to {fifo_group} '
              f'(controller writes may fail if it runs as a different user): {e}')


CHANNEL_CONSUMER = 'consumer'  # HID Input Report ID 1 (Consumer Page 0x0C) + Arris 2141e101
CHANNEL_KEYBOARD = 'keyboard'  # HID Input Report ID 2 (Keyboard Page 0x07) + Arris 2141e103
CHANNEL_SPECIAL  = 'special'   # HID Input Report ID 3 (Vendor Page 0xFF00) — no Arris mirror

# Keys that route through the third HID Input Report (vendor page). The
# real remote sends these ONLY on its third 0x2a4d characteristic (handle
# 0x0045 in the sniff), with no parallel Arris vendor notify. See
# BLUETOOTH.md § 6.7.16.
_SPECIAL_KEYS = frozenset({'INFO'})


def parse_key(line):
    """Parse a FIFO line into ``(code, channel)`` or ``None``.

    Routing:
    - Names in ``_SPECIAL_KEYS`` (currently ``INFO``) → third HID Input
      Report (CHANNEL_SPECIAL). No Arris vendor parity.
    - Names starting with ``KEY_`` (numeric keypad) → Keyboard HID Input
      Report + Arris 2141e103 parity.
    - Everything else (including raw hex codes) → Consumer HID Input Report
      + Arris 2141e101 parity.
    """
    line = line.strip()
    if not line:
        return None
    up = line.upper()
    if up in KEYS:
        if up in _SPECIAL_KEYS:
            channel = CHANNEL_SPECIAL
        elif up.startswith('KEY_'):
            channel = CHANNEL_KEYBOARD
        else:
            channel = CHANNEL_CONSUMER
        return KEYS[up], channel
    try:
        return int(line, 0) & 0xFFFF, CHANNEL_CONSUMER
    except ValueError:
        print(f'Unknown key: {line}')
        return None


def send_key(arris_svc, code, channel=CHANNEL_CONSUMER, hid_svc=None):
    # Real-remote-confirmed 4-byte Arris payload: [code, 0, 0, 0] press,
    # all zeros release. Emitted regardless of channel for GATT parity
    # with the real remote; BlueZ drops it if the STB never subscribed.
    arris_press = bytes([code & 0xFF, 0x00, 0x00, 0x00])
    arris_release = bytes([0x00, 0x00, 0x00, 0x00])

    # Single HID Input Report (Report ID 1), 6-byte payload with three
    # parallel 16-bit fields:
    #   bytes 0-1 : Keyboard Page usage     (digits)
    #   bytes 2-3 : Consumer Page usage     (OK/UP/CH+/VOL/TV/VOICE/…)
    #   bytes 4-5 : Generic Desktop 0x01    (System Control — INFO)
    # Fill the slot for this key's channel, zero the others. Release is
    # six zero bytes. See HID_REPORT_MAP_BYTES docstring for why we
    # consolidate into one report rather than mirroring the real remote's
    # three — host3's STB only honours the first Input Report char.
    hid_chrc = hid_svc.input_report if hid_svc is not None else None
    hid_release = bytes([0x00] * 6)
    if channel == CHANNEL_SPECIAL:
        # INFO / System Control: bytes 4-5.
        hid_press = bytes([0x00, 0x00,
                           0x00, 0x00,
                           code & 0xFF, (code >> 8) & 0xFF])
        # No Arris vendor mirror for System reports (real remote doesn't
        # expose one on 2141e10x either).
        arris_chrc = None
    elif channel == CHANNEL_KEYBOARD:
        # Digits: bytes 0-1.
        hid_press = bytes([code & 0xFF, (code >> 8) & 0xFF,
                           0x00, 0x00,
                           0x00, 0x00])
        arris_chrc = arris_svc.keyboard
    else:
        # Consumer: bytes 2-3.
        hid_press = bytes([0x00, 0x00,
                           code & 0xFF, (code >> 8) & 0xFF,
                           0x00, 0x00])
        arris_chrc = arris_svc.notify

    def press():
        if arris_chrc is not None:
            arris_chrc.notify_value(arris_press)
        if hid_chrc is not None:
            hid_chrc.notify_value(hid_press)
        return False  # one-shot

    def releasekey():
        if arris_chrc is not None:
            arris_chrc.notify_value(arris_release)
        if hid_chrc is not None:
            hid_chrc.notify_value(hid_release)
        return False  # one-shot

    GLib.idle_add(press)
    GLib.timeout_add(80, releasekey)


def fifo_reader_thread(arris_svc, hid_svc=None):
    ensure_fifo()
    print(f'FIFO ready: {FIFO_PATH} (known keys: {sorted(KEYS)})')
    while True:
        with open(FIFO_PATH, 'r') as f:
            for line in f:
                # WAKE sentinel: trigger wake_on_press without sending a
                # key. Used by the controller to proactively reconnect an
                # idle STB when the frontend panel takes control.
                if line.strip().upper() == 'WAKE':
                    bus = _WAKE_CTX.get('bus')
                    if bus is not None and count_connected_peers(bus) == 0:
                        print('WAKE sentinel: no peer, triggering wake_on_press')
                        wake_on_press()
                    else:
                        print('WAKE sentinel: peer already connected, no-op')
                    continue
                # COLD_WAKE sentinel: wake a box in deep/cold standby (S2/S3)
                # via the Broadcom WoBLE pattern. Distinct from WAKE
                # (ADV_DIRECT_IND, active standby) — see cold_wake_on_press().
                if line.strip().upper() == 'COLD_WAKE':
                    bus = _WAKE_CTX.get('bus')
                    if bus is not None and count_connected_peers(bus) == 0:
                        print('COLD_WAKE sentinel: no peer, triggering cold_wake_on_press')
                        cold_wake_on_press()
                    else:
                        print('COLD_WAKE sentinel: peer already connected, no-op')
                    continue
                parsed = parse_key(line)
                if parsed is None:
                    continue
                code, channel = parsed
                print(f'Injecting 0x{code:04X} ({channel})')
                # Wake-on-press: if the STB has let the link idle out and
                # entered its low-power scan mode, emit ADV_DIRECT_IND at
                # its bonded MAC to wake it. Blocks for up to
                # WAKE_TIMEOUT_S. No-ops if already connected.
                bus = _WAKE_CTX.get('bus')
                if bus is not None:
                    adapter_hci = _WAKE_CTX.get('adapter_hci', 'hci0')
                    if count_connected_peers(bus) == 0:
                        wake_on_press()
                    else:
                        # D-Bus says peer is connected; probe the mgmt layer
                        # in case it's a ghost (bluetoothd stale Connected).
                        peer = _bonded_peer_mac(bus)
                        if peer and _link_state_via_mgmt(peer, adapter_hci) == 'not-connected':
                            print(f'ghost connection for {peer}; triggering wake_on_press')
                            wake_on_press()
                send_key(arris_svc, code, channel, hid_svc)


# ---------- Main -------------------------------------------------------------
def acquire_run_lock():
    """Take the exclusive per-adapter run lock, or exit.

    Must run before any D-Bus/GATT/FIFO work: a duplicate that got far
    enough to register a GATT app or open the FIFO has already started
    stealing keys. Exits 1 (not 0) so systemd surfaces the collision
    instead of silently treating the duplicate as a clean run.
    """
    global _lock_fh
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    # O_RDWR|O_CREAT, never 'w': mode 'w' truncates on open, so a second
    # daemon would erase the holder's pid before it could read it and the
    # collision message would name no culprit.
    fh = os.fdopen(os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644), 'r+')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        holder = fh.read().strip()
        sys.stderr.write(
            f'hid_remote: {_ADAPTER} already served by pid {holder or "?"} '
            f'({LOCK_PATH}); refusing to start a second daemon — two readers '
            f'on {FIFO_PATH} would split the key stream.\n')
        sys.exit(1)
    fh.seek(0)
    fh.truncate(0)
    fh.write(str(os.getpid()))
    fh.flush()
    _lock_fh = fh
    print(f'Run lock acquired: {LOCK_PATH} (pid {os.getpid()})')


def install_bluez_owner_watch(bus):
    """Exit — so systemd relaunches us — when bluetoothd is replaced.

    A bluetoothd restart silently invalidates everything this daemon
    registered over D-Bus (RegisterApplication, advertising) while the
    daemon itself keeps running. The resulting failure mode is nasty
    (§6.7.28, host3 2026-07-16): the bond still encrypts, wake-on-press
    still reconnects the STB, every press still logs `Injecting 0x..` —
    but the new bluetoothd serves an EMPTY GATT table, the STB finds
    nothing to subscribe to, and BlueZ drops every notification without
    an error anywhere.

    Re-registering in place would mean rebuilding every proxy, signal
    match and the device watcher against the new bluetoothd; exiting
    re-runs the already-tested startup path instead. hid-remote@.service
    has Restart=always + RestartSec=2, so exiting IS the re-register.

    Act on the NEW owner appearing, not on the old one vanishing:
    restarting while bluetoothd is still down would just crash-loop
    find_adapter() until the unit's start limit trips.
    """
    def on_owner_changed(name, old_owner, new_owner):
        if str(name) != BLUEZ or not new_owner:
            return
        print(f'org.bluez owner changed ({old_owner or "none"} -> {new_owner}): '
              'our GATT registration died with the old bluetoothd; '
              'exiting so systemd relaunches us clean')
        sys.stdout.flush()
        # os._exit, not sys.exit: this fires on the GLib main loop, where
        # SystemExit is swallowed, and a polite shutdown would block on
        # Unregister* calls to a bluetoothd that has already forgotten us.
        os._exit(1)

    bus.add_signal_receiver(on_owner_changed,
                            dbus_interface='org.freedesktop.DBus',
                            signal_name='NameOwnerChanged',
                            arg0=BLUEZ)


def main():
    acquire_run_lock()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    install_bluez_owner_watch(bus)

    adapter_path = find_adapter(bus)
    if not adapter_path:
        sys.stderr.write('No BlueZ adapter with GattManager1+LEAdvertisingManager1\n')
        sys.exit(1)
    print(f'Using adapter: {adapter_path}')

    # Publish adapter_path for the GetManagedObjects-walking helpers.
    # MUST happen BEFORE install_device_watcher() so the initial-state
    # scan inside that function can filter to this adapter.
    global _ADAPTER_PATH
    _ADAPTER_PATH = adapter_path

    install_device_watcher(bus)

    adapter_props = dbus.Interface(bus.get_object(BLUEZ, adapter_path),
                                   DBUS_PROP_IFACE)
    adapter_props.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(True))
    adapter_props.Set(ADAPTER_IFACE, 'Alias', dbus.String(LOCAL_NAME))
    # §6.7.30: Pairable/Discoverable ONLY while no bond exists. Used to be
    # unconditionally True here, which re-opened the pairing window that
    # resume.sh had just closed (§6.7.29) on every daemon start.
    _bonded_at_start = _bonded_addresses(bus)
    _set_pairing_window(bus, not _bonded_at_start,
                        f'bonded to {_bonded_at_start}' if _bonded_at_start
                        else 'no bond yet — pairing window open')
    if len(_bonded_at_start) > 1:
        print(f'*** {_ADAPTER_PATH} holds {len(_bonded_at_start)} bonds {_bonded_at_start} '
              f'— duplicate bond (§6.7.29); remove the stale one ***')
    # §6.7.31: resume.sh/start.sh enabled a raw-HCI ADV_IND open to anyone.
    # With a bond, re-arm it locked to the bonded STB. Without a bond
    # (start.sh pairing window) leave it open — the STB must be able to connect.
    if os.environ.get('HID_REMOTE_SKIP_ADV') == '1' and _bonded_at_start:
        _enable_identity_adv(bus, _ADAPTER)

    app = Application(bus)
    app.add_service(BatteryService(bus, 0))
    app.add_service(DeviceInfoService(bus, 1))
    hid_svc = HidService(bus, 2)
    app.add_service(hid_svc)
    arris = ArrisService(bus, 3)
    app.add_service(arris)

    gatt_mgr = dbus.Interface(bus.get_object(BLUEZ, adapter_path),
                              GATT_MANAGER_IFACE)
    adv_mgr = dbus.Interface(bus.get_object(BLUEZ, adapter_path),
                             LE_ADV_MANAGER_IFACE)
    adv = Advertisement(bus)

    mainloop = GLib.MainLoop()

    def on_register_ok():
        print('GATT application registered')
        _clear_subscriptions()  # write initial status (hid_ready=false)

    def on_register_err(err):
        print(f'GATT register failed: {err}')
        mainloop.quit()

    def on_adv_ok():
        print('Advertisement registered')

    def on_adv_err(err):
        # Do NOT quit on advertisement registration failure: this happens
        # in the legitimate case where the controller already has an
        # active LE connection (e.g. the STB grabbed us between our radio
        # coming up and our advertising request). In that case we keep
        # the GATT app registered so the existing connection can use it,
        # and we just live without (re-)advertising. We will still accept
        # new connections via the in-progress one.
        print(f'Advertisement register failed (continuing without advert): {err}')

    gatt_mgr.RegisterApplication(app.get_path(), {},
                                 reply_handler=on_register_ok,
                                 error_handler=on_register_err)
    if os.environ.get('HID_REMOTE_SKIP_ADV') == '1':
        print('Skipping D-Bus RegisterAdvertisement (HID_REMOTE_SKIP_ADV=1); '
              'start.sh/resume.sh handles advertising via raw HCI.')
    else:
        adv_mgr.RegisterAdvertisement(adv.get_path(), {},
                                      reply_handler=on_adv_ok,
                                      error_handler=on_adv_err)

    # Populate the wake-on-press context so fifo_reader_thread can emit
    # ADV_DIRECT_IND when a key arrives while no peer is connected.
    _WAKE_CTX.update({
        'bus': bus,
        'adv_mgr': adv_mgr,
        'adv_path': adv.get_path(),
        'adapter_hci': adapter_path.rsplit('/', 1)[-1],
    })

    t = threading.Thread(target=fifo_reader_thread,
                         args=(arris, hid_svc), daemon=True)
    t.start()

    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            adv_mgr.UnregisterAdvertisement(adv.get_path())
        except Exception:
            pass
        try:
            gatt_mgr.UnregisterApplication(app.get_path())
        except Exception:
            pass


if __name__ == '__main__':
    main()
