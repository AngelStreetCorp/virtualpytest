"""The video-vs-UI partition of the `no qualifying screen` bucket (TASK-68 row 7,
EXPERIMENT-01's stop condition).

The abstain histogram said ~89% of content abstains exit at v5 `no qualifying
screen`. Whether that justifies building a local semantic model depends entirely on
WHAT those frames are: broadcast video is a Tier 2 question (deterministic frame
difference), unnamed UI is a Tier 3 one. `video_vs_ui.py` answers that by measuring
adjacent-frame motion and by dumping the static residue out to be looked at.

Both of this module's two easy-to-get-wrong decisions are pinned here:

  * the floor is a PERCENTAGE (0.8, not 0.008, not 80) — `changed_pct`/`diff_percentage`
    from `freeze_facts.compare` and `detector.detect_freeze` are 0-100;
  * "adjacent" means consecutive frames inside one window, never an even stride over
    the archive — comparing frames minutes apart answers a different question than the
    one production asks.

Fakes only — no device, no DB, no network. The matcher is the REAL ImageHelpers.
"""
import importlib.util
import os
import sys

import cv2
import numpy as np
import pytest

_LOCALIZE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'features', 'avq', 'backend_host', 'localize'))


def _load(name):
    """The replay scripts live under features/ (not an importable package) — load by path."""
    path = os.path.join(_LOCALIZE, name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vvu = _load('video_vs_ui.py')


# ── the floor: detector.py:59 says "0.8% pixel difference = frozen" ───────────────────

def test_the_floor_matches_detector_freeze_threshold():
    """Guarding the NUMBER. Its unit is pinned by the next test."""
    assert vvu.VIDEO_FLOOR_PCT == 0.8


def test_a_frame_pair_difference_is_a_percentage_not_a_fraction():
    """The unit. `_masked_grey`-style helpers and detector both return 0-100, so a frame
    that differs entirely reads 100.0 — a floor of 0.8 compared against a fraction would
    call every moving frame frozen."""
    black = np.zeros((200, 300), np.uint8)
    white = np.full((200, 300), 255, np.uint8)
    assert vvu.diff_pct(black, black) == 0.0
    assert vvu.diff_pct(black, white) == pytest.approx(100.0, abs=0.5)


def test_a_half_blackened_frame_reads_fifty_percent():
    a = np.full((200, 300), 128, np.uint8)
    b = a.copy()
    b[:, :150] = 0
    assert vvu.diff_pct(a, b) == pytest.approx(50.0, abs=0.5)


def test_frames_of_different_sizes_are_unknown_not_zero():
    """compare() resizes before diffing; returning 0.0 for a size mismatch would make an
    unreadable frame look FROZEN, which is the one direction that must never be silent."""
    a = np.zeros((200, 300), np.uint8)
    assert vvu.diff_pct(a, None) is None
    assert vvu.diff_pct(a, np.zeros((10, 10), np.uint8)) is None


def test_small_changes_are_below_the_floor_and_a_cut_is_above_it():
    """The threshold discriminates. A 1-in-1000 salt-and-pepper difference is noise;
    a 10% band is motion."""
    a = np.full((200, 300), 128, np.uint8)
    noise = a.copy()
    noise[:, ::1000] = 255                       # ~0.03% of pixels
    assert vvu.diff_pct(a, noise) < vvu.VIDEO_FLOOR_PCT
    band = a.copy()
    band[:, :30] = 0                             # 10% of pixels
    assert vvu.diff_pct(a, band) >= vvu.VIDEO_FLOOR_PCT


# ── "adjacent" must mean adjacent ───────────────────────────────────────────────────

def _fake_tree(tmp_path, hours, per_hour):
    root = tmp_path / 'capture'
    for h in range(hours):
        d = root / ('%02d' % h)
        d.mkdir(parents=True)
        for i in range(per_hour):
            cv2.imwrite(str(d / ('capture_%04d.jpg' % i)),
                        np.full((40, 60, 3), 90, np.uint8))
    found = []
    for d in sorted(os.listdir(root)):
        for f in sorted(os.listdir(root / d)):
            found.append(str(root / d / f))
    return found


def test_windows_yield_contiguous_runs_not_an_even_stride(tmp_path):
    """A stride would compare frames minutes apart. `capture_0000,0001,...` ascending with
    no gaps is what makes 'the picture changed between these two frames' true."""
    paths = _fake_tree(tmp_path, hours=8, per_hour=40)
    wins = vvu.windows(paths, n_windows=4, per_window=6)
    assert len(wins) == 4
    for w in wins:
        idx = [int(os.path.basename(p)[8:12]) for p in w]
        assert idx == list(range(len(w))), idx
        assert len(w) == 6


def test_windows_spread_across_the_whole_archive(tmp_path):
    """Not just the oldest hour — the sample has to cover the archive."""
    paths = _fake_tree(tmp_path, hours=12, per_hour=30)
    wins = vvu.windows(paths, n_windows=4, per_window=3)
    dirs = {os.path.basename(os.path.dirname(w[0])) for w in wins}
    assert len(dirs) == 4, dirs


def test_avq_motion_crop_tiles_are_excluded(tmp_path):
    """AVQ writes `motion_crop*` analysis TILES beside the captures. They are not 16:9
    frames, and motion on a tile answers a different question -- two of them landed in the
    static bucket by accident before this filter existed. `text_source_image*` UI
    screenshots are excluded for the same reason: real UI pixels that are not captures."""
    root = tmp_path / 'capture' / '00'
    root.mkdir(parents=True)
    cv2.imwrite(str(root / 'capture_0000.jpg'), np.full((40, 60, 3), 90, np.uint8))
    cv2.imwrite(str(root / 'capture_0001.jpg'), np.full((40, 60, 3), 90, np.uint8))
    cv2.imwrite(str(root / 'motion_crop1_1790667210552.png'), np.full((30, 30, 3), 90, np.uint8))
    cv2.imwrite(str(root / 'motion_crop2_1790667210552.png'), np.full((30, 30, 3), 90, np.uint8))
    cv2.imwrite(str(root / 'text_source_image_0_1791264198054.jpg'),
                np.full((40, 60, 3), 90, np.uint8))
    paths = [str(p) for p in sorted(root.iterdir())]
    wins = vvu.windows(paths, n_windows=1, per_window=10)
    assert len(wins) == 1
    for w in wins:
        names = [os.path.basename(p) for p in w]
        assert names == ['capture_0000.jpg', 'capture_0001.jpg'], names


def test_a_window_shorter_than_two_frames_is_dropped(tmp_path):
    """One frame has no predecessor, so it carries no diff at all."""
    root = tmp_path / 'capture' / '00'
    root.mkdir(parents=True)
    cv2.imwrite(str(root / 'capture_0000.jpg'), np.full((40, 60, 3), 90, np.uint8))
    paths = [str(p) for p in sorted(root.iterdir())]
    assert vvu.windows(paths, n_windows=1, per_window=10) == []


# ── which abstain this is counting ───────────────────────────────────────────────────

def test_only_the_no_qualifying_screen_reason_counts_as_the_bucket():
    """The partition is scoped to ONE exit from match_fingerprint_v5. A frame that
    abstained at an earlier door, or at the confidence floor, is a different question
    and must not be folded in."""
    assert vvu.is_no_qualifying({'reason': 'no qualifying screen (best region 0.91)'})
    # v5 runs last, so a frame it empties carries it as the TERMINAL note — earlier doors
    # in the chain must not hide it.
    assert vvu.is_no_qualifying({'reason': 'nav underline far from chrome, no title match'
                                           ' +no qualifying screen (best region 0.91)'})
    assert not vvu.is_no_qualifying({'reason': 'nav underline far from chrome, no title match'})
    assert not vvu.is_no_qualifying({'reason': 'confidence floor: 1 candidate(s)'})
    assert not vvu.is_no_qualifying({'reason': ''})
    assert not vvu.is_no_qualifying({})


def test_a_capture_side_fault_is_named_separately_from_content():
    """`no_signal` is the capture card's test pattern, not an unidentified screen, and
    folds into it only when the STB is powered down. It is excluded from the split."""
    assert 'no_signal' in vvu.NAMED_STATES
    assert 'blackscreen' in vvu.NAMED_STATES


def test_percentiles_survive_an_empty_population():
    """One of the two Pi hosts had a single static frame; the report must not divide by zero."""
    assert vvu.pct([]) == {}
    p = vvu.pct([float(i) for i in range(1, 101)])
    assert p['p10'] == pytest.approx(11, abs=1)
    assert p['p50'] == pytest.approx(51, abs=1)
    assert p['max'] == pytest.approx(100, abs=1)