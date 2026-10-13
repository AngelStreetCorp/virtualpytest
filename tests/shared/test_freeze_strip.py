"""TASK-27 step 4g: the freeze strip builder (shared/src/lib/ai/freeze_strip.py) and the
near-duplicate check on two strips of the same frozen screen.

Pure: real tiny JPEGs in a tmp dir, no DB, bucket or network. record_sample's DB and
storage calls are replaced.

Run: pytest tests/shared/test_freeze_strip.py -v
"""
import os
import sys

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import freeze_strip as fs  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402
from shared.src.lib.utils.image_hash import dhash_hamming  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"


def _frame(seed=0, w=320, h=180):
    """A frozen-looking picture: a fixed pattern, optionally shifted by seed."""
    img = np.zeros((h, w, 3), np.uint8)
    cv2.rectangle(img, (20 + seed, 20), (150 + seed, 120), (40, 160, 220), -1)
    cv2.circle(img, (240, 90), 40, (200, 60, 60), -1)
    cv2.putText(img, "MENU", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def _write(folder, n, img=None):
    path = os.path.join(str(folder), f"capture_{n:09d}.jpg")
    cv2.imwrite(path, _frame() if img is None else img)
    return path


def _meta(folder, current, previous, last_3=None, duration_ms=30174, diffs=(0.13, 0.14, 0.11)):
    cur = os.path.join(str(folder), f"capture_{current:09d}.jpg")
    comps = [{"current_frame": os.path.basename(cur), "current_capture_path": cur,
              "previous_frame": f"capture_{p:09d}.jpg",
              "previous_capture_path": os.path.join(str(folder), f"capture_{p:09d}.jpg"),
              "difference_percentage": 0.1, "frozen": True} for p in previous]
    return {
        "filename": os.path.basename(cur),
        "freeze_event_start": "2026-09-29T19:55:50.397648",
        "freeze_event_duration_ms": duration_ms,
        "freeze_diffs": list(diffs),
        "freeze_comparisons": comps,
        "last_3_filenames": [os.path.join(str(folder), f"capture_{p:09d}.jpg") for p in (last_3 or previous)],
    }


def _times(meta):
    return [f["t_rel_s"] for f in meta["frames"]]


# ---- frame selection ----------------------------------------------------------------

def test_real_alert_shape_uses_the_freeze_start_and_a_middle_frame(tmp_path):
    """The Pi alert: current 188, last_3 = 186/185/184 (200 ms apart), frozen 30.2 s.
    The freeze-start frame (188 - 151) and a middle frame are on disk."""
    for n in (37, 110, 112, 184, 185, 186, 188):
        _write(tmp_path, n)
    built = fs.build_freeze_strip(_meta(tmp_path, 188, [187, 186, 185], last_3=[186, 185, 184]))
    assert built is not None
    jpeg, meta = built
    assert _times(meta) == [0.0, 15.0, 30.2]          # 37 -> 112 (the midpoint) -> 188 at 5 fps
    assert [f["file"] for f in meta["frames"]][::2] == ["capture_000000037.jpg", "capture_000000188.jpg"]
    assert meta["time_source"] == "capture_number" and meta["fps"] == 5
    assert meta["duration_ms"] == 30174 and meta["diffs"] == [0.13, 0.14, 0.11]
    assert meta["event_start"] == "2026-09-29T19:55:50.397648"
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) <= 1280 and img.shape[1] == 1278  # 3 x 426


def test_every_picked_pair_is_at_least_500_ms_apart(tmp_path):
    for n in (100, 101, 102, 103, 104, 106):
        _write(tmp_path, n)
    # No start frame on disk (duration 0): only the detector's frames, 200 ms apart.
    built = fs.build_freeze_strip(_meta(tmp_path, 106, [105, 104, 103], last_3=[104, 103, 102],
                                        duration_ms=0))
    assert built is not None
    times = _times(built[1])
    assert all(b - a >= 0.5 for a, b in zip(times, times[1:]))
    assert times[0] == 0.0 and times[-1] >= 0.5


def test_two_frames_when_no_middle_fits(tmp_path):
    # current 110, last_3 = 107,106,105: 105 is the earliest, 1.0 s before. No frame is
    # 500 ms from both ends, so the strip has two frames.
    for n in (105, 106, 107, 110):
        _write(tmp_path, n)
    built = fs.build_freeze_strip(_meta(tmp_path, 110, [107, 106, 105], duration_ms=0))
    assert _times(built[1]) == [0.0, 1.0]


def test_the_middle_can_come_from_last_3(tmp_path):
    # Long-freeze cached comparison: previous frame 95 frames (19 s) back, 0% diff;
    # last_3 are near the current frame. A last_3 frame is a valid middle only if it is
    # 500 ms from both ends, which 105 is not here; the probe finds one near 142.
    for n in (95, 142, 187, 188, 189, 190):
        _write(tmp_path, n)
    built = fs.build_freeze_strip(_meta(tmp_path, 190, [95], last_3=[189, 188, 187], duration_ms=0))
    assert _times(built[1]) == [0.0, 9.4, 19.0]


def test_none_when_no_two_frames_are_500_ms_apart(tmp_path):
    for n in (101, 102, 103):   # 400 ms from first to last
        _write(tmp_path, n)
    assert fs.build_freeze_strip(_meta(tmp_path, 103, [102, 101, 100], duration_ms=0)) is None


def test_none_when_only_one_frame_exists(tmp_path):
    _write(tmp_path, 188)
    assert fs.build_freeze_strip(_meta(tmp_path, 188, [187, 186, 185])) is None


def test_missing_files_are_skipped_without_crashing(tmp_path):
    # Only the current frame and one old one exist; every other path is missing.
    _write(tmp_path, 50)
    _write(tmp_path, 188)
    built = fs.build_freeze_strip(_meta(tmp_path, 188, [187, 186, 50], duration_ms=0))
    assert built is not None and _times(built[1]) == [0.0, 27.6]


def test_a_corrupt_file_is_dropped(tmp_path):
    _write(tmp_path, 37)
    _write(tmp_path, 188)
    with open(os.path.join(str(tmp_path), f"capture_{112:09d}.jpg"), "wb") as f:
        f.write(b"not a jpeg")
    built = fs.build_freeze_strip(_meta(tmp_path, 188, [187]))
    assert built is not None and _times(built[1]) == [0.0, 30.2]


@pytest.mark.parametrize("bad", [None, {}, {"freeze_comparisons": "nope"}, "string", 42])
def test_bad_metadata_never_raises(bad):
    assert fs.build_freeze_strip(bad) is None


def test_mtime_is_the_fallback_when_names_have_no_capture_number(tmp_path):
    a = os.path.join(str(tmp_path), "frame_a.jpg")
    b = os.path.join(str(tmp_path), "frame_b.jpg")
    cv2.imwrite(a, _frame())
    cv2.imwrite(b, _frame())
    os.utime(a, (1000.0, 1000.0))
    os.utime(b, (1002.5, 1002.5))
    meta = {"freeze_comparisons": [{"current_capture_path": b, "previous_capture_path": a}],
            "freeze_event_duration_ms": 30000, "freeze_diffs": [0.1]}
    built = fs.build_freeze_strip(meta)
    assert built is not None
    assert built[1]["time_source"] == "mtime" and _times(built[1]) == [0.0, 2.5]


def test_current_frame_path_falls_back_to_filename_next_to_last_3():
    meta = {"filename": "capture_000000188.jpg",
            "last_3_filenames": ["/x/hot/captures/capture_000000186.jpg"]}
    assert fs.current_frame_path(meta) == os.path.join("/x/hot/captures", "capture_000000188.jpg")
    assert fs.current_frame_path({"filename": "capture_1.jpg"}) is None


def test_footer_text():
    assert fs._footer_text(30174, [0.13, 0.14, 0.11]) == "frozen 30.2 s | diff 0.14%"
    assert fs._footer_text(None, []) == "freeze"


# ---- dedup: two alerts on the same frozen screen ---------------------------------------

def test_second_near_identical_strip_is_skipped(tmp_path, monkeypatch):
    """Two alerts of the same frozen menu: different times burned in, same picture. The
    near-duplicate check (8 bits) skips the second strip; a different screen is kept."""
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    for n in (37, 112, 188):
        _write(a, n)
    for n in (1000, 1060, 1120):   # a later alert, 24 s span
        _write(b, n)
    other = np.full((180, 320, 3), 30, np.uint8)
    cv2.rectangle(other, (0, 0), (160, 180), (250, 250, 250), -1)
    for n in (37, 112, 188):
        _write(c, n, other)
    strip_a = fs.build_freeze_strip(_meta(a, 188, [187]))[0]
    strip_b = fs.build_freeze_strip(_meta(b, 1120, [1119], duration_ms=24000))[0]
    strip_c = fs.build_freeze_strip(_meta(c, 188, [187]))[0]
    _, hash_a = training_samples._prepare_image(strip_a)
    _, hash_b = training_samples._prepare_image(strip_b)
    _, hash_c = training_samples._prepare_image(strip_c)
    assert dhash_hamming(hash_a, hash_b) <= training_samples.NEAR_DUP_BITS
    assert dhash_hamming(hash_a, hash_c) > training_samples.NEAR_DUP_BITS

    stored = []
    monkeypatch.setattr(training_samples, "enabled", lambda: True)
    monkeypatch.setattr(samples_db, "team_opted_in", lambda t: True)
    monkeypatch.setattr(samples_db, "get_group",
                        lambda *a, **k: [(r["id"], r["dhash"], None, False) for r in stored])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", lambda *a, **k: [])

    def fake_insert(row):
        stored.append(row)
        return row["id"]

    class Storage:
        def upload_bytes(self, *a, **k):
            return {"success": True}

    monkeypatch.setattr(samples_db, "insert_sample", fake_insert)
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: Storage())

    def record(jpeg, alert):
        return training_samples.record_sample(
            image=jpeg, family="av-fault", team_id=TEAM, device_model="stb",
            model_answer={"incident_type": "freeze", "evidence": "strip"}, label_source="none",
            source_ref={"alert_id": alert}, force=False, skip_cap=True)

    assert record(strip_a, "alert-1") is not None
    assert record(strip_b, "alert-2") is None      # near-identical strip of another alert
    assert record(strip_c, "alert-3") is not None  # a different frozen screen
    assert [r["source_ref"]["alert_id"] for r in stored] == ["alert-1", "alert-3"]
