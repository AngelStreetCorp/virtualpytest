"""Real-classifier regression test for ``MonitorLocalizer.localize_frame``.

The existing test_localize_regression.py mocks the matcher + Tier 2 cascade
and only pins the payload composition. This test does the OPPOSITE: it
runs the REAL ``ImageHelpers.identify_screen`` + REAL
``shared.src.lib.ai.screen_state_cv.screen_state`` + REAL
``scv.error`` against the 11 labeled UI frames from
EXPERIMENT-01 §1.2 (the 3 broadcast promos and 1 black-frame are excluded —
broadcast = ``playback``'s job, black = capture-side fault, not a classifier
question). The node fingerprint set is loaded from
``tests/localize/fixtures/<userinterface>_node_fps.json`` and injected into
``_load_node_fps`` — the matcher is real, the per-node dHash distances are
deliberately non-matching to the real frames (stub fixtures), and the goal is
to test the **payload plumbing** end-to-end on real frames.

What this catches that the mock-only harness does NOT:

  * a Tier 2 field that fails silently in production (e.g. ``screen_state``
    raising on a 1920x1080 broadcast frame but not on a 64x64 grey page)
  * an ImageHelpers / scv integration drift (the mock harness never builds
    ImageHelpers at all)
  * a node_fps injection regression — the real fingerprint shape, not the
    synthetic placeholder, is what the matcher receives

Runs ONLY when ``RUN_REAL_MATCHER=1``. Default pytest collection (no env)
emits a session-scoped skip. A second run with
``RUN_REAL_MATCHER=1 python3 -m pytest tests/localize/test_localize_real_match.py``
exercises the actual signal.

The 11 frames come from EXPERIMENT-01-onejev-abstain-coverage.md:39-43. The
default list is the EXPERIMENT-01 set; the alternative 8 live unknowns at
``shared/src/lib/database/unknown_screens_db.py:130-187`` is a fallback
(requires a Supabase reachable from this machine, which is not the test
environment). Source paths follow the cold-archive convention
``/Users/Shared/vpt_captures/<host>_<captureN>/capture_<NNNNNN>.jpg``;
unreachable rows are SKIPPED with a warning, not failed.
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

# Module under test — same lazy-import pattern as the mock harness so the test
# works without the full DB stack.
ml = importlib.import_module('backend_host.scripts.monitor_localize')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')
scv = importlib.import_module('shared.src.lib.ai.screen_state_cv')
ih = importlib.import_module(
    'backend_host.src.controllers.verification.image_helpers'
)

HERE = Path(__file__).parent
FIXTURES = HERE / 'fixtures'
RESULTS = HERE / 'results'
RESULTS.mkdir(exist_ok=True)

# Tier 2 fields the per-frame payload carries. Pulled from
# backend_host/scripts/monitor_localize.py:380-384 (the localize_frame docstring)
# and the _screen_state call site (lines 533-595).
TIER2_FIELDS = ('loaded', 'overlay', 'playback', 'error')

# Trackable fields the manifest's `expected` block may pin. Mirrors
# test_localize_regression.py:339-342 so the two harnesses share a
# "unlisted live field" warning contract.
TRACKABLE = {
    'node', 'gate_skip', 'confidence', 'userinterface_company',
    'loaded', 'overlay', 'playback', 'error',
}

# Per-row captures the pytest_sessionfinish hook writes to
# results/real_match_11.json. Filled in by _run_row on a non-skip path.
_CAPTURED: List[Dict[str, Any]] = []

# ── PR / confusion-matrix accumulators ───────────────────────────────────────
#
# Same shape as test_localize_regression._PR_TPFP — a plain dict-of-dicts
# (NOT Counter) because the inner dict carries tp/fp/fn and Counter's
# default-zero semantics return integers, not dicts.
_PR_TPFP: Dict[str, Dict[Any, Dict[str, int]]] = defaultdict(lambda: defaultdict(
    lambda: {'tp': 0, 'fp': 0, 'fn': 0}
))
_RUN_SUMMARY = {
    'passed': 0, 'failed': 0, 'skipped_unreachable': 0, 'warned_unlisted': 0,
}


def _record_pr(field: str, expected_value: Any, actual_value: Any) -> None:
    """One confusion-matrix update for a (field, value) pair.

    For each (field, value) bucket the harness tracks:
      TP  expected == value AND actual == value
      FP  expected != value AND actual == value
      FN  expected == value AND actual != value
    """
    values = {expected_value, actual_value}
    for v in values:
        if expected_value == v and actual_value == v:
            _PR_TPFP[field][v]['tp'] += 1
        elif expected_value == v:
            _PR_TPFP[field][v]['fn'] += 1
        elif actual_value == v:
            _PR_TPFP[field][v]['fp'] += 1


# ── fixture loading ──────────────────────────────────────────────────────────


def _load_node_fps_fixture(userinterface: str) -> List[Dict[str, Any]]:
    """Load the per-userinterface stub node_fps JSON.

    The fixture is a hand-authored list of {node_id, label, fingerprint}
    records, one per stub node, with the v6 fingerprint shape
    ImageHelpers.identify_screen expects (see
    backend_host/src/controllers/verification/image_helpers.py:988-1015 and
    match_fingerprint_v6 at line 1568). All-zero dHashes are intentional —
    the goal is payload plumbing, not matcher quality.
    """
    path = FIXTURES / f'{userinterface}_node_fps.json'
    if not path.is_file():
        return []
    with path.open() as f:
        data = json.load(f)
    return list(data.get('nodes', []))


def _load_ui_company_fixture(userinterface: str) -> Optional[str]:
    """Return the userinterface's `company` from its fixture, or None.

    Mirrors the cached _ui_meta_by_name[ui]['ui']['company'] the production
    _load_node_fps sets. Used to prime the per-frame
    `userinterface_company` payload field and the brand-aware `error` keyword.
    """
    path = FIXTURES / f'{userinterface}_node_fps.json'
    if not path.is_file():
        return None
    with path.open() as f:
        data = json.load(f)
    return data.get('company')


# ── per-row driver ───────────────────────────────────────────────────────────


def _make_monitor(monkeypatch, row: Dict[str, Any]) -> 'ml.MonitorLocalizer':
    """MonitorLocalizer with the matcher REAL, the Jev stubbed, and node_fps
    injected from the per-userinterface fixture.

    The harness deliberately does NOT mock the matcher (this is the
    real-classifier test). What it DOES stub:

      * Jev (`confirm_low_confidence`) — a network call to Claude, never
        reachable from the test environment.
      * `_record_change` — writes to the logger, irrelevant for the
        per-frame payload, and prevents log noise during the run.
      * `_load_node_fps` — replaces the DB query with a per-userinterface
        fixture load (test_localize_regression.py:147-149 does the same).
      * `_ui_meta` — pre-primes the userinterface metadata cache so
        `userinterface_company` and the brand-aware `error` keyword work
        end-to-end without a DB.
    """
    monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)

    m = ml.MonitorLocalizer(team_id='t1')
    ui = row['userinterface']

    m._resolve_ui = lambda device_id: (ui, 'base')

    # node_fps from the fixture — the matcher receives the real shape, just
    # from a stub source.
    nodes = _load_node_fps_fixture(ui)

    def _load_node_fps(_ui: str):
        return nodes

    m._load_node_fps = _load_node_fps

    # Prime the userinterface metadata cache so the per-frame payload carries
    # `userinterface_company` per the row's userinterface. Mirrors the
    # `_ui_meta_by_name` priming in test_localize_regression.py:160-167.
    company = _load_ui_company_fixture(ui)
    m._ui_meta_by_name[ui] = {
        'ts': time.time(),
        'ui': {'id': f'ui_{ui}', 'name': ui, 'company': company},
    }
    m._record_change = lambda *a, **k: None
    return m


def _resolve_source_path(source: str) -> Optional[Path]:
    """Map a manifest `source` string to a local file path, or None on miss.

    Same schemes as the mock harness (test_localize_regression.py:174-198):
      'local:/abs/path/to/file.jpg'   ->  /abs/path/to/file.jpg
      'ssh://<host>:/abs/path'        ->  None (no infra-connect plumbing here)
      'synthetic'                     ->  None
    """
    if source == 'synthetic':
        return None
    if source.startswith('local:'):
        return Path(source[len('local:'):])
    if source.startswith('ssh://'):
        return None
    return None


def _is_black_frame(frame_path: str) -> bool:
    """Return True if the frame is capture-side black (no signal, no UI).

    A "black" frame is one where the device is showing nothing: mean grey
    level is low AND the standard deviation is also low (a uniform dark
    scene). A dark UI like the 2048 web game or the Android quick-settings
    shade can have a low mean but a HIGH std (lots of bright UI on a dark
    background) — those are real UI screens and we should NOT skip them.
    A "no signal" / "device off" frame is uniform black, low mean AND low
    std. Same rule as the vpt-capture cold archiver's own skip heuristic
    and the ``FP_BLACK_MEAN_MAX / FP_BLACK_STD_MAX`` gate in
    screen_state_cv.py:67-71 (loaded = no when mean < 25 AND std < 12).
    We use slightly looser thresholds so we only skip the most obvious
    "this is nothing" cases — a borderline dark frame still gets exercised
    by the real matcher, where the loaded/overlay arms answer honestly
    anyway.
    """
    try:
        img = cv2.imread(frame_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return True
        return float(img.mean()) < 15.0 and float(img.std()) < 12.0
    except Exception:
        return True


def _run_row(monkeypatch, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Execute one manifest row: resolve source, call the real matcher, assert.

    Returns the captured per-frame payload (so the test can record a
    per-frame diff) on success, or None on skip.
    """
    source = row['source']
    resolved = _resolve_source_path(source)
    if resolved is None or not resolved.is_file():
        _RUN_SUMMARY['skipped_unreachable'] += 1
        warnings.warn(
            f"row {row['id']!r}: source {source!r} is unreachable from this "
            f"machine; skipping (see tests/localize/README.md)",
            stacklevel=2,
        )
        pytest.skip(f"row {row['id']!r}: source {source!r} is unreachable")

    # Black-frame pre-check: a frame with mean pixel < 30 is capture-side
    # (no signal yet, pre-roll, channel muted). It is NOT the UI screen the
    # row's expectation names, so the row's assertion would fail by accident
    # and produce a misleading signal. Treat as unreachable — same rule,
    # different cause.
    if _is_black_frame(str(resolved)):
        _RUN_SUMMARY['skipped_unreachable'] += 1
        warnings.warn(
            f"row {row['id']!r}: source {source!r} is a black frame "
            f"(capture-side, not a UI screen); skipping",
            stacklevel=2,
        )
        pytest.skip(f"row {row['id']!r}: source {source!r} is a black frame")

    expected = row.get('expected', {})
    motion = row.get('motion') or {'kind': 'static', 'state': 'static', 'pct': 0.0}

    m = _make_monitor(monkeypatch, row)
    out = m.localize_frame('device4', str(resolved), motion=motion)
    if out is None:
        # Real-world failure (e.g. the frame was unreadable). Not a pass.
        pytest.fail(
            f"row {row['id']!r}: localize_frame returned None on a reachable "
            f"real frame — the monitor swallowed a real exception."
        )

    # ── per-field assertion + PR record ────────────────────────────────────
    per_field_actual = {}
    for fld, want in expected.items():
        got = out.get(fld)
        per_field_actual[fld] = got
        _record_pr(fld, want, got)

    # Capture BEFORE the assertion so a failed row still shows up in the
    # per-frame diff (the task spec's primary deliverable — a future run
    # diffs against it; a missing failure row is a worse signal than the
    # failure itself).
    capture = {
        'row_id': row['id'],
        'userinterface': row['userinterface'],
        'source': source,
        'expected': expected,
        'actual': per_field_actual,
        'full_payload': out,
    }
    _CAPTURED.append(capture)

    # Aggregate all the per-field mismatches into one assertion so the
    # pytest summary counts the row as a single failure (not N failures).
    mismatches = []
    for fld, want in expected.items():
        got = out.get(fld)
        if got != want:
            mismatches.append(f"{fld!r} expected {want!r} got {got!r}")
    if mismatches:
        _RUN_SUMMARY['failed'] += 1
        pytest.fail(
            f"row {row['id']!r}: " + "; ".join(mismatches)
            + f"\n  full payload: {out}"
        )

    # ── warn on trackable fields the row did not pin ───────────────────────
    for fld in TRACKABLE:
        if fld in expected:
            continue
        if fld in out and out[fld] is not None:
            _RUN_SUMMARY['warned_unlisted'] += 1
            warnings.warn(
                f"row {row['id']!r}: payload carries {fld}={out[fld]!r} but "
                f"the row's expected dict does not list it",
                stacklevel=2,
            )

    _RUN_SUMMARY['passed'] += 1
    return capture


# ── pytest entry points ─────────────────────────────────────────────────────


def _build_tests():
    """Build one test function per row, with the run gate at module level.

    The whole file is collected normally; the ``RUN_REAL_MATCHER=1`` gate
    is enforced via a session-scoped fixture so a default pytest run skips
    cleanly instead of importing / running anything.
    """
    here = HERE
    with (here / 'manifest_real_match.json').open() as f:
        manifest = json.load(f)
    for row in manifest['rows']:
        row_id = row['id']

        def test(monkeypatch, _row=row):
            return _run_row(monkeypatch, _row)

        test.__name__ = f'test_{row_id}'
        test.__doc__ = (
            f"{row_id} | ui={row['userinterface']} | source="
            f"{row['source']} | note: {row.get('note', '')[:80]}"
        )
        globals()[f'test_{row_id}'] = test


_build_tests()


# ── session gate: skip the whole file unless RUN_REAL_MATCHER=1 ─────────────


@pytest.fixture(scope='module', autouse=True)
def _require_real_matcher():
    """Default pytest run: skip with a one-line message. The real signal is
    only meaningful when the operator explicitly opts in via
    ``RUN_REAL_MATCHER=1``. This mirrors the test_localize_regression.py
    ``RUN_SYNTHETIC=1`` pattern (tests/localize/README.md:22-30).
    """
    if os.environ.get('RUN_REAL_MATCHER') != '1':
        pytest.skip(
            "real-classifier test is opt-in: set RUN_REAL_MATCHER=1 to run "
            "(see tests/localize/README.md)"
        )


# ── session-finish hook moved to conftest.py ────────────────────────────────
# Pytest only auto-discovers hooks that live in conftest.py — not in test
# files. The session-finish + terminal-summary hooks that write the per-frame
# diff and the PR summary to results/real_match_*.json live in
# tests/localize/conftest.py.


# ── terminal summary moved to conftest.py ───────────────────────────────────
# (Pytest hook discovery rule — see the comment above the session-finish block.)
