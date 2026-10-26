"""A counting device's overlay shows without a click: the host says which devices draw one."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend_host.src.lib.utils.monitor_profile as mp  # noqa: E402


def test_only_profiles_with_a_ui_block_open_with_the_overlay_on():
    profiles = {'device1': 'tv_lite', 'device2': 'tv_app', 'device3': 'egg_count_yolo_belt_fast', 'device4': 'counting_cars'}
    assert mp.get_overlay_on(profiles) == ['device3', 'device4']


def test_an_unknown_profile_is_not_an_overlay():
    assert mp.get_overlay_on({'device1': 'no_such_profile'}) == []
