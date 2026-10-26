"""Host monitor-profile picker backend (TASK-90 follow-up): GET /host/monitor/profiles, /profiles/status,
the apply outcome record, and the guardrails of POST /host/system/config. No systemctl, no real .env."""
import json
import os

import pytest
from flask import Flask

from backend_host.src.lib.utils import monitor_profile as mp
from backend_host.src.routes import host_system_routes as hsr


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A host .env in tmp, state and result files in tmp, no model files."""
    env_file = tmp_path / '.env'
    env_file.write_text('DEVICE1_NAME=a\nDEVICE2_NAME=b\n')
    monkeypatch.setattr(hsr, '_host_env_path', lambda: env_file)
    monkeypatch.setattr(mp, 'STATE_FILE', str(tmp_path / 'applied.json'))
    for k in ('MONITOR_COCO_MODEL', 'MONITOR_EGG_MODEL', 'MONITOR_PROFILE', 'DEVICE1_MONITOR_PROFILE', 'DEVICE2_MONITOR_PROFILE'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mp, 'read_env_files', lambda pattern=None: {k: v for k, v in _parse(env_file).items() if (pattern.match(k) if pattern else True)})
    import shared.src.lib.utils.monitor_profile as smp
    monkeypatch.setattr(smp, 'read_env_files', lambda pattern=smp._PROFILE_KEY: {k: v for k, v in _parse(env_file).items() if pattern.match(k)})
    monkeypatch.setattr(mp, 'resolve_monitor_profile', lambda idx, profiles_dir=None, env=None: smp.resolve_monitor_profile(idx, profiles_dir, env))
    return env_file


def _parse(path):
    out = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            out[k] = v
    return out


@pytest.fixture
def client(env, monkeypatch):
    from backend_host.src.routes.host_monitor_profile_routes import host_monitor_profile_bp
    monkeypatch.setattr(mp, '_is_active', lambda unit: unit != 'vpt-monitor-subtitle')
    app = Flask(__name__)
    app.register_blueprint(host_monitor_profile_bp)
    app.register_blueprint(hsr.host_system_bp)
    app.config['TESTING'] = True
    return app.test_client()


def test_list_has_every_manifest_with_title_services_and_usability(client):
    body = client.get('/host/monitor/profiles').get_json()
    by = {p['name']: p for p in body['profiles']}
    assert set(by) >= {'tv_app', 'counting_cars', 'egg_quality', 'ad_meter'}
    assert by['ad_meter']['title'] == 'Ad meter' and by['ad_meter']['usable'] is True
    monitors = lambda name: {k: v for k, v in by[name]['services'].items() if k in ('img', 'audio', 'subtitle')}   # tv_lite added archiver, kpi and avq
    assert monitors('ad_meter') == {'img': True, 'audio': False, 'subtitle': False}
    assert monitors('tv_app') == {'img': True, 'audio': True, 'subtitle': True}
    assert body['default'] == 'tv_app'
    assert body['units']['subtitle']['active'] is False and body['units']['img']['active'] is True


def test_profile_with_missing_model_is_unusable_with_a_reason(client):
    by = {p['name']: p for p in client.get('/host/monitor/profiles').get_json()['profiles']}
    assert by['counting_cars']['usable'] is False
    assert 'MONITOR_COCO_MODEL' in by['counting_cars']['reason']
    assert by['counting_cars']['models'][0]['present'] is False


def test_profile_becomes_usable_when_the_model_file_exists(client, tmp_path, monkeypatch):
    model = tmp_path / 'yolox.onnx'
    model.write_bytes(b'x')
    monkeypatch.setenv('MONITOR_COCO_MODEL', str(model))
    by = {p['name']: p for p in client.get('/host/monitor/profiles').get_json()['profiles']}
    assert by['counting_cars']['usable'] is True


def test_save_rejects_an_unknown_profile_name(client, env):
    r = client.post('/host/system/config', json={'host': {}, 'devices': {'DEVICE1': {'DEVICE_NAME': 'a', 'DEVICE_MONITOR_PROFILE': 'nope'}}})
    assert r.status_code == 400 and 'nope' in r.get_json()['error']
    assert 'MONITOR_PROFILE' not in env.read_text()


def test_save_rejects_a_host_default_that_is_unknown(client):
    r = client.post('/host/system/config', json={'host': {'MONITOR_PROFILE': '../etc'}, 'devices': {}})
    assert r.status_code == 400


def test_save_rejects_a_profile_whose_model_is_missing(client):
    r = client.post('/host/system/config', json={'host': {}, 'devices': {'DEVICE1': {'DEVICE_MONITOR_PROFILE': 'egg_quality'}}})
    assert r.status_code == 400 and 'model' in r.get_json()['error']


def test_save_writes_a_valid_profile_and_empty_means_default(client, env, monkeypatch):
    started = []
    monkeypatch.setattr(mp, 'start_apply', lambda **kw: started.append(1))
    r = client.post('/host/system/config', json={'host': {}, 'devices': {
        'DEVICE1': {'DEVICE_NAME': 'a', 'DEVICE_MONITOR_PROFILE': 'ad_meter'}, 'DEVICE2': {'DEVICE_NAME': 'b', 'DEVICE_MONITOR_PROFILE': ''}}})
    assert r.status_code == 200 and r.get_json()['monitor_profiles'] == 'applying'
    text = env.read_text()
    assert 'DEVICE1_MONITOR_PROFILE=ad_meter' in text and 'DEVICE2_MONITOR_PROFILE=' in text
    assert started == [1]


def test_an_old_bad_value_does_not_block_saving_other_fields(client, env, monkeypatch):
    env.write_text('DEVICE1_NAME=a\nDEVICE1_MONITOR_PROFILE=counting_cars\n')
    monkeypatch.setattr(mp, 'start_apply', lambda **kw: None)
    r = client.post('/host/system/config', json={'host': {}, 'devices': {'DEVICE1': {'DEVICE_NAME': 'z', 'DEVICE_MONITOR_PROFILE': 'counting_cars'}}})
    assert r.status_code == 200


def _apply(profile_lines, env, active=True):
    env.write_text('DEVICE1_NAME=a\nDEVICE2_NAME=b\n' + profile_lines)
    restarted = []
    out = mp.apply_monitor_profiles(restart=lambda u: restarted.append(u) or True, is_active=lambda u: active if isinstance(active, bool) else active(u))
    return out, restarted


def test_apply_records_what_it_did_and_the_status_route_serves_it(client, env):
    _apply('', env)  # first run: records
    out, restarted = _apply('DEVICE1_MONITOR_PROFILE=ad_meter\n', env, active=lambda u: u != 'vpt-monitor-subtitle')
    assert restarted == ['vpt-monitor-img', 'vpt-monitor-audio']
    assert out['not_running'] == ['vpt-monitor-subtitle']
    body = client.get('/host/monitor/profiles/status').get_json()
    assert body['result']['state'] == 'done'
    assert body['result']['restarted'] == ['vpt-monitor-img', 'vpt-monitor-audio']
    assert body['result']['not_running'] == ['vpt-monitor-subtitle']
    assert body['saved'] == {'device1': 'ad_meter', 'device2': 'tv_app'}
    assert body['mismatch'] == []  # recorded after the restarts succeeded


def test_status_flags_a_device_saved_but_not_yet_applied(client, env):
    _apply('', env)
    env.write_text('DEVICE1_NAME=a\nDEVICE2_NAME=b\nDEVICE1_MONITOR_PROFILE=ad_meter\n')
    body = client.get('/host/monitor/profiles/status').get_json()
    assert body['mismatch'] == ['device1'] and body['applied']['device1'] == 'tv_app'


def test_nothing_changed_restarts_nothing(env):
    _apply('MONITOR_PROFILE=ad_meter\n', env)
    out, restarted = _apply('MONITOR_PROFILE=ad_meter\n', env)
    assert restarted == [] and out['failed'] == []


def test_a_failed_restart_is_reported_and_not_recorded(env):
    _apply('', env)
    env.write_text('DEVICE1_NAME=a\nDEVICE2_NAME=b\nMONITOR_PROFILE=ad_meter\n')
    out = mp.apply_monitor_profiles(restart=lambda u: False, is_active=lambda u: True)
    assert out['failed'] and out['restarted'] == []


def test_unknown_name_in_the_env_is_reported_as_a_fallback(env):
    _apply('', env)
    out, _ = _apply('DEVICE1_MONITOR_PROFILE=ghost\nDEVICE2_MONITOR_PROFILE=egg_quality\n', env)
    by = {f['device']: f for f in out['fallbacks']}
    assert by['device1']['kind'] == 'unknown' and by['device1']['effective'] == 'tv_app'
    assert by['device2']['kind'] == 'model_missing'


def test_start_apply_marks_applying_before_the_thread_runs(env, monkeypatch):
    seen = []
    monkeypatch.setattr(mp.threading, 'Thread', lambda **kw: type('T', (), {'start': lambda self: seen.append(mp.read_apply_result())})())
    mp.start_apply()
    assert seen[0]['state'] == 'applying'


def test_tv_lite_and_drone_have_a_title_a_description_and_the_stream_mode(client):
    by = {p['name']: p for p in client.get('/host/monitor/profiles').get_json()['profiles']}
    assert by['tv_lite']['title'] == 'TV lite' and by['tv_lite']['stream'] == 'lean'
    assert 'monitoring' in by['tv_lite']['description'] and 'vpt-stream' in by['tv_lite']['cost']
    assert by['drone']['description'] and by['tv_app']['stream'] == 'full'
