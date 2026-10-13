"""TASK-27 step 3a: alert frames become pending av-fault training samples.

Pure: create_alert_safe, the device lookup, the team lookup and record_sample are
all replaced. record_sample is a fake that never writes anything, so no sample row
can be written for any team, opted in or not.

Run: pytest tests/backend_host/test_training_hook_alerts.py -v
"""
import os
import sys
import threading

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.scripts import incident_manager as im  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.config import constants  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"
FRAMES = ["/cap/capture_1.jpg", "/cap/capture_2.jpg", "/cap/capture_3.jpg", "/cap/capture_4.jpg"]
DEVICE_INFO = {"device_id": "device1", "device_name": "Box 1", "device_model": "H96_MAX",
               "stream_path": "/stream/1", "capture_path": "capture1"}


class SyncThread:
    """Runs the target on start(), so the test can assert the calls it made."""
    created = []

    def __init__(self, target=None, args=(), kwargs=None, name=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}
        self.name, self.daemon = name, daemon
        SyncThread.created.append(self)

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture
def manager(monkeypatch):
    alerts = []

    def fake_create_alert_safe(**kwargs):
        alerts.append(kwargs)
        return {"success": True, "alert_id": "alert-1"}

    monkeypatch.setattr(im, "create_alert_safe", fake_create_alert_safe)
    monkeypatch.setattr(im, "get_device_info_from_capture_folder", lambda folder: dict(DEVICE_INFO))
    monkeypatch.setattr(constants, "get_team_id", lambda: TEAM)
    monkeypatch.delenv("TRAINING_DATA_ENABLED", raising=False)
    SyncThread.created = []
    mgr = im.IncidentManager(skip_startup_cleanup=True)
    mgr.alerts = alerts
    return mgr


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_record_sample(**kwargs):
        recorded.append(kwargs)
        return f"sample-{len(recorded)}"

    monkeypatch.setattr(training_samples, "record_sample", fake_record_sample)
    return recorded


def _create(mgr, frames=FRAMES, issue_type="blackscreen"):
    # Step 4g: freeze records one strip instead (test_training_hook_freeze_strip.py);
    # the per-frame path is exercised with blackscreen.
    return mgr.create_incident("capture1", issue_type, "host-a",
                               {"last_3_filenames": list(frames), "blackscreen_percentage": 99})


def test_feature_off_records_nothing_and_starts_no_thread(manager, calls, monkeypatch):
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    assert _create(manager) == "alert-1"
    assert calls == []
    assert SyncThread.created == []
    assert len(manager.alerts) == 1


def test_each_of_the_last_three_frames_is_recorded_as_a_deduped_av_fault(manager, calls, monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)

    assert _create(manager) == "alert-1"

    assert [t.daemon for t in SyncThread.created] == [True]
    assert [c["image"] for c in calls] == FRAMES[-3:]
    for c in calls:
        assert c == {
            "image": c["image"],
            "family": "av-fault",
            "team_id": TEAM,
            "device_model": "H96_MAX",
            "model_answer": {"incident_type": "blackscreen"},
            "label_source": "none",
            "source_ref": {"alert_id": "alert-1"},
            # step 4d: near-duplicate check yes, group cap no
            "force": False,
            "skip_cap": True,
        }


def test_alert_creation_is_not_delayed_by_a_slow_upload(manager, monkeypatch):
    """The real daemon thread: create_incident returns while record_sample is blocked."""
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    release, entered, done = threading.Event(), threading.Event(), threading.Event()
    seen = []

    def blocking_record_sample(**kwargs):
        entered.set()
        release.wait(5)
        seen.append(kwargs["image"])
        if len(seen) == 3:
            done.set()
        return "sample"

    monkeypatch.setattr(training_samples, "record_sample", blocking_record_sample)
    assert _create(manager) == "alert-1"
    assert entered.wait(5), "training thread never started"
    assert seen == []  # still blocked, yet the alert id is already back
    release.set()
    assert done.wait(5)
    assert seen == FRAMES[-3:]


def test_a_failing_sample_does_not_stop_the_others_or_the_alert(manager, calls, monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    ok = []

    def flaky(**kwargs):
        if kwargs["image"] == FRAMES[1]:
            raise RuntimeError("minio down")
        ok.append(kwargs["image"])
        return "sample"

    monkeypatch.setattr(training_samples, "record_sample", flaky)
    assert _create(manager) == "alert-1"
    assert ok == [FRAMES[2], FRAMES[3]]


def test_a_thread_that_cannot_start_does_not_break_alert_creation(manager, calls, monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")

    def broken_thread(*a, **k):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(im.threading, "Thread", broken_thread)
    assert _create(manager) == "alert-1"
    assert calls == []


def test_a_team_lookup_failure_inside_the_worker_is_swallowed(manager, calls, monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)

    def boom():
        raise RuntimeError("no team")

    monkeypatch.setattr(constants, "get_team_id", boom)
    assert _create(manager) == "alert-1"
    assert calls == []


def test_no_frames_or_failed_alert_records_nothing(manager, calls, monkeypatch):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    assert _create(manager, frames=[]) == "alert-1"
    assert calls == []

    monkeypatch.setattr(im, "create_alert_safe", lambda **k: {"success": False, "error": "db"})
    assert _create(manager) is None
    assert calls == []
    assert SyncThread.created == []


# ---- step 4f: visual incident types only ----------------------------------------------

def test_visual_allowlist_is_the_visual_types_and_no_audio():
    assert im.VISUAL_INCIDENT_TYPES == {"blackscreen", "freeze", "macroblocks"}
    assert not any("audio" in t for t in im.VISUAL_INCIDENT_TYPES)


@pytest.mark.parametrize("issue_type", ["blackscreen", "macroblocks"])
def test_each_per_frame_visual_type_records_its_frames(manager, calls, monkeypatch, issue_type):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    assert manager.create_incident("capture1", issue_type, "host-a",
                                   {"last_3_filenames": list(FRAMES)}) == "alert-1"
    assert [c["model_answer"] for c in calls] == [{"incident_type": issue_type}] * 3


@pytest.mark.parametrize("issue_type", ["audio_loss", "audio_glitch", "something_new"])
def test_audio_and_unknown_types_record_nothing_but_the_alert_is_created(manager, calls, monkeypatch,
                                                                         issue_type):
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    monkeypatch.setattr(im.threading, "Thread", SyncThread)
    assert manager.create_incident("capture1", issue_type, "host-a",
                                   {"last_3_filenames": list(FRAMES), "volume_percentage": 0}) == "alert-1"
    assert calls == []
    assert SyncThread.created == []
    assert [a["incident_type"] for a in manager.alerts] == [issue_type]
