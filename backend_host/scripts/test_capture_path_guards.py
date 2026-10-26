#!/usr/bin/env python3
"""
Tests for the CPU/IO guards TASK-169 added to the capture path on vpt-pi1.

Three behaviours, all measured on the Pi that was overloaded (load 12-17 on 4
cores, 423,000 journal lines/day from the subtitle monitor alone):

1. The per-frame skip decision is announced ONCE per reason per heartbeat, not
   once per frame.
2. A picture the OCR already answered is not decoded and OCR'd again: the
   previous analysis is reused.
3. The capture monitor announces its issue set only when the set CHANGES, so a
   long freeze does not write the same line thousands of times.

Pure functions and one narrow method each — no frame, no DB, no device.
Run: pytest backend_host/scripts/test_subtitle_ocr_reuse.py
"""

import json
import sys
import types
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
# The monitor analyzers import each other by the bare `monitor.` package name.
sys.path.insert(0, str(project_root / 'backend_host' / 'scripts'))

# The subtitle monitor imports `inotify.adapters` on Linux. The test never opens
# a watch, so a stub is enough and keeps the test runnable where the C extension
# is not installed (codebox). The Pi itself has the real one.
if 'inotify.adapters' not in sys.modules:
    _inotify = types.ModuleType('inotify')
    _inotify_adapters = types.ModuleType('inotify.adapters')

    class _Inotify:  # pragma: no cover - stub
        def add_watch(self, *args, **kwargs):
            return None

    _inotify_adapters.Inotify = _Inotify
    _inotify.adapters = _inotify_adapters
    sys.modules['inotify'] = _inotify
    sys.modules['inotify.adapters'] = _inotify_adapters

from backend_host.scripts.subtitle_monitor import SubtitleMonitor, _file_digest  # noqa: E402
from monitor.analyzers.tv_app import TvAppAnalyzer, _frame_digest  # noqa: E402


# ── 1. the digest ─────────────────────────────────────────────────────────────

def test_digest_is_stable_for_the_same_bytes(tmp_path):
    a = tmp_path / 'a.jpg'
    b = tmp_path / 'b.jpg'
    a.write_bytes(b'\xff\xd8frame-bytes')
    b.write_bytes(b'\xff\xd8frame-bytes')
    assert _file_digest(str(a)) == _file_digest(str(b))


def test_digest_differs_for_different_bytes(tmp_path):
    a = tmp_path / 'a.jpg'
    b = tmp_path / 'b.jpg'
    a.write_bytes(b'\xff\xd8picture-one')
    b.write_bytes(b'\xff\xd8picture-two')
    assert _file_digest(str(a)) != _file_digest(str(b))


def test_digest_of_a_missing_file_is_none(tmp_path):
    assert _file_digest(str(tmp_path / 'nope.jpg')) is None


# ── 2. the skip throttle ──────────────────────────────────────────────────────

def _monitor_without_threads():
    """A SubtitleMonitor with the worker thread and the inotify watch skipped."""
    monitor = object.__new__(SubtitleMonitor)
    monitor._last_skip_reason = {}
    monitor._last_ocr_frame = {}
    return monitor


def test_first_skip_logs_and_the_repeat_does_not(caplog):
    monitor = _monitor_without_threads()
    with caplog.at_level('INFO'):
        assert monitor._log_skip('capture1', 'no_audio', 'SKIP: no audio') is True
        assert monitor._log_skip('capture1', 'no_audio', 'SKIP: no audio') is False
    info_lines = [r for r in caplog.records if r.levelname == 'INFO']
    assert len(info_lines) == 1


def test_each_reason_keeps_its_own_heartbeat(caplog):
    """Two reasons alternating must not produce one line per frame."""
    monitor = _monitor_without_threads()
    with caplog.at_level('INFO'):
        assert monitor._log_skip('capture1', 'no_pending', 'SKIP: nothing pending') is True
        assert monitor._log_skip('capture1', 'no_edges', 'SKIP: no edges') is True
        # both reasons are now on their heartbeat -> only DEBUG from here
        assert monitor._log_skip('capture1', 'no_pending', 'SKIP: nothing pending') is False
        assert monitor._log_skip('capture1', 'no_edges', 'SKIP: no edges') is False
    info_lines = [r for r in caplog.records if r.levelname == 'INFO']
    assert len(info_lines) == 2


def test_the_heartbeat_lets_the_reason_be_announced_again(caplog):
    monitor = _monitor_without_threads()
    with caplog.at_level('INFO'):
        assert monitor._log_skip('capture1', 'no_audio', 'SKIP: no audio') is True
        # a heartbeat of 0 means "no throttle": the next call announces again
        assert monitor._log_skip('capture1', 'no_audio', 'SKIP: no audio', heartbeat=0) is True
    info_lines = [r for r in caplog.records if r.levelname == 'INFO']
    assert len(info_lines) == 2


# ── 3. the unchanged picture reuses the previous answer ───────────────────────

def _write_metadata(tmp_path, capture_folder='capture1'):
    captures_dir = tmp_path / 'captures'
    captures_dir.mkdir(exist_ok=True)
    frame = captures_dir / 'capture_000000001.jpg'
    frame.write_bytes(b'\xff\xd8the-same-picture')
    metadata = {
        'analyzed': True,
        'subtitle_ocr_pending': True,
        'audio': True,
        'freeze': False,
        'blackscreen': False,
    }
    json_path = tmp_path / 'capture_000000001.json'
    json_path.write_text(json.dumps(metadata))
    return str(json_path), str(captures_dir), str(frame)


def test_an_unchanged_picture_reuses_the_previous_analysis(tmp_path):
    json_path, captures_dir, frame_path = _write_metadata(tmp_path)
    monitor = _monitor_without_threads()
    monitor._last_ocr_frame['capture1'] = (
        _file_digest(frame_path),
        {'has_subtitles': True, 'extracted_text': 'hello', 'skipped': False},
    )

    monitor.process_ocr(json_path, captures_dir, 'capture1')

    written = json.loads(Path(json_path).read_text())
    assert written['subtitle_ocr_pending'] is False
    assert written['subtitle_analysis']['extracted_text'] == 'hello'
    assert written['subtitle_analysis']['reused_from_previous_frame'] is True
    # the original verdict is not overwritten by the reuse marker
    assert written['subtitle_analysis']['has_subtitles'] is True


def test_a_new_picture_is_not_treated_as_unchanged(tmp_path):
    """A different digest must not take the reuse path."""
    json_path, captures_dir, frame_path = _write_metadata(tmp_path)
    monitor = _monitor_without_threads()
    monitor._last_ocr_frame['capture1'] = ('a-digest-of-another-picture', {'has_subtitles': False})

    # The OCR path needs OpenCV and a real image, so the test stops at the point
    # that matters: the reuse path must NOT have been taken.
    try:
        monitor.process_ocr(json_path, captures_dir, 'capture1')
    except Exception:
        pass

    written = json.loads(Path(json_path).read_text())
    assert 'reused_from_previous_frame' not in (written.get('subtitle_analysis') or {})


# ── 4. the capture monitor announces an issue set only when it CHANGES ────────

def _analyzer_without_threads():
    analyzer = object.__new__(TvAppAnalyzer)
    analyzer._last_issues = {}
    return analyzer


def test_the_first_issue_set_is_remembered_silently(caplog):
    analyzer = _analyzer_without_threads()
    with caplog.at_level('INFO'):
        assert analyzer._log_issues('capture1', ['freeze']) is False
    assert [r for r in caplog.records if r.levelname == 'INFO'] == []


def test_the_same_issue_set_is_not_announced_again(caplog):
    analyzer = _analyzer_without_threads()
    analyzer._log_issues('capture1', ['freeze'])
    with caplog.at_level('INFO'):
        for _ in range(20):
            assert analyzer._log_issues('capture1', ['freeze']) is False
    assert [r for r in caplog.records if r.levelname == 'INFO'] == []


def test_a_changed_issue_set_is_announced(caplog):
    analyzer = _analyzer_without_threads()
    analyzer._log_issues('capture1', ['freeze'])
    with caplog.at_level('INFO'):
        assert analyzer._log_issues('capture1', ['blackscreen']) is True
        # the incident ending is announced too
        assert analyzer._log_issues('capture1', []) is True
    info_lines = [r for r in caplog.records if r.levelname == 'INFO']
    assert len(info_lines) == 2
    assert 'blackscreen' in info_lines[0].getMessage()
    assert 'cleared' in info_lines[1].getMessage()


# ── 5. the host exit cleanup runs once ────────────────────────────────────────

def test_cleanup_on_exit_runs_only_once(monkeypatch):
    """The stop path used to run the cleanup twice (signal handler + atexit)."""
    from backend_host.src.lib.utils import host_utils

    calls = []
    monkeypatch.setattr(host_utils, 'stop_ping_thread', lambda: calls.append('ping'))
    monkeypatch.setattr(host_utils, 'stop_metrics_thread', lambda: calls.append('metrics'))
    monkeypatch.setattr(host_utils, 'unregister_from_server', lambda: calls.append('unregister'))
    monkeypatch.setattr(host_utils, '_cleanup_done', False, raising=False)

    host_utils.cleanup_on_exit()
    host_utils.cleanup_on_exit()

    assert calls == ['ping', 'metrics', 'unregister']


# ── 6. the Localize matcher is not run twice on the same picture ───────────────

def test_the_frame_digest_sees_two_identical_pictures_as_one(tmp_path):
    a = tmp_path / 'a.jpg'
    b = tmp_path / 'b.jpg'
    a.write_bytes(b'\xff\xd8same')
    b.write_bytes(b'\xff\xd8same')
    assert _frame_digest(str(a)) == _frame_digest(str(b))
    b.write_bytes(b'\xff\xd8other')
    assert _frame_digest(str(a)) != _frame_digest(str(b))


def test_the_frame_digest_of_a_missing_file_is_none(tmp_path):
    assert _frame_digest(str(tmp_path / 'nope.jpg')) is None


def test_an_unchanged_frame_and_audio_skips_the_matcher(tmp_path):
    """The worker must not call identify_screen again on the same picture."""
    frame = tmp_path / 'capture_000000001.jpg'
    frame.write_bytes(b'\xff\xd8the-same-picture')

    analyzer = object.__new__(TvAppAnalyzer)
    analyzer._localize_input = {}
    analyzer._last_localize = {}
    analyzer._last_motion = {'device1': {'kind': 'static', 'state': 'static'}}
    analyzer._last_audio = {'device1': (True, -40.0)}
    analyzer._foreground_package = lambda device_id, frame_path: None

    calls = []

    class _Localizer:
        def localize_frame(self, device_id, frame_path, motion=None, audio=None, foreground=None):
            calls.append(device_id)
            return {'node': 'Home', 'confidence': 0.9}

    analyzer.localizer = _Localizer()

    assert analyzer._localize_one('device1', str(frame)) is True
    assert calls == ['device1']          # the first pass matches

    assert analyzer._localize_one('device1', str(frame)) is False
    assert calls == ['device1']          # the second pass does NOT match again

    # a changed picture must match again
    frame.write_bytes(b'\xff\xd8a-different-picture')
    assert analyzer._localize_one('device1', str(frame)) is True
    assert calls == ['device1', 'device1']


def test_a_changed_audio_makes_the_matcher_run_again(tmp_path):
    frame = tmp_path / 'capture_000000001.jpg'
    frame.write_bytes(b'\xff\xd8the-same-picture')

    analyzer = object.__new__(TvAppAnalyzer)
    analyzer._localize_input = {}
    analyzer._last_localize = {}
    analyzer._last_motion = {'device1': {'kind': 'static', 'state': 'static'}}
    analyzer._last_audio = {'device1': (True, -40.0)}
    analyzer._foreground_package = lambda device_id, frame_path: None

    calls = []

    class _Localizer:
        def localize_frame(self, device_id, frame_path, motion=None, audio=None, foreground=None):
            calls.append(device_id)
            return {'node': 'Home', 'confidence': 0.9}

    analyzer.localizer = _Localizer()

    analyzer._localize_one('device1', str(frame))
    analyzer._last_audio['device1'] = (True, -12.0)     # the sound changed
    analyzer._localize_one('device1', str(frame))
    assert calls == ['device1', 'device1']
