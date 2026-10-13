"""TASK-27 step 4g: a freeze alert records ONE av-fault sample, a multi-frame strip.

Pure: create_alert_safe, the device lookup, the team lookup and record_sample are
replaced; the frames are real tiny JPEGs in a tmp dir. record_sample is a fake that
never writes anything.

Run: pytest tests/backend_host/test_training_hook_freeze_strip.py -v
"""
import os
import sys

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.scripts import incident_manager as im  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.config import constants  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"
DEVICE_INFO = {"device_id": "device1", "device_name": "Box 1", "device_model": "H96_MAX",
               "stream_path": "/stream/1", "capture_path": "capture1"}


class SyncThread:
    created = []

    def __init__(self, target=None, args=(), kwargs=None, name=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}
        self.name, self.daemon = name, daemon
        SyncThread.created.append(self)

    def start(self):
        self.target(*self.args, **self.kwargs)


def _path(folder, n):
    return os.path.join(str(folder), f"capture_{n:09d}.jpg")


def _write(folder, *numbers):
    img = np.zeros((180, 320, 3), np.uint8)
    cv2.rectangle(img, (20, 20), (150, 120), (40, 160, 220), -1)
    for n in numbers:
        cv2.imwrite(_path(folder, n), img)


def _freeze_result(folder, current=188, last_3=(186, 185, 184), duration_ms=30174):
    cur = _path(folder, current)
    return {
        "filename": os.path.basename(cur),
        "freeze_event_start": "2026-09-29T19:55:50.397648",
        "freeze_event_duration_ms": duration_ms,
        "freeze_diffs": [0.13, 0.14, 0.11],
        "freeze_comparisons": [{"current_frame": os.path.basename(cur), "current_capture_path": cur,
                                "previous_frame": os.path.basename(_path(folder, p)),
                                "previous_capture_path": _path(folder, p),
                                "difference_percentage": 0.1, "frozen": True}
                               for p in (current - 1, current - 2, current - 3)],
        "last_3_filenames": [_path(folder, p) for p in last_3],
    }


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(im, "create_alert_safe", lambda **k: {"success": True, "alert_id": "alert-1"})
    monkeypatch.setattr(im, "get_device_info_from_capture_folder", lambda folder: dict(DEVICE_INFO))
    monkeypatch.setattr(constants, "get_team_id", lambda: TEAM)
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    SyncThread.created = []
    return im.IncidentManager(skip_startup_cleanup=True)


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_record_sample(**kwargs):
        recorded.append(kwargs)
        return f"sample-{len(recorded)}"

    monkeypatch.setattr(training_samples, "record_sample", fake_record_sample)
    return recorded


def test_freeze_alert_records_exactly_one_strip_sample(manager, calls, tmp_path):
    _write(tmp_path, 37, 112, 184, 185, 186, 187, 188)
    assert manager.create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"

    assert [t.daemon for t in SyncThread.created] == [True]
    assert len(calls) == 1
    call = dict(calls[0])
    image = call.pop("image")
    assert isinstance(image, bytes) and image[:2] == b"\xff\xd8"
    at = call["source_ref"].pop("at")
    assert at.endswith("+00:00")                     # UTC, for the Alerts page deep link
    assert call == {
        "family": "av-fault",
        "team_id": TEAM,
        "device_model": "H96_MAX",
        "model_answer": {"incident_type": "freeze", "evidence": "strip", "duration_ms": 30174,
                         "diffs": [0.13, 0.14, 0.11], "frames": [0.0, 15.0, 30.2]},
        "label_source": "none",
        "source_ref": {"alert_id": "alert-1", "host": "host-a", "device": "device1"},
        "boxes": None,
        "force": False,
        "skip_cap": True,
    }


def test_freeze_with_too_few_spaced_frames_records_nothing(manager, calls, tmp_path):
    _write(tmp_path, 186, 187, 188)                  # 400 ms, and no start frame on disk
    assert manager.create_incident("capture1", "freeze", "host-a",
                                   _freeze_result(tmp_path, last_3=(187, 186))) == "alert-1"
    assert calls == []


def test_freeze_without_a_current_frame_path_starts_no_thread(manager, calls):
    assert manager.create_incident("capture1", "freeze", "host-a",
                                   {"freeze_diffs": [0.1], "last_3_filenames": []}) == "alert-1"
    assert calls == [] and SyncThread.created == []


def test_freeze_strip_failure_never_breaks_the_alert(manager, monkeypatch, tmp_path):
    _write(tmp_path, 37, 112, 188)

    def boom(**kwargs):
        raise RuntimeError("minio down")

    monkeypatch.setattr(training_samples, "record_sample", boom)
    assert manager.create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"


def test_feature_off_records_no_strip(manager, calls, monkeypatch, tmp_path):
    monkeypatch.delenv("TRAINING_DATA_ENABLED", raising=False)
    _write(tmp_path, 37, 112, 188)
    assert manager.create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"
    assert calls == [] and SyncThread.created == []


def test_blackscreen_still_records_per_frame(manager, calls, tmp_path):
    frames = [_path(tmp_path, n) for n in (1, 2, 3)]
    assert manager.create_incident("capture1", "blackscreen", "host-a",
                                   {"last_3_filenames": frames, "blackscreen_percentage": 99}) == "alert-1"
    assert [c["image"] for c in calls] == frames
    assert all(c["model_answer"] == {"incident_type": "blackscreen"} for c in calls)
    assert all(c["source_ref"] == {"alert_id": "alert-1"} for c in calls)
