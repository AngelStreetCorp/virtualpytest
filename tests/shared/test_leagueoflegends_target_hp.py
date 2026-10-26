"""TASK-132: exact minion health read from the target frame (top left) after a left click, on real saved crops."""

from __future__ import annotations

import glob
import os

import numpy as np
import pytest
from PIL import Image

from shared.src.lib.game.leagueoflegends import target_hp as T

pytestmark = pytest.mark.unit
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "lol_target_hp")


def _frame_with(crop_path: str) -> np.ndarray:
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    x0, y0, x1, y1 = T.TEXT_RECT
    img[y0:y1, x0:x1] = np.asarray(Image.open(crop_path).convert("RGB"))
    return img


def test_reads_exact_current_and_max_health_from_real_frames() -> None:
    files = sorted(glob.glob(os.path.join(FIX, "*.png")))
    assert len(files) >= 12
    for f in files:
        label = os.path.basename(f).split("_")[1].removesuffix(".png")  # "406-465"
        cur, mx = (int(v) for v in label.split("-"))
        assert T.read_target_health(_frame_with(f)) == (cur, mx), f


def test_returns_none_when_nothing_is_selected() -> None:
    assert T.read_target_health(np.zeros((1200, 1920, 3), dtype=np.uint8)) is None
    assert T.read_target_health(np.zeros((600, 960, 3), dtype=np.uint8)) is None  # wrong resolution
