"""cv2_io reads and writes like cv2.imread / cv2.imwrite, without leaking the path string.

opencv-python keeps a reference to every str filename passed to cv2.imread / cv2.imwrite,
so capture_monitor (two reads per frame) grew to 1.45 GB on vpt-pi1 (BUG-0474).
"""
import gc
import os
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.utils import cv2_io  # noqa: E402


@pytest.fixture
def images(tmp_path):
    rng = np.random.default_rng(7)
    color = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    rgba = rng.integers(0, 255, (40, 60, 4), dtype=np.uint8)
    jpg, png = str(tmp_path / "frame.jpg"), str(tmp_path / "alpha.png")
    cv2.imwrite(jpg, color)
    cv2.imwrite(png, rgba)
    return {"jpg": jpg, "png": png, "tmp": tmp_path, "color": color}


@pytest.mark.parametrize("flags", [None, cv2.IMREAD_COLOR, cv2.IMREAD_GRAYSCALE, cv2.IMREAD_REDUCED_GRAYSCALE_4])
def test_imread_matches_cv2(images, flags):
    args = () if flags is None else (flags,)
    expected = cv2.imread(images["jpg"], *args)
    got = cv2_io.imread(images["jpg"], *args)
    assert got is not None and got.shape == expected.shape
    assert np.array_equal(got, expected)


def test_imread_unchanged_keeps_alpha(images):
    assert np.array_equal(cv2_io.imread(images["png"], cv2.IMREAD_UNCHANGED),
                          cv2.imread(images["png"], cv2.IMREAD_UNCHANGED))


def test_imread_missing_or_not_an_image_is_none(images):
    assert cv2_io.imread(str(images["tmp"] / "missing.jpg")) is None
    bad = images["tmp"] / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert cv2_io.imread(str(bad)) is None
    empty = images["tmp"] / "empty.jpg"
    empty.write_bytes(b"")
    assert cv2_io.imread(str(empty)) is None


def test_imwrite_round_trip_and_params(images):
    png = str(images["tmp"] / "out.png")
    assert cv2_io.imwrite(png, images["color"]) is True
    assert np.array_equal(cv2.imread(png), images["color"])  # PNG is lossless
    low, high = str(images["tmp"] / "q10.jpg"), str(images["tmp"] / "q95.jpg")
    assert cv2_io.imwrite(low, images["color"], [cv2.IMWRITE_JPEG_QUALITY, 10])
    assert cv2_io.imwrite(high, images["color"], [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert os.path.getsize(low) < os.path.getsize(high)
    assert cv2_io.imwrite(str(images["tmp"] / "no_dir" / "x.jpg"), images["color"]) is False


def _leaked_blocks_per_call(fn, n=3000):
    fn()
    gc.collect()
    before = sys.getallocatedblocks()
    for _ in range(n):
        fn()
    gc.collect()
    return (sys.getallocatedblocks() - before) / n


def test_no_path_string_leak(images):
    base, name = os.path.dirname(images["jpg"]) + "/", os.path.basename(images["jpg"])
    small = images["color"][:10, :10]
    # A new str object per call, as in the monitor (one path per frame). cv2.imread /
    # cv2.imwrite leak exactly 1.00 block per call; allocator warm-up noise stays under ~0.1.
    assert _leaked_blocks_per_call(lambda: cv2_io.imread(base + name[:])) < 0.5
    assert _leaked_blocks_per_call(lambda: cv2_io.imwrite(base + "w.jpg"[:], small)) < 0.5


RUNTIME_PATHS = [
    "backend_host/src", "backend_server/src", "shared/src", "features/companion",
    "backend_host/scripts/detector.py", "backend_host/scripts/monitor_localize.py",
    "backend_host/scripts/incident_manager.py", "backend_host/scripts/subtitle_monitor.py",
    "backend_host/scripts/capture_monitor.py",
]


def test_runtime_code_does_not_call_cv2_imread_or_imwrite():
    """Contract #30: long-running code reads and writes images through cv2_io."""
    import re
    root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
    pattern = re.compile(r"\b_?cv2\.(imread|imwrite)\(")
    offenders = []
    for rel in RUNTIME_PATHS:
        path = os.path.join(root, rel)
        files = [path] if path.endswith(".py") else [
            os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs if f.endswith(".py")]
        for f in files:
            if f.endswith("cv2_io.py"):
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern.search(line) and not line.lstrip().startswith("#"):
                        offenders.append(f"{os.path.relpath(f, root)}:{n}")
    assert not offenders, "use shared.src.lib.utils.cv2_io instead: " + ", ".join(offenders)
