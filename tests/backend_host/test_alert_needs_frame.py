"""BUG-0493: an alert is never created without an uploaded frame.

The freeze detector does not always find thumbnails on disk (the host VNC capture often has none): the capture
frames are uploaded instead. When no frame uploads at all, the incident stays pending and is retried after
CREATE_RETRY_BACKOFF instead of reaching the DB without an image.

Run: pytest tests/backend_host/test_alert_needs_frame.py -v
"""
import os
import sys
import time

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_host.scripts import incident_manager as im  # noqa: E402
from shared.src.lib.utils import storage_path_utils  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def env(monkeypatch, tmp_path):
    frames = []
    for n in (184, 185, 186):
        path = tmp_path / f"capture_{n:09d}.jpg"
        path.write_bytes(b"jpg")
        frames.append(str(path))
    state = {"frames": frames, "uploads": [], "created": [], "upload_ok": True}
    monkeypatch.setattr(im, "get_device_info_from_capture_folder", lambda folder: {"device_id": "host"})
    monkeypatch.setattr(storage_path_utils, "copy_to_cold_storage", lambda p: p)
    manager = im.IncidentManager(skip_startup_cleanup=True)

    def upload(captures, thumbnails, folder, time_key, thumbnails_only=False):
        state["uploads"].append(list(thumbnails))
        return {"thumbnail_urls": ["https://r2/t0.jpg"], "thumbnail_r2_paths": ["alerts/freeze/t0.jpg"]} \
            if state["upload_ok"] else None

    monkeypatch.setattr(manager, "upload_freeze_frames_to_r2", upload)
    monkeypatch.setattr(manager, "create_incident",
                        lambda folder, kind, host, result: state["created"].append(result) or "alert-1")
    manager.get_device_state("host")["pending_incidents"]["freeze"] = time.time() - 40
    state["manager"] = manager
    return state


def _freeze(env):
    return {"freeze": True, "freeze_event_duration_ms": 40000, "last_3_filenames": env["frames"],
            "last_3_thumbnails": []}


def test_freeze_without_thumbnails_uploads_the_capture_frames(env):
    env["manager"].process_detection("capture", _freeze(env), "labox-web")
    assert env["uploads"] == [env["frames"]]
    assert len(env["created"]) == 1 and env["created"][0]["r2_images"]["thumbnail_r2_paths"]


def test_no_alert_without_a_frame_then_retry_after_backoff(env):
    env["upload_ok"] = False
    manager = env["manager"]
    manager.process_detection("capture", _freeze(env), "vpt-nipogi")
    state = manager.get_device_state("host")
    assert env["created"] == [] and "freeze" in state["pending_incidents"]
    assert "freeze_create_retry_ts" in state

    manager.process_detection("capture", _freeze(env), "vpt-nipogi")  # inside the back-off: no new upload
    assert len(env["uploads"]) == 1

    state["freeze_create_retry_ts"] -= manager.CREATE_RETRY_BACKOFF + 1
    env["upload_ok"] = True
    manager.process_detection("capture", _freeze(env), "vpt-nipogi")
    assert len(env["created"]) == 1 and env["created"][0]["r2_images"]
