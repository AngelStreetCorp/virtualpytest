"""Localize v3 cascade order (TASK-104): signal -> live -> node -> unknown.

The pure verdict functions (shared/src/lib/utils/localize_verdict.py) and
NavigationExecutor.localize wired to fakes: no device, no DB, no network.
"""
import importlib

import networkx as nx
import numpy as np
import pytest

lv = importlib.import_module('shared.src.lib.utils.localize_verdict')
nav = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')

pytestmark = pytest.mark.unit

RNG = np.random.default_rng(7)


def noise():
    """A fresh random frame: every pair of these is full-frame motion."""
    return RNG.integers(0, 255, (360, 640, 3), dtype=np.uint8)


def ui_frame():
    """A still, non-black, non-test-pattern screen: grey with a few boxes and text-like edges."""
    img = np.full((360, 640, 3), 90, dtype=np.uint8)
    for x in range(40, 600, 120):
        img[60:140, x:x + 90] = 200
        img[200:205, x:x + 90] = 20
    return img


BLACK = np.full((360, 640, 3), 16, dtype=np.uint8)


# ---------------------------------------------------------------- pure functions

def test_motion_full_only_when_every_pair_is_full():
    still = ui_frame()
    assert lv.measure_motion([noise(), noise(), noise()])['kind'] == 'full'
    # One screen change between two still frames is not live video.
    assert lv.measure_motion([still, still, noise()])['kind'] != 'full'
    assert lv.measure_motion([still, still, still])['kind'] == 'static'
    assert lv.measure_motion([still]) is None


def test_signal_beats_live_beats_matcher():
    full = {'kind': 'full', 'pct': 80.0}
    live = {'node_id': 'n-live', 'label': 'live'}
    assert lv.verdict_before_match('blackscreen', 'Black Screen', full, live)['kind'] == 'signal'
    v = lv.verdict_before_match(None, None, full, live)
    assert (v['kind'], v['node_id'], v['label']) == ('live', 'n-live', 'live')
    assert lv.verdict_before_match(None, None, full, None)['label'] == lv.LIVE_LABEL
    assert lv.verdict_before_match(None, None, {'kind': 'band', 'pct': 20.0}, live) is None
    assert lv.verdict_before_match(None, None, None, live) is None


def test_verdict_from_match():
    one = {'candidates': [{'node_id': 'home', 'label': 'home', 'confidence': 0.9}], 'excluded_count': 5, 'total': 6}
    assert lv.verdict_from_match(one)['kind'] == 'node'
    # A kept tie reads as every caller of `candidates` reads it: the first one, others in evidence.
    tie = {'candidates': [{'node_id': 'a', 'confidence': 0.8}, {'node_id': 'b', 'confidence': 0.7}]}
    v = lv.verdict_from_match(tie)
    assert (v['kind'], v['node_id'], v['evidence']['tied']) == ('node', 'a', ['b'])
    assert lv.verdict_from_match({'candidates': [], 'state': 'no_signal'})['kind'] == 'signal'
    assert lv.verdict_from_match({'candidates': [], 'reason': 'low-content frame'})['evidence']['reason']


def test_signal_needs_every_frame():
    assert lv.common_signal_state(['blackscreen'] * 3) == 'blackscreen'
    assert lv.common_signal_state([None, None, 'blackscreen']) is None      # a zap ends on black
    assert lv.common_signal_state([]) is None


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_grab_waits_for_a_new_capture_file():
    """2 fps capture: the newest file changes every 0.5 s, so a fixed 0.3 s step would pair a
    file with itself. The grab keeps polling until the basename changes."""
    clock = _Clock()
    shot = lambda: f'/cap/capture_{int(clock.t / 0.5)}.jpg'
    got = lv.grab_distinct_frames(shot, lambda p: ui_frame(), clock.sleep, clock)
    names = [p for p, _ in got]
    assert len(names) == 3 and len(set(names)) == 3
    assert clock.t <= lv.MOTION_DEADLINE_S


def test_grab_gives_up_on_a_stuck_capture():
    clock = _Clock()
    got = lv.grab_distinct_frames(lambda: '/cap/capture_1.jpg', lambda p: ui_frame(), clock.sleep, clock)
    assert len(got) == 1 and clock.t <= lv.MOTION_DEADLINE_S + lv.MOTION_POLL_S
    assert lv.measure_motion([f for _, f in got]) is None


def test_live_node_is_the_node_named_live():
    nodes = [{'node_id': 'b', 'label': 'tv', 'data': {'live': True}},
             {'node_id': 'a', 'label': 'Live'}]
    assert lv.find_live_node(nodes) == {'node_id': 'a', 'label': 'Live'}
    assert lv.find_live_node(nodes[:1]) is None


# ---------------------------------------------------------------- executor wiring

class _Av:
    def __init__(self, frames):
        self.frames = list(frames)
        self.n = 0

    def take_screenshot(self):
        self.n += 1
        return f'/tmp/frame_{self.n}.jpg'


class _Device:
    def __init__(self, av):
        self.av = av
        self.navigation_context = {}
        self.device_id = 'device1'

    def _get_controller(self, kind):
        return self.av


def _graph():
    g = nx.DiGraph()
    fp = {'dhash': 'ab' * 32}
    g.add_node('n-home', label='home', metadata={}, __fingerprint=fp, variant_state={'active': True})
    g.add_node('n-live', label='live', metadata={'live': True}, __fingerprint=fp, variant_state={'active': True})
    return g


@pytest.fixture
def run_localize(monkeypatch):
    def _run(frames, match_result=None, motion=True, retries=0):
        monkeypatch.setattr(nav, 'MOTION_RETRIES', retries)
        av = _Av(frames)
        ex = nav.NavigationExecutor.__new__(nav.NavigationExecutor)
        ex.device = _Device(av)
        ex.device_id = 'device1'
        ex.host_name = 'h'
        calls = []
        monkeypatch.setattr(ex, '_sync_unified_graph', lambda *a, **k: _graph())
        monkeypatch.setattr(ex, '_read_classifier_diagnostics', lambda *a, **k: None)
        monkeypatch.setattr(ex, '_frame_url_from_path', lambda p: 'url')
        monkeypatch.setattr(nav.cv2_io, 'imread', lambda p: av.frames[(int(p.split('_')[1].split('.')[0]) - 1) % len(av.frames)])
        monkeypatch.setattr(nav.time, 'sleep', lambda s: None)
        monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
        monkeypatch.setattr(jso, 'localize_shadow', lambda *a, **k: None)

        def fake_match(helpers, img, node_fps, site):
            calls.append(site)
            return dict(match_result or {'candidates': [], 'excluded_count': 2, 'total': 2})
        monkeypatch.setattr(nav, 'run_identify_screen', fake_match)
        result = ex.localize('team', 'stb-testop', tree_id='tree-1', motion=motion)
        result['_grabbed'] = av.n
        return result, calls
    return _run


def test_black_screen_is_signal_without_matching(run_localize):
    result, calls = run_localize([BLACK, BLACK, BLACK])
    assert result['verdict']['kind'] == 'signal'
    assert result['state'] == 'blackscreen'
    assert calls == []


def test_full_motion_is_the_live_node_without_matching(run_localize):
    result, calls = run_localize([noise(), noise(), noise()])
    assert result['verdict']['kind'] == 'live'
    assert result['verdict']['node_id'] == 'n-live'
    assert [c['node_id'] for c in result['candidates']] == ['n-live']
    assert result['classifier_diagnostics']['motion']['kind'] == 'full'
    assert 'state' not in result                  # live is never the capture-failure channel
    assert calls == []


def test_still_screen_runs_the_matcher(run_localize):
    still = ui_frame()
    match = {'candidates': [{'node_id': 'n-home', 'label': 'home', 'confidence': 0.91}],
             'excluded_count': 1, 'total': 2}
    result, calls = run_localize([still, still, still], match)
    assert calls == ['mcp']
    assert (result['verdict']['kind'], result['verdict']['node_id']) == ('node', 'n-home')


def test_still_screen_without_match_is_unknown(run_localize):
    still = ui_frame()
    result, calls = run_localize([still, still, still])
    assert calls == ['mcp']
    assert result['verdict']['kind'] == 'unknown'


def test_black_only_on_the_last_frame_is_not_signal(run_localize):
    """A fade or a zap ends on black: the cascade does not call that a signal state."""
    still = ui_frame()
    result, calls = run_localize([still, still, BLACK])
    assert result['verdict']['kind'] != 'signal' and 'state' not in result
    assert calls == ['mcp']


def test_one_screen_change_is_not_live(run_localize):
    still = ui_frame()
    result, calls = run_localize([still, still, noise()])
    assert result['verdict']['kind'] != 'live'
    assert calls == ['mcp']


def test_carousel_band_is_not_live(run_localize):
    a, b, c = ui_frame(), ui_frame(), ui_frame()
    b[150:220] = RNG.integers(0, 255, (70, 640, 3), dtype=np.uint8)    # a moving strip only
    c[150:220] = RNG.integers(0, 255, (70, 640, 3), dtype=np.uint8)
    result, calls = run_localize([a, b, c])
    assert result['classifier_diagnostics']['motion']['kind'] == 'band'
    assert calls == ['mcp']


def test_a_tie_is_the_first_candidate_like_the_popover(run_localize):
    still = ui_frame()
    tie = {'candidates': [{'node_id': 'n-home', 'label': 'home', 'confidence': 0.8},
                          {'node_id': 'n-replay', 'label': 'replay', 'confidence': 0.8}],
           'excluded_count': 0, 'total': 2}
    result, _ = run_localize([still, still, still], tie)
    assert result['verdict']['node_id'] == result['candidates'][0]['node_id'] == 'n-home'
    assert result['verdict']['evidence']['tied'] == ['n-replay']


def test_motion_off_grabs_one_frame_and_never_says_live(run_localize):
    result, calls = run_localize([noise(), noise(), noise()], motion=False)
    assert result['_grabbed'] == 1
    assert result['verdict']['kind'] != 'live' and calls == ['mcp']


# ---------------------------------------------------------------- monitor path

ml = importlib.import_module('backend_host.scripts.monitor_localize')


class _MonHelpers:
    SPECIAL_STATE_LABELS = {'blackscreen': 'Black Screen'}

    def __init__(self, state=None):
        self.state = state
        self.calls = 0

    def classify_special_state(self, img):
        return self.state

    def identify_screen(self, img, node_fps):
        self.calls += 1
        return {'candidates': [{'node_id': 'n-home', 'label': 'home', 'confidence': 0.9}],
                'excluded_count': 1, 'total': 2}


def _monitor(monkeypatch, tmp_path, node_fps, helpers):
    import cv2
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
    frame = str(tmp_path / 'frame.jpg')
    cv2.imwrite(frame, ui_frame())
    m = ml.MonitorLocalizer(team_id='t1')
    m._resolve_ui = lambda device_id: ('stb-testop', 'base')
    m._load_node_fps = lambda ui: node_fps
    m._get_helpers = lambda: helpers
    m._record_change = lambda *a, **k: None
    m._screen_state = lambda *a, **k: None
    m._fps_by_ui['stb-testop'] = {'ts': 0, 'node_fps': node_fps, 'live_node': {'node_id': 'n-live', 'label': 'live'}}
    return m, frame


FPS = [{'node_id': 'n-home', 'label': 'home', 'fingerprint': {'dhash': 'a'}}]
LIVE_MOTION = {'kind': 'full', 'state': 'live', 'pct': 90.0}


def test_monitor_first_live_frame_answers_live_without_matching(monkeypatch, tmp_path):
    h = _MonHelpers()
    m, frame = _monitor(monkeypatch, tmp_path, FPS, h)
    out = m.localize_frame('device3', frame, motion=LIVE_MOTION)
    assert (out['kind'], out['node'], out['verdict']['node_id']) == ('live', 'live', 'n-live')
    assert h.calls == 0


def test_monitor_still_frame_is_the_matched_node(monkeypatch, tmp_path):
    h = _MonHelpers()
    m, frame = _monitor(monkeypatch, tmp_path, FPS, h)
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert (out['kind'], out['verdict']['node_id']) == ('node', 'n-home') and h.calls == 1


def test_monitor_signal_before_matching(monkeypatch, tmp_path):
    h = _MonHelpers('blackscreen')
    m, frame = _monitor(monkeypatch, tmp_path, FPS, h)
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out['kind'] == 'signal' and out['state'] == 'blackscreen' and h.calls == 0


def test_monitor_stale_live_motion_on_blackscreen_is_signal(monkeypatch, tmp_path):
    """vpt-mf1 stbv1: detector says blackscreen, cached motion is still kind=full live."""
    h = _MonHelpers('blackscreen')
    m, frame = _monitor(monkeypatch, tmp_path, FPS, h)
    out = m.localize_frame(
        'device2', frame,
        motion={'kind': 'full', 'state': 'blackscreen', 'pct': 81.3, 'cells': 16, 'raw_state': 'blackscreen'},
    )
    assert out['kind'] == 'signal' and out['state'] == 'blackscreen'
    assert out['verdict']['label'] == 'Black Screen'
    assert 'gate_skip' not in out and h.calls == 0


def test_monitor_without_fingerprints_still_has_a_verdict(monkeypatch, tmp_path):
    m, frame = _monitor(monkeypatch, tmp_path, [], _MonHelpers())
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out['kind'] == 'unknown' and out['verdict']['evidence']['reason'] == 'no fingerprinted nodes'
    m, frame = _monitor(monkeypatch, tmp_path, [], _MonHelpers('blackscreen'))
    out = m.localize_frame('device3', frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out['kind'] == 'signal'


# ---------------------------------------------------------------- no image monitor, no Localize

mp = importlib.import_module('backend_host.src.lib.utils.monitor_profile')


def test_lite_profile_turns_localize_off(monkeypatch):
    """Owner, 2026-10-14: a profile without vpt-monitor-img (tv_lite) gets no Localize. Read from the
    device's resolved profile, the same data as the host's `monitoring_off` list."""
    monkeypatch.setenv('DEVICE3_MONITOR_PROFILE', 'tv_lite')
    monkeypatch.setenv('DEVICE4_MONITOR_PROFILE', 'tv_app')
    assert 'image monitor' in mp.localize_off_reason('device3')
    assert mp.localize_off_reason('device4') is None


def test_executor_refuses_before_any_capture(run_localize, monkeypatch):
    monkeypatch.setattr(mp, 'localize_off_reason', lambda d: 'Localize is off for device1')
    result, calls = run_localize([noise(), noise(), noise()])
    assert result['success'] is False and result['localize_off'] is True
    assert result['_grabbed'] == 0 and calls == []


# ---------------------------------------------------------------- steps 4-5 through the executor

ssc = importlib.import_module('shared.src.lib.ai.screen_state_cv')
sfdb = importlib.import_module('shared.src.lib.database.screen_fingerprints_db')


def test_executor_abstain_then_overlay(run_localize, monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('keyboard', (0.0, 0.6, 1.0, 0.4)))
    monkeypatch.setattr(sfdb, 'known_screen_lookup',
                        lambda t, s: (lambda img: pytest.fail('memory is only asked after no overlay')))
    still = ui_frame()
    result, calls = run_localize([still, still, still])
    assert calls == ['mcp'] and result['verdict']['kind'] == 'overlay'
    assert result['verdict']['evidence']['overlay'] == 'keyboard'
    assert result['candidates'] == []                     # an overlay is never a position to start from


def test_executor_abstain_then_known_screen(run_localize, monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: ('none', None))
    scopes = []
    row = {'id': 's9', 'scope': 'h/device1', 'verdict': 'expected', 'seen_count': 5}
    monkeypatch.setattr(sfdb, 'known_screen_lookup', lambda t, s: scopes.append((t, s)) or (lambda img: (row, 1)))
    still = ui_frame()
    result, _ = run_localize([still, still, still])
    assert result['verdict']['kind'] == 'known_screen'
    assert scopes and scopes[0][0] == 'team'              # queried with the caller's team_id


def test_a_slow_scene_is_still_live():
    """Live check on stb-testop: a close-up film scene gave one full pair and one minor pair over ~1 s."""
    a = noise()
    b = noise()
    c = b.copy()
    for y, x in ((36, 64), (162, 288), (288, 512)):                            # scattered: minor, not one box
        c[y:y + 45, x:x + 80] = RNG.integers(0, 255, (45, 80, 3), dtype=np.uint8)
    m = lv.measure_motion([a, b, c])
    assert m['pairs'] == ['full', 'minor'] and m['kind'] == 'full'


def test_overlay_is_not_read_on_moving_content(monkeypatch):
    monkeypatch.setattr(ssc, 'overlay_plate', lambda img: pytest.fail('overlay must not run on video'))
    v = lv.after_abstain(lv.unknown_verdict(), None, [], None, None, motion={'kind': 'change', 'pct': 8.6})
    assert v['kind'] == 'unknown'


def test_abstain_after_a_zap_reads_live_on_a_fresh_window(run_localize):
    """stb4 channel change: a held picture first (all pairs still), then the video moves: the retry
    window reads live, a still screen stays unknown."""
    still = [ui_frame(), ui_frame(), ui_frame()]
    moving = [np.full((720, 1280, 3), v, np.uint8) for v in (40, 140, 40)]
    result, calls = run_localize(still + moving, retries=1)
    assert result['verdict']['kind'] == 'live' and calls == ['mcp']
    result, calls = run_localize(still, retries=2)
    assert result['verdict']['kind'] == 'unknown' and result['verdict']['evidence']['motion']['kind'] == 'static'
