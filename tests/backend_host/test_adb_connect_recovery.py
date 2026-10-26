"""ADBUtils.connect_device recovery ladder (BUG-0845): fake adb, no device needed."""
from unittest.mock import patch

from backend_host.src.lib.utils.adb_utils import ADBUtils


class FakeAdb:
    """Plays `adb` from a mutable device table; records every command."""

    def __init__(self, devices, server_up=True, usb_ips=None, on_connect=None, on_tcpip=None):
        self.devices = dict(devices)
        self.server_up = server_up
        self.usb_ips = usb_ips or {}
        self.on_connect = on_connect
        self.on_tcpip = on_tcpip
        self.calls = []

    def __call__(self, command, timeout=None):
        self.calls.append(command)
        args = command.split()[1:]
        if args == ['kill-server']:
            return True, '', '', 0
        if args == ['start-server']:
            self.server_up = True
            return True, '', '', 0
        if not self.server_up:
            return False, '', 'Command timed out', -1
        if args == ['devices']:
            body = '\n'.join(f"{s}\t{st}" for s, st in self.devices.items())
            return True, f"List of devices attached\n{body}\n", '', 0
        if args[0] == 'connect' and self.on_connect:
            self.on_connect(self, args[1])
        if args[0] == 'disconnect':
            self.devices.pop(args[1], None)
        if args[0] == '-s' and args[2] == 'shell':
            ip = self.usb_ips.get(args[1])
            return True, (f"3: wlan0    inet {ip}/24 brd x" if ip else ''), '', 0
        if args[0] == '-s' and args[2] == 'tcpip' and self.on_tcpip:
            self.on_tcpip(self)
        return True, '', '', 0


def run(fake, device_id):
    adb = ADBUtils()
    with patch.object(adb, 'execute_command', side_effect=fake), patch('time.sleep'):
        return adb.connect_device(device_id)


def test_tcp_device_missing_is_reconnected():
    fake = FakeAdb({}, on_connect=lambda f, t: f.devices.update({t: 'device'}))
    assert run(fake, '192.168.1.29:5555')
    assert 'adb connect 192.168.1.29:5555' in fake.calls
    assert 'adb kill-server' not in fake.calls


def test_phone_on_usb_is_switched_to_tcpip():
    state = {'tcpip': False}

    def on_connect(f, target):
        if state['tcpip']:
            f.devices[target] = 'device'

    def on_tcpip(f):
        state['tcpip'] = True

    fake = FakeAdb({'R58M12': 'device'}, usb_ips={'R58M12': '192.168.1.29'},
                   on_connect=on_connect, on_tcpip=on_tcpip)
    assert run(fake, '192.168.1.29:5555')
    assert 'adb -s R58M12 tcpip 5555' in fake.calls


def test_other_usb_phone_is_not_switched():
    fake = FakeAdb({'OTHER': 'device'}, usb_ips={'OTHER': '192.168.1.50'})
    assert not run(fake, '192.168.1.29:5555')
    assert not any('tcpip' in c for c in fake.calls)


def test_offline_tcp_device_is_disconnected_then_connected():
    fake = FakeAdb({'192.168.1.29:5555': 'offline'},
                   on_connect=lambda f, t: f.devices.update({t: 'device'}))
    assert run(fake, '192.168.1.29:5555')
    assert fake.calls.index('adb disconnect 192.168.1.29:5555') < fake.calls.index('adb connect 192.168.1.29:5555')


def test_server_restarted_only_when_it_does_not_answer():
    fake = FakeAdb({'R58M12': 'device'}, server_up=False)
    assert run(fake, 'R58M12')
    assert 'adb kill-server' in fake.calls

    fake = FakeAdb({})
    assert not run(fake, 'R58M12')
    assert 'adb kill-server' not in fake.calls
