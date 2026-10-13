"""identify_screen emits its own `⏱ localize.identify_screen` line (TASK-68 row 6).

The matcher's elapsed time was previously swallowed by `nav.hop.verify_destination`, so
there was no way to state the fingerprint cost a model call is measured against. Three
call sites are wrapped; two are low-frequency (log every call), the monitor runs on every
captured frame at ~5 fps and is therefore rate-limited to verdict changes + a heartbeat.

Fakes only: no device, no DB, no network.
"""
import importlib
import io
import time
from contextlib import redirect_stdout

import cv2
import numpy as np
import pytest

from shared.src.lib.utils import phase_timing

nav = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')

# Shapes taken from identify_screen's own result keys (its docstring, and the
# candidate/state assignments at the tail of the method): `candidates` entries carry
# `node_id`/`label`/`dist`/`confidence`; `excluded_count`/`total` come from _pack*;
# `state`/`state_label`/`state_hint` appear only when nothing matched.
MATCHED = {
    'candidates': [{'node_id': 'home_tile', 'label': 'home', 'dist': 3, 'confidence': 0.93},
                   {'node_id': 'guide', 'label': 'guide', 'dist': 5, 'confidence': 0.81}],
    'excluded_count': 4, 'total': 6,
}
ABSTAINED = {'candidates': [], 'excluded_count': 6, 'total': 6,
             'state': 'no_signal', 'state_label': 'No signal'}
ABSTAINED_UNKNOWN = {'candidates': [], 'excluded_count': 6, 'total': 6}


def phase_lines(fn):
    """Run `fn`, return the ⏱ lines it printed."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return [ln for ln in buf.getvalue().splitlines() if ln.startswith(phase_timing.MARKER)]


class FakeHelpers:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def identify_screen(self, img, node_fps):
        self.calls.append((img, node_fps))
        return self.result


# ---------------------------------------------------------------- detail rendering

def test_detail_renders_the_matched_case():
    assert nav.identify_screen_detail(MATCHED) == 'matched  node=home_tile conf=0.93 excl=4/6'
    assert ml.identify_screen_detail(MATCHED) == nav.identify_screen_detail(MATCHED)


def test_detail_renders_the_abstain_case_with_a_named_state():
    assert ml.identify_screen_detail(ABSTAINED) == 'abstain  state=no_signal excl=6/6'


def test_abstain_without_a_state_falls_back_to_unknown():
    # `state` is only set when classify_special_state names the screen; an ordinary
    # abstain carries no state key at all.
    assert nav.identify_screen_detail(ABSTAINED_UNKNOWN) == 'abstain  state=unknown excl=6/6'


def test_matched_and_abstained_details_are_distinguishable():
    assert nav.identify_screen_detail(MATCHED) != nav.identify_screen_detail(ABSTAINED)
    assert nav.identify_screen_verdict(MATCHED) != nav.identify_screen_verdict(ABSTAINED)
    assert nav.identify_screen_verdict(ABSTAINED_UNKNOWN) == 'abstain:unknown'


def test_verdict_tracks_the_top_node_not_the_confidence():
    # Confidence drifts frame to frame; the signature must not, or every frame on a
    # stable screen would read as a change and defeat the rate limit.
    hi = dict(MATCHED, candidates=[dict(MATCHED['candidates'][0], confidence=0.93)])
    lo = dict(MATCHED, candidates=[dict(MATCHED['candidates'][0], confidence=0.61)])
    assert nav.identify_screen_verdict(hi) == nav.identify_screen_verdict(lo) == 'matched:home_tile'
    other = dict(MATCHED, candidates=[dict(MATCHED['candidates'][0], node_id='guide')])
    assert nav.identify_screen_verdict(other) == 'matched:guide'


def test_both_copies_of_the_detail_helper_agree():
    """Duplicated on purpose (the monitor may not import the navigation stack) — keep in step."""
    for result in (MATCHED, ABSTAINED, ABSTAINED_UNKNOWN):
        assert ml.identify_screen_detail(result) == nav.identify_screen_detail(result)
        assert ml.identify_screen_verdict(result) == nav.identify_screen_verdict(result)


# ----------------------------------------------------------------- the wrapper

def test_wrapper_logs_one_phase_line_carrying_the_verdict_detail():
    lines = phase_lines(lambda: nav.run_identify_screen(FakeHelpers(ABSTAINED), 'img', [], 'dispatch'))
    assert len(lines) == 1
    assert ' localize.identify_screen ' in lines[0]
    assert 'site=dispatch' in lines[0]
    assert 'abstain  state=no_signal' in lines[0]
    assert ' ms' in lines[0]


def test_wrapper_passes_img_and_node_fps_through_untouched():
    helpers, fps, img = FakeHelpers(MATCHED), [{'node_id': 'x'}], object()
    nav.run_identify_screen(helpers, img, fps, 'mcp')
    assert helpers.calls == [(img, fps)]


def test_instrumentation_does_not_alter_the_returned_result():
    """Same dict object back, same keys, not mutated — matched and abstained alike."""
    for result in (MATCHED, ABSTAINED, ABSTAINED_UNKNOWN):
        before = repr(result)
        out = nav.run_identify_screen(FakeHelpers(result), None, [], 'mcp')
        assert out is result
        assert repr(out) == before
        assert set(out) == set(result)


def test_a_failure_while_logging_still_returns_the_result(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('stdout is gone')

    monkeypatch.setattr(nav, '_log_duration', boom)
    assert nav.run_identify_screen(FakeHelpers(MATCHED), None, [], 'mcp') is MATCHED


def test_an_exception_from_the_matcher_still_propagates():
    class Boom:
        def identify_screen(self, *_a, **_k):
            raise ValueError('matcher exploded')

    with pytest.raises(ValueError):
        nav.run_identify_screen(Boom(), None, [], 'mcp')


# ------------------------------------------------------- the 5 fps path's rate limit

@pytest.fixture
def monitor(monkeypatch, tmp_path):
    """A MonitorLocalizer with the matcher, the fingerprint load and Jev all faked.

    The frame path must be a REAL readable file: localize_frame does cv2.imread on it
    before the matcher ever runs.
    """
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
    frame = str(tmp_path / 'frame.jpg')
    cv2.imwrite(frame, _page())
    m = ml.MonitorLocalizer(team_id='t1')
    m.frame = frame
    m._resolve_ui = lambda device_id: ('ui', 'base')
    m._load_node_fps = lambda ui: [{'node_id': 'home', 'label': 'home', 'fingerprint': {'dhash': 'a'}}]
    m._get_helpers = lambda: m._helpers
    m._record_change = lambda *a, **k: None
    return m


def _frames(m, n, result=MATCHED, device='device4'):
    """Feed `n` frames with `result` as the matcher verdict; return the ⏱ lines."""
    m._helpers = FakeHelpers(result)

    def run():
        for _ in range(n):
            m.localize_frame(device, m.frame)

    return phase_lines(run)


def test_repeated_identical_verdicts_are_suppressed(monitor):
    lines = _frames(monitor, 50)               # 50 frames (~10 s at 5 fps) of one stable screen
    assert len(lines) == 1                      # the first one, then silence
    assert 'matched  node=home_tile conf=0.93 excl=4/6' in lines[0]
    assert 'site=monitor' in lines[0]
    assert 'on-change' in lines[0]


def test_a_verdict_change_is_always_logged(monitor):
    first = _frames(monitor, 1)                 # match
    second = _frames(monitor, 1, ABSTAINED)     # ... now it abstains
    third = _frames(monitor, 1, ABSTAINED)      # unchanged -> suppressed
    assert len(first) == 1 and len(second) == 1 and third == []
    assert 'matched  node=home_tile' in first[0] and 'on-change' in first[0]
    assert 'abstain  state=no_signal' in second[0] and 'on-change' in second[0]


def test_a_different_top_node_is_a_change(monitor):
    other = dict(MATCHED, candidates=[dict(MATCHED['candidates'][0], node_id='apps_netflix')])
    assert len(_frames(monitor, 1)) == 1
    assert len(_frames(monitor, 1, other)) == 1


class _FakeClock:
    """A hand-cranked stand-in for the `time` module, so heartbeat timing is exact."""

    def __init__(self, t=1000.0):
        self.t = t

    def time(self):
        return self.t

    def perf_counter(self):
        return self.t


def test_the_gate_logs_on_change_then_once_per_heartbeat(monitor, monkeypatch):
    """A stable verdict is one line per heartbeat, however many frames run in between."""
    clock = _FakeClock()
    monkeypatch.setattr(ml, 'time', clock)
    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor._log_identify_screen('d', 1000.0, MATCHED)        # t=1000.0 -- first verdict
        for _ in range(19):                                      # 19 frames, 200 ms apart = 3.8 s
            clock.t += 0.2
            monitor._log_identify_screen('d', 1000.0, MATCHED)
        clock.t += 30.0                                          # a full heartbeat has passed
        monitor._log_identify_screen('d', 1000.0, MATCHED)
        monitor._log_identify_screen('d', 1000.0, ABSTAINED)      # ... and the screen changed
    lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith(phase_timing.MARKER)]
    assert len(lines) == 3
    assert 'on-change frames=0' in lines[0]
    assert 'heartbeat frames=20' in lines[1]      # 20 frames since the previous line, this one included
    assert 'on-change frames=1' in lines[2] and 'abstain  state=no_signal' in lines[2]


def test_the_rate_limit_is_per_device(monitor):
    monitor._helpers = FakeHelpers(MATCHED)
    lines = phase_lines(lambda: [monitor.localize_frame(d, monitor.frame)
                                 for d in ('device4', 'device5')])
    assert len(lines) == 2                      # device5's first frame is its own change


VERDICT_KEYS = ('node', 'confidence', 'excluded', 'total')


def _verdict(out):
    """Only the verdict fields.

    The overlay payload also carries diagnostic keys (`tier`, and `reason`/`door`
    on abstains). Those are deliberately added by later work and are NOT part of
    what these tests assert is unchanged, so compare the verdict subset rather
    than the whole dict — exact-dict equality would fail on any additive field.
    """
    assert out is not None
    return {k: out[k] for k in VERDICT_KEYS}


def test_the_overlay_verdict_is_unchanged_by_the_timing(monitor):
    monitor._helpers = FakeHelpers(MATCHED)
    with redirect_stdout(io.StringIO()):
        out = monitor.localize_frame('device4', monitor.frame)
    assert _verdict(out) == {'node': 'home', 'confidence': 0.93, 'excluded': 4, 'total': 6}


def test_a_failure_while_timing_does_not_break_the_frame(monitor, monkeypatch):
    monitor._helpers = FakeHelpers(MATCHED)
    monkeypatch.setattr(ml, 'identify_screen_detail', lambda _r: (_ for _ in ()).throw(ValueError('bad')))
    with redirect_stdout(io.StringIO()):
        out = monitor.localize_frame('device4', monitor.frame)
    assert _verdict(out) == {'node': 'home', 'confidence': 0.93, 'excluded': 4, 'total': 6}


# --------------------------------------------------------------------- cost measure

def test_measured_cost_of_the_added_instrumentation(monitor, capsys):
    """Measured, not asserted: what the gate costs on the 5 fps path."""
    monitor.localize_frame('device4', monitor.frame)          # prime the state
    started = time.perf_counter()
    n = 20000
    for _ in range(n):
        monitor._log_identify_screen('device4', started, MATCHED)
    per_call_us = (time.perf_counter() - started) / n * 1e6
    with capsys.disabled():
        print(f"\nidentify_screen instrumentation: {per_call_us:.1f} us/call on the 5 fps path"
              f" = {per_call_us * 5 / 10_000:.4f}% of one core at 5 fps")
    assert per_call_us < 1000, f'{per_call_us:.1f} us/call is too expensive for a per-frame gate'


# ------------------------------------------------------------- real matcher, real frame

def _page():
    img = np.full((720, 1280, 3), 255, np.uint8)
    rng = np.random.RandomState(5)
    for _ in range(150):
        x, y = int(rng.randint(0, 1100)), int(rng.randint(0, 650))
        cv2.rectangle(img, (x, y), (x + int(rng.randint(40, 200)), y + int(rng.randint(20, 90))),
                      (0, 0, 0), int(rng.choice([2, -1])))
    return img


def test_a_real_match_is_unchanged_and_gets_its_own_line():
    """Guard against the wrappers altering the matcher: real ImageHelpers, real frame."""
    img = _page()
    helpers = ih.ImageHelpers(None, None)
    fps = [{'node_id': 'home', 'label': 'home', 'fingerprint': helpers.compute_fingerprint(img)}]
    direct = helpers.identify_screen(img, fps)
    wrapped = nav.run_identify_screen(helpers, img, fps, 'mcp')
    assert [c['label'] for c in direct['candidates']] == ['home']
    assert [c['node_id'] for c in wrapped['candidates']] == [c['node_id'] for c in direct['candidates']]
    lines = phase_lines(lambda: nav.run_identify_screen(helpers, img, fps, 'mcp'))
    assert len(lines) == 1
    assert 'matched  node=home' in lines[0] and 'excl=' in lines[0]


def test_a_black_frame_abstains_and_the_line_says_so():
    helpers = ih.ImageHelpers(None, None)
    fps = [{'node_id': 'home', 'label': 'home',
            'fingerprint': helpers.compute_fingerprint(_page())}]
    black = np.zeros((720, 1280, 3), np.uint8)
    result = helpers.identify_screen(black, fps)
    lines = phase_lines(lambda: nav.run_identify_screen(helpers, black, fps, 'mcp'))
    assert not result['candidates']
    assert len(lines) == 1
    assert 'abstain  state=' in lines[0]