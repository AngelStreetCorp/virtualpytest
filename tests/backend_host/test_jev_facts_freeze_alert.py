"""TASK-55 step 2: a freeze alert gets metadata.jev_facts from its own frames, off the frame path.

Pure: create_alert_safe, the device lookup and the alert update are replaced; the frames are real tiny
JPEGs in a tmp dir; OCR is a stub that records whether it was asked.

Run: pytest tests/backend_host/test_jev_facts_freeze_alert.py -v
"""
import os
import sys

import cv2
import numpy as np
import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.scripts import incident_manager as im  # noqa: E402
from shared.src.lib.ai import freeze_facts  # noqa: E402
from shared.src.lib.database import alerts_db  # noqa: E402

pytestmark = pytest.mark.unit


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


def _freeze_result(folder, current=188):
    cur = _path(folder, current)
    return {"filename": os.path.basename(cur), "freeze_event_duration_ms": 30174, "freeze_diffs": [0.1],
            "freeze_comparisons": [{"current_capture_path": cur, "previous_capture_path": _path(folder, current - 1)}],
            "last_3_filenames": [_path(folder, p) for p in (186, 185, 184)]}


@pytest.fixture
def env(monkeypatch):
    state = {"device": {"device_id": "device1", "device_name": "Box 1", "device_model": "H96_MAX",
                        "stream_path": "/s", "capture_path": "capture1"},
             "merged": [], "ocr": 0}
    monkeypatch.setattr(im, "create_alert_safe", lambda **k: {"success": True, "alert_id": "alert-1"})
    monkeypatch.setattr(im, "get_device_info_from_capture_folder", lambda folder: dict(state["device"]))
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    monkeypatch.setattr(alerts_db, "merge_alert_metadata",
                        lambda alert_id, patch: state["merged"].append((alert_id, patch)) or True)

    def fake_ocr(img, psm=6, lang="deu+eng"):
        state["ocr"] += 1
        return "Entdecken Filme Serien"

    monkeypatch.setattr(freeze_facts, "ocr", fake_ocr)
    monkeypatch.delenv("TRAINING_DATA_ENABLED", raising=False)
    monkeypatch.setenv("ALERT_JEV_FACTS_ENABLED", "true")
    SyncThread.created = []
    state["manager"] = im.IncidentManager(skip_startup_cleanup=True)
    return state


def test_facts_written_on_a_freeze_alert(env, tmp_path):
    _write(tmp_path, 37, 112, 184, 185, 186, 187, 188)
    assert env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"
    assert [t.daemon for t in SyncThread.created] == [True]
    (alert_id, patch), = env["merged"]
    facts = patch["jev_facts"]
    assert alert_id == "alert-1" and list(patch) == ["jev_facts"]
    assert facts["version"] == 1 and facts["device_model"] == "H96_MAX" and facts["n_frames"] == 3
    assert facts["text"]["read_first"] == "Entdecken Filme Serien"
    assert facts["first_last"]["changed_pct"] == 0.0 and len(facts["pairs"]) == 2
    assert facts["facts"] and isinstance(facts["ms"], int) and "footer" not in facts
    assert env["ocr"] == 2


def test_disabled_does_nothing(env, monkeypatch, tmp_path):
    monkeypatch.delenv("ALERT_JEV_FACTS_ENABLED")
    _write(tmp_path, 37, 112, 188)
    assert env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"
    assert env["merged"] == [] and SyncThread.created == []


def test_other_alert_types_get_no_facts(env, tmp_path):
    assert env["manager"].create_incident("capture1", "blackscreen", "host-a",
                                          {"last_3_filenames": [_path(tmp_path, 1)]}) == "alert-1"
    assert env["merged"] == []


def test_camera_gets_change_facts_without_ocr(env, tmp_path):
    env["device"]["device_model"] = "camera"
    _write(tmp_path, 37, 112, 188)
    env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path))
    facts = env["merged"][0][1]["jev_facts"]
    assert env["ocr"] == 0 and facts["text"]["read_first"] == "" and facts["n_frames"] == 3


def test_too_few_frames_writes_nothing(env, tmp_path):
    _write(tmp_path, 188)
    env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path))
    assert env["merged"] == []


def test_exception_in_the_thread_does_not_propagate(env, monkeypatch, tmp_path):
    _write(tmp_path, 37, 112, 188)

    def boom(frames, with_ocr=True):
        raise RuntimeError("tesseract missing")

    monkeypatch.setattr(freeze_facts, "facts_from_frames", boom)
    assert env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"
    assert env["merged"] == []


def test_db_failure_does_not_propagate(env, monkeypatch, tmp_path):
    _write(tmp_path, 37, 112, 188)

    def down(alert_id, patch):
        raise RuntimeError("db down")

    monkeypatch.setattr(alerts_db, "merge_alert_metadata", down)
    assert env["manager"].create_incident("capture1", "freeze", "host-a", _freeze_result(tmp_path)) == "alert-1"
