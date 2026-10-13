"""The archiver names each 1-min batch after the minute it was recorded in (BUG-0277).

The fast loop merges the oldest 150 HLS segments (60 s) whenever enough exist, on cycles of
30 s + the cycle's own work. Naming the slot and the 10-min chunk after the clock at merge
time put two merges in one clock minute and none in the next under load: slot N written twice,
N+1 skipped, chunks of 9 and 11 minutes. Pure simulation, no ffmpeg.
"""
import os
import random
import sys
from datetime import datetime

_test_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "backend_host", "scripts"))

import hot_cold_archiver as archiver  # noqa: E402
from shared.src.lib.utils.storage_path_utils import calculate_chunk_location  # noqa: E402

SEG = 0.4
BATCH = 150


def _run(hours=3, seed=7):
    """Simulate ffmpeg + a loaded fast loop. Returns [(merge_wall_time, batch_minute)]."""
    rng = random.Random(seed)
    start = datetime(2026, 10, 4, 7, 0, 13).timestamp()  # arbitrary phase vs the minute
    on_disk, next_seg, t, merges = [], start, start, []
    while t < start + hours * 3600:
        while next_seg <= t:  # segments ffmpeg finished by now
            on_disk.append(next_seg)
            next_seg += SEG
        work = rng.uniform(2, 25)  # loaded Pi: cycles take 32-55 s
        minute = archiver.batch_minute(on_disk, BATCH)
        if minute is not None:
            on_disk = sorted(on_disk)[BATCH:]  # merge deletes the batch
            merges.append((t + work * rng.random(), minute))
        t += 30 + work
    return merges


def _slot_steps(slots):
    return [(b - a) % 10 for a, b in zip(slots, slots[1:])]


def test_slots_advance_one_per_merge():
    merges = _run()
    assert len(merges) > 170
    assert set(_slot_steps([m.minute % 10 for _, m in merges])) == {1}


def test_merge_clock_repeats_and_skips_slots():
    # The old naming, same schedule: the defect this guards against.
    merges = _run()
    steps = _slot_steps([datetime.fromtimestamp(t).minute % 10 for t, _ in merges])
    assert 0 in steps and any(s > 1 for s in steps)


def test_every_closed_chunk_gets_ten_minutes():
    per_chunk = {}
    for _, m in _run():
        key = calculate_chunk_location(m)
        per_chunk[key] = per_chunk.get(key, 0) + 1
    closed = list(per_chunk.values())[1:-1]  # first and last chunk are partial
    assert closed and set(closed) == {10}


def test_not_enough_segments():
    assert archiver.batch_minute([1.0] * (BATCH - 1), BATCH) is None


def test_middle_segment_names_the_minute():
    t0 = datetime(2026, 10, 4, 7, 56, 40).timestamp()  # 20 s in 07:56, 40 s in 07:57
    batch = [t0 + i * SEG for i in range(BATCH)]
    assert archiver.batch_minute(batch, BATCH) == datetime(2026, 10, 4, 7, 57)


# --- BUG-0291: a late cycle drains every waiting minute instead of losing one ---------------

CEILING = 300  # ffmpeg keeps list_size + delete_threshold segments, deletes the oldest beyond


def _run_late(monkeypatch, catch_up, hours=3, seed=11, ceiling=CEILING, stall=(40, 60)):
    """ffmpeg + the real process_hot_storage loop, with archive_hot_minute simulated on a
    segment list. A cycle's work is 2-25 s, one in eight 40-60 s (a 14 s append on each of
    four captures under load; vpt-pi1's longest gap was 114 s), and the next cycle starts
    max(30 s, work + 5 s) after the last. catch_up=False replays the old code: one minute per
    cycle, 30 s sleep after the work, unpinned merges. Returns the archived batch minutes."""
    rng = random.Random(seed)
    start = datetime(2026, 10, 4, 10, 0, 7).timestamp()
    state = {"disk": [], "next": start, "t": start}
    minutes = []

    def produce():
        while state["next"] <= state["t"]:
            state["disk"].append(state["next"])
            state["next"] += SEG
        del state["disk"][:-ceiling]  # ffmpeg delete_segments past its ceiling

    def fake_minute(capture_dir, ram_mode):
        produce()
        disk = state["disk"]
        minute = archiver.batch_minute(disk, BATCH)
        if minute is None:
            return None, None, False
        if not catch_up and len(disk) >= ceiling and rng.random() < 0.75:
            return None, None, False  # old code: an unpinned concat at the ceiling mostly failed
        del disk[:BATCH]
        minutes.append(minute)
        state["t"] += rng.uniform(1, 4)  # the merge + append take time; ffmpeg keeps writing
        return "1min.mp4", "chunk.mp4", len(disk) >= BATCH

    for name in ("cleanup_hot_files", "rotate_hot_captures", "clean_old_thumbnails", "sweep_stale_hot_files"):
        monkeypatch.setattr(archiver, name, lambda *a, **k: 0)
    monkeypatch.setattr(archiver, "ARCHIVE_CAPTURES", False)
    monkeypatch.setattr(archiver, "cleanup_temp_files", lambda *a: (0, 0, 0))
    monkeypatch.setattr(archiver, "is_ram_mode", lambda *a: True)
    monkeypatch.setattr(archiver, "archive_hot_minute", fake_minute)
    if not catch_up:
        monkeypatch.setattr(archiver, "MAX_MINUTES_PER_CYCLE", 1)

    while state["t"] < start + hours * 3600:
        t0 = state["t"]
        archiver.process_hot_storage("/x/capture3")
        work = state["t"] - t0 + (rng.uniform(*stall) if rng.random() < 1 / 8 else rng.uniform(2, 25))
        state["t"] = t0 + work + (archiver.hot_cycle_sleep(work) if catch_up else 30)
    return minutes


def _gaps(minutes):
    return sum(len(archiver.lost_minutes(a, b)) for a, b in zip(minutes, minutes[1:]))


def test_late_cycles_lose_minutes_without_catch_up(monkeypatch):
    assert _gaps(_run_late(monkeypatch, catch_up=False)) > 0


def test_late_cycles_lose_nothing_with_catch_up(monkeypatch):
    minutes = _run_late(monkeypatch, catch_up=True)
    assert len(minutes) > 170
    assert _gaps(minutes) == 0
    assert set(_slot_steps([m.minute % 10 for m in minutes])) == {1}


def test_lost_minutes_names_the_gap():
    a = datetime(2026, 10, 4, 10, 5)
    assert archiver.lost_minutes(None, a) == []
    assert archiver.lost_minutes(a, datetime(2026, 10, 4, 10, 6)) == []
    assert archiver.lost_minutes(a, datetime(2026, 10, 4, 10, 8)) == [datetime(2026, 10, 4, 10, 6), datetime(2026, 10, 4, 10, 7)]


# --- BUG-0297: more segments on disk so a cycle 2+ minutes late still loses nothing ---------

def test_two_minute_stalls_lose_minutes_at_300_but_not_at_600(monkeypatch):
    # 150 + 150 segments (120 s) on disk: a finished minute survives 60-120 s, so a cycle
    # 100-150 s late loses part of it even with catch-up. 150 + 450 (240 s) keeps it.
    assert _gaps(_run_late(monkeypatch, catch_up=True, ceiling=300, stall=(100, 150))) > 0
    minutes = _run_late(monkeypatch, catch_up=True, ceiling=600, stall=(100, 150))
    assert len(minutes) > 170 and _gaps(minutes) == 0


def test_safety_limit_stays_above_what_ffmpeg_keeps():
    # The archiver's segment safety cleanup must never delete what ffmpeg still keeps, or it
    # deletes the oldest minutes before they are merged (BUG-0230). An HLS writer keeps its
    # playlist plus min(delete_threshold, playlist) segments past it (ffmpeg 5.1 hlsenc).
    import re
    sh = open(os.path.join(_root, "backend_host", "scripts", "run_ffmpeg.sh")).read()
    pairs = [(int(a), int(b)) for a, b in re.findall(r"-hls_list_size (\d+) -hls_delete_threshold (\d+)", sh)]
    assert "-hls_list_size $stream_hls_list -hls_delete_threshold $stream_hls_list" in sh
    pairs += [(int(x), int(x)) for x in re.findall(r"stream_hls_list=(\d+)", sh)]
    assert len(pairs) >= 5
    on_disk = [n + min(t, n) for n, t in pairs]
    assert max(on_disk) == 600  # 300 x 0.4 s listed + 300 past the playlist = 240 s (BUG-0297)
    assert archiver.HOT_LIMITS["segments"] > max(on_disk)
