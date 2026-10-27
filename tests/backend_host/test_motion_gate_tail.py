"""TASK-107 goal 6: the monitor's motion gate, end to end on MonitorLocalizer (fakes only).

The 1 Hz matcher is skipped on live / moving frames, forced ONCE after 1.5 s of stillness,
never gated on a dHash delta (an app-grid focus move is ~3 bits), and the gate logs on change
plus a 30 s heartbeat. A gate-skip payload carries the v3 verdict and no Tier-2 fields.
"""
import importlib

import cv2
import numpy as np
import pytest

ml = importlib.import_module('backend_host.scripts.monitor_localize')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')

pytestmark = pytest.mark.unit

LIVE = {'kind': 'full', 'state': 'live', 'pct': 30.0}
BAND_UI = {'kind': 'band', 'state': 'ui', 'pct': 6.0}
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
    m._live_node = lambda ui: {'node_id': 'n-live', 'label': 'live'}
    m._ui_meta = lambda ui: {}
    m.calls = []

    class Matcher(ih.ImageHelpers):
        def identify_screen(self, img, node_fps):
            m.calls.append(int(img.sum()) % 997)
            return {'candidates': [{'node_id': 'n1', 'label': 'home', 'confidence': 0.95}],
                    'excluded_count': 0, 'total': 1}
    m._get_helpers = lambda: Matcher(None, None)
    frame = tmp_path / 'f.jpg'
    img = np.full((180, 320, 3), 90, dtype=np.uint8)
    img[20:60, 20:120] = 220
    cv2.imwrite(str(frame), img)
    m.frame, m.clock, m.img = str(frame), clock, img
    return m


def test_live_frames_skip_the_matcher_and_answer_live(mon):
    out = mon.localize_frame('device3', mon.frame, motion=LIVE)
    assert out['gate_skip'] == 'live' and out['kind'] == 'live' and out['node'] == 'live'
    assert mon.calls == []
    assert not {'loaded', 'overlay', 'playback', 'error'} & set(out)      # no Tier 2 on a skipped frame


def test_forced_rematch_once_after_settle(mon):
    """live -> ui edge: a carousel (band) is gated, except ONE forced matcher run once the new
    state has been held 1.5 s; after that the carousel is gated again until the next edge."""
    mon.localize_frame('device3', mon.frame, motion=STATIC)           # first sight: a cached match
    assert len(mon.calls) == 1
    for _ in range(3):
        mon.clock.t += 0.3
        assert mon.localize_frame('device3', mon.frame, motion=LIVE)['gate_skip'] == 'live'
    mon.clock.t += 0.3
    assert mon.localize_frame('device3', mon.frame, motion=BAND_UI)['gate_skip'] == 'motion'   # edge, 0 s held
    mon.clock.t += 1.0
    assert mon.localize_frame('device3', mon.frame, motion=BAND_UI)['gate_skip'] == 'motion'   # 1.0 s < 1.5 s
    assert len(mon.calls) == 1
    mon.clock.t += 0.6
    out = mon.localize_frame('device3', mon.frame, motion=BAND_UI)                             # 1.6 s: forced
    assert 'gate_skip' not in out and out['kind'] == 'node' and len(mon.calls) == 2
    for _ in range(3):
        mon.clock.t += 1.0
        assert mon.localize_frame('device3', mon.frame, motion=BAND_UI)['gate_skip'] == 'motion'
    assert len(mon.calls) == 2                                          # one-shot per edge


def test_no_dhash_gate_a_small_focus_move_reaches_the_matcher(mon):
    """Two still frames ~a few dHash bits apart (a focus move on an app grid): both are matched."""
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    moved = mon.img.copy()
    moved[20:60, 20:120] = 90
    moved[20:60, 130:230] = 220                                        # the focus box moved one tile
    cv2.imwrite(mon.frame, moved)
    mon.clock.t += 1.0
    mon.localize_frame('device3', mon.frame, motion=STATIC)
    assert len(mon.calls) == 2 and mon.calls[0] != mon.calls[1]


def test_gate_log_on_change_plus_heartbeat(mon, monkeypatch):
    lines = []
    monkeypatch.setattr(ml.logger, 'info', lambda msg, *a, **k: lines.append(msg))
    for _ in range(10):                                                # 10 live ticks in 9 s
        mon.localize_frame('device3', mon.frame, motion=LIVE)
        mon.clock.t += 1.0
    assert len(lines) == 1 and 'on-change' in lines[0]
    mon.clock.t += ml._GATE_LOG_HEARTBEAT_SECONDS
    mon.localize_frame('device3', mon.frame, motion=LIVE)
    assert len(lines) == 2 and 'heartbeat' in lines[1] and 'frames=' in lines[1]
    mon.localize_frame('device3', mon.frame, motion=STATIC)            # matcher ran: cached match exists
    mon.localize_frame('device3', mon.frame, motion=BAND_UI)
    assert 'gate=motion' in lines[-1] and 'on-change' in lines[-1]


def test_a_hero_trailer_behind_a_menu_is_not_live(mon):
    """stb-testop home: the trailer gives static / box / full frames in turn. A single raw 'full' frame
    keeps the matched screen (gate 'motion'); live needs LIVE_WINDOW moving ticks in a row."""
    mon.localize_frame('device3', mon.frame, motion=STATIC)                       # home matched
    out = mon.localize_frame('device3', mon.frame, motion={'kind': 'full', 'state': 'ui', 'pct': 9.0})
    assert out['gate_skip'] == 'motion' and out['kind'] == 'node' and out['node'] == 'home'
    for _ in range(2):
        out = mon.localize_frame('device3', mon.frame, motion={'kind': 'full', 'state': 'ui', 'pct': 9.0})
    assert out['gate_skip'] == 'live' and out['kind'] == 'live'                     # sustained: live
    assert ml.live_by_window(['full', 'minor', 'full']) and not ml.live_by_window(['full', 'static', 'full'])
