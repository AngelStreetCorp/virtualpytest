"""Incident types follow the monitor profile (TASK-90 goal 4)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import incident_manager as im  # noqa: E402


def make(monkeypatch):
    monkeypatch.setattr(im, 'get_device_info_from_capture_folder',
                        lambda f: {'device_id': 'device1', 'device_name': 'Device 1', 'capture_path': f})
    return im.IncidentManager(skip_startup_cleanup=True)


def test_tv_app_declares_the_six_tv_types(monkeypatch):
    m = make(monkeypatch)
    name, allowed = m.profile_of('device1')
    assert name == 'tv_app'
    assert allowed == {'blackscreen', 'no_signal', 'freeze', 'errors', 'audio_loss', 'macroblocks'}   # no_signal: BUG-0504


def test_type_not_declared_by_the_profile_is_refused_before_any_db_call(monkeypatch):
    m = make(monkeypatch)
    m.set_profile('device1', 'counting_cars', [])            # counting raises no alerts
    called = []
    monkeypatch.setattr(im, '_lazy_import_db', lambda: called.append(1))
    assert m.create_incident('capture1', 'blackscreen', 'host') is None
    assert not called


def test_declared_type_passes_the_check(monkeypatch):
    m = make(monkeypatch)
    m.set_profile('device1', 'intrusion', ['intruder'])
    assert 'intruder' in m.profile_of('device1')[1]
    # reaches the DB layer (stubbed to "unavailable"), i.e. the profile check did not stop it
    monkeypatch.setattr(im, '_lazy_import_db', lambda: None)
    monkeypatch.setattr(im, 'create_alert_safe', None)
    assert m.create_incident('capture1', 'intruder', 'host') is None


def test_profiles_are_per_device(monkeypatch):
    m = make(monkeypatch)
    m.set_profile('device2', 'counting_cars', [])
    assert m.profile_of('device1')[0] == 'tv_app'          # untouched device keeps tv_app
    assert m.profile_of('device2') == ('counting_cars', frozenset())
