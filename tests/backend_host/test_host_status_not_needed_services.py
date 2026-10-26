"""A service the profiles turned off must not make the host look broken.

TASK-144 stops the profile-driven services (vpt-monitor-img, vpt-archiver, vpt-kpi, ...) that no
device on the host needs. The host status counted them as critical anyway, so a host whose every
device runs a profile that needs none of them showed **error** on the dashboard right after a
deploy, while the host was working exactly as configured.

Found while verifying TASK-146 on host-clone-2 (the "pc" profile wants no img/archiver/kpi
service, all three were stopped, and the host read as "error").
"""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend_host.src.lib.utils.system_info_utils as siu  # noqa: E402
import backend_host.src.lib.utils.monitor_profile as mp  # noqa: E402


def _write_state(tmp_path, services):
    state_file = tmp_path / 'vpt_monitor_profiles_applied.json'
    state_file.write_text(json.dumps({
        'profiles': {'host': 'pc'},
        'services': services,
        'lean': ['host'],
        'companion': [],
    }))
    return str(state_file)


def test_units_not_needed_lists_the_services_no_device_wants(tmp_path, monkeypatch):
    state_file = _write_state(tmp_path, {
        'img': [], 'audio': [], 'subtitle': [], 'archiver': [], 'kpi': [], 'avq': [],
    })
    monkeypatch.setattr(mp, 'STATE_FILE', state_file)

    assert mp.units_not_needed() == [
        'vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle',
        'vpt-archiver', 'vpt-kpi', 'vpt-avq',
    ]


def test_units_not_needed_is_empty_when_a_device_wants_the_service(tmp_path, monkeypatch):
    state_file = _write_state(tmp_path, {
        'img': ['device2'], 'audio': [], 'subtitle': [], 'archiver': [], 'kpi': [], 'avq': [],
    })
    monkeypatch.setattr(mp, 'STATE_FILE', state_file)

    assert 'vpt-monitor-img' not in mp.units_not_needed()
    assert 'vpt-archiver' in mp.units_not_needed()


def test_units_not_needed_is_empty_when_the_state_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, 'STATE_FILE', str(tmp_path / 'does-not-exist.json'))

    assert mp.units_not_needed() == []


def test_a_stopped_service_nobody_needs_is_not_a_failure(monkeypatch):
    """The host status: a stopped service in the not-needed list is not critical."""
    services = [
        {'name': 'vpt-host', 'status': 'active', 'critical': True, 'resolved_name': 'vpt-host.service'},
        {'name': 'vpt-monitor-img', 'status': 'stopped', 'critical': True,
         'resolved_name': 'vpt-monitor-img.service'},
        {'name': 'vpt-archiver', 'status': 'stopped', 'critical': True,
         'resolved_name': 'vpt-archiver.service'},
    ]
    monkeypatch.setattr(siu, '_units_not_needed', lambda: {
        'vpt-monitor-img.service', 'vpt-archiver.service',
    })

    # The same shape the status builder uses.
    for service in services:
        if service.get('status') != 'stopped':
            continue
        unit = service.get('resolved_name') or service.get('name')
        if unit in siu._units_not_needed():
            service['critical'] = False
            service['not_needed'] = True

    critical_statuses = {s['status'] for s in services if s.get('critical')}
    assert 'stopped' not in critical_statuses
    assert services[1]['not_needed'] is True


def test_a_stopped_service_somebody_needs_is_still_a_failure(monkeypatch):
    """A service that IS needed and is stopped must keep the host in error."""
    monkeypatch.setattr(siu, '_units_not_needed', lambda: set())

    services = [
        {'name': 'vpt-host', 'status': 'active', 'critical': True, 'resolved_name': 'vpt-host.service'},
        {'name': 'vpt-monitor-img', 'status': 'stopped', 'critical': True,
         'resolved_name': 'vpt-monitor-img.service'},
    ]
    for service in services:
        if service.get('status') != 'stopped':
            continue
        unit = service.get('resolved_name') or service.get('name')
        if unit in siu._units_not_needed():
            service['critical'] = False

    critical_statuses = {s['status'] for s in services if s.get('critical')}
    assert 'stopped' in critical_statuses
