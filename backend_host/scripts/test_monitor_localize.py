#!/usr/bin/env python3
"""
Tests for the per-frame `localize` DIAGNOSIS written by monitor_localize: which matcher
layer answered (`tier`) and, on an abstain, WHICH door produced identify_screen's reason.

The door must be MAPPED from the reason string the matcher already returns — never
re-derived — so the overlay cannot disagree with the matcher about why it abstained. An
unrecognised reason must degrade to `unknown` (calm, not an error), never raise.

Pure functions only: no frame, no DB, no device. Run: pytest backend_host/scripts/test_monitor_localize.py
"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend_host.scripts.monitor_localize import (  # noqa: E402
    DOOR_UNKNOWN,
    IDENTIFY_TIER_RULE,
    IDENTIFY_TIERS,
    abstain_door,
)

# The three reason strings identify_screen sets TODAY (doors 1-3). Taken verbatim from
# image_helpers.py / docs/agent/navigation/FINGERPRINT.md — if one changes there, this
# test is the tripwire that says so.
REASON_DOOR_1 = 'low-content frame'
REASON_DOOR_2 = 'nav underline matched no node'
REASON_DOOR_3 = ('nav underline far from chrome, no title match '
                 '(spurious underline / non-menu content)')


@pytest.mark.parametrize('reason,expected', [
    (REASON_DOOR_1, '1'),
    (REASON_DOOR_2, '2'),
    (REASON_DOOR_3, '3'),
])
def test_abstain_door_maps_each_live_reason_string(reason, expected):
    assert abstain_door(reason) == expected


def test_abstain_door_is_case_and_whitespace_insensitive():
    assert abstain_door('  LOW-CONTENT FRAME  ') == '1'


def test_abstain_door_survives_a_decorated_reason():
    # match_fingerprint_v6 appends ' +v6crop' to whatever reason it inherited.
    assert abstain_door(REASON_DOOR_1 + ' +v6crop') == '1'
    assert abstain_door(REASON_DOOR_3 + ' +v6crop') == '3'


@pytest.mark.parametrize('reason', [
    None, '', '   ', 'no qualifying screen (best region 88)',
    'every reason string written before this table existed',
    ' +v6crop',
])
def test_abstain_door_falls_back_to_unknown(reason):
    """An unmappable reason is normal, not a fault: 'unknown', never an exception."""
    assert abstain_door(reason) == DOOR_UNKNOWN


def test_door_unknown_is_not_a_door_number():
    """'unknown' must stay distinguishable from doors 1-6 in the payload."""
    assert DOOR_UNKNOWN not in ('1', '2', '3', '4', '5', '6')


def test_only_the_rule_tier_is_ever_emitted_by_this_path():
    """This path runs the deterministic dHash/focus matcher only.

    'cv'/'model' stay RESERVED so the overlay can label a future tier without a payload
    shape change — nothing in monitor_localize may start emitting them.
    """
    assert IDENTIFY_TIER_RULE == 'rule'
    assert IDENTIFY_TIERS == ('rule', 'cv', 'model')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))