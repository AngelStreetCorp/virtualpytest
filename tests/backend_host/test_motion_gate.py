"""Unit tests for the motion-gate decision in the 1 Hz localize loop.

Covers the pure `gate_motion_decision` function (no fixtures, no I/O): every
shape of motion dict the gate can see, the pct threshold boundary for 'minor',
and the defensive defaults for malformed input. The state-tracking / cache /
force-tail logic lives in `MonitorLocalizer._update_motion_state` and is
exercised end-to-end via the standalone monitor; here we keep the rule itself
isolated so a future tweak to the rule has a single, fast check.
"""

import os
import sys

# Tests are run from the repo root, but the helpers live under backend_host/
# and shared/. Mirror the conftest style used by sibling test_identify_screen_*
# files: prepend the path so a bare `python -m pytest tests/backend_host/...`
# works without a `conftest.py` rewrite.
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend_host.scripts.monitor_localize import (
    GATE_LIVE,
    GATE_MOTION,
    GATE_MINOR_PCT_FLOOR,
    GATE_TRANSITION_FORCE_SECONDS,
    gate_motion_decision,
)


# ---------------------------------------------------------------------------
# Pure rule — every motion shape
# ---------------------------------------------------------------------------


def test_gate_no_motion_runs_matcher():
    assert gate_motion_decision(None) is None
    assert gate_motion_decision({}) is None


def test_gate_fused_live_state_skips():
    # Fused 'live' state (held behind the gatekeeper sustain window) wins over
    # any raw kind — the gatekeeper's view of "this is a live broadcast" is
    # the authoritative input when it is present.
    assert gate_motion_decision({"kind": "static", "state": "live"}) == GATE_LIVE


def test_gate_full_kind_skips_live():
    # Raw 'full' (full-frame distributed motion) without a fused state still skips
    # as 'live' — the no-node / full-motion pattern that signals a live channel.
    assert gate_motion_decision({"kind": "full"}) == GATE_LIVE


def test_gate_band_kind_skips_motion():
    # Horizontal moving strip = carousel; the gate serves the cached verdict.
    assert gate_motion_decision({"kind": "band"}) == GATE_MOTION


def test_gate_box_kind_runs_matcher():
    # Compact moving region (PiP) — the localize loop should still try to
    # identify the surrounding chrome, even though a small region is moving.
    assert gate_motion_decision({"kind": "box"}) is None


def test_gate_static_kind_runs_matcher():
    assert gate_motion_decision({"kind": "static"}) is None


# ---------------------------------------------------------------------------
# 'minor' pct threshold boundary (the 1% floor)
# ---------------------------------------------------------------------------


def test_gate_minor_above_floor_skips_motion():
    # A few percent of pixels changing every frame is enough to keep the gate
    # closed — that's the carousel / ticker case.
    assert gate_motion_decision({"kind": "minor", "pct": 1.5}) == GATE_MOTION
    assert gate_motion_decision({"kind": "minor", "pct": 100.0}) == GATE_MOTION


def test_gate_minor_at_or_below_floor_runs_matcher():
    # Exactly the floor: inclusive — runs the matcher (a sub-floor twitch is
    # not enough to conclude "this is a moving screen").
    assert gate_motion_decision({"kind": "minor", "pct": 1.0}) is None
    assert gate_motion_decision({"kind": "minor", "pct": 0.5}) is None
    assert gate_motion_decision({"kind": "minor", "pct": 0.0}) is None


def test_gate_minor_missing_pct_runs_matcher():
    # No pct at all: defensive default — run the matcher. We never want the
    # gate to crash the 1 Hz loop on a freshly-decoded motion dict.
    assert gate_motion_decision({"kind": "minor"}) is None


def test_gate_minor_non_numeric_pct_runs_matcher():
    # Tolerate type errors (e.g. a JSON-decoded "abc" or a None) and default to
    # running the matcher. The gate is an optimisation, not a correctness gate.
    assert gate_motion_decision({"kind": "minor", "pct": "abc"}) is None
    assert gate_motion_decision({"kind": "minor", "pct": None}) is None
    # A numeric-looking string IS a number (JSON round-trip preserves it): we
    # respect the value, not the type. Strings that float() can parse fall
    # through the same path as a real float.
    assert gate_motion_decision({"kind": "minor", "pct": "1.5"}) == GATE_MOTION


def test_gate_minor_zero_pct_string_runs_matcher():
    # '0' coerces to 0.0 → not above the floor → run the matcher.
    assert gate_motion_decision({"kind": "minor", "pct": "0"}) is None


# ---------------------------------------------------------------------------
# Defensive defaults — never raises, never lies about its decision
# ---------------------------------------------------------------------------


def test_gate_non_dict_inputs_run_matcher():
    # Anything that is not a dict (None, list, str, …) means "no motion info";
    # the gate is an optimisation, so the safe choice is to run the matcher.
    for bad in (None, [], "live", 0, False, 1.0):
        assert gate_motion_decision(bad) is None, f"unexpected decision for {bad!r}"


def test_gate_unknown_kind_runs_matcher():
    # A new kind we have not taught the gate about: defensive default runs
    # the matcher. Adding a new skip path is an explicit code change; do not
    # silently start skipping on an unknown shape.
    assert gate_motion_decision({"kind": "wave"}) is None
    assert gate_motion_decision({"kind": ""}) is None


# ---------------------------------------------------------------------------
# Constants — guard against silent threshold drift
# ---------------------------------------------------------------------------


def test_gate_constants_are_sane():
    # These are not private — they are part of the documented rule in
    # `gate_motion_decision` and in FINGERPRINT.md, so a reviewer should be
    # able to point at them when reading the rule. If any of these change,
    # the docs must move with them.
    assert GATE_LIVE == "live"
    assert GATE_MOTION == "motion"
    assert 0.0 < GATE_MINOR_PCT_FLOOR <= 5.0            # 1% by spec, allow tiny drift only
    assert 0.0 < GATE_TRANSITION_FORCE_SECONDS <= 5.0   # 1.5 s by spec, allow tiny drift only
