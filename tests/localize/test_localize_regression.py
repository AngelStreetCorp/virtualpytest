"""Regression harness for ``MonitorLocalizer.localize_frame``.

Three commits just landed on ``main``:

  c3af47fec  motion gate on the 1 Hz localize tick
  aacc08dff  wire Tier 2 (screen_state_cv) into the per-frame localize payload
  861451d29  userinterface ``company`` metadata (opt-in brand passthrough)

They changed the shape of the per-frame ``localize`` payload. New fields:

  gate_skip             'live' | 'motion' | null
  userinterface_company str   | null  (opt-in brand passthrough)
  loaded                'yes' | 'no' | 'unknown'
  overlay               'none' | 'popup' | 'tooltip' | 'keyboard' | 'notification' | 'unknown'
  playback              'playing' | 'paused' | 'stopped' | 'not_applicable' | 'unknown'
  error                 'none' | 'visible' | 'unknown'

A new function ``MonitorLocalizer.localize_frame(device_id, frame_path, motion=...)``
takes a motion dict shaped like ``{"kind": "static|full|band|box|minor", "pct": float,
"state": "static|ui|live|motion|unknown"}``.

This harness drives ``localize_frame`` over a labeled set of captures (see
``manifest.json``) and asserts the per-frame payload matches expectations. It
catches future classifier regressions before they ship, and feeds the operator
capture job (item 3 in EXPERIMENT-01 §7.1).

The harness is fakes-only: no device, no DB, no network. It mirrors the fake
pattern in ``tests/backend_host/test_userinterface_company_passthrough.py`` and
``tests/backend_host/test_localize_tier2.py`` (mock the matcher via
``_load_node_fps`` and ``_get_helpers``, mock the Tier-2 cascade via
``scv.screen_state``). Frames just need to be readable by ``cv2.imread`` — the
harness generates a 64x64 grey placeholder for ``synthetic`` rows.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytest

# Module under test (imported lazily so the harness works without the full DB stack).
ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')
scv = importlib.import_module('shared.src.lib.ai.screen_state_cv')

# ── shared fakes ──────────────────────────────────────────────────────────────


def _grey_page() -> np.ndarray:
    """A 64x64 grey page. Readable JPEG, enough for cv2.imread. Intentionally
    NOT random noise: the harness mocks the matcher and Tier-2, so the actual
    pixel content does not matter — but a flat colour keeps the test fast and
    the inputs predictable.
    """
    return np.full((64, 64, 3), 96, dtype=np.uint8)


class _FakeHelpers:
    """Stand-in for backend_host.src.controllers.verification.image_helpers.ImageHelpers.

    The harness stubs ``identify_screen`` to return either a matched node or an
    empty candidate list. The matcher is the thing we want to keep OUT of the
    test — Tier-1 fingerprint matching has its own test suite, and coupling the
    regression to it would mean every matcher regression breaks every payload
    regression. So we pin only ``localize_frame``'s composition: gate decision,
    payload shape, Tier-2 merge, company passthrough.
    """

    def __init__(self, result: Dict[str, Any]):
        self.result = result
        self.calls: List[Tuple[Any, Any]] = []

    def identify_screen(self, img, node_fps):
        self.calls.append((img, node_fps))
        return self.result


def _build_matcher_result(node: Optional[str]) -> Dict[str, Any]:
    """The exact shape ``identify_screen`` returns when it matches (or abstains).

    A row with ``expected.node`` set produces a 1-candidate match; a row with
    ``expected.node is None`` produces an empty candidate list (an abstain).
    """
    if node is None:
        return {'candidates': [], 'excluded_count': 0, 'total': 1}
    return {
        'candidates': [{'node_id': node, 'label': node, 'dist': 3, 'confidence': 0.93}],
        'excluded_count': 0, 'total': 1,
    }


def _tier2_stub(expected: Dict[str, Any]) -> Dict[str, str]:
    """Build a ``scv.screen_state`` stub from the row's ``expected`` Tier-2 fields.

    The four keys the cascade returns — ``loaded``, ``overlay``, ``playback``,
    ``error`` — are all optional in the row's ``expected`` dict (a row may
    pin only one of them, e.g. ``{"error": "visible"}``). Missing fields fall
    back to the cascade's own honest default of ``'unknown'`` so the merge in
    ``_screen_state`` still produces a complete Tier-2 dict.

    The harness does NOT call the real ``scv.screen_state`` — that would couple
    the regression to the Tier-2 cascade's own behavior, which has its own
    tests. The point is to assert that ``localize_frame`` MERGES the four
    answers correctly into the payload.
    """
    return {
        'loaded':   expected.get('loaded', 'unknown'),
        'overlay':  expected.get('overlay', 'unknown'),
        'playback': expected.get('playback', 'unknown'),
        'error':    expected.get('error', 'unknown'),
    }


def _make_monitor(monkeypatch, row: Dict[str, Any]) -> 'ml.MonitorLocalizer':
    """MonitorLocalizer with the matcher / fingerprint load / Jev / record all faked.

    Mirrors the pattern in ``tests/backend_host/test_userinterface_company_passthrough.py``
    so the harness can run without a real DB and without ``DEVICE{N}_USERINTERFACE``
    env vars.
    """
    # Jev is a network call (Claude second opinion). Stub it.
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)

    m = ml.MonitorLocalizer(team_id='t1')
    ui = row['userinterface']
    expected = row.get('expected', {})
    node = expected.get('node')

    # node_fps MUST be non-empty even when the row expects `node: None`.
    # The monitor short-circuits to `{node: None, ...}` when node_fps is empty
    # (a misconfigured UI), which would skip the Tier-2 cascade and the gate
    # cache setup — so a blackscreen / live-tv row that should reach Tier 2
    # would never get there. We always pass one synthetic node_fps; the
    # matcher's return value (matched or abstained) is what decides the
    # payload's `node` field.
    m._resolve_ui = lambda device_id: (ui, 'base')
    m._load_node_fps = lambda _ui: [
        {'node_id': 'synthetic', 'label': 'synthetic', 'fingerprint': {'dhash': 'a'}}
    ]
    m._helpers = _FakeHelpers(_build_matcher_result(node))
    m._get_helpers = lambda: m._helpers
    m._record_change = lambda *a, **k: None

    # Userinterface metadata cache. The monitor's _ui_meta reads from
    # _ui_meta_by_name with a TTL; prime it so the per-frame payload
    # includes (or omits) `userinterface_company` per the row's expected.
    # A row with `userinterface_company` in expected sets the company;
    # a row without it (or with it as None) sets the company to None so
    # the field is absent — mirrors the NULL behaviour in production.
    if 'userinterface_company' in expected:
        company = expected['userinterface_company']
    else:
        company = None
    m._ui_meta_by_name[ui] = {
        'ts': time.time(),
        'ui': {'id': 'u1', 'name': ui, 'company': company},
    }
    return m


# ── source resolution ─────────────────────────────────────────────────────────


def _resolve_source_path(source: str) -> Optional[Path]:
    """Map a manifest `source` string to a local file path, or None on miss.

    Supported forms:
      'local:/abs/path/to/file.jpg'   ->  /abs/path/to/file.jpg
      'ssh://<host>:/abs/path'        ->  None (we cannot resolve remote paths
                                            without the infra-connect skill; the
                                            operator runs the harness on the
                                            Pi's local copy, or pulls the
                                            frame via the cold archive).
      'synthetic'                     ->  None (the harness generates a
                                            placeholder in tmp_path).
    """
    if source == 'synthetic':
        return None
    if source.startswith('local:'):
        return Path(source[len('local:'):])
    if source.startswith('ssh://'):
        # Remote source. The harness cannot read it from this machine without
        # SSH plumbing (intentionally — the operator's job, item 3 in
        # EXPERIMENT-01 §7.1, is to plumb real frames into the harness). We
        # do not try to reach out; we just say "unreachable".
        return None
    # Unknown source scheme: treat as missing.
    return None


# ── per-row test driver ───────────────────────────────────────────────────────


# Module-level accumulator for the precision/recall summary at the end of the
# run. We cannot rely on a fixture (pytest does not guarantee execution order
# for parametrized tests), so a module dict is the simplest.
# Schema: _PR_TPFP[field][value] = {'tp': N, 'fp': M, 'fn': K}.
# We use a plain dict-of-dicts-of-dicts (NOT Counter) because Counter's
# default-zero semantics turn into integer returns — `Counter()[v] += 1` works
# but `dict[c] = d['tp'] + 1` then sees an int, not a dict.
_PR_TPFP: Dict[str, Dict[Any, Dict[str, int]]] = defaultdict(lambda: defaultdict(
    lambda: {'tp': 0, 'fp': 0, 'fn': 0}
))
_RUN_SUMMARY = {
    'passed': 0, 'failed': 0, 'skipped_synthetic': 0, 'skipped_unreachable': 0,
    'warned_unlisted': 0,
}


def _record_pr(field: str, expected_value: Any, actual_value: Any) -> None:
    """One confusion-matrix update for a (field, value) pair.

    For each field the row pins, we count:
      TP  expected == value AND actual == value
      FP  expected != value AND actual == value
      FN  expected == value AND actual != value

    The (field, value) pair is keyed by ``value``, which can be None (e.g.
    ``expected.gate_skip is None`` means 'no gate fired'). None is a valid
    bucket; it just means 'the absence of a gate_skip'. We do NOT skip
    None — the absence is a real class the harness tracks.
    """
    values = {expected_value, actual_value}
    for v in values:
        if expected_value == v and actual_value == v:
            _PR_TPFP[field][v]['tp'] += 1
        elif expected_value == v:
            _PR_TPFP[field][v]['fn'] += 1
        elif actual_value == v:
            _PR_TPFP[field][v]['fp'] += 1
    # The schema is _PR_TPFP[field][value] = {'tp', 'fp', 'fn'}; a single
    # increment must have happened above. The defaultdict access above
    # initialises the inner dict on first read, so the structure is now
    # complete and the session-finish summary can read it.


def _run_row(monkeypatch, tmp_path, row: Dict[str, Any]) -> None:
    """Execute one manifest row: resolve the source, mock the cascade, assert.

    Skips (do not fail) on:
      * 'synthetic' source when RUN_SYNTHETIC is not '1'
      * 'local:' source whose file does not exist on disk
      * 'ssh://' source (unreachable from this machine)
    """
    source = row['source']

    # ── 1. Resolve the source path ────────────────────────────────────────────
    is_synthetic = source == 'synthetic'
    if is_synthetic and os.environ.get('RUN_SYNTHETIC') != '1':
        _RUN_SUMMARY['skipped_synthetic'] += 1
        pytest.skip(f"row {row['id']!r} is synthetic; set RUN_SYNTHETIC=1 to run")
    if is_synthetic:
        frame_path = str(tmp_path / f"{row['id']}.jpg")
        cv2.imwrite(frame_path, _grey_page())
    else:
        resolved = _resolve_source_path(source)
        if resolved is None:
            _RUN_SUMMARY['skipped_unreachable'] += 1
            warnings.warn(
                f"row {row['id']!r}: source {source!r} is unreachable from this "
                f"machine; skipping (see tests/localize/README.md §'Plugging in "
                f"real frames')",
                stacklevel=2,
            )
            pytest.skip(f"row {row['id']!r}: source {source!r} is unreachable")
        if not resolved.is_file():
            _RUN_SUMMARY['skipped_unreachable'] += 1
            warnings.warn(
                f"row {row['id']!r}: source file {resolved} does not exist; "
                f"skipping",
                stacklevel=2,
            )
            pytest.skip(f"row {row['id']!r}: source file {resolved} missing")
        frame_path = str(resolved)

    # ── 2. Mock the Tier-2 cascade ────────────────────────────────────────────
    # The harness pins only the merge, not the cascade itself. Stub screen_state
    # so the test does not depend on the real CV running on a 64x64 grey page.
    # _screen_state also calls scv.error() separately for the company passthrough
    # (see backend_host/scripts/monitor_localize.py:585-591), so we stub that
    # function the same way — when the row pins `error` to a value, the stub
    # has to return that value for BOTH the default run and the company-aware
    # re-check.
    expected = row.get('expected', {})
    tier2_state = _tier2_stub(expected)
    monkeypatch.setattr(scv, 'screen_state', lambda *a, **k: tier2_state)
    monkeypatch.setattr(scv, 'error', lambda *a, **k: expected.get('error', 'unknown'))

    # ── 3. Build the monitor and call localize_frame ─────────────────────────
    m = _make_monitor(monkeypatch, row)
    motion = row.get('motion')

    # Gate_skip rows need a primed cache: the very first gated call has no
    # `_last_match` to serve, so the gate falls through to a fresh matcher run
    # (see backend_host/scripts/monitor_localize.py:430-449). To exercise the
    # real gate_skip path we pre-prime by running one call with static motion
    # first, which populates `_last_match`. The harness then re-issues the
    # call with the row's actual motion dict and asserts on the gate_skip
    # payload.
    is_gate_skip_row = expected.get('gate_skip') in ('live', 'motion')
    if is_gate_skip_row:
        prime_motion = {'kind': 'static', 'state': 'static', 'pct': 0.0}
        prime = m.localize_frame('device4', frame_path, motion=prime_motion)
        assert prime is not None, (
            f"row {row['id']!r}: prime call (static motion) returned None — "
            f"the row cannot exercise the gate_skip path without a primed cache"
        )

    out = m.localize_frame('device4', frame_path, motion=motion)
    assert out is not None, (
        f"row {row['id']!r}: localize_frame returned None "
        f"(feature disabled for the device or an exception was caught)"
    )

    # ── 4. Assert every expected field, record PR ────────────────────────────
    for fld, want in expected.items():
        got = out.get(fld)
        _record_pr(fld, want, got)
        assert got == want, (
            f"row {row['id']!r}: field {fld!r} expected {want!r}, got {got!r}\n"
            f"  full payload: {out}"
        )

    # ── 5. Warn on fields that came through but the row did not list ─────────
    # Per the schema: 'absent is don't care, but warn if a value comes through
    # that the manifest didn't list'. Catches additions to the payload that
    # silently slip past old rows (a new Tier-2 field added to localize_frame
    # would, without this check, never be tested on the rows that pre-date it).
    trackable = {
        'node', 'gate_skip', 'confidence', 'userinterface_company',
        'loaded', 'overlay', 'playback', 'error',
    }
    for fld in trackable:
        if fld in expected:
            continue
        if fld in out and out[fld] is not None:
            _RUN_SUMMARY['warned_unlisted'] += 1
            warnings.warn(
                f"row {row['id']!r}: payload carries {fld}={out[fld]!r} but the "
                f"row's expected dict does not list it (the harness treats this "
                f"as 'don't care' but the field is now live — add it to the "
                f"manifest to keep this row useful)",
                stacklevel=2,
            )

    _RUN_SUMMARY['passed'] += 1


# ── pytest entry points ──────────────────────────────────────────────────────


def _make_test(row: Dict[str, Any]):
    """Build a pytest test function for a single row, parametrized by id."""
    row_id = row['id']
    motion_summary = row.get('motion', {})
    src_kind = row['source'].split(':', 1)[0]

    def test(monkeypatch, tmp_path):
        _run_row(monkeypatch, tmp_path, row)

    # Annotate with the row id so pytest -v prints a useful name.
    test.__name__ = f'test_{row_id}'
    test.__doc__ = (
        f"{row_id} | source={src_kind} | motion={motion_summary.get('kind')}/"
        f"{motion_summary.get('state')}/pct={motion_summary.get('pct')} | "
        f"note: {row.get('note', '')[:80]}"
    )
    return test


# Dynamically build one test function per row. The manifest is loaded once at
# collection time; pytest's test id is the row id (so failures point at the
# specific scenario).
def _build_tests():
    here = Path(__file__).parent
    with (here / 'manifest.json').open() as f:
        manifest = json.load(f)
    for row in manifest['rows']:
        globals()[f'test_{row["id"]}'] = _make_test(row)


_build_tests()


# ── precision/recall summary at the end of the run ───────────────────────────
#
# Implemented as a ``pytest_terminal_summary`` hook in
# ``tests/localize/conftest.py`` (pytest only auto-discovers hooks that
# live in a conftest.py — not in test files). The conftest reads
# ``_PR_TPFP`` and ``_RUN_SUMMARY`` from this module via sys.modules,
# prints the per-field P/R/F1, and a one-line run summary, and writes
# both into the visible end-of-run block.

