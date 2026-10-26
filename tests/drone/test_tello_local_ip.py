"""DEVICE<i>_TELLO_LOCAL_IP -> TelloRemoteController(local_ip=...).

Two Tellos on one host are both access points at 192.168.10.1, so the drone address alone cannot
say which radio to use. With one USB dongle per drone (scripts/drone/tello_prio.sh) the two links
are separated by SOURCE address: each controller binds its sockets to its own radio's host address
and an `ip rule from <addr>` keeps that traffic on that radio.

The env key has to survive the whole chain - .env -> controller_manager -> _get_remote_params ->
TelloRemoteController - or the second drone silently reuses the first one's link. `local_ip`
itself is exercised against the simulator in test_tello_controller.py; these tests pin the
plumbing, including the single-drone case that must keep the wildcard.
"""

import pytest

from backend_host.src.controllers.controller_config_factory import _get_remote_params


def _cfg(**kw):
    base = {'device_id': 'device3', 'device_name': 'Tello-1'}
    base.update(kw)
    return base


def test_local_ip_passes_through_when_set():
    params = _get_remote_params('tello', _cfg(tello_ip='192.168.10.1',
                                              tello_state_port='8890',
                                              tello_video_port='11111',
                                              tello_local_ip='192.168.10.2'))
    assert params['local_ip'] == '192.168.10.2'
    assert params['tello_ip'] == '192.168.10.1'


def test_local_ip_defaults_to_wildcard_for_a_single_drone():
    """No TELLO_LOCAL_IP must stay 0.0.0.0 - the verified single-drone setup binds the wildcard."""
    params = _get_remote_params('tello', _cfg(tello_ip='192.168.10.1'))
    assert params['local_ip'] == '0.0.0.0'


def test_local_ip_defaults_to_wildcard_when_empty_string():
    """An empty key in .env (present but blank) must not become an empty bind address."""
    params = _get_remote_params('tello', _cfg(tello_ip='192.168.10.1', tello_local_ip=''))
    assert params['local_ip'] == '0.0.0.0'


def test_two_drones_get_distinct_local_ips():
    """The whole point: two drones, one address each. Same source IP = both on one radio."""
    one = _get_remote_params('tello', _cfg(device_id='device3',
                                          tello_ip='192.168.10.1',
                                          tello_local_ip='192.168.10.2'))
    two = _get_remote_params('tello', _cfg(device_id='device4',
                                          tello_ip='192.168.10.1',
                                          tello_local_ip='192.168.10.4'))
    assert one['local_ip'] != two['local_ip']
    # Same drone address and same stock ports on both: only the source tells them apart.
    assert one['tello_ip'] == two['tello_ip'] == '192.168.10.1'
    assert one['state_port'] == two['state_port'] == 8890
    assert one['video_port'] == two['video_port'] == 11111


def test_controller_accepts_the_plumbed_local_ip():
    """The key must match the constructor kwarg name, not just exist in the dict."""
    from backend_host.src.controllers.remote.tello import TelloRemoteController
    import inspect
    assert 'local_ip' in inspect.signature(TelloRemoteController.__init__).parameters