#!/usr/bin/env python3
"""Reverse-engineer a physical BLE remote by bonding with it as a central.

Pairs with the remote, lists every GATT service + characteristic, reads
every readable value, subscribes to every notify/indicate characteristic,
and prints each incoming ATT Handle Value Notification with a timestamp,
the service + characteristic UUID, and the payload bytes in hex. Because
the Pi holds the LTK after bonding, BlueZ decrypts every notification for
us — which is what we need to recover a remote's button protocol without
passive sniffing (which cannot decrypt LE Secure Connections links).

Typical use: a new STB ships with a remote whose HID layout / vendor
service we don't know. Put the remote in pair-new mode, point this script
at its MAC, press each button, and the output tells you the exact
characteristic and byte pattern that the real remote uses — which then
feeds back into a new ble_conf/<model>.json + the relevant branches of
send_key() in hid_remote.py.

Prerequisites:
  * hid-remote.service stopped if using the SAME adapter that it runs on
    (it owns hci0 as peripheral; central-role pairing needs the radio).
    `sudo systemctl stop hid-remote.service` then restart when done.
  * Remote physically in pairing mode (usually a button combo).
  * Run as root (needs BlueZ management access).

See docs/agent/devices/BLUETOOTH.md § 8 (bluetooth/BLUETOOTH_ANALYSIS.md) for the full capture procedure.
"""
import argparse
import datetime
import os
import re
import signal
import sys
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


BLUEZ = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DEVICE_IFACE = 'org.bluez.Device1'
GATT_SVC_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'
AGENT_IFACE = 'org.bluez.Agent1'
AGENT_MGR_IFACE = 'org.bluez.AgentManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
AGENT_PATH = '/virtualpytest/dump_agent'


def ts() -> str:
    return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]


class Agent(dbus.service.Object):
    """NoInputNoOutput agent — auto-accepts every pairing prompt so Just
    Works pairing with an LE remote completes with zero interaction."""

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        return '0000'

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Cancel(self):
        pass


def find_adapter(bus, adapter_hci: str) -> str:
    om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
    for path, ifaces in om.GetManagedObjects().items():
        if ADAPTER_IFACE in ifaces and path.endswith('/' + adapter_hci):
            return path
    raise RuntimeError(f'adapter {adapter_hci} not found')


def device_path_for(adapter_path: str, mac: str) -> str:
    return f'{adapter_path}/dev_' + mac.upper().replace(':', '_')


def scan_and_list(bus, adapter_path, timeout_s) -> None:
    """Run a discovery for `timeout_s` seconds and print every device seen."""
    adapter = dbus.Interface(bus.get_object(BLUEZ, adapter_path), ADAPTER_IFACE)
    try:
        adapter.SetDiscoveryFilter({'Transport': dbus.String('le')})
    except Exception:
        pass
    try:
        adapter.StartDiscovery()
    except Exception:
        pass
    print(f'[{ts()}] scanning for {timeout_s}s… press Ctrl+C to stop early')
    mainloop = GLib.MainLoop()
    seen = {}

    def dump_device(path, props):
        mac = props.get('Address')
        name = props.get('Name') or props.get('Alias') or '-'
        rssi = props.get('RSSI')
        if mac and mac not in seen:
            seen[mac] = (name, rssi)
            print(f'[{ts()}]   {mac}   rssi={rssi!s:>5}   name={name}')

    def on_added(path, ifaces):
        if DEVICE_IFACE in ifaces:
            dump_device(path, ifaces[DEVICE_IFACE])

    def on_changed(iface, changed, invalidated, path=None):
        # In BlueZ D-Bus signals the path is the signal's sender; rely on
        # re-query via ObjectManager instead (keeps this simple).
        pass

    bus.add_signal_receiver(
        on_added, dbus_interface=DBUS_OM_IFACE,
        signal_name='InterfacesAdded')

    # Prime with whatever's already known.
    om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
    for path, ifaces in om.GetManagedObjects().items():
        if DEVICE_IFACE in ifaces and path.startswith(adapter_path + '/'):
            dump_device(path, ifaces[DEVICE_IFACE])

    GLib.timeout_add_seconds(timeout_s, lambda: mainloop.quit())
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    try:
        adapter.StopDiscovery()
    except Exception:
        pass


def wait_for_prop(bus, obj_path, iface, prop, desired, timeout_s) -> bool:
    """Block up to timeout_s until the named property on obj_path equals
    desired. Uses the GLib mainloop + PropertiesChanged signal so we don't
    busy-poll."""
    mainloop = GLib.MainLoop()
    result = {'ok': False}

    def check_current():
        try:
            props = dbus.Interface(bus.get_object(BLUEZ, obj_path),
                                   DBUS_PROP_IFACE)
            cur = props.Get(iface, prop)
            if cur == desired:
                result['ok'] = True
                mainloop.quit()
        except Exception:
            pass

    def on_props_changed(changed_iface, changed, invalidated, path=None):
        if prop in changed and changed[prop] == desired:
            result['ok'] = True
            mainloop.quit()

    match = bus.add_signal_receiver(
        on_props_changed, dbus_interface=DBUS_PROP_IFACE,
        signal_name='PropertiesChanged', path=obj_path,
        path_keyword='path')

    check_current()
    if not result['ok']:
        GLib.timeout_add_seconds(timeout_s, lambda: mainloop.quit())
        mainloop.run()
    match.remove()
    return result['ok']


def fmt_hex(value) -> str:
    return ' '.join(f'{int(b):02x}' for b in value)


def enumerate_and_subscribe(bus, adapter_path, device_path):
    """Print every service + characteristic, read readable chars, subscribe
    to every notify/indicate. Returns a list of (uuid, path) pairs we
    subscribed to so we can StopNotify on shutdown."""
    om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
    managed = om.GetManagedObjects()

    # Group chrcs under their service.
    services = {}
    chars = []
    for path, ifaces in managed.items():
        if not path.startswith(device_path + '/'):
            continue
        if GATT_SVC_IFACE in ifaces:
            services[path] = dict(ifaces[GATT_SVC_IFACE])
        elif GATT_CHRC_IFACE in ifaces:
            chars.append((path, dict(ifaces[GATT_CHRC_IFACE])))

    subscribed = []
    for svc_path, svc_props in sorted(services.items()):
        svc_uuid = str(svc_props.get('UUID', '-'))
        print(f'\n[{ts()}] Service {svc_uuid}   {svc_path}')
        for chrc_path, chrc_props in sorted(chars):
            if not chrc_path.startswith(svc_path + '/'):
                continue
            chrc_uuid = str(chrc_props.get('UUID', '-'))
            flags = [str(f) for f in chrc_props.get('Flags', [])]
            print(f'[{ts()}]   chrc {chrc_uuid}   flags={",".join(flags)}   '
                  f'{chrc_path}')
            chrc = dbus.Interface(bus.get_object(BLUEZ, chrc_path),
                                  GATT_CHRC_IFACE)
            if 'read' in flags or 'encrypt-read' in flags:
                try:
                    value = chrc.ReadValue({})
                    print(f'[{ts()}]     read  [{fmt_hex(value)}]')
                except Exception as e:
                    print(f'[{ts()}]     read  failed: {e}')
            if 'notify' in flags or 'encrypt-notify' in flags or \
                    'indicate' in flags or 'encrypt-indicate' in flags:
                try:
                    chrc.StartNotify()
                    subscribed.append((chrc_uuid, chrc_path))
                    print(f'[{ts()}]     subscribed')
                except Exception as e:
                    print(f'[{ts()}]     subscribe failed: {e}')
    return subscribed


def install_notify_printer(bus):
    """Print every PropertiesChanged on any GattCharacteristic1.Value so we
    see live key events from the remote with timestamps and payloads."""

    def on_changed(iface, changed, invalidated, path=None):
        if iface != GATT_CHRC_IFACE or 'Value' not in changed:
            return
        value = changed['Value']
        try:
            uuid_prop = dbus.Interface(bus.get_object(BLUEZ, path),
                                       DBUS_PROP_IFACE)
            uuid = str(uuid_prop.Get(GATT_CHRC_IFACE, 'UUID'))
        except Exception:
            uuid = '?'
        print(f'[{ts()}] NOTIFY {uuid} ({path.rsplit("/", 1)[-1]})   '
              f'[{fmt_hex(value)}]')

    bus.add_signal_receiver(
        on_changed, dbus_interface=DBUS_PROP_IFACE,
        signal_name='PropertiesChanged', arg0=GATT_CHRC_IFACE,
        path_keyword='path')


def ensure_device_known(bus, adapter_path, device_path, scan_secs=20):
    """If the Device1 object doesn't exist (e.g. after `bluetoothctl remove`
    or a never-paired target), start a brief LE discovery so BlueZ
    populates the object. Blocks until the object appears or the timeout
    fires. Raises on timeout."""
    om = dbus.Interface(bus.get_object(BLUEZ, '/'), DBUS_OM_IFACE)
    if device_path in om.GetManagedObjects():
        return
    adapter = dbus.Interface(bus.get_object(BLUEZ, adapter_path), ADAPTER_IFACE)
    try:
        adapter.SetDiscoveryFilter({'Transport': dbus.String('le')})
    except Exception:
        pass
    try:
        adapter.StartDiscovery()
    except dbus.DBusException as e:
        # "InProgress" is fine — another scan is already running.
        if 'InProgress' not in str(e):
            raise
    print(f'[{ts()}] scanning up to {scan_secs}s for {device_path}…')
    deadline = time.time() + scan_secs
    while time.time() < deadline:
        if device_path in om.GetManagedObjects():
            break
        time.sleep(0.5)
    try:
        adapter.StopDiscovery()
    except Exception:
        pass
    if device_path not in om.GetManagedObjects():
        raise RuntimeError(
            f'{device_path} not discovered within {scan_secs}s — is the '
            f'remote powered and in pair-new-remote mode?')


def pair_connect_listen(bus, adapter_path, mac, pair_timeout, listen_for):
    device_path = device_path_for(adapter_path, mac)
    ensure_device_known(bus, adapter_path, device_path)
    dev = dbus.Interface(bus.get_object(BLUEZ, device_path), DEVICE_IFACE)
    props = dbus.Interface(bus.get_object(BLUEZ, device_path),
                           DBUS_PROP_IFACE)

    print(f'[{ts()}] device {mac} -> {device_path}')

    # Ensure we're about to pair over LE, not BR/EDR. When the device was
    # only seen during an LE scan, AddressType should already be "public"
    # or "random"; if BlueZ is confused and Device1.Pair() tries Page
    # (BR/EDR) it returns "Page Timeout". Going via Connect() first on the
    # LE-filtered device forces LE transport and triggers SMP automatically
    # if the peer demands pairing.
    print(f'[{ts()}] connecting over LE (up to {pair_timeout}s)…')
    try:
        dev.Connect()
    except dbus.DBusException as e:
        msg = str(e)
        if 'AlreadyConnected' not in msg:
            print(f'[{ts()}] Connect() failed: {e}')
            return
    if not wait_for_prop(bus, device_path, DEVICE_IFACE, 'Connected',
                         True, pair_timeout):
        print(f'[{ts()}] Connected did not go true within timeout')
        return

    try:
        already_paired = bool(props.Get(DEVICE_IFACE, 'Paired'))
    except Exception:
        already_paired = False
    if not already_paired:
        # SMP usually runs as part of Connect() on LE peers that advertise
        # with pairing required, so Paired flips to true a moment after
        # Connected without us calling Pair(). If it hasn't, nudge it.
        try:
            dev.Pair()
        except dbus.DBusException as e:
            if 'AlreadyExists' not in str(e):
                print(f'[{ts()}] Pair() nudge failed (continuing): {e}')
        if not wait_for_prop(bus, device_path, DEVICE_IFACE, 'Paired',
                             True, pair_timeout):
            print(f'[{ts()}] pairing did not complete within timeout')
            return
    print(f'[{ts()}] paired')

    try:
        props.Set(DEVICE_IFACE, 'Trusted', dbus.Boolean(True))
    except Exception:
        pass

    if not wait_for_prop(bus, device_path, DEVICE_IFACE, 'ServicesResolved',
                         True, pair_timeout):
        print(f'[{ts()}] ServicesResolved did not go true; aborting')
        return
    print(f'[{ts()}] connected + services resolved')

    subscribed = enumerate_and_subscribe(bus, adapter_path, device_path)
    install_notify_printer(bus)

    print(f'\n[{ts()}] ---- listening for key events for {listen_for}s ----')
    print(f'[{ts()}] press buttons on the remote; each press prints '
          f'a NOTIFY line')

    mainloop = GLib.MainLoop()

    def stop(*_):
        mainloop.quit()
        return False

    GLib.timeout_add_seconds(listen_for, stop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop)

    try:
        mainloop.run()
    finally:
        print(f'\n[{ts()}] stopping subscriptions…')
        for _uuid, chrc_path in subscribed:
            try:
                dbus.Interface(bus.get_object(BLUEZ, chrc_path),
                               GATT_CHRC_IFACE).StopNotify()
            except Exception:
                pass


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--adapter', default='hci0',
                   help='BlueZ adapter (default: hci0). Use a free one — if '
                        'hid-remote.service owns hci0 you must stop it first, '
                        'or use a second USB dongle.')
    p.add_argument('--mac',
                   help='Target remote MAC. If omitted, --scan prints '
                        'discovered devices and exits.')
    p.add_argument('--scan', action='store_true',
                   help='Scan for LE devices and exit (does not pair).')
    p.add_argument('--scan-timeout', type=int, default=30,
                   help='Seconds to scan when --scan given (default: 30).')
    p.add_argument('--pair-timeout', type=int, default=30,
                   help='Seconds to wait for pairing + service resolution '
                        '(default: 30).')
    p.add_argument('--listen-for', type=int, default=300,
                   help='Seconds to listen for key events after pair '
                        '(default: 300). Ctrl+C to stop early.')
    args = p.parse_args()

    if os.geteuid() != 0:
        print('dump_remote: must run as root (BlueZ mgmt access)',
              file=sys.stderr)
        return 2
    if not args.scan and not args.mac:
        print('dump_remote: provide --mac, or --scan to list devices first',
              file=sys.stderr)
        return 2
    if args.mac and not re.fullmatch(r'[0-9A-Fa-f:]{17}', args.mac):
        print(f'dump_remote: bad MAC {args.mac!r}', file=sys.stderr)
        return 2

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Register agent so Just Works pairing auto-accepts.
    Agent(bus, AGENT_PATH)
    mgr = dbus.Interface(bus.get_object(BLUEZ, '/org/bluez'), AGENT_MGR_IFACE)
    try:
        mgr.RegisterAgent(AGENT_PATH, 'NoInputNoOutput')
        mgr.RequestDefaultAgent(AGENT_PATH)
    except dbus.DBusException as e:
        print(f'dump_remote: RegisterAgent: {e} (continuing; another agent '
              f'may be handling pairing)', file=sys.stderr)

    adapter_path = find_adapter(bus, args.adapter)
    adapter_props = dbus.Interface(bus.get_object(BLUEZ, adapter_path),
                                   DBUS_PROP_IFACE)
    adapter_props.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(True))

    try:
        if args.scan:
            scan_and_list(bus, adapter_path, args.scan_timeout)
            return 0
        pair_connect_listen(bus, adapter_path, args.mac,
                            args.pair_timeout, args.listen_for)
        return 0
    finally:
        try:
            mgr.UnregisterAgent(AGENT_PATH)
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
