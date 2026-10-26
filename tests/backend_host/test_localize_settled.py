"""TASK-159 step 6: settled screens under motion reach the matcher, opt-in per device.

Fixtures are drawn frames that look like the real cases: a splash with words drifting a few pixels, a TV guide with a
small moving preview, and a live video (every second a different scene)."""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import monitor_localize as ml  # noqa: E402
from shared.src.lib import screen_memory  # noqa: E402

W, H = 640, 360


def splash(t):
    """Dark gradient with 'Welcome' words drifting 3 px per tick."""
    img = np.tile(np.linspace(20, 90, W, dtype=np.uint8), (H, 1))
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for i, word in enumerate(('Welcome', 'Bienvenue', 'Willkommen')):
        cv2.putText(img, word, (60 + 3 * t + 40 * i, 120 + 70 * i), cv2.FONT_HERSHEY_DUPLEX, 1.6, (235, 235, 235), 3)
    return img


def tv_guide(t):
    """Header, tab bar with a red underline, programme grid, and a small preview whose picture changes every tick."""
    img = np.full((H, W, 3), 28, np.uint8)
    cv2.putText(img, 'TV Guide', (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 2)
    cv2.line(img, (30, 62), (190, 62), (30, 30, 220), 4)
    for r in range(5):
        cv2.rectangle(img, (30, 90 + 50 * r), (400, 130 + 50 * r), (60, 60, 60), -1)
        cv2.putText(img, f'Channel {r + 1}', (40, 118 + 50 * r), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2)
    preview = np.random.RandomState(t).randint(0, 255, (120, 160, 3), dtype=np.uint8)   # the moving preview
    img[90:210, 450:610] = preview
    return img


def video(t):
    """A different scene every tick: random blobs on a random background."""
    rs = np.random.RandomState(1000 + t)
    img = rs.randint(0, 255, (H // 8, W // 8, 3), dtype=np.uint8)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_CUBIC)
    cv2.circle(img, (int(rs.randint(50, W - 50)), int(rs.randint(50, H - 50))), 80, (255, 255, 255), -1)
    return img


def run(maker, ticks, step=1.0):
    state, forces, now = None, [], 1000.0
    for t in range(ticks):
        fp = screen_memory.fingerprint_frame(maker(t))
        state, force = ml.settled_decision(state, fp['dhash'] if fp else None, now)
        forces.append(force)
        now += step
    return forces


def test_a_settled_splash_is_forced_after_the_hold_then_every_refresh():
    forces = run(splash, 20)
    first = forces.index(True)
    assert first * 1.0 >= ml.SETTLED_HOLD_S
    assert not any(forces[:first])
    gaps = [i for i, f in enumerate(forces) if f]
    assert len(gaps) >= 3 and all(b - a >= ml.SETTLED_REFRESH_S for a, b in zip(gaps, gaps[1:]))


def test_a_tv_guide_with_a_moving_preview_is_forced():
    assert any(run(tv_guide, 15))


def test_live_video_is_never_forced():
    assert not any(run(video, 60))


def test_a_scene_change_restarts_the_hold():
    state, now, forces = None, 0.0, []
    for t in list(range(6)) + [0] * 0:
        fp = screen_memory.fingerprint_frame(splash(t))
        state, f = ml.settled_decision(state, fp['dhash'], now)
        forces.append(f)
        now += 1.0
    fp = screen_memory.fingerprint_frame(tv_guide(0))
    state, f = ml.settled_decision(state, fp['dhash'], now)
    assert f is False and state['since'] == now


def test_flat_or_missing_frames_never_force():
    st, f = ml.settled_decision(None, None, 5.0)
    assert f is False
    st, f = ml.settled_decision(st, None, 60.0)
    assert f is False


def test_the_flag_is_off_by_default_and_per_device(monkeypatch):
    monkeypatch.delenv('DEVICE3_LOCALIZE_SETTLED', raising=False)
    monkeypatch.delenv('DEVICE4_LOCALIZE_SETTLED', raising=False)
    m = ml.MonitorLocalizer()
    assert m._settled_enabled('device3') is False
    monkeypatch.setenv('DEVICE3_LOCALIZE_SETTLED', '1')
    m = ml.MonitorLocalizer()
    assert m._settled_enabled('device3') is True and m._settled_enabled('device4') is False


def test_the_gate_decision_for_other_classes_is_unchanged():
    assert ml.gate_motion_decision({'kind': 'full', 'state': 'live'}) == ml.GATE_LIVE
    assert ml.gate_motion_decision({'kind': 'band'}) == ml.GATE_MOTION
    assert ml.gate_motion_decision({'kind': 'static'}) is None
    assert ml.gate_motion_decision({'kind': 'minor', 'pct': 0.5}) is None


def test_settled_force_reads_the_frame_and_forces_after_the_hold(monkeypatch, tmp_path):
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, splash(0))
    clock = [500.0]
    monkeypatch.setattr(ml.time, 'time', lambda: clock[0])
    m = ml.MonitorLocalizer()
    results = []
    for _ in range(6):
        results.append(m._settled_force('device3', path))
        clock[0] += 1.0
    assert results[:3] == [False, False, False] and any(results[3:])


# --- the call path: a mocked matcher on a real captured frame ---------------------------------------------------
from tests.backend_host.fixtures.stb_frames import write_jpeg  # noqa: E402  (a real stb3 TV guide frame, as text)


class _Helpers:
    SPECIAL_STATE_LABELS = {}

    def __init__(self):
        self.identify_calls = 0

    def classify_special_state(self, img):
        return None

    def identify_screen(self, img, node_fps):
        self.identify_calls += 1
        return {'candidates': [], 'excluded_count': 0, 'total': len(node_fps), 'reason': 'no qualifying screen'}


def _localizer(monkeypatch, flag, tmp_path):
    import types
    if flag:
        monkeypatch.setenv('DEVICE3_LOCALIZE_SETTLED', '1')
    else:
        monkeypatch.delenv('DEVICE3_LOCALIZE_SETTLED', raising=False)
    monkeypatch.setenv('DEVICE3_USERINTERFACE', 'stb_tv')
    m = ml.MonitorLocalizer()
    helpers = _Helpers()
    monkeypatch.setattr(m, '_get_helpers', lambda: helpers)
    monkeypatch.setattr(m, '_load_node_fps', lambda name: [{'node_id': 'n1', 'label': 'home'}])
    monkeypatch.setattr(m, '_after_match', lambda verdict, *a, **k: verdict)
    monkeypatch.setattr(m, '_screen_state', lambda *a, **k: {})
    monkeypatch.setattr(m, '_record_change', lambda *a, **k: None)
    monkeypatch.setattr(m, '_enqueue_match_run_async', lambda *a, **k: None)
    monkeypatch.setattr(m, '_live_node', lambda name: None)
    jev = types.ModuleType('backend_host.src.controllers.verification.jev_second_opinion')
    jev.confirm_low_confidence = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, 'backend_host.src.controllers.verification.jev_second_opinion', jev)
    m.fixture = write_jpeg(str(tmp_path / 'guide.jpg'))
    return m, helpers


LIVE_MOTION = {'kind': 'full', 'state': 'live', 'pct': 40.0}


def _ticks(m, seconds, monkeypatch):
    clock = [2000.0]
    monkeypatch.setattr(ml.time, 'time', lambda: clock[0])
    out = []
    for _ in range(seconds):
        out.append(m.localize_frame('device3', m.fixture, motion=dict(LIVE_MOTION)))
        clock[0] += 1.0
    return out


def test_flag_on_a_settled_gated_frame_reaches_the_matcher(monkeypatch, tmp_path):
    m, helpers = _localizer(monkeypatch, True, tmp_path)
    out = _ticks(m, 8, monkeypatch)
    assert helpers.identify_calls >= 1                       # the settled screen was read
    assert out[0].get('gate_skip') == 'live'                 # but not before the hold: the first tick is still gated
    assert helpers.identify_calls <= 2                       # and not on every tick


def test_flag_off_the_same_frames_stay_gated(monkeypatch, tmp_path):
    m, helpers = _localizer(monkeypatch, False, tmp_path)
    out = _ticks(m, 8, monkeypatch)
    assert helpers.identify_calls == 0
    assert all(o.get('gate_skip') == 'live' for o in out)
