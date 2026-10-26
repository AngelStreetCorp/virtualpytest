"""Localize v3 phases 2-3 and corrections (TASK-104 goals 9, 10, 11).

overlay (with the node under the plate) -> known_screen (TASK-84 screen memory) -> unknown, on an
abstain only; operator samples and negatives in the matcher; the audit list edits. Fakes only.
"""
import importlib

import cv2
import numpy as np
import pytest

lv = importlib.import_module('shared.src.lib.utils.localize_verdict')
ssc = importlib.import_module('shared.src.lib.ai.screen_state_cv')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
lvdb = importlib.import_module('shared.src.lib.database.localize_verdicts_db')

pytestmark = pytest.mark.unit

H = ih.ImageHelpers(None, None)
RNG = np.random.default_rng(11)


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
    """A centred bright plate over a dimmed page (the _dialog_plate shape)."""
    out = (img * 0.15).astype(np.uint8)          # a modal dims the page below the plate threshold
    out[110:250, 200:440] = 230
    out[150:160, 230:410] = 40
    return out


NODES = [{'node_id': f'n{i}', 'label': f'screen{i}', 'fingerprint': fp_of(screen(i))} for i in range(4)]


# ---------------------------------------------------------------- goal 9: overlay

def test_popup_is_detected_with_its_box():
    kind, box = ssc.overlay_plate(with_popup(screen(1)))
    assert kind == 'popup' and box and 0.2 < box[0] < 0.4
    assert ssc.overlay(with_popup(screen(1))) == 'popup'            # the old call answers the same


def test_the_screen_under_a_popup_is_matched():
    img = with_popup(screen(2))
    box = ssc.overlay_plate(img)[1]
    under = H.match_under_plate(img, box, NODES)
    assert 'center' not in under['regions'] and 'full' not in under['regions']
    assert under['node_id'] == 'n2'


def test_overlay_verdict_names_the_screen_under():
    v = lv.overlay_verdict('popup', (0.3, 0.3, 0.4, 0.4), {'node_id': 'n2', 'label': 'screen2', 'confidence': 0.9})
    assert (v['kind'], v['node_id'], v['label']) == ('overlay', 'n2', 'Popup over screen2')
    bare = lv.overlay_verdict('keyboard', None, None)
    assert (bare['node_id'], bare['label']) == (None, 'Keyboard')


# ---------------------------------------------------------------- goal 10: known screen

ROW = {'id': 's1', 'scope': 'vpt-pi1/device3', 'verdict': 'expected', 'seen_count': 42, 'label': None}


def test_known_screen_verdict_label():
    assert lv.known_screen_verdict(ROW, 4)['label'] == 'Known screen (expected, seen 42x)'
    assert lv.known_screen_verdict({**ROW, 'label': 'Netflix profile picker'}, 4)['label'] == 'Netflix profile picker'


# ---------------------------------------------------------------- the cascade after an abstain

class _Helpers:
    def __init__(self, under=None):
        self.under = under or {}

    def match_under_plate(self, img, box, node_fps):
        return self.under


UNKNOWN = lv.unknown_verdict({'reason': 'x'})


def test_after_abstain_order(monkeypatch):
    seen = []
    lookup = lambda img: seen.append('memory') or (ROW, 3)
    # overlay first: memory is not consulted
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('popup', (0.3, 0.3, 0.4, 0.4)))
    v = lv.after_abstain(UNKNOWN, None, NODES, _Helpers({'node_id': 'n1', 'label': 'screen1', 'confidence': 0.8}), lookup)
    assert v['kind'] == 'overlay' and v['node_id'] == 'n1' and seen == []
    # a tooltip is not a place: memory answers
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('tooltip', (0.1, 0.1, 0.05, 0.05)))
    assert lv.after_abstain(UNKNOWN, None, NODES, _Helpers(), lookup)['kind'] == 'known_screen'
    # nothing at all: unknown stays unknown
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('none', None))
    assert lv.after_abstain(UNKNOWN, None, NODES, _Helpers(), lambda img: None)['kind'] == 'unknown'


def test_after_abstain_never_overrides_an_answer(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: pytest.fail('overlay must not run'))
    node = {'kind': 'node', 'node_id': 'n1', 'label': 'screen1', 'confidence': 0.9, 'evidence': {}}
    assert lv.after_abstain(node, None, NODES, _Helpers(), None) is node


# ---------------------------------------------------------------- goal 11: samples and negatives

def test_extra_samples_expand_and_collapse_to_one_node():
    nodes = [{'node_id': 'n0', 'label': 'screen0',
              'fingerprint': {**NODES[0]['fingerprint'], 'title': 'home', 'extra': [fp_of(screen(9))]}}]
    expanded = H.expand_fingerprint_samples(nodes)
    assert [n['node_id'] for n in expanded] == ['n0', 'n0']
    assert expanded[1]['fingerprint']['title'] == 'home'           # title tie-break still applies
    result = {'candidates': [{'node_id': 'n0'}, {'node_id': 'n0'}, {'node_id': 'n1'}]}
    H._dedupe_by_node(result)
    assert [c['node_id'] for c in result['candidates']] == ['n0', 'n1']


def test_an_added_sample_makes_the_frame_match_its_node(monkeypatch):
    """The frame of screen 9 matches nothing; once it is added to n0 the matcher answers n0."""
    img = screen(9)
    before = H.identify_screen(img, NODES)
    assert not before.get('candidates')
    nodes = [dict(n) for n in NODES]
    nodes[0] = {**nodes[0], 'fingerprint': lvdb.add_sample(nodes[0]['fingerprint'], fp_of(img), 'v1')}
    after = H.identify_screen(img, nodes)
    assert [c['node_id'] for c in after['candidates']] == ['n0']


def test_a_negative_stops_the_node_claiming_the_frame():
    img = screen(1)
    assert [c['node_id'] for c in H.identify_screen(img, NODES)['candidates']] == ['n1']
    nodes = [dict(n) for n in NODES]
    nodes[1] = {**nodes[1], 'fingerprint': lvdb.add_negative(nodes[1]['fingerprint'], fp_of(img), 'v2')}
    result = H.identify_screen(img, nodes)
    assert not result.get('candidates') and 'operator negative' in result.get('reason', '')


def test_audit_list_edits_and_undo():
    base = {'dhash': 'ab', 'regions': {'top': 'cd'}}
    fp = lvdb.add_sample(base, {'dhash': 'ef', 'regions': {'top': 'gh'}, 'title': 'x'}, 'v1')
    fp = lvdb.add_negative(fp, {'dhash': 'ij', 'regions': {'top': 'kl'}}, 'v2')
    assert fp['extra'][0]['verdict_id'] == 'v1' and 'title' not in fp['extra'][0]
    assert lvdb.remove_verdict(fp, 'v1')['extra'] == [] and len(lvdb.remove_verdict(fp, 'v1')['negatives']) == 1
    for i in range(lvdb.MAX_EXTRA_SAMPLES + 3):
        fp = lvdb.add_sample(fp, {'regions': {'top': str(i)}}, f's{i}')
    assert len(fp['extra']) == lvdb.MAX_EXTRA_SAMPLES and fp['extra'][-1]['verdict_id'] == f's{lvdb.MAX_EXTRA_SAMPLES + 2}'


def test_record_correction_refuses_without_a_target():
    out = lvdb.record_correction('t', 'ui', {'regions': {'top': 'a'}}, wrong_node_id=None, true_node_id=None)
    assert out['success'] is False and 'wrong_node_id' in out['error']
    assert lvdb.record_correction('t', 'ui', {}, wrong_node_id='n', true_node_id=None)['success'] is False


# ---------------------------------------------------------------- monitor emits the same kinds

ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')


def test_monitor_overlay_and_known_screen_kinds(monkeypatch, tmp_path):
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
    frame = str(tmp_path / 'f.jpg')
    cv2.imwrite(frame, with_popup(screen(3)))
    m = ml.MonitorLocalizer(team_id='t1')
    m._resolve_ui = lambda d: ('ui', 'base')
    m._load_node_fps = lambda ui: NODES
    m._record_change = lambda *a, **k: None
    m._screen_state = lambda *a, **k: None

    class Abstains(ih.ImageHelpers):          # the matcher abstains on the frame (step 4 runs only then)
        def identify_screen(self, img, node_fps):
            return {'candidates': [], 'excluded_count': len(node_fps), 'total': len(node_fps)}
    helpers = Abstains(None, None)
    m._get_helpers = lambda: helpers
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out['kind'] == 'overlay' and out['verdict']['node_id'] == 'n3'

    from shared.src.lib.database import screen_fingerprints_db as sfdb
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('none', None))
    monkeypatch.setattr(sfdb, 'known_screen_lookup', lambda team, scope: (lambda img: (ROW, 2)))
    cv2.imwrite(frame, screen(77))
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out['kind'] == 'known_screen' and out['verdict']['evidence']['screen_id'] == 's1'


def test_known_screen_without_label_or_verdict_is_unnamed():
    v = lv.known_screen_verdict({**ROW, 'verdict': 'unknown'}, 4)
    assert v['label'] == '' and v['evidence']['named'] is False
    assert lv.known_screen_verdict(ROW, 4)['evidence']['named'] is True
    assert lv.known_screen_verdict({**ROW, 'verdict': 'unknown', 'label': 'Splash'}, 4)['evidence']['named'] is True
