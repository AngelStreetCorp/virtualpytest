"""Wire Tier 2 (screen_state_cv) into the per-frame `localize` payload.

The motion gate, when it lets the matcher run, also calls
`shared.src.lib.ai.screen_state_cv.screen_state` and folds the four returned
answers (loaded / overlay / playback / error) into the per-frame `localize`
dict. On a `gate_skip` the cascade does NOT run (we did not read the frame),
so the four fields are absent — the cached `node` is served with
`confidence: 0` instead. This file pins both halves:

  1. fresh matcher run    -> the four Tier-2 keys are present on the payload
  2. gate-skip frame      -> gate_skip is set, none of the Tier-2 keys are set
  3. AVQ analyze_positions-> the new `positions_<field>` lanes appear when the
                              per-frame JSON carries Tier-2 data, and are
                              simply absent on a window that does not.

Fakes only: no device, no DB, no network. Reuses the `_page` helper from
test_identify_screen_timing to get a real, readable JPEG on disk (cv2.imread
is the only way to make localize_frame's first check happy).
"""
import importlib
import os
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np
import pytest

ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')
avq = importlib.import_module('features.avq.backend_host.avq_analyze')


# ── shared fakes ──────────────────────────────────────────────────────────────


def _page():
    """A 64x64 grey page — readable JPEG, enough for cv2.imread and for
    screen_state_cv's loaded / overlay arms to actually run. It is
    intentionally NOT random noise: the cascade would still answer on noise,
    but a flat colour makes the test inputs predictable and the test fast.
    """
    return np.full((64, 64, 3), 96, dtype=np.uint8)


class _FakeHelpers:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def classify_special_state(self, img):
        return None          # Localize v3 step 1 (TASK-104): never a black / no-signal frame here

    def identify_screen(self, img, node_fps):
        self.calls.append((img, node_fps))
        return self.result


MATCHED = {
    'candidates': [{'node_id': 'home_tile', 'label': 'home', 'dist': 3, 'confidence': 0.93}],
    'excluded_count': 4, 'total': 6,
}


def _make_monitor(monkeypatch, tmp_path, helpers_result=MATCHED):
    """MonitorLocalizer with the matcher / fingerprint load / Jev / record all faked.

    A real, readable JPEG is required (cv2.imread is called before the
    matcher ever runs).
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
    m._helpers = _FakeHelpers(helpers_result)
    return m


# ── per-frame payload carries Tier 2 when the gate lets the matcher run ──────


def test_tier2_fields_present_on_a_fresh_matcher_run(monkeypatch, tmp_path):
    """When motion is 'static' (gate open), Tier 2 is called and the four
    fields appear in the payload. The exact Tier-2 values come from
    screen_state_cv on a 64x64 grey page; what we assert is the SHAPE
    (every key present) and the absence of `gate_skip`.
    """
    m = _make_monitor(monkeypatch, tmp_path)
    out = m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out is not None
    assert 'gate_skip' not in out                              # the gate let the matcher run
    for fld in ('loaded', 'overlay', 'playback', 'error'):
        assert fld in out, f'Tier-2 field {fld!r} missing from the per-frame payload'
    # On a flat-grey page the overlay arm should confidently answer 'none'
    # (no plate, no tooltip, std > tooltip_contrast_min). The other arms
    # answer honestly: 'loaded' is 'yes' on a still image, 'playback' is
    # 'unknown' (we did not pass is_media), 'error' is 'unknown' (no tokens).
    assert out['overlay'] in ('none', 'unknown')               # the safe claim is 'none'
    assert out['loaded'] in ('yes', 'no', 'unknown')           # cascade decides, we don't second-guess
    assert out['playback'] in ('playing', 'paused', 'stopped', 'not_applicable', 'unknown')
    assert out['error'] in ('none', 'visible', 'unknown')


def test_tier2_fields_absent_on_a_gate_skip(monkeypatch, tmp_path):
    """A `gate_skip` frame serves the cached verdict with `confidence: 0` and
    NO Tier-2 fields. The Tier-2 cascade does not run on a gate-skip frame
    (we did not even read the image) so the four keys must be absent.
    """
    m = _make_monitor(monkeypatch, tmp_path)
    # Prime the cache: first call is a fresh run that fills _last_match.
    m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    # Second call is a full-motion frame: the gate says skip-live.
    out = m.localize_frame('device4', m.frame, motion={'kind': 'full', 'state': 'live', 'pct': 90.0})
    assert out is not None
    assert out.get('gate_skip') == 'live'
    assert out.get('confidence') == 0.0
    assert out.get('node') == 'home'                          # cached
    for fld in ('loaded', 'overlay', 'playback', 'error'):
        assert fld not in out, f'Tier-2 field {fld!r} leaked into a gate-skip payload'


# ── `_screen_state` is a defensive helper: failure never breaks the verdict ──


def test_screen_state_failure_keeps_the_verdict(monkeypatch, tmp_path):
    """Each Tier-2 check runs on its own (its own input shape): one that raises answers 'unknown'
    and the others still answer; the matcher verdict is never touched. Tier 2 is not a
    correctness gate (TASK-107 goal 7)."""
    m = _make_monitor(monkeypatch, tmp_path)
    import shared.src.lib.ai.screen_state_cv as scv
    monkeypatch.setattr(scv, 'overlay', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    out = m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out is not None
    assert out.get('node') == 'home'
    assert out['overlay'] == 'unknown'
    assert {'loaded', 'playback', 'error'} <= set(out)


def test_each_check_gets_its_own_input(monkeypatch, tmp_path):
    """loaded <- the per-device window of motion.pct (deque, last 8); overlay <- the frame;
    playback <- (is_media, current pct); error <- OCR tokens (skipped on a media surface)."""
    m = _make_monitor(monkeypatch, tmp_path)
    import shared.src.lib.ai.screen_state_cv as scv
    seen = {}
    monkeypatch.setattr(scv, 'loaded', lambda win, **k: seen.setdefault('loaded', list(win)) and 'yes')
    monkeypatch.setattr(scv, 'overlay', lambda img, **k: seen.setdefault('overlay', getattr(img, 'shape', None)) and 'none')
    monkeypatch.setattr(scv, 'playback', lambda is_media, pct, **k: seen.setdefault('playback', (is_media, pct)) and 'playing')
    monkeypatch.setattr(scv, 'error', lambda tokens, **k: seen.setdefault('error', tokens) or 'none')
    m._ui_meta = lambda ui: {'is_media': True}
    for pct in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        seen.clear()
        m._matched_thumb.clear()     # the same frame every tick: defeat the unchanged-frame skip (TASK-115)
        m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': pct})
    assert seen['loaded'] == [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]     # the last 8, oldest first
    assert seen['overlay'] is not None and seen['playback'] == (True, 0.9)
    assert seen['error'] is None                                         # media surface: no OCR


# ── AVQ analyze_positions: Tier-2 lanes appear when the JSON carries them ───


def test_avq_positions_emits_tier2_lanes_when_present(tmp_path, monkeypatch):
    """Two per-frame JSONs carrying the four Tier-2 fields -> analyze_positions
    produces `positions_loaded` / `positions_overlay` / `positions_playback` /
    `positions_error` alongside the existing `positions` lane. Each lane is
    an RLE list of {s, e, value} segments.
    """
    mdir = tmp_path / 'metadata'
    mdir.mkdir()
    now = time.time()
    frames = [
        ({'localize': {'node': 'home', 'confidence': 0.9, 'excluded': 4, 'total': 6,
                       'loaded': 'yes', 'overlay': 'none', 'playback': 'unknown', 'error': 'none'}},
         now - 4.0),
        ({'localize': {'node': 'home', 'confidence': 0.9, 'excluded': 4, 'total': 6,
                       'loaded': 'yes', 'overlay': 'popup', 'playback': 'unknown', 'error': 'none'}},
         now - 2.0),
    ]
    for i, (payload, mt) in enumerate(frames):
        p = mdir / f'capture_{i:09d}.json'
        p.write_text(__import__('json').dumps(payload))
        os.utime(p, (mt, mt))

    monkeypatch.setattr(avq, '_metadata_dir', lambda _cf: str(mdir))
    out = avq.analyze_positions('cf', window_seconds=60)
    assert 'positions' in out and out['positions']
    # All four Tier-2 lanes are present and non-empty.
    for fld in ('loaded', 'overlay', 'playback', 'error'):
        key = f'positions_{fld}'
        assert key in out, f'{key!r} missing from analyze_positions output'
        segs = out[key]
        assert segs and all('s' in s and 'e' in s and 'value' in s for s in segs)
    # The two overlay values ('none', 'popup') are distinct, so the lane is split.
    overlay_values = sorted({s['value'] for s in out['positions_overlay']})
    assert overlay_values == ['none', 'popup']


def test_avq_positions_omits_tier2_lanes_when_payload_lacks_them(tmp_path, monkeypatch):
    """Backwards compat: a window of per-frame JSONs without Tier-2 fields
    must still produce a valid `positions` lane and NO Tier-2 lanes. The
    shape grew additively, so old readers continue to work.
    """
    mdir = tmp_path / 'metadata'
    mdir.mkdir()
    now = time.time()
    frames = [
        ({'localize': {'node': 'home', 'confidence': 0.9, 'excluded': 4, 'total': 6}}, now - 4.0),
        ({'localize': {'node': 'home', 'confidence': 0.85, 'excluded': 4, 'total': 6}}, now - 2.0),
    ]
    for i, (payload, mt) in enumerate(frames):
        p = mdir / f'capture_{i:09d}.json'
        p.write_text(__import__('json').dumps(payload))
        os.utime(p, (mt, mt))

    monkeypatch.setattr(avq, '_metadata_dir', lambda _cf: str(mdir))
    out = avq.analyze_positions('cf', window_seconds=60)
    assert out['positions'] and len(out['positions']) == 1                  # both rolled up
    for fld in ('loaded', 'overlay', 'playback', 'error'):
        assert f'positions_{fld}' not in out                                 # absent, not empty


def test_avq_positions_handles_a_window_with_no_metadata(tmp_path, monkeypatch):
    """Defensive: an empty / missing metadata dir must not raise. The old
    contract (positions=None) is preserved.
    """
    monkeypatch.setattr(avq, '_metadata_dir', lambda _cf: str(tmp_path / 'nope'))
    out = avq.analyze_positions('cf', window_seconds=60)
    assert out == {'positions': None}
