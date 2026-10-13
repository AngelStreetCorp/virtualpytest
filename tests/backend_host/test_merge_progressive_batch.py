"""merge_progressive_batch survives segments that vanish under it (BUG-0230, BUG-0291).

ffmpeg's delete_segments removed the oldest HLS segments while the archiver was
concatenating them into the 1-min MP4: the concat failed and the whole minute was
lost from the 10-min archive chunk. Real ffmpeg, tiny generated .ts segments.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.utils import video_utils  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _segments(d, n, src="testsrc=size=64x36:rate=10"):
    # One HLS writer, like run_ffmpeg.sh: consecutive 0.4 s segments with continuous timestamps.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", f"{n * 0.4:.1f}",
                    "-c:v", "libx264", "-x264opts", "keyint=4:min-keyint=4:no-scenecut:bframes=0",
                    "-f", "hls", "-hls_time", "0.4", "-hls_list_size", "0", "-hls_flags", "split_by_time",
                    "-hls_segment_filename", str(d / "segment_%09d.ts"), str(d / "out.m3u8")], check=True)
    (d / "out.m3u8").unlink()
    segs = sorted(d.glob("segment_*.ts"))
    assert len(segs) == n
    for i, p in enumerate(segs):
        t = time.time() - 100 + i
        os.utime(p, (t, t))
    return segs


def _duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def test_merges_oldest_count_in_order(tmp_path):
    _segments(tmp_path, 6)
    out = video_utils.merge_progressive_batch(str(tmp_path), "segment_*.ts", str(tmp_path / "m.mp4"), 4, True, 20, skip_faststart=True)
    assert out and _duration(out) == pytest.approx(1.6, abs=0.15)
    assert sorted(p.name for p in tmp_path.glob("segment_*.ts")) == ["segment_000000004.ts", "segment_000000005.ts"]


def test_segment_deleted_during_merge_keeps_the_rest(tmp_path, monkeypatch):
    # At ffmpeg's on-disk ceiling the writer deletes the oldest segment every 0.4 s, so it
    # always lands inside the concat. The batch is pinned with hard links first (BUG-0291):
    # the whole minute is merged, and the originals still go.
    _segments(tmp_path, 5)
    real = video_utils.merge_video_files
    calls = []

    def racing_merge(files, *a, **kw):
        calls.append(list(files))
        os.remove(tmp_path / os.path.basename(files[0]))   # the writer deletes the oldest original
        return real(files, *a, **kw)

    monkeypatch.setattr(video_utils, "merge_video_files", racing_merge)
    out = video_utils.merge_progressive_batch(str(tmp_path), "segment_*.ts", str(tmp_path / "m.mp4"), 4, True, 20, skip_faststart=True)
    assert out and len(calls) == 1 and len(calls[0]) == 4
    assert _duration(out) == pytest.approx(1.6, abs=0.15)
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "m.mp4") == ["segment_000000004.ts"]


def test_segment_gone_before_the_merge_is_skipped(tmp_path, monkeypatch):
    _segments(tmp_path, 5)
    real_link = os.link

    def link(src, dst):
        if src.endswith("segment_000000000.ts"):
            os.remove(src)               # deleted between the listing and the pin
        return real_link(src, dst)

    monkeypatch.setattr(video_utils.os, "link", link)
    out = video_utils.merge_progressive_batch(str(tmp_path), "segment_*.ts", str(tmp_path / "m.mp4"), 4, True, 20, skip_faststart=True)
    assert out and _duration(out) == pytest.approx(1.2, abs=0.15)


def test_not_enough_segments_is_not_a_merge(tmp_path):
    _segments(tmp_path, 2)
    assert video_utils.merge_progressive_batch(str(tmp_path), "segment_*.ts", str(tmp_path / "m.mp4"), 4, True, 20) is None


def test_tiny_static_segments_merge(tmp_path):
    # A black or frozen picture at the live tier's 320x180 / 150k encodes to ~1.5 KB per
    # 0.4 s segment: under the 10 TS packets ffmpeg's mpegts probe needs, so the concat
    # demuxer took each file for MPEG-PS and every minute failed (capture_switch1, BUG-0298).
    segs = _segments(tmp_path, 6, src="color=black:size=320x180:rate=10")
    assert max(p.stat().st_size for p in segs[1:]) < 1880
    out = video_utils.merge_progressive_batch(str(tmp_path), "segment_*.ts", str(tmp_path / "m.mp4"), 5, True, 20, skip_faststart=True)
    assert out and _duration(out) == pytest.approx(2.0, abs=0.15)
