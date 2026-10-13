"""shared image_hash == the pre-extraction ImageHelpers dHash (TASK-27 step 2).

The expected hex strings were recorded from the ORIGINAL ImageHelpers._dhash_hex
(internal/main 85adacc55, before the body moved to shared/src/lib/utils/image_hash.py).

Run: pytest tests/shared/test_image_hash.py -v
"""
import os
import sys

import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.utils.image_hash import dhash_hamming, dhash_hex  # noqa: E402

GRID, BITS = 16, 256   # ImageHelpers.FP_DHASH_GRID / FP_DHASH_BITS


def _arrays():
    yy1, xx1 = np.mgrid[0:120, 0:160]
    a1 = ((xx1 * xx1 + 3 * yy1 * yy1) % 251).astype(np.uint8)
    yy, xx = np.mgrid[0:90, 0:160]
    a2 = ((xx * 7 + yy * 13) % 256).astype(np.uint8)
    a3 = np.random.default_rng(1234).integers(0, 256, size=(72, 128), dtype=np.uint8)
    return [a1, a2, a3]


EXPECTED = [
    "cc948a644b65ef26656b9595931a356ad4931649556a2b6aec34339532a522ba",
    "cccd99bb3776eeecdd9933336666cccd99bb3776eeccdd99b3336666cccd99bb",
    "c22745a5096aa1c69a99993527b5578d7c5273544966eb2e945ac4ea2574b71f",
]


@pytest.mark.parametrize("idx", range(3))
def test_matches_pre_extraction_output(idx):
    assert dhash_hex(_arrays()[idx], GRID, BITS) == EXPECTED[idx]


def test_hex_width_follows_bits():
    h = dhash_hex(_arrays()[0], GRID, BITS)
    assert len(h) == 64


def test_hamming_with_itself_is_zero():
    for h in EXPECTED:
        assert dhash_hamming(h, h) == 0


def test_one_flipped_bit_is_one():
    h = EXPECTED[2]
    flipped = format(int(h, 16) ^ (1 << 77), "x").zfill(64)
    assert dhash_hamming(h, flipped) == 1
    assert dhash_hamming(flipped, h) == 1


def test_image_helpers_delegates_to_shared_hash():
    """ImageHelpers keeps its method names and returns the same strings/distances."""
    try:
        from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    except Exception as e:  # host deps missing in this environment
        pytest.skip(f"ImageHelpers not importable here: {e}")
    helpers = ImageHelpers.__new__(ImageHelpers)
    for arr, expected in zip(_arrays(), EXPECTED):
        assert helpers._dhash_hex(arr) == expected
    assert ImageHelpers._dhash_hamming(EXPECTED[0], EXPECTED[1]) == dhash_hamming(EXPECTED[0], EXPECTED[1])
