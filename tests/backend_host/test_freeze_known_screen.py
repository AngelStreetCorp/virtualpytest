"""A freeze on a screen that screen memory already judged expected is never opened (any device, not only the host
desktop); any other freeze is opened with its screen stamped. Runs the replay fixture through a real IncidentManager."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.backend_host.test_monitor_incident_integration import WITH_NO_SIGNAL, replay_through_incident_manager  # noqa: E402


def _replay(tmp_path, monkeypatch, verdict):
    import incident_manager as im
    lookups = []

    def freeze_screen(metadata, host_name, device_id, capture_folder):
        lookups.append(device_id)
        return {'id': 's1', 'dist': 0, 'is_new': False, 'verdict': verdict, 'seen': 7}
    monkeypatch.setenv('ALERT_SCREEN_MEMORY', 'on')
    monkeypatch.setattr(im.IncidentManager, '_freeze_screen', staticmethod(freeze_screen))
    db, _uploads = replay_through_incident_manager(tmp_path, monkeypatch, WITH_NO_SIGNAL)
    return db, lookups


def test_a_freeze_on_an_expected_screen_is_never_opened(tmp_path, monkeypatch):
    base, _ = _replay(tmp_path / 'base', monkeypatch, 'unknown')
    db, lookups = _replay(tmp_path / 'known', monkeypatch, 'expected')
    base_types = [c['incident_type'] for c in base.created]
    assert 'freeze' in base_types
    assert [c['incident_type'] for c in db.created] == [t for t in base_types if t != 'freeze']
    assert 1 <= len(lookups) <= base_types.count('freeze')    # one lookup per freeze episode, not one per tick


def test_a_freeze_on_an_unjudged_screen_is_opened_with_its_screen(tmp_path, monkeypatch):
    db, _lookups = _replay(tmp_path, monkeypatch, 'unknown')
    freezes = [c for c in db.created if c['incident_type'] == 'freeze']
    assert freezes
    assert all(c['metadata']['screen_id'] == 's1' and c['metadata']['screen_seen'] == 7 for c in freezes)
