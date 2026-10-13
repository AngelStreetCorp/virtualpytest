"""
Perceptual image hash (dHash) shared by the host fingerprint matcher and the
AI training-sample index.

Moved out of ``ImageHelpers._dhash_hex`` / ``_dhash_hamming``
(backend_host/src/controllers/verification/image_helpers.py) so code in
``shared/`` can compute the same hash. ``ImageHelpers`` delegates here, so both
callers produce identical strings and distances.
"""

import cv2
import numpy as np


def dhash_hex(gray: np.ndarray, grid: int, bits: int) -> str:
    """Difference hash of a grayscale image, as a zero-padded hex string.

    ``grid`` is the side of the comparison grid (16 -> 16x16 = 256 bits);
    ``bits`` sets the hex width (``bits // 4`` characters).
    """
    r = cv2.resize(gray, (grid + 1, grid), interpolation=cv2.INTER_AREA)
    flat = (r[:, 1:] > r[:, :-1]).flatten()
    val = 0
    for b in flat:
        val = (val << 1) | int(b)
    return format(val, 'x').zfill(bits // 4)


def dhash_hamming(hex_a: str, hex_b: str) -> int:
    """Hamming distance between two dHash hex strings."""
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count('1')


def dhash_popcount(hex_hash: str) -> int:
    """Number of set bits of a dHash hex string (0 for an empty hash).

    A dHash bit says "the next pixel is brighter", so flat frames (black, no signal) and
    frames that only darken left to right (colour bars) have almost no set bits."""
    if not hex_hash:
        return 0
    return bin(int(hex_hash, 16)).count('1')
