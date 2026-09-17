"""Device config parsed from DEVICEn_* env (BUG-0096 regression guard).

Runs without a host or server: only the env parser of controller_manager is exercised.
"""
import importlib

import pytest


@pytest.fixture
def parse(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith('DEVICE'):
            monkeypatch.delenv(key, raising=False)
    cm = importlib.import_module('backend_host.src.controllers.controller_manager')
    return cm._get_devices_config_from_environment


@pytest.mark.unit
def test_stream_path_derived_from_capture_folder(monkeypatch, parse):
    monkeypatch.setenv('DEVICE2_NAME', 'Phone slot 1')
    monkeypatch.setenv('DEVICE2_MODEL', 'phone_agent')
    monkeypatch.setenv('DEVICE2_VIDEO', '/var/www/html/stream/phone_frames/device2/latest.jpg')
    monkeypatch.setenv('DEVICE2_VIDEO_CAPTURE_PATH', '/var/www/html/stream/capture2/')

    (cfg,) = parse()
    assert cfg['device_id'] == 'device2'
    assert cfg['device_model'] == 'phone_agent'
    assert cfg['video_stream_path'] == '/host/stream/capture2'


@pytest.mark.unit
def test_explicit_stream_path_wins(monkeypatch, parse):
    monkeypatch.setenv('DEVICE1_NAME', 'STB')
    monkeypatch.setenv('DEVICE1_MODEL', 'stb')
    monkeypatch.setenv('DEVICE1_VIDEO_CAPTURE_PATH', '/var/www/html/stream/capture1')
    monkeypatch.setenv('DEVICE1_VIDEO_STREAM_PATH', '/host/stream/custom')

    (cfg,) = parse()
    assert cfg['video_stream_path'] == '/host/stream/custom'
