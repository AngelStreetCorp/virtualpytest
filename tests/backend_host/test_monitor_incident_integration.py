"""The replay fixture through a REAL IncidentManager (review 2): pending, create, resolve and the frame upload, against a fake alerts database that
enforces a CHECK list on incident_type. The replay gate (test_monitor_replay.py) stops at the detections handed to the incident worker; this goes on.

The fixture has a blackscreen, a freeze, a freeze that no_signal takes over, a no_signal stretch and a near-black blackscreen. The report delay is set to
4 s here (the stretches are 8-20 s) so each of them outlasts it.
"""
import logging
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.backend_host.test_monitor_replay import run_replay  # noqa: E402

CHECK_ERROR = 'new row for relation "alerts" violates check constraint "alerts_incident_type_check"'
MAIN_CHECK = {'blackscreen', 'freeze', 'errors', 'audio_loss', 'macroblocks'}              # main's schema: no no_signal
WITH_NO_SIGNAL = MAIN_CHECK | {'no_signal'}                                                # 20261013c, or no CHECK at all after 20261013b


class FakeAlertsDb:
    def __init__(self, allowed):
        self.allowed = allowed
        self.attempts, self.created, self.resolved = [], [], []

    def create(self, **kw):
        self.attempts.append(kw['incident_type'])
        if self.allowed is not None and kw['incident_type'] not in self.allowed:
            return {'success': False, 'error': CHECK_ERROR}
        self.created.append(kw)
        return {'success': True, 'alert_id': f"a{len(self.created)}"}

    def resolve(self, alert_id, closure_metadata=None):
        self.resolved.append(alert_id)
        return {'success': True}


def replay_through_incident_manager(tmp_path, monkeypatch, allowed):
    import incident_manager as im
    db = FakeAlertsDb(allowed)
    uploads = []

    def configure():
        monkeypatch.setattr(im, 'create_alert_safe', db.create)
        monkeypatch.setattr(im, 'resolve_alert', db.resolve)
        monkeypatch.setattr(im.IncidentManager, 'upload_incident_frame_to_r2',
                            lambda self, path, device, key, itype, stage='start': uploads.append((itype, stage)) or
                            {'thumbnail_url': 'https://r2.example/x.jpg', 'thumbnail_r2_path': 'alerts/x.jpg', 'time_key': key, 'stage': stage})
        monkeypatch.setattr(im.IncidentManager, 'upload_freeze_frames_to_r2',
                            lambda self, *a, **k: uploads.append(('freeze', 'start')) or {'thumbnail_urls': ['https://r2.example/f.jpg']})
        monkeypatch.setattr('shared.src.lib.utils.storage_path_utils.copy_to_cold_storage', lambda path: path)   # the hot file is the cold file here

    def feed(fm, name, folder):
        fm.incident_manager.INCIDENT_REPORT_DELAY = 4
        queue = fm.incident_queues[folder]
        while not queue.empty():                                     # what the incident worker thread does, inline and in order
            detection, host = queue.get_nowait()
            fm.incident_manager.process_detection(folder, detection, host)
    run_replay(str(tmp_path), configure=configure, after_frame=feed)
    return db, uploads


def test_the_replayed_incidents_become_alerts_and_resolve(tmp_path, monkeypatch):
    db, uploads = replay_through_incident_manager(tmp_path, monkeypatch, WITH_NO_SIGNAL)
    # in fixture order: the blackscreen (1200), the freeze (1402), the 8 s freeze that becomes no_signal (1602; with the real 30 s delay it would not
    # be an alert at all), the no_signal stretch (1640), the near-black blackscreen (1730)
    assert [c['incident_type'] for c in db.created] == ['blackscreen', 'freeze', 'freeze', 'no_signal', 'blackscreen']
    assert all(c['profile'] == 'tv_app' for c in db.created)
    assert len(db.resolved) == 4                                      # all closed, the last blackscreen is still open when the fixture ends
    assert [i for i in db.attempts] == [c['incident_type'] for c in db.created]    # nothing refused, nothing retried
    assert uploads == [('blackscreen', 'start'), ('freeze', 'start'), ('freeze', 'start'), ('no_signal', 'start'), ('blackscreen', 'start')]   # every alert has its frame
    # no_signal outranks freeze: the freeze that no_signal took over was resolved by it (not left open next to it)
    assert db.created[2]['incident_type'] == 'freeze' and 'a3' in db.resolved


def test_on_mains_alerts_check_a_no_signal_alert_is_refused_quietly_and_the_rest_works(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG, logger='capture_monitor'):
        db, uploads = replay_through_incident_manager(tmp_path, monkeypatch, MAIN_CHECK)
    assert [c['incident_type'] for c in db.created] == ['blackscreen', 'freeze', 'freeze', 'blackscreen']   # everything else is unaffected
    assert db.attempts.count('no_signal') == 1                         # one attempt, then the manager waits (hourly) instead of every minute
    refused = [r for r in caplog.records if r.levelno == logging.WARNING and 'refuses' in r.getMessage()]
    assert len(refused) == 1 and '20261013c' in refused[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR and 'FAILED' in r.getMessage()]
    assert uploads.count(('no_signal', 'start')) == 1                  # the frame was uploaded once, not at every attempt
    assert len(db.resolved) == 3                                       # the no_signal incident stays pending: nothing to resolve for it


def test_without_any_check_a_no_signal_alert_is_created_too(tmp_path, monkeypatch):
    db, _ = replay_through_incident_manager(tmp_path, monkeypatch, None)        # the database after 20261013b: no CHECK
    assert [c['incident_type'] for c in db.created].count('no_signal') == 1
