import os

from backend_host.scripts.monitor.profiles import load_profile
from shared.src.lib.utils.monitor_profile import (device_captions, profile_captions, profile_services,
                                                  validate_manifest_light)


def test_manifest_loads_in_both_validators():
    p = load_profile('caption_playback')
    assert p.captions.delay_s == 150 and p.captions.whisper_model == 'tiny'
    assert profile_services('caption_playback') == {**profile_services('tv_app'), 'archiver': True}
    assert profile_services('caption_playback')['subtitle'] and profile_services('caption_playback')['audio']


def test_tv_app_has_no_captions():
    assert profile_captions('tv_app') is None
    assert device_captions(1, {}) is None


def test_device_override_and_language():
    env = {'DEVICE3_MONITOR_PROFILE': 'caption_playback'}
    assert device_captions(3, env)['delay_s'] == 150
    assert device_captions(4, env) is None                          # only the device that selected the profile
    assert device_captions(3, {**env, 'DEVICE3_CAPTION_LANGUAGE': 'de'})['language'] == 'de'
    assert device_captions(3, {**env, 'MONITOR_PROFILE': 'tv_app', 'DEVICE3_CAPTION_LANGUAGE': 'auto'})['language'] is None


def test_captions_validation():
    base = {'name': 'x', 'services': {'audio': True}, 'img': {'analyzers': [{'type': 'tv_app'}]}}
    validate_manifest_light({**base, 'captions': {'delay_s': 150}}, 'x')
    for bad in ({'delay_s': 30}, {'whisper_model': 'huge'}, {'language': 'German'}, {'foo': 1}):
        try:
            validate_manifest_light({**base, 'captions': bad}, 'x')
        except ValueError:
            continue
        raise AssertionError(bad)
    try:
        validate_manifest_light({**base, 'services': {}, 'captions': {}}, 'x')
    except ValueError:
        return
    raise AssertionError('captions without audio')
