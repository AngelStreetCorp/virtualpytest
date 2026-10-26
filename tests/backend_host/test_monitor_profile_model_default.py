"""Model default of the monitor profile resolver: host_vnc -> pc, phones -> mobile, an explicit value wins."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402


def test_phones_default_to_mobile_and_tvs_to_tv_app():
    env = {'DEVICE1_MODEL': 'android_mobile', 'DEVICE2_MODEL': 'phone_agent', 'DEVICE3_MODEL': 'cloud_android_mobile',
           'DEVICE4_MODEL': 'stb', 'DEVICE5_MODEL': 'android_tv'}
    assert [mp.resolve_monitor_profile(i, env=env) for i in (1, 2, 3)] == ['mobile'] * 3
    assert [mp.resolve_monitor_profile(i, env=env) for i in (4, 5, 6)] == ['tv_app'] * 3


def test_host_level_device_is_pc_only_with_a_host_vnc_capture():
    assert mp.resolve_monitor_profile(None, env={'HOST_VNC_STREAM_PATH': '/vnc_lite.html'}) == 'pc'
    assert mp.resolve_monitor_profile(None, env={}) == 'tv_app'


def test_an_explicit_value_wins_over_the_model():
    env = {'DEVICE1_MODEL': 'android_mobile', 'DEVICE1_MONITOR_PROFILE': 'tv_app'}
    assert mp.resolve_monitor_profile(1, env=env) == 'tv_app'
    env = {'DEVICE1_MODEL': 'android_mobile', 'MONITOR_PROFILE': 'tv_lite'}
    assert mp.resolve_monitor_profile(1, env=env) == 'tv_lite'


def test_mobile_keeps_the_image_service_and_drops_audio_and_subtitle():
    s = mp.profile_services('mobile')
    assert s['img'] is True and s['audio'] is False and s['subtitle'] is False
