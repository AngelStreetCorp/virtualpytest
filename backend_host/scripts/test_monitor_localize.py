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

def test_hold_live_keeps_live_over_an_abstain_only_within_the_hold():
    from backend_host.scripts.monitor_localize import LIVE_HOLD_SECONDS, hold_live
    unknown = {"kind": "unknown"}
    unnamed = {"kind": "known_screen", "evidence": {"named": False}}
    assert hold_live(unknown, 100.0, 100.0 + LIVE_HOLD_SECONDS - 1)
    assert hold_live(unnamed, 100.0, 105.0)
    assert not hold_live(unknown, 100.0, 100.0 + LIVE_HOLD_SECONDS + 1)   # live not seen for a while
    assert not hold_live(unknown, None, 105.0)                            # never live
    for k in ("node", "overlay", "signal", "live"):                       # a positive answer ends it
        assert not hold_live({"kind": k}, 100.0, 105.0)
    assert not hold_live({"kind": "known_screen", "evidence": {"named": True}}, 100.0, 105.0)


def test_slow_live_and_audio_cues():
    from backend_host.scripts.monitor_localize import audio_playing, hold_live, slow_live_by_window
    assert slow_live_by_window(['minor', 'minor', 'full'], [2.8, 3.1, 5.3])          # presenter
    assert not slow_live_by_window(['minor', 'minor', 'minor'], [2.8, 1.2, 3.0])      # one tick below 2 %
    assert not slow_live_by_window(['box', 'minor', 'minor'], [3.0, 3.0, 3.0])        # a PiP / trailer box is not live
    assert not slow_live_by_window(['minor', 'static', 'minor'], [3.0, 0.0, 3.0])
    assert not slow_live_by_window(['minor', 'minor'], [3.0, 3.0])                    # window not full yet
    assert audio_playing((True, -24.1), {'kind': 'minor'})
    assert not audio_playing((True, -24.1), {'kind': 'static'})                       # sound over a still picture
    assert not audio_playing((True, -70.0), {'kind': 'minor'})                        # silence
    assert not audio_playing((False, None), {'kind': 'full'})
    assert not audio_playing(None, {'kind': 'full'})
    assert hold_live({'kind': 'unknown'}, None, 100.0, playing=True)                  # cue alone, never seen live
    assert not hold_live({'kind': 'node'}, 100.0, 101.0, playing=True)                # a node still wins


def test_foreground_app_parse_and_label():
    from monitor.foreground_app import adb_address, app_label, parse_package
    t = "topResumedActivity=ActivityRecord{95af49e u0 com.supercell.clashofclans/com.supercell.titan.GameApp t1445}"
    assert parse_package(t) == "com.supercell.clashofclans"
    assert parse_package("nothing here") is None
    assert app_label("com.supercell.clashofclans") == "Clash of Clans"
    assert app_label("com.foo.my_app") == "My App"                       # fallback: last segment
    assert adb_address({"serial": "R5CR", "ip": "1.2.3.4"}) == "R5CR"    # USB serial wins
    assert adb_address({"ip": "1.2.3.4"}) == "1.2.3.4:5555"
    assert adb_address({}) is None
