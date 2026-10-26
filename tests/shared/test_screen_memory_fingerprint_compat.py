"""G2/G3 retrieval compatibility — the stored v6 fingerprint does not break
`screen_memory.match_screen`, and legacy rows still match by dhash.

`match_screen` reads only ``dhash`` and ``region_center`` from the row; the new
``fingerprint`` JSONB is extra data for the classifier/registration, never a
matching input.
"""
import importlib

import pytest

sm = importlib.import_module('shared.src.lib.screen_memory')

pytestmark = pytest.mark.unit

FULL = 'f' * 64      # 256 set bits
CENTER = 'f' * 64
DIFFERENT = '0f' * 32  # 128-bit difference from FULL, above the 12-bit floor


def test_row_with_full_fingerprint_still_matches():
    row = {'id': 'r1', 'dhash': FULL, 'region_center': CENTER,
           'fingerprint': {'v': 6, 'dhash': FULL, 'regions': {'center': CENTER}}}
    got = sm.match_screen({'dhash': FULL, 'region_center': CENTER}, [row])
    assert got is not None
    assert got[0]['id'] == 'r1'
    assert got[1] == 0


def test_legacy_row_without_center_matches_by_dhash():
    row = {'id': 'r2', 'dhash': FULL, 'region_center': '', 'fingerprint': None}
    got = sm.match_screen({'dhash': FULL, 'region_center': CENTER}, [row])
    assert got is not None
    assert got[0]['id'] == 'r2'


def test_different_screen_does_not_match():
    row = {'id': 'r3', 'dhash': FULL, 'region_center': CENTER}
    got = sm.match_screen({'dhash': DIFFERENT, 'region_center': CENTER}, [row])
    assert got is None
