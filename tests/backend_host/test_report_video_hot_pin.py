"""A report video keeps its HOT tail when the archiver deletes those segments mid-build.

extract_test_video_hybrid read COLD first and copied the HOT segments only afterwards; the
archiver archived and deleted the next minute of HOT in between, so that minute was in
neither half and the video lost its tail (43 s on vpt-pi1, 2026-10-11). The HOT segments
are now pinned with hard links before the COLD read, and the archiver deletes a minute's
HOT segments only after it is in the 10-min chunk. No ffmpeg: merges are stubbed.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "backend_host", "scripts"))

from shared.src.lib.utils import storage_path_utils as spu  # noqa: E402
import hot_cold_archiver as archiver  # noqa: E402

SEG = 0.4


@pytest.fixture
def hot(tmp_path, monkeypatch):
    hot_dir = tmp_path / 'hot'
    hot_dir.mkdir()
    now = time.time()
    segs = []
    for i in range(100):  # 40 s of HOT ending now
        p = hot_dir / f'segment_{i:09d}.ts'
        p.write_bytes(b'ts%d' % i)
        m = now - (99 - i) * SEG
        os.utime(p, (m, m))
        segs.append(str(p))
    merged = {}

    def fake_cold(device, start, seconds, scratch_dir=None):
        for s in segs:  # the archiver archives this minute and deletes its HOT segments
            os.remove(s)
        out = tmp_path / 'cold.mp4'
        out.write_bytes(b'cold')
        return str(out), {'start_ts': start.timestamp(), 'end_ts': start.timestamp() + seconds, 'gaps': []}

    def fake_merge(files, output, scratch_dir=None):
        merged['inputs'] = list(files)
        merged['readable'] = all(os.path.exists(f) for f in files)
        with open(output, 'wb') as f:
            f.write(b'hot')
        return output

    def fake_concat(files, output):
        with open(output, 'wb') as f:
            f.write(b'final')
        return output

    monkeypatch.setattr(spu, 'get_segments_path', lambda d: str(hot_dir))
    monkeypatch.setattr(spu, 'get_video_scratch_dir', lambda d: str(tmp_path))
    monkeypatch.setattr(spu, 'get_device_segment_duration', lambda d: SEG)
    monkeypatch.setattr(spu, '_extract_from_cold_chunks', fake_cold)
    monkeypatch.setattr(spu, '_merge_segments_to_mp4', fake_merge)
    monkeypatch.setattr(spu, '_concat_videos', fake_concat)
    monkeypatch.setattr(spu, '_summarize_report_video', lambda *a, **k: None)
    return {'dir': str(hot_dir), 'tmp': tmp_path, 'merged': merged}


def test_hot_tail_survives_archiver_deleting_it_during_cold_read(hot):
    start = datetime.now() - timedelta(seconds=90)  # older than HOT: COLD must fill
    out = str(hot['tmp'] / 'report.mp4')
    assert spu.extract_test_video_hybrid('capture1', start, 85, out, lead_seconds=0) == out
    assert hot['merged']['readable']
    assert len(hot['merged']['inputs']) > 90


def test_pin_dir_is_removed_after_the_build(hot):
    start = datetime.now() - timedelta(seconds=90)
    spu.extract_test_video_hybrid('capture1', start, 85, str(hot['tmp'] / 'report.mp4'), lead_seconds=0)
    assert not [n for n in os.listdir(hot['dir']) if n.startswith('.pin_report_')]


def test_archiver_deletes_hot_batch_after_the_minute_is_archived(tmp_path, monkeypatch):
    seg = tmp_path / 'segment_000000001.ts'
    seg.write_bytes(b'x')
    seen = {}

    def fake(capture_dir, ram_mode, hot_batch):
        hot_batch.append(str(seg))
        seen['present_during_append'] = seg.exists()
        return 'one_min.mp4', 'chunk.mp4', False

    monkeypatch.setattr(archiver, '_archive_hot_minute', fake)
    assert archiver.archive_hot_minute(str(tmp_path), True)[1] == 'chunk.mp4'
    assert seen['present_during_append'] and not seg.exists()


def test_archiver_deletes_hot_batch_even_when_the_append_fails(tmp_path, monkeypatch):
    seg = tmp_path / 'segment_000000001.ts'
    seg.write_bytes(b'x')

    def boom(capture_dir, ram_mode, hot_batch):
        hot_batch.append(str(seg))
        raise OSError('no space')

    monkeypatch.setattr(archiver, '_archive_hot_minute', boom)
    with pytest.raises(OSError):
        archiver.archive_hot_minute(str(tmp_path), True)
    assert not seg.exists()  # never left behind to be archived a second time
