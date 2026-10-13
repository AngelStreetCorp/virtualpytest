"""/host/transcript/status classification: the transcript, or WHY there is none (BUG-0293).

Fake capture tree in tmp_path: audio_status.json, transcript chunk JSONs, MP3 files.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from backend_host.src.lib.utils import transcript_status as ts  # noqa: E402
from shared.src.lib.utils import storage_path_utils as spu  # noqa: E402

NOW = datetime(2026, 10, 4, 13, 25, 0)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    base = tmp_path / "capture4"
    monkeypatch.setattr(spu, "get_metadata_path", lambda f: str(base / "hot" / "metadata"))
    monkeypatch.setattr(spu, "get_cold_storage_path", lambda f, sub: str(base / sub))
    monkeypatch.setattr(spu, "get_transcript_chunk_path",
                        lambda f, h, i, language="original": str(base / "transcript" / str(h) / f"chunk_10min_{i}.json"))
    monkeypatch.setattr(ts, "_service_state", lambda: "active")
    monkeypatch.setattr(ts.time, "time", lambda: NOW.timestamp())
    (base / "hot" / "metadata").mkdir(parents=True)
    return base


def _touch(path, when):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("x")
    os.utime(path, (when.timestamp(), when.timestamp()))


def _audio(base, audio=True, transcription=True, age_s=5):
    p = base / "hot" / "metadata" / "audio_status.json"
    data = {"audio": audio, "mean_volume_db": -30.0 if audio else (-91.0 if audio is False else None)}
    if transcription is not None:
        data["transcription"] = transcription
    p.write_text(json.dumps(data))
    _touch(p, NOW - timedelta(seconds=age_s))


def _chunk(base, hour, idx, segments, statuses=None, written=None):
    p = base / "transcript" / str(hour) / f"chunk_10min_{idx}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"language": "French", "segments": segments, "minute_statuses": statuses or {}}))
    _touch(p, written or NOW - timedelta(seconds=30))


def _run(base, minutes=10):
    start, end = ts.resolve_window(NOW, minutes, None, None)
    return ts.read_transcript_status("device4", "capture4", start, end, now=NOW)


def test_returns_text(tree):
    _audio(tree)
    _chunk(tree, 13, 2, [{"start": 30, "text": "bonjour"}, {"start": 200, "text": "a tous"}])
    r = _run(tree)
    assert (r["status"], r["reason"]) == ("ok", "transcribed")
    assert r["text"] == "bonjour a tous" and r["segments"][0]["time"] == "2026-10-04T13:20:30"


def test_yesterdays_chunk_is_ignored(tree):
    _audio(tree)
    _chunk(tree, 13, 2, [{"start": 30, "text": "hier"}], written=NOW - timedelta(days=1))
    _touch(tree / "audio" / "temp" / "1min_3.mp3", NOW - timedelta(minutes=8))
    r = _run(tree)
    assert r["segments"] == [] and r["reason"] == "transcript_missing"


def test_service_inactive(tree, monkeypatch):
    monkeypatch.setattr(ts, "_service_state", lambda: "inactive")
    _audio(tree, age_s=900)
    assert _run(tree)["reason"] == "service_inactive"


def test_transcription_disabled(tree):
    _audio(tree, transcription=False)
    r = _run(tree)
    assert (r["status"], r["reason"]) == ("unavailable", "transcription_disabled")
    assert "AUDIO DETECTION ONLY" in r["message"]


def test_no_audio_stream(tree):
    _audio(tree, audio=None)
    assert _run(tree)["reason"] == "no_audio_stream"


def test_silent(tree):
    _audio(tree, audio=False)
    _touch(tree / "audio" / "temp" / "1min_3.mp3", NOW - timedelta(minutes=2))
    assert _run(tree)["reason"] == "silent_audio"


def test_no_speech(tree):
    _audio(tree)
    _chunk(tree, 13, 2, [], {"1": {"processed_day": "2026-10-04", "has_audio": False, "skip_reason": "no_speech"}})
    _touch(tree / "audio" / "temp" / "1min_1.mp3", NOW - timedelta(minutes=4))
    assert _run(tree)["reason"] == "no_speech"


def test_processing_pending(tree):
    _audio(tree)
    _touch(tree / "audio" / "temp" / "1min_4.mp3", NOW - timedelta(seconds=40))
    assert _run(tree)["reason"] == "processing_pending"


def test_missing_and_stale_are_errors(tree):
    assert _run(tree)["reason"] == "audio_status_missing"
    _audio(tree, age_s=300)
    assert _run(tree)["status"] == "error" and _run(tree)["reason"] == "audio_check_stale"
    _audio(tree, transcription=None)
    assert _run(tree)["reason"] == "transcription_mode_unknown"
    _audio(tree)
    assert _run(tree)["reason"] == "mp3_missing"


def test_hour_window_is_most_recent_occurrence():
    start, end = ts.resolve_window(NOW, None, 14, None)
    assert start == datetime(2026, 10, 3, 14, 0) and end == datetime(2026, 10, 3, 15, 0)
    start, end = ts.resolve_window(NOW, None, 13, 2)
    assert start == datetime(2026, 10, 4, 13, 20) and end == NOW
