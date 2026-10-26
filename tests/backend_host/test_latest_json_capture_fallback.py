"""A device with no monitor (tv_lite / pc) writes captures but no metadata JSON. The heatmap asks
latest-json with capture_fallback and gets the newest capture, marked capture_only."""
import os
import time

from backend_host.src.controllers.verification.video_monitoring_helpers import VideoMonitoringHelpers


def _helpers(tmp_path, monkeypatch):
    captures = tmp_path / 'stream' / 'capture7' / 'captures'
    captures.mkdir(parents=True)
    helpers = VideoMonitoringHelpers(object(), 'test')
    monkeypatch.setattr(helpers, '_get_capture_folder', lambda: str(captures))
    return helpers, captures


def test_no_json_without_fallback_still_fails(tmp_path, monkeypatch):
    helpers, captures = _helpers(tmp_path, monkeypatch)
    (captures / 'capture_000001.jpg').write_bytes(b'jpg')
    result = helpers.get_latest_monitoring_json()
    assert result['success'] is False


def test_fallback_returns_newest_capture(tmp_path, monkeypatch):
    helpers, captures = _helpers(tmp_path, monkeypatch)
    old = captures / 'capture_000009.jpg'
    old.write_bytes(b'jpg')
    past = time.time() - 60
    os.utime(old, (past, past))
    time.sleep(0.01)
    (captures / 'capture_000010.jpg').write_bytes(b'jpg')
    (captures / 'capture_000011_thumbnail.jpg').write_bytes(b'jpg')

    result = helpers.get_latest_monitoring_json(capture_fallback=True)

    assert result['success'] is True
    assert result['capture_only'] is True
    assert result['filename'] == 'capture_000010.json'
    assert result['json_data']['monitoring_off'] is True
    assert '/stream/capture7/' in result['json_data']['capture_path']


def test_fallback_with_no_capture_fails(tmp_path, monkeypatch):
    helpers, _ = _helpers(tmp_path, monkeypatch)
    assert helpers.get_latest_monitoring_json(capture_fallback=True)['success'] is False
