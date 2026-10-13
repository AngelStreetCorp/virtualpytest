"""WOLPowerController: magic packet bytes, SSH shutdown argv, and the factory
picking the wol transport only when DEVICE{i}_POWER_MAC is set (a Tapo device
on the same model must not be clobbered)."""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.src.controllers.power.wol_power import WOLPowerController, build_magic_packet
from backend_host.src.controllers.controller_config_factory import create_controller_configs_from_device_info


def test_magic_packet_layout():
    packet = build_magic_packet('AA:BB:CC:DD:EE:FF')
    assert len(packet) == 102
    assert packet[:6] == b'\xff' * 6
    assert packet[6:] == bytes.fromhex('AABBCCDDEEFF') * 16


def test_magic_packet_accepts_dash_separators():
    assert build_magic_packet('aa-bb-cc-dd-ee-ff') == build_magic_packet('AA:BB:CC:DD:EE:FF')


def test_invalid_mac_rejected():
    with pytest.raises(ValueError):
        WOLPowerController(mac='AA:BB:CC', device_ip='192.168.1.70')


def test_power_on_broadcasts_packet(monkeypatch):
    sent = []

    class FakeSocket:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def setsockopt(self, *a):
            pass

        def sendto(self, data, addr):
            sent.append((data, addr))

    monkeypatch.setattr('backend_host.src.controllers.power.wol_power.socket.socket', FakeSocket)
    ctrl = WOLPowerController(mac='AA:BB:CC:DD:EE:FF', device_ip='192.168.1.70', broadcast='192.168.1.255')
    assert ctrl.execute_command('power_on') == {'success': True}
    assert sent == [(build_magic_packet('AA:BB:CC:DD:EE:FF'), ('192.168.1.255', 9))]


def test_power_off_runs_ssh_shutdown(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ''
        stderr = ''

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result()

    monkeypatch.setattr('backend_host.src.controllers.power.wol_power.subprocess.run', fake_run)
    ctrl = WOLPowerController(mac='AA:BB:CC:DD:EE:FF', device_ip='192.168.1.70', ssh_user='pcuser', ssh_port='2222')
    assert ctrl.power_off() is True
    argv = calls[0]
    assert argv[0] == 'ssh'
    assert 'BatchMode=yes' in argv
    assert argv[argv.index('-p') + 1] == '2222'
    assert argv[-6:] == ['pcuser@192.168.1.70', 'shutdown', '/s', '/t', '0', '/f']


def test_power_off_without_ssh_user_fails(monkeypatch):
    monkeypatch.setattr('backend_host.src.controllers.power.wol_power.subprocess.run',
                        lambda *a, **k: pytest.fail('ssh must not run without a user'))
    ctrl = WOLPowerController(mac='AA:BB:CC:DD:EE:FF', device_ip='192.168.1.70')
    assert ctrl.power_off() is False


def _device(**extra):
    return {'device_model': 'stb', 'device_name': 'pc', **extra}


def test_factory_selects_wol_when_mac_set():
    configs = create_controller_configs_from_device_info(_device(
        power_mac='AA:BB:CC:DD:EE:FF', power_ip='192.168.1.70', power_ssh_user='pcuser'))
    assert configs['power']['implementation'] == 'wol'
    assert configs['power']['params'] == {
        'mac': 'AA:BB:CC:DD:EE:FF', 'device_ip': '192.168.1.70', 'ssh_user': 'pcuser',
        'ssh_port': 22, 'broadcast': '255.255.255.255',
    }


def test_factory_keeps_tapo_when_no_mac():
    configs = create_controller_configs_from_device_info(_device(
        power_name='tapo_tv', power_ip='192.168.1.50', power_email='a@b.c', power_pwd='x'))
    assert configs['power']['implementation'] == 'tapo'
