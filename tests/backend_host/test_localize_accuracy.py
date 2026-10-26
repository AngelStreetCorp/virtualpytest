"""Localize accuracy levers (TASK-110): a nav single decided without Jev, the all-region tie-break,
a plate over a node match, a slow live scene. Fakes and synthetic frames only.
"""
import importlib

import cv2
import numpy as np
import pytest

lv = importlib.import_module('shared.src.lib.utils.localize_verdict')
ssc = importlib.import_module('shared.src.lib.ai.screen_state_cv')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
jev = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')

pytestmark = pytest.mark.unit

H = ih.ImageHelpers(None, None)


def screen(seed):
    """A busy, textured UI-like page: distinct per seed, stable for the same seed."""
    rng = np.random.default_rng(seed)
    img = np.full((360, 640, 3), 70, dtype=np.uint8)
    for _ in range(40):
        x, y = int(rng.integers(0, 600)), int(rng.integers(0, 330))
        w, h = int(rng.integers(20, 120)), int(rng.integers(10, 60))
        img[y:y + h, x:x + w] = int(rng.integers(90, 250))
    return img


def fp_of(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {'v': 6, 'dhash': H._dhash_hex(gray), 'regions': H._region_dhashes(gray), 'focus': {'kind': 'none'}}


def with_popup(img):
    out = (img * 0.15).astype(np.uint8)
    out[110:250, 200:440] = 230
    out[150:160, 230:410] = 40
    return out


NODES = [{'node_id': f'n{i}', 'label': f'screen{i}', 'fingerprint': fp_of(screen(i))} for i in range(4)]


# ---------------------------------------------------------------- lever 1: nav single

def _nav(monkeypatch, cands):
    """identify_screen on the nav path with the matcher's candidates fixed (no OCR: no title)."""
    monkeypatch.setattr(H, '_focus_signature', lambda img: {'kind': 'nav', 'x': 0.2, 'width': 0.05})
    monkeypatch.setattr(H, '_focus_crop_hex', lambda img: None)
    monkeypatch.setattr(H, 'match_fingerprint_v6', lambda *a: {'candidates': [dict(c) for c in cands],
                                                                'excluded_count': 0, 'total': 4})
    monkeypatch.setattr(H, '_title_text', lambda img: '')
    return H.identify_screen(screen(0), NODES)['candidates']


def test_nav_single_that_alone_qualifies_is_not_left_to_jev(monkeypatch):
    # node_0019 on stb3_autobuild: a sibling shares the tab 17 bits away, its 2nd region 78 off
    cands = _nav(monkeypatch, [{'node_id': 'n0', 'label': 'a', 'dist': 0, 'dhash_dist': 0, 'nav_second': 0},
                               {'node_id': 'n1', 'label': 'b', 'dist': 17, 'dhash_dist': 17, 'nav_second': 78}])
    assert [c['node_id'] for c in cands] == ['n0']
    assert cands[0]['confidence'] == H.FP_NAV_UNIQUE_CONFIDENCE
    assert jev.loc_band(cands) == 'single'


def test_nav_single_with_a_qualifying_sibling_stays_borderline(monkeypatch):
    # two siblings are the same screen by v5's rule; door 5 keeps one, but the title did not decide
    cands = _nav(monkeypatch, [{'node_id': 'n0', 'label': 'a', 'dist': 0, 'dhash_dist': 0, 'nav_second': 0},
                               {'node_id': 'n1', 'label': 'b', 'dist': 8, 'dhash_dist': 8, 'nav_second': 10}])
    assert [c['node_id'] for c in cands] == ['n0'] and cands[0]['confidence'] == 0.6
    assert jev.loc_band(cands) == 'low-confidence'


def test_nav_single_far_from_chrome_stays_borderline(monkeypatch):
    cands = _nav(monkeypatch, [{'node_id': 'n0', 'label': 'a', 'dist': 20, 'dhash_dist': 20, 'nav_second': 25}])
    assert cands[0]['confidence'] == 0.6


# ---------------------------------------------------------------- lever 2: ties

def test_tie_on_the_best_region_is_broken_by_every_region():
    """Same screen, focus on another tile: the chrome ties, the moved tile decides."""
    base = screen(5)
    moved = base.copy()
    moved[120:200, 300:420] = 250                     # the focused tile is elsewhere
    nodes = [{'node_id': 'other_focus', 'label': 'x', 'fingerprint': fp_of(moved)},
             {'node_id': 'this_focus', 'label': 'x', 'fingerprint': fp_of(base)}]
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    res = H.match_fingerprint_v5(gray, H._region_dhashes(gray), {'kind': 'none'}, nodes)
    assert [c['node_id'] for c in res['candidates']][0] == 'this_focus'
    assert res['candidates'][0]['all'] < res['candidates'][1]['all']


# ---------------------------------------------------------------- lever 3: plate over a node

class _Helpers:
    def __init__(self, in_node):
        self.in_node = in_node

    def plate_in_node(self, img, box, fp):
        return self.in_node

    def match_under_plate(self, img, box, node_fps):
        return {'node_id': 'n1', 'label': 'screen1', 'confidence': 0.9}


NODE = {'kind': 'node', 'node_id': 'n1', 'label': 'screen1', 'confidence': 0.9, 'evidence': {}}


def test_a_popup_over_a_node_match_is_an_overlay(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('popup', (0.3, 0.3, 0.4, 0.4)))
    v = lv.after_match(NODE, None, NODES, _Helpers(in_node=False))
    assert (v['kind'], v['node_id'], v['evidence']['matched']) == ('overlay', 'n1', 'n1')


def test_a_plate_the_node_itself_shows_keeps_the_node(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('keyboard', (0.0, 0.6, 1.0, 0.4)))
    assert lv.after_match(NODE, None, NODES, _Helpers(in_node=True)) is NODE


def test_no_plate_check_on_a_moving_frame_or_a_tooltip(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: pytest.fail('overlay must not run'))
    assert lv.after_match(NODE, None, NODES, _Helpers(False), motion={'pct': 4.0}) is NODE
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('tooltip', (0.1, 0.1, 0.05, 0.05)))
    assert lv.after_match(NODE, None, NODES, _Helpers(False)) is NODE


def test_plate_in_node_on_real_frames():
    """A popup drawn over screen 2 is new; the node whose own screenshot has it keeps it."""
    img = with_popup(screen(2))
    box = ssc.overlay_plate(img)[1]
    assert not H.plate_in_node(img, box, NODES[2]['fingerprint'])
    assert H.plate_in_node(img, box, fp_of(img))


# ---------------------------------------------------------------- lever 4: slow live

LIVE = {'node_id': 'live', 'label': 'live'}
UNKNOWN = lv.unknown_verdict({'reason': 'x'})


@pytest.mark.parametrize('motion, live', [
    ({'kind': 'minor', 'pct': 5.3, 'pairs': ['minor', 'minor'], 'pair_pcts': [5.1, 5.3]}, True),   # presenter
    ({'kind': 'minor', 'pct': 2.8, 'pairs': ['minor', 'minor'], 'pair_pcts': [1.7, 2.8]}, False),  # too quiet
    ({'kind': 'box', 'pct': 6.0, 'pairs': ['box', 'minor'], 'pair_pcts': [6.0, 3.0]}, False),     # trailer on a menu
    ({'kind': 'band', 'pct': 6.0, 'pairs': ['band', 'band'], 'pair_pcts': [6.0, 6.0]}, False),    # carousel
    ({'kind': 'minor', 'pct': 5.0, 'pairs': ['minor', 'static'], 'pair_pcts': [5.0, 0.2]}, False),  # ends still
    ({'pct': 5.0}, False),                                                                           # monitor: no pairs
])
def test_slow_live(monkeypatch, motion, live):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('none', None))
    v = lv.after_abstain(UNKNOWN, None, NODES, _Helpers(False), None, motion=motion, live_node=LIVE)
    assert (v['kind'] == 'live') is live


def test_slow_live_needs_a_live_node(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('none', None))
    motion = {'kind': 'minor', 'pct': 5.3, 'pairs': ['minor', 'minor'], 'pair_pcts': [5.1, 5.3]}
    assert lv.after_abstain(UNKNOWN, None, NODES, _Helpers(False), None, motion=motion)['kind'] == 'unknown'


def test_measure_motion_reports_every_pair():
    a = screen(1)
    b = np.clip(a.astype(int) + np.random.default_rng(3).integers(-60, 60, a.shape), 0, 255).astype(np.uint8)
    m = lv.measure_motion([a, b, a])
    assert len(m['pairs']) == 2 and len(m['pair_pcts']) == 2


def _shift(img, dx):
    return np.roll(img, dx, axis=1)


def _with_box(img, value):
    out = img.copy()
    out[20:70, 20:100] = value
    return out


def test_zap_out_of_live_onto_a_menu_box_is_not_live():
    """stb3 live -> home: the zap is still in the first pair, the menu's hero box in the last."""
    menu = screen(5)
    m = lv.measure_motion([screen(9), _with_box(menu, 10), _with_box(menu, 250)])
    assert m['pairs'] == ['full', 'box']
    assert m['kind'] == 'change'


def test_live_video_keeps_full_motion():
    a = screen(1)
    m = lv.measure_motion([a, _shift(a, 40), _shift(a, 80)])
    assert m['pairs'] == ['full', 'full'] and m['kind'] == 'full'
