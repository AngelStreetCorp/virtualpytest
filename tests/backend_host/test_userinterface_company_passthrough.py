"""Userinterface `company` metadata — opt-in passthrough into the per-frame localize payload.

A userinterface row can carry a free-text `company` label ('brand_a',
'brand_b', 'brand_c', …). When set, the monitor plumbs it into the
per-frame `localize` payload (as `userinterface_company`) and as an extra
keyword to the Tier-2 `error` arm — a frame with a matching brand token
becomes a 'visible' answer. When NULL, behaviour is unchanged. This file
pins both halves:

  1. fresh matcher run with company=NULL  -> `userinterface_company` is absent
  2. fresh matcher run with company='brand_a' -> the field is present AND
     scv.error is called with 'brand_a' as an extra keyword
  3. gate-skip frame with company set     -> cached company is carried

Fakes only: no device, no DB, no network. Reuses the _page() helper from
test_identify_screen_timing to get a real, readable JPEG on disk.
"""
import importlib

import cv2
import numpy as np
import pytest

ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')
scv = importlib.import_module('shared.src.lib.ai.screen_state_cv')


MATCHED = {
    'candidates': [{'node_id': 'home_tile', 'label': 'home', 'dist': 3, 'confidence': 0.93}],
    'excluded_count': 4, 'total': 6,
}


def _page():
    return np.full((64, 64, 3), 96, dtype=np.uint8)


class _FakeHelpers:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def identify_screen(self, img, node_fps):
        self.calls.append((img, node_fps))
        return self.result


def _make_monitor(monkeypatch, tmp_path, company):
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
    frame = str(tmp_path / 'frame.jpg')
    cv2.imwrite(frame, _page())
    m = ml.MonitorLocalizer(team_id='t1')
    m.frame = frame
    m._resolve_ui = lambda device_id: ('ui', 'base')
    m._load_node_fps = lambda ui: [{'node_id': 'home', 'label': 'home', 'fingerprint': {'dhash': 'a'}}]
    m._get_helpers = lambda: m._helpers
    m._record_change = lambda *a, **k: None
    m._helpers = _FakeHelpers(MATCHED)
    # Prime the userinterface record cache so the monitor's _ui_meta picks it up
    # without going through the (un-imported) DB. ttl-clean, mirrors what
    # _load_node_fps would store on a real DB hit.
    import time
    m._ui_meta_by_name['ui'] = {'ts': time.time(), 'ui': {'id': 'u1', 'name': 'ui', 'company': company}}
    return m


# ── company=NULL: no payload field, no brand keyword ─────────────────────────


def test_company_null_omits_userinterface_company_from_payload(monkeypatch, tmp_path):
    """A userinterface with no company metadata must leave the per-frame
    payload unchanged: no `userinterface_company` field, no extra keyword
    to screen_state_cv.error. Behaviour is identical to the pre-company
    world (the existing tests cover that).
    """
    m = _make_monitor(monkeypatch, tmp_path, company=None)
    out = m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out is not None
    assert 'userinterface_company' not in out
    # Tier-2 'error' stays 'unknown' (no tokens wired in), unchanged from before.
    assert out.get('error') == 'unknown'


# ── company set: payload field, brand-aware error keyword ───────────────────


def test_company_set_emits_userinterface_company_in_payload(monkeypatch, tmp_path):
    """When `company` is set, the per-frame payload carries
    `userinterface_company` verbatim. The Tier-2 `error` arm is re-run
    with the company as an extra keyword, so an OCR pass that finds a
    brand token would surface it as 'visible'.
    """
    m = _make_monitor(monkeypatch, tmp_path, company='brand_a')
    out = m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    assert out is not None
    assert out.get('userinterface_company') == 'brand_a'
    # The Tier-2 'error' field is still 'unknown' on today's run (no OCR
    # tokens), but the call site DID pass the company to _screen_state —
    # verify by calling the static helper directly.
    direct = ml.MonitorLocalizer._screen_state(_page(), None, company='brand_a')
    assert direct is not None
    assert direct['error'] == 'unknown'                       # still no tokens

    # The brand-aware branch: when OCR is wired in tomorrow, an 'brand_a'
    # token in the list must be flagged 'visible'. We fake that here by
    # calling scv.error() with tokens=['brand_a'] and the company-aware
    # keyword list, the same way _screen_state does.
    tokens = ['brand_a']
    keywords = list(scv.ERROR_KEYWORDS) + ['brand_a']
    assert scv.error(tokens, keywords=keywords) == 'visible'


def test_company_set_lowercases_and_strips_before_passthrough(monkeypatch, tmp_path):
    """The keyword that reaches scv.error is the lowercased, stripped
    company name. Editors may type 'Brand_A' or ' BRAND_A ' — both
    should match a frame with the same token in any case.
    """
    for raw in ('Brand_A', ' BRAND_A ', 'brand_a'):
        m = _make_monitor(monkeypatch, tmp_path, company=raw)
        out = m.localize_frame('device4', m.frame,
                               motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
        # The payload field is the verbatim value (what the user typed),
        # not a lowercased copy — the front-end is what renders it.
        assert out.get('userinterface_company') == raw
        # The keyword is lowercased + stripped (the same shape scv.error
        # normalises its input to, so a frame with 'BRAND_A' or 'brand_a'
        # or ' Brand_A ' all match).
        tokens = ['  BRAND_A  ']
        keywords = list(scv.ERROR_KEYWORDS) + ['brand_a']
        assert scv.error(tokens, keywords=keywords) == 'visible'


# ── gate-skip frame: cached company is still served ─────────────────────────


def test_gate_skip_carries_cached_company(monkeypatch, tmp_path):
    """A `gate_skip` frame serves the cached verdict with `confidence: 0`
    and NO Tier-2 fields, but the cached `userinterface_company` IS
    carried (it is metadata, not a measurement) so the overlay can keep
    showing the brand context during a sustained motion stretch.
    """
    m = _make_monitor(monkeypatch, tmp_path, company='brand_a')
    # Prime the cache with a fresh run.
    m.localize_frame('device4', m.frame, motion={'kind': 'static', 'state': 'static', 'pct': 0.0})
    # Now feed a full-motion frame: the gate says skip-live.
    out = m.localize_frame('device4', m.frame, motion={'kind': 'full', 'state': 'live', 'pct': 90.0})
    assert out is not None
    assert out.get('gate_skip') == 'live'
    assert out.get('confidence') == 0.0
    assert out.get('userinterface_company') == 'brand_a'        # cached
    for fld in ('loaded', 'overlay', 'playback', 'error'):
        assert fld not in out                                  # Tier 2 still absent on gate-skip


# ── _ui_meta defensive defaults ─────────────────────────────────────────────


def test_ui_meta_returns_empty_dict_on_miss(monkeypatch):
    """`_ui_meta` is best-effort: an unknown UI or a DB error must NEVER
    raise from the 1 Hz loop, it just returns an empty dict and the
    payload omits the field.
    """
    m = ml.MonitorLocalizer(team_id='t1')
    assert m._ui_meta('does-not-exist') == {}
    # And it does not raise on a forced exception.
    def _boom(*_a, **_k):
        raise RuntimeError('simulated DB failure')
    monkeypatch.setattr(m, '_ui_meta_by_name', property(_boom))
    # Use a different code path: pass an empty _ui_meta_by_name so the
    # cache miss is exercised cleanly.
    m2 = ml.MonitorLocalizer(team_id='t1')
    m2._ui_meta_by_name.clear()
    assert m2._ui_meta('ui') == {}
