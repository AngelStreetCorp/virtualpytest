#!/usr/bin/env python3
"""BlueZ pairing agent — KeyboardDisplay capability.

Registers as the system default agent so bluetoothd routes pairing
requests to it. Auto-confirms pairing while the adapter has NO bond
(the start.sh pairing window). Once an adapter holds a bond, only that
bonded address may pair again; every other device is rejected
(BLUETOOTH.md §6.7.30 — host1 2026-09-02: a foreign central
paired Just-Works onto hci2 next to the STB's bond and held the link, so
the STB could never reconnect = "lost pairing"). Set HID_AGENT_ALLOW_ANY=1
to restore accept-all for a debugging session.
"""
import os
import sys
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BUS_NAME = 'org.bluez'
AGENT_PATH = '/test/agent'
CAPABILITY = 'NoInputNoOutput'

bus = None


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


ALLOW_ANY = os.environ.get('HID_AGENT_ALLOW_ANY') == '1'


def _pairing_allowed(device_path):
    """§6.7.30 gate. True if `device_path` may pair on its adapter:
    - the adapter holds no bond yet (start.sh pairing window), or
    - the requesting device IS the bonded one (STB re-pairing its own bond).
    False (reject) when the adapter already has a bond for another address.
    Any D-Bus failure fails OPEN with a log line, so a bluetoothd hiccup
    can never turn into an un-pairable host."""
    if ALLOW_ANY:
        return True
    try:
        device_path = str(device_path)
        adapter_path = device_path.rsplit('/', 1)[0]
        om = dbus.Interface(bus.get_object(BUS_NAME, '/'),
                            'org.freedesktop.DBus.ObjectManager')
        others = []
        for path, ifaces in om.GetManagedObjects().items():
            dev = ifaces.get('org.bluez.Device1')
            if not dev or not str(path).startswith(adapter_path + '/'):
                continue
            if not dev.get('Bonded', False):
                continue
            if str(path) == device_path:
                return True          # the bonded STB itself
            others.append(str(dev.get('Address', path)))
        if others:
            print(f'Agent: REJECT {device_path} — {adapter_path} already bonded to '
                  f'{others} (§6.7.30); run start.sh to pair a different device')
            sys.stdout.flush()
            return False
        return True
    except Exception as e:
        print(f'Agent: bond check failed ({e}) — allowing pairing')
        return True


class Agent(dbus.service.Object):
    exit_on_release = True

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        print("Agent: Release")
        if self.exit_on_release:
            mainloop.quit()

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"Agent: AuthorizeService {device} {uuid}")
        if not _pairing_allowed(device):
            raise Rejected("adapter already bonded to another device")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"Agent: RequestPinCode {device}")
        if not _pairing_allowed(device):
            raise Rejected("adapter already bonded to another device")
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"Agent: RequestPasskey {device}")
        if not _pairing_allowed(device):
            raise Rejected("adapter already bonded to another device")
        return dbus.UInt32(123456)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"Agent: DisplayPasskey {device} {passkey:06d} entered={entered}")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"Agent: DisplayPinCode {device} {pincode}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        if not _pairing_allowed(device):
            print(f"Agent: RequestConfirmation {device} {passkey:06d} -> REJECT")
            raise Rejected("adapter already bonded to another device")
        print(f"Agent: RequestConfirmation {device} {passkey:06d} -> accept")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        if not _pairing_allowed(device):
            print(f"Agent: RequestAuthorization {device} -> REJECT")
            raise Rejected("adapter already bonded to another device")
        print(f"Agent: RequestAuthorization {device} -> accept")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        print("Agent: Cancel")


def install_bluez_owner_watch(watch_bus):
    """Exit when bluetoothd is replaced so systemd relaunches us.

    RegisterAgent/RequestDefaultAgent die with the bluetoothd instance
    they were made against; a restarted bluetoothd has no default agent
    and pairing silently regresses to reject-all. Same failure family as
    hid_remote.py's GATT registration loss (BLUETOOTH.md §6.7.28). The
    unit has Restart=always, so exiting on the NEW owner appearing is a
    clean re-register; ignore owner loss to avoid crash-looping while
    bluetoothd is still down.
    """
    def on_owner_changed(name, old_owner, new_owner):
        if str(name) != BUS_NAME or not new_owner:
            return
        print(f'org.bluez owner changed ({old_owner or "none"} -> {new_owner}): '
              'agent registration died with the old bluetoothd; exiting for relaunch')
        sys.stdout.flush()
        os._exit(1)

    watch_bus.add_signal_receiver(on_owner_changed,
                                  dbus_interface='org.freedesktop.DBus',
                                  signal_name='NameOwnerChanged',
                                  arg0=BUS_NAME)


def main():
    global bus, mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    install_bluez_owner_watch(bus)

    Agent(bus, AGENT_PATH)

    mgr = dbus.Interface(bus.get_object(BUS_NAME, "/org/bluez"),
                         "org.bluez.AgentManager1")
    mgr.RegisterAgent(AGENT_PATH, CAPABILITY)
    mgr.RequestDefaultAgent(AGENT_PATH)
    print(f"Agent registered ({CAPABILITY}), default agent set.")

    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            mgr.UnregisterAgent(AGENT_PATH)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
