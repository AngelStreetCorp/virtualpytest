from backend_host.src.controllers.controller_config_factory import (
    create_controller_configs_from_device_info,
)
from backend_host.src.controllers.controller_manager import _create_controller_instance
from backend_host.src.controllers.switch.bluetooth_procon import BluetoothProconSwitchController
from shared.src.lib.models.device import Device


def _device_config():
    return {
        'device_id': 'device5',
        'device_name': 'switch1',
        'device_model': 'nintendo_switch',
        'video': '/dev/video8',
        'video_stream_path': '/host/stream/capture_switch1',
        'video_capture_path': '/var/www/html/stream/capture_switch1',
    }


def _controller():
    switch_config = create_controller_configs_from_device_info(_device_config())['switch']
    return _create_controller_instance(
        switch_config['type'], switch_config['implementation'], switch_config['params'])


def test_nintendo_switch_factory_creates_bluetooth_procon_controller():
    assert isinstance(_controller(), BluetoothProconSwitchController)


def test_nintendo_switch_capability_is_serialized():
    device = Device('device5', 'switch1', 'nintendo_switch')
    device.add_controller('switch', _controller())

    assert device.to_dict()['device_capabilities']['switch'] == 'bluetooth_procon'


def test_daemon_down_is_reported():
    controller = BluetoothProconSwitchController(device_id='device5', daemon_url='http://127.0.0.1:9')

    result = controller.send_command('press:a')

    assert result['success'] is False
    assert 'vpt-procon' in result['error']
    assert controller.get_status()['state'] == 'daemon_down'


def test_commands_map_to_daemon_calls(monkeypatch):
    controller = BluetoothProconSwitchController(device_id='device5')
    calls = []
    monkeypatch.setattr(controller, '_call',
                        lambda method, path, body=None, timeout=30: calls.append((path, body)) or {'success': True})

    controller.send_command('press:a')
    controller.send_command('sequence:[down, down, a]')
    controller.send_command('stick:left,up')
    controller.send_command('stick:right,left,500')
    controller.send_command('pair')

    assert calls == [
        ('/press', {'button': 'a', 'hold_ms': 100}),
        ('/sequence', {'buttons': ['down', 'down', 'a'], 'hold_ms': 100, 'gap_ms': 150}),
        ('/stick', {'stick': 'left', 'direction': 'up', 'duration_ms': 200}),
        ('/stick', {'stick': 'right', 'direction': 'left', 'duration_ms': 500}),
        ('/pair', {}),
    ]


def test_unknown_command_is_rejected():
    assert BluetoothProconSwitchController(device_id='device5').send_command('dance')['success'] is False


def test_remote_daemon_url_and_token_come_from_device_config(monkeypatch):
    config = dict(_device_config(), switch_procon_url='http://192.168.1.103:6190',
                  switch_procon_token='secret')
    switch_config = create_controller_configs_from_device_info(config)['switch']
    controller = _create_controller_instance(
        switch_config['type'], switch_config['implementation'], switch_config['params'])
    seen = {}

    class _Resp:
        def json(self):
            return {'success': True}

    def _request(method, url, json=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return _Resp()

    monkeypatch.setattr('backend_host.src.controllers.switch.bluetooth_procon.requests.request', _request)
    controller.send_command('press:a')

    assert seen == {'url': 'http://192.168.1.103:6190/press', 'headers': {'X-Procon-Token': 'secret'}}
