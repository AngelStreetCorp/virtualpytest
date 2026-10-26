"""A profile's incidents become alerts through the incident manager (TASK-90 item A): fake DB, fake R2, no network."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import incident_manager as im  # noqa: E402


class Fake:
    def __init__(self):
        self.created, self.resolved, self.uploads = [], [], []

    def create(self, **kw):
        self.created.append(kw)
        return {'success': True, 'alert_id': f'a{len(self.created)}'}

    def resolve(self, alert_id, closure_metadata=None):
        self.resolved.append(alert_id)
        return {'success': True}

    def upload(self, path, device_id, time_key, incident_type, stage='start'):
        self.uploads.append((path, incident_type, stage))
        return {'thumbnail_url': 'https://r2.example/alert.jpg', 'thumbnail_r2_path': 'alerts/x.jpg', 'time_key': time_key, 'stage': stage}


def make(monkeypatch, tmp_path, profile='ad_meter', declared=('ads_overload',)):
    fake = Fake()
    clock = [1_000_000.0]
    monkeypatch.setattr(im, 'get_device_info_from_capture_folder',
                        lambda f: {'device_id': 'device1', 'device_name': 'Device 1', 'capture_path': f})
    monkeypatch.setattr(im, 'create_alert_safe', fake.create)
    monkeypatch.setattr(im, 'resolve_alert', fake.resolve)
    monkeypatch.setattr(im.time, 'time', lambda: clock[0])
    monkeypatch.setattr('shared.src.lib.utils.storage_path_utils.copy_to_cold_storage', lambda p: p)
    m = im.IncidentManager(skip_startup_cleanup=True)
    monkeypatch.setattr(m, 'upload_incident_frame_to_r2', fake.upload)
    m.set_profile('device1', profile, declared)
    frame = tmp_path / 'capture_000000001.jpg'
    frame.write_bytes(b'jpg')
    return m, fake, clock, str(frame)


def detection(frame, active, value=40.0, name='ads_overload'):
    return {'incidents': {name: {'active': active, 'value': value}}, 'last_3_filenames': [frame]}


def test_a_profile_incident_is_pending_then_created_with_its_profile_and_frame(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path)
    assert m.process_detection('capture1', detection(frame, True), 'host') == {'ads_overload': 'first_detected'}
    assert not fake.created                                             # 30 s of continuous detection first
    clock[0] += 31
    m.process_detection('capture1', detection(frame, True), 'host')
    assert len(fake.created) == 1
    a = fake.created[0]
    assert a['incident_type'] == 'ads_overload' and a['profile'] == 'ad_meter' and a['device_id'] == 'device1'
    assert fake.uploads == [(frame, 'ads_overload', 'start')]           # an alert never goes out without its frame
    assert a['metadata']['incidents']['ads_overload']['value'] == 40.0  # the value that tripped it is in the alert
    assert m.get_device_state('device1')['active_incidents'] == {'ads_overload': 'a1'}


def test_it_is_resolved_when_the_profile_says_it_cleared(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path)
    m.process_detection('capture1', detection(frame, True), 'host')
    clock[0] += 31
    m.process_detection('capture1', detection(frame, True), 'host')
    clock[0] += 5
    t = m.process_detection('capture1', detection(frame, False, 10.0), 'host')
    assert t == {'ads_overload': 'cleared'} and fake.resolved == ['a1']
    assert m.get_device_state('device1')['active_incidents'] == {}


def test_a_short_blip_never_reaches_the_database(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path)
    m.process_detection('capture1', detection(frame, True), 'host')
    clock[0] += 10
    assert m.process_detection('capture1', detection(frame, False), 'host') == {'ads_overload': 'cleared'}
    assert not fake.created and not fake.resolved


def test_an_incident_the_manifest_does_not_declare_is_ignored(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path)
    assert m.process_detection('capture1', detection(frame, True, name='made_up'), 'host') == {}
    clock[0] += 60
    m.process_detection('capture1', detection(frame, True, name='made_up'), 'host')
    assert not fake.created


def test_tv_app_ignores_an_incidents_key(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path, profile='tv_app', declared=sorted(im.TV_INCIDENT_TYPES))
    assert m.process_detection('capture1', detection(frame, True), 'host') == {}
    assert not fake.created


def test_the_sampled_analyzer_hands_the_manager_its_incident_state_and_the_current_frame():
    sys.path.insert(0, os.path.join(ROOT, 'tests', 'backend_host'))
    from monitor.analyzers.sampled import SampledWorkerAnalyzer
    from monitor.context import FrameContext
    from monitor.profiles import load_profile

    a = SampledWorkerAnalyzer(None, load_profile('ad_meter'), 2.0)
    ctx = FrameContext(capture_folder='capture1', device_index=1, sequence=1, timestamp=1.0, frame_path='/x/capture_1.jpg', thumbnail=None,
                       device_state={}, profile=None)
    assert a.analyze(ctx) == {}                                          # no sample yet
    a._latest['capture1'] = {'incidents': {'ads_overload': {'active': True, 'value': 41.0}}}
    assert a.analyze(ctx) == {'incidents': {'ads_overload': {'active': True, 'value': 41.0}}, 'last_3_filenames': ['/x/capture_1.jpg']}


# ---- no_signal is a first-class TV incident type (BUG-0504, ported in the TASK-90 merge) ---------------------------------

def test_a_no_signal_incident_is_created_with_its_start_frame_and_outranks_freeze(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path, profile='tv_app', declared=sorted(im.TV_INCIDENT_TYPES))
    assert 'no_signal' in im.TV_INCIDENT_TYPES and 'no_signal' in im.VISUAL_INCIDENT_TYPES
    state = m.get_device_state('device1')
    state['no_signal_start_thumbnail_cold'] = frame          # what the tv_app analyzer copies to cold when a no_signal event starts
    det = {'no_signal': True, 'blackscreen': False, 'freeze': False, 'macroblocks': False, 'last_3_filenames': [frame]}   # the analyzer has already put freeze and macroblocks down
    assert m.process_detection('capture1', dict(det), 'host') == {'no_signal': 'first_detected'}
    clock[0] += 31
    m.process_detection('capture1', dict(det), 'host')
    assert [c['incident_type'] for c in fake.created] == ['no_signal']
    assert fake.uploads == [(frame, 'no_signal', 'start')]                  # the alert has its frame: it used to find none and never be created
    assert m.get_device_state('device1')['active_incidents'] == {'no_signal': 'a1'}
    clock[0] += 5
    t = m.process_detection('capture1', {'no_signal': False, 'blackscreen': False, 'freeze': False}, 'host')
    assert t.get('no_signal') == 'cleared' and fake.resolved == ['a1']


def test_no_signal_clears_a_freeze_that_is_already_an_alert(monkeypatch, tmp_path):
    m, fake, clock, frame = make(monkeypatch, tmp_path, profile='tv_app', declared=sorted(im.TV_INCIDENT_TYPES))
    state = m.get_device_state('device1')
    state['freeze_start_thumbnail_cold'] = frame
    freeze = {'freeze': True, 'last_3_filenames': [frame], 'last_3_thumbnails': [frame]}
    m.process_detection('capture1', dict(freeze), 'host')
    clock[0] += 31
    monkeypatch.setattr(m, 'upload_freeze_frames_to_r2', lambda *a, **k: {'thumbnail_urls': ['https://r2.example/f.jpg']})
    m.process_detection('capture1', dict(freeze), 'host')
    assert [c['incident_type'] for c in fake.created] == ['freeze']
    t = m.process_detection('capture1', {'no_signal': True, 'freeze': False, 'last_3_filenames': [frame]}, 'host')
    assert t.get('freeze') == 'cleared_by_no_signal' and 'a1' in fake.resolved


# ---- review 2: a CHECK violation is quiet, keeps the incident pending and retries rarely --------------------------------------

CHECK_ERROR = 'new row for relation "alerts" violates check constraint "alerts_incident_type_check"'


def test_a_check_violation_is_logged_once_keeps_the_incident_pending_and_retries_hourly(monkeypatch, tmp_path, caplog):
    import logging
    m, fake, clock, frame = make(monkeypatch, tmp_path, profile='tv_app', declared=sorted(im.TV_INCIDENT_TYPES))
    attempts = []
    accept = [False]

    def create(**kw):
        attempts.append(kw['incident_type'])
        return fake.create(**kw) if accept[0] else {'success': False, 'error': CHECK_ERROR}
    monkeypatch.setattr(im, 'create_alert_safe', create)
    m.get_device_state('device1')['no_signal_start_thumbnail_cold'] = frame
    det = {'no_signal': True, 'blackscreen': False, 'freeze': False, 'last_3_filenames': [frame]}
    with caplog.at_level(logging.DEBUG, logger='capture_monitor'):
        for _ in range(60):                                                  # 10 minutes of detections, one every 10 s
            m.process_detection('capture1', dict(det), 'host')
            clock[0] += 10
        warned = [r for r in caplog.records if r.levelno == logging.WARNING and 'refuses' in r.getMessage()]
        assert attempts == ['no_signal'] and len(warned) == 1                # one attempt, one warning, not one a minute
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR] # and nothing at error level
        assert len(fake.uploads) == 1                                        # the frame was uploaded once, not at every retry
        assert 'no_signal' in m.get_device_state('device1')['pending_incidents'] and not fake.created   # still pending
        assert '20261013b' in warned[0].getMessage() and '20261013c' in warned[0].getMessage()         # it says what to apply
        clock[0] += 3600
        m.process_detection('capture1', dict(det), 'host')
        assert attempts == ['no_signal', 'no_signal'] and len([r for r in caplog.records if r.levelno == logging.WARNING and 'refuses' in r.getMessage()]) == 1
        accept[0] = True                                                     # the migration was applied meanwhile
        clock[0] += 3600
        m.process_detection('capture1', dict(det), 'host')
        assert [c['incident_type'] for c in fake.created] == ['no_signal'] and len(fake.uploads) == 1   # created with the frame uploaded long before
        assert m.get_device_state('device1')['active_incidents'] == {'no_signal': 'a1'}


def test_another_database_error_is_still_an_error_with_the_short_retry(monkeypatch, tmp_path, caplog):
    import logging
    m, fake, clock, frame = make(monkeypatch, tmp_path, profile='tv_app', declared=sorted(im.TV_INCIDENT_TYPES))
    calls = []
    monkeypatch.setattr(im, 'create_alert_safe', lambda **kw: calls.append(1) or {'success': False, 'error': 'connection reset'})
    m.get_device_state('device1')['no_signal_start_thumbnail_cold'] = frame
    det = {'no_signal': True, 'last_3_filenames': [frame]}
    with caplog.at_level(logging.DEBUG, logger='capture_monitor'):
        for _ in range(30):
            m.process_detection('capture1', dict(det), 'host')
            clock[0] += 10
    assert 3 <= len(calls) <= 6                                              # about once a minute, like before
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and 'FAILED' in r.getMessage()]


def test_the_no_signal_migrations_exist_and_are_consistent():
    import re
    base = os.path.join(ROOT, 'setup', 'db', 'migrations')
    up = open(os.path.join(base, '20261013c_alerts_no_signal_check.sql')).read()
    down = open(os.path.join(base, '20261013c_alerts_no_signal_check_rollback.sql')).read()
    types = lambda sql: set(re.findall(r"'(\w+)'::text", sql))
    assert types(up) == {'blackscreen', 'no_signal', 'freeze', 'errors', 'audio_loss', 'macroblocks'}
    assert types(down) == {'blackscreen', 'freeze', 'errors', 'audio_loss', 'macroblocks'} and 'NOT VALID' in down
    assert 'IF EXISTS (SELECT 1 FROM pg_constraint' in up and 'IF EXISTS (SELECT 1 FROM pg_constraint' in down       # a no-op after 20261013b
    rb = open(os.path.join(base, '20261013b_alerts_profile_rollback.sql')).read()
    assert 'no_signal' in types(rb) and '20261013c' in open(os.path.join(base, '20261013b_alerts_profile.sql')).read()
