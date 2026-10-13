"""Zap banner training hook (TASK-27 step 3b).

Pure: no network, no DB, no device. Every side effect of detect_and_record_zapping
(cold copy, R2 upload, report, frame JSON, zap_results insert, banner AI) is replaced
by a fake, and record_sample is a spy. The background thread is made synchronous so
the spy can be asserted right after the call.

Run: pytest tests/shared/test_training_hook_zap.py -v
"""
import os
import sys
import threading

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import gateway as ai_gateway  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.utils import ai_utils  # noqa: E402
from shared.src.lib.utils import storage_path_utils  # noqa: E402
from shared.src.lib.utils import zap_report_generator  # noqa: E402
from shared.src.lib.utils import zapping_detector_utils as zd  # noqa: E402

FRAME_BYTES = b"\xff\xd8fake-frame"
ZAP_ROW_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CHANNEL_INFO = {"channel_name": "BBC One", "channel_number": "101", "program_name": "News",
                "start_time": "", "end_time": "", "confidence": 0.9}
AUTO_ACTION = {"last_action_executed": "press_key", "last_action_timestamp": 1.0,
               "time_since_action_ms": 400, "action_params": {"key": "KEY_1", "channel": "101"}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolate detect_and_record_zapping from disk, storage, AI and DB."""
    frame = tmp_path / "capture_000000123.jpg"
    frame.write_bytes(FRAME_BYTES)

    monkeypatch.setattr(storage_path_utils, "get_captures_path", lambda folder: str(tmp_path))
    monkeypatch.setattr(storage_path_utils, "get_thumbnails_path", lambda folder: str(tmp_path))
    monkeypatch.setattr(storage_path_utils, "copy_to_cold_storage", lambda path: None)
    monkeypatch.setattr(zap_report_generator, "generate_and_upload_zap_report", lambda data: None)
    monkeypatch.setattr(zd, "_write_zapping_to_frame", lambda **kw: None)
    monkeypatch.setattr(zd, "_write_last_zapping_json", lambda **kw: None)
    monkeypatch.setattr(zd, "_store_zapping_event", lambda **kw: ZAP_ROW_ID)

    state = {"banner_calls": 0, "banner_result": {"success": True, "banner_detected": True,
                                                  "channel_info": dict(CHANNEL_INFO)}}

    def fake_banner(image_path, context_name=None):
        state["banner_calls"] += 1
        return state["banner_result"]

    monkeypatch.setattr(ai_utils, "analyze_channel_banner_ai", fake_banner)
    monkeypatch.setattr(ai_gateway, "is_available", lambda usage, *a, **k: True)
    monkeypatch.setenv("MONITOR_BANNER_AI", "true")

    # Training capture on, recording spied, background thread run inline.
    monkeypatch.setattr(training_samples, "enabled", lambda: True)
    calls = []

    def spy_record_sample(**kwargs):
        calls.append(kwargs)
        return "sample-1"

    monkeypatch.setattr(training_samples, "record_sample", spy_record_sample)
    monkeypatch.setattr(zd, "_run_in_background", lambda target, *a, **kw: target(*a, **kw))

    state["calls"] = calls
    state["frame"] = str(frame)
    return state


def _detect(**overrides):
    kwargs = dict(device_id="device1", device_model="stb_model_x", capture_folder="capture1",
                  frame_filename="capture_000000123.jpg", blackscreen_duration_ms=800,
                  action_info=dict(AUTO_ACTION))
    kwargs.update(overrides)
    return zd.detect_and_record_zapping(**kwargs)


def test_numeric_zap_records_run_label(env):
    result = _detect(expected_channel="101")

    assert result["success"] and result["zapping_detected"]
    assert len(env["calls"]) == 1
    call = env["calls"][0]
    assert call["family"] == "banner"
    assert call["image"] == FRAME_BYTES  # bytes read at analysis time, not a path
    assert call["team_id"] == zd.ZAP_TEAM_ID
    assert call["device_model"] == "stb_model_x"
    assert call["model_answer"] == CHANNEL_INFO
    assert call["ground_truth"] == {"channel_number": "101"}
    assert call["label_source"] == "run"
    assert call["source_ref"] == {"zap_id": ZAP_ROW_ID}
    assert call["prompt"] and "channel" in call["prompt"].lower()


def test_channel_up_has_no_ground_truth(env):
    action = dict(AUTO_ACTION, action_params={"key": "CHANNEL_UP"})
    result = _detect(action_info=action)  # expected_channel defaults to None

    assert result["zapping_detected"]
    assert len(env["calls"]) == 1
    call = env["calls"][0]
    assert call["ground_truth"] is None
    assert call["label_source"] == "none"
    assert call["source_ref"] == {"zap_id": ZAP_ROW_ID}


def test_no_banner_found_still_recorded_with_empty_answer(env):
    env["banner_result"] = {"success": True, "banner_detected": False}
    _detect()

    assert len(env["calls"]) == 1
    assert env["calls"][0]["model_answer"] == {}


def test_zap_id_falls_back_when_db_insert_fails(env, monkeypatch):
    monkeypatch.setattr(zd, "_store_zapping_event", lambda **kw: None)
    _detect()

    assert env["calls"][0]["source_ref"] == {"zap_id": "zap_cache_capture_000000123.jpg"}


@pytest.mark.parametrize("disable", ["env_flag", "no_vision"])
def test_skipped_banner_ai_records_nothing(env, monkeypatch, disable):
    if disable == "env_flag":
        monkeypatch.setenv("MONITOR_BANNER_AI", "false")
    else:
        monkeypatch.setattr(ai_gateway, "is_available", lambda usage, *a, **k: False)

    result = _detect(expected_channel="101")

    assert result["zapping_detected"]
    assert env["banner_calls"] == 0
    assert env["calls"] == []


def test_disabled_capture_is_noop_and_starts_no_thread(env, monkeypatch):
    monkeypatch.setattr(training_samples, "enabled", lambda: False)
    started = []
    monkeypatch.setattr(zd, "_run_in_background", lambda *a, **kw: started.append(a))
    opened = []
    monkeypatch.setattr(zd, "open", lambda *a, **kw: opened.append(a), raising=False)

    result = _detect(expected_channel="101")

    assert result["zapping_detected"]
    assert started == []
    assert opened == []  # no frame read at all when capture is off
    assert env["calls"] == []


def test_hook_exception_does_not_break_detection(env, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("minio down")

    monkeypatch.setattr(training_samples, "record_sample", boom)
    result = _detect(expected_channel="101")
    assert result["success"] and result["zapping_detected"]
    assert result["channel_number"] == "101"

    def enabled_boom():
        raise RuntimeError("config broken")

    monkeypatch.setattr(training_samples, "enabled", enabled_boom)
    result = _detect(expected_channel="101")
    assert result["success"] and result["zapping_detected"]


def test_recording_runs_on_a_daemon_thread(monkeypatch):
    """The real _run_in_background: the upload never runs on the caller's thread."""
    seen = {}
    done = threading.Event()

    def target(x):
        seen["thread"] = threading.current_thread()
        seen["x"] = x
        done.set()

    thread = zd._run_in_background(target, 42)
    assert done.wait(5)
    thread.join(5)
    assert seen["x"] == 42
    assert seen["thread"] is not threading.main_thread()
    assert seen["thread"].daemon


def test_noop_when_training_env_unset(monkeypatch):
    """Real enabled(): TRAINING_DATA_ENABLED unset means no thread and no record_sample call."""
    monkeypatch.delenv("TRAINING_DATA_ENABLED", raising=False)
    started = []
    monkeypatch.setattr(zd, "_run_in_background", lambda *a, **kw: started.append(a))

    assert training_samples.enabled() is False
    zd._record_banner_training_sample(image=b"x", device_model="m", channel_info={},
                                      expected_channel="101", zap_id="z")
    assert started == []


def test_frame_deleted_before_background_run_still_records(env, monkeypatch):
    """Live bug: the cold copy is auto-deleted after upload and the hot frame rotates, so
    the recorder must work from bytes read at analysis time, not from a path."""
    import cv2
    import numpy as np

    img = np.zeros((72, 128, 3), np.uint8)
    cv2.rectangle(img, (10, 10), (60, 40), (255, 255, 255), -1)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    with open(env["frame"], "wb") as f:
        f.write(buf.tobytes())

    def delete_then_run(target, *a, **kw):
        os.remove(env["frame"])
        assert not os.path.exists(env["frame"])
        return target(*a, **kw)

    monkeypatch.setattr(zd, "_run_in_background", delete_then_run)
    result = _detect(expected_channel="101")

    assert result["zapping_detected"]
    assert len(env["calls"]) == 1
    image = env["calls"][0]["image"]
    assert isinstance(image, bytes) and image == buf.tobytes()
    jpeg, dhash = training_samples._prepare_image(image)  # record_sample can decode it
    assert jpeg is not None and dhash


def test_skipped_banner_ai_reads_no_frame(env, monkeypatch):
    monkeypatch.setenv("MONITOR_BANNER_AI", "false")
    opened = []
    monkeypatch.setattr(zd, "open", lambda *a, **kw: opened.append(a), raising=False)

    _detect(expected_channel="101")

    assert opened == []
    assert env["calls"] == []
