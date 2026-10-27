"""TASK-115: the monitor's unchanged-frame skip, end to end on MonitorLocalizer (fakes only).

A frame with no changed 4x4 cell against the last matched one serves the cached verdict (the
matcher does not run); one changed cell (an app-grid focus move) re-runs it; the matcher still
runs once per UNCHANGED_REFRESH_SECONDS on a still screen; the skip logs on change + heartbeat.
"""
import importlib

import cv2
import numpy as np
import pytest

ml = importlib.import_module('backend_host.scripts.monitor_localize')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')

pytestmark = pytest.mark.unit

STATIC = {'kind': 'static', 'state': 'static', 'pct': 0.0}
NODES = [{'node_id': 'n1', 'label': 'home', 'fingerprint': {'dhash': 'ab' * 32}}]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def mon(monkeypatch, tmp_path):
    clock = Clock()
    monkeypatch.setattr(ml.time, 'time', clock)
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
    m = ml.MonitorLocalizer(team_id='t1')
    m._resolve_ui = lambda d: ('ui', 'base')
    m._load_node_fps = lambda ui: NODES
    m._record_change = lambda *a, **k: None
    m._ui_meta = lambda ui: {}
    m.calls = []

    class Matcher(ih.ImageHelpers):
        def identify_screen(self, img, node_fps):
            m.calls.append(1)
            return {'candidates': [{'node_id': 'n1', 'label': 'home', 'confidence': 0.96}],
                    'excluded_count': 0, 'total': 1}
    m._get_helpers = lambda: Matcher(None, None)
    frame = tmp_path / 'f.png'
    img = np.full((720, 1280, 3), 90, dtype=np.uint8)
    for c in range(4):                                                 # an app grid: 4 tiles
        img[300:420, 80 + c * 300:320 + c * 300] = 140
    img[300:420, 80:320] = 230                                         # focus on tile 0
    cv2.imwrite(str(frame), img)
    m.frame, m.clock, m.img = str(frame), clock, img
    return m


def _tick(mon, seconds=1.0):
    mon.clock.t += seconds
    return mon.localize_frame('device3', mon.frame, motion=STATIC)


def test_still_screen_serves_the_cached_verdict(mon):
    first = mon.localize_frame('device3', mon.frame, motion=STATIC)
    outs = [_tick(mon) for _ in range(20)]
    assert len(mon.calls) == 1
    for out in outs:                                                   # the overlay never blinks
        assert out['verdict'] == first['verdict'] and out['node'] == 'home' and out['confidence'] == 0.96


def test_sensor_noise_is_unchanged(mon):
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    noisy = np.clip(mon.img.astype(int) + np.random.default_rng(1).integers(-6, 7, mon.img.shape), 0, 255)
    cv2.imwrite(mon.frame, noisy.astype(np.uint8))
    _tick(mon)
    assert len(mon.calls) == 1


def test_a_focus_move_reruns_the_matcher_once(mon):
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    moved = mon.img.copy()
    moved[300:420, 80:320] = 140
    moved[300:420, 380:620] = 230                                      # focus moved one tile right
    cv2.imwrite(mon.frame, moved)
    _tick(mon)
    assert len(mon.calls) == 2
    _tick(mon)
    assert len(mon.calls) == 2                                         # then still again


def test_refresh_bound_reruns_a_still_screen(mon):
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    for _ in range(int(ml.UNCHANGED_REFRESH_SECONDS) - 1):
        _tick(mon)
    assert len(mon.calls) == 1
    _tick(mon, 1.5)
    assert len(mon.calls) == 2                                         # ~2 runs/min on a still menu


def test_skip_logs_on_change_plus_heartbeat(mon, monkeypatch):
    lines = []
    monkeypatch.setattr(ml.logger, 'info', lambda msg, *a, **k: lines.append(msg))
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    for _ in range(10):
        _tick(mon)
    skips = [l for l in lines if 'gate=unchanged' in l]
    assert len(skips) == 1 and 'on-change' in skips[0]


def test_frame_unchanged_pure():
    a = np.full((180, 320), 100, dtype=np.uint8)
    b = a.copy()
    assert ml.frame_unchanged(a, b) and not ml.frame_unchanged(None, b)
    b[0:45, 0:80] = 200                                                # one 4x4 cell
    assert not ml.frame_unchanged(a, b)


# --- Moving-box skip (TASK-115 §5): a hero trailer in the top-right cells, the rest a still menu ---

def _trailer_frame(mon, tick, base=None):
    img = (mon.img if base is None else base).copy()
    rng = np.random.default_rng(tick)
    img[0:180, 640:1280] = rng.integers(0, 256, (180, 640, 3), dtype=np.uint8)   # 2 cells, every tick new
    cv2.imwrite(mon.frame, img)
    return img


def _settle_on_trailer(mon, ticks=8):
    for t in range(ticks):
        _trailer_frame(mon, t)
        _tick(mon)


def test_a_trailer_alone_stops_running_the_matcher(mon):
    _settle_on_trailer(mon, ml.MOVING_BOX_TICKS + 1)
    settled = len(mon.calls)
    assert settled == ml.MOVING_BOX_TICKS + 1                        # runs until the box is learned
    outs = []
    for t in range(100, 100 + int(ml.MOVING_BOX_REFRESH_SECONDS) - 2):
        _trailer_frame(mon, t)
        outs.append(_tick(mon))
    assert len(mon.calls) == settled                                 # trailer only: cached verdict
    assert all(o['node'] == 'home' and o['confidence'] == 0.96 for o in outs)
    for t in range(200, 204):
        _trailer_frame(mon, t)
        _tick(mon)
    assert len(mon.calls) == settled + 1                             # the refresh bound still runs it


def test_a_focus_move_beside_the_trailer_reruns_the_matcher(mon):
    _settle_on_trailer(mon)
    before = len(mon.calls)
    moved = mon.img.copy()
    moved[300:420, 80:320] = 140
    moved[300:420, 380:620] = 230                                     # app-grid focus one tile right
    _trailer_frame(mon, 50, base=moved)
    _tick(mon)
    assert len(mon.calls) == before + 1                               # on that very tick


def test_a_popup_larger_than_the_trailer_reruns_the_matcher(mon):
    _settle_on_trailer(mon)
    before = len(mon.calls)
    img = _trailer_frame(mon, 50)
    img[0:360, 480:1280] = 30                                         # dialog over the trailer and beyond
    cv2.imwrite(mon.frame, img)
    _tick(mon)
    assert len(mon.calls) == before + 1


def test_a_popup_covering_only_the_trailer_is_caught_next_tick(mon):
    _settle_on_trailer(mon)
    before = len(mon.calls)
    img = mon.img.copy()
    img[0:180, 640:1280] = 30                                         # opaque popup exactly on the box
    cv2.imwrite(mon.frame, img)
    _tick(mon)                                                        # looks like one more trailer frame
    _tick(mon)                                                        # box cells stopped moving
    assert len(mon.calls) == before + 1


def test_moving_box_skip_pure():
    none = np.zeros((4, 4), dtype=bool)
    box = none.copy()
    box[0, 2:4] = True
    inside, outside = box.copy(), box.copy()
    inside[0, 3] = False
    outside[2, 0] = True
    assert ml.moving_box_skip(inside, box, box)
    assert not ml.moving_box_skip(outside, box, box)                 # change beside the box
    assert not ml.moving_box_skip(inside, none, box)                 # box stopped moving (popup / freeze)
    assert not ml.moving_box_skip(inside, box, none)                 # box was not moving at the last run
    assert not ml.moving_box_skip(none, box, box) and not ml.moving_box_skip(None, box, box)
    big = np.ones((4, 4), dtype=bool)
    assert not ml.moving_box_skip(inside, big, big)                  # whole-frame motion: not a box


def test_trailer_cuts_do_not_force_a_matcher_run(mon):
    """stb-testop home: each trailer cut is a few gated motion frames, then a motion -> still edge
    whose forced settle tick sees only the trailer box changed: no matcher run."""
    _settle_on_trailer(mon, ml.MOVING_BOX_TICKS + 1)
    before = len(mon.calls)
    cut = {'kind': 'full', 'state': 'motion', 'pct': 40.0}
    t = 300
    for _ in range(2):                                                # two trailer cuts
        for _ in range(3):
            t += 1
            _trailer_frame(mon, t)
            mon.clock.t += 1
            mon.localize_frame('device3', mon.frame, motion=cut)
        for _ in range(3):                                            # settle: edge held 1.5 s -> forced tick
            t += 1
            _trailer_frame(mon, t)
            _tick(mon)
    assert len(mon.calls) == before
