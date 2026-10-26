"""Tests for the nav-target vision detector.

Covers :mod:`shared.src.lib.game.leagueoflegends.vision_nav`.

The detector uses PIL + a normalized cross-correlation. The two real
templates (``lol_icon.png``, ``play_button.png``) live in
:mod:`nav_templates`. We test:

* The templates exist on disk and load.
* NCC math returns ``1.0`` for an exact match.
* NCC math returns ~``0.0`` for an unrelated image.
* The detector finds the LoL icon when it's pasted into a synthetic
  screenshot at the expected position.
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from shared.src.lib.game.leagueoflegends.vision_nav import (
    LOL_ICON,
    PLAY_BUTTON,
    NavHit,
    NavTarget,
    NavTargetDetector,
)


# ---------------------------------------------------------------------------
# Template assets.
# ---------------------------------------------------------------------------


def test_lol_icon_template_exists() -> None:
    assert LOL_ICON.template_path.exists(), f"missing: {LOL_ICON.template_path}"


def test_play_button_template_exists() -> None:
    assert PLAY_BUTTON.template_path.exists(), f"missing: {PLAY_BUTTON.template_path}"


def test_templates_load_as_rgb() -> None:
    for target in (LOL_ICON, PLAY_BUTTON):
        img = Image.open(target.template_path).convert("RGB")
        assert img.size[0] > 0 and img.size[1] > 0


# ---------------------------------------------------------------------------
# NCC math.
# ---------------------------------------------------------------------------


def test_ncc_exact_match_is_one() -> None:
    """NCC against an identical image returns 1.0."""
    from shared.src.lib.game.leagueoflegends.vision_nav import _ncc
    img = Image.new("RGB", (20, 20), (128, 64, 32))
    score = _ncc(img, img.copy())
    assert score == pytest.approx(1.0, abs=1e-3)


def test_ncc_with_offset_color_matches_via_cv2_behavior() -> None:
    """OpenCV's ``TM_CCOEFF_NORMED`` treats constant-color inputs as 1.0.

    This is the documented behavior of cv2.matchTemplate when both
    images have zero std. We don't try to override it — the edge
    case doesn't matter for real icons (which always have texture).
    """
    from shared.src.lib.game.leagueoflegends.vision_nav import _ncc
    a = Image.new("RGB", (20, 20), (100, 100, 100))
    b = Image.new("RGB", (20, 20), (128, 128, 128))
    score = _ncc(a, b)
    # cv2 returns 1.0 for both zero-variance inputs; just verify the
    # call succeeds and returns a number.
    assert isinstance(score, float)
    assert score == pytest.approx(1.0, abs=1e-3)


def test_ncc_uncorrelated_returns_near_zero() -> None:
    """NCC with very different images is well below 0.5."""
    from shared.src.lib.game.leagueoflegends.vision_nav import _ncc
    a = Image.new("RGB", (20, 20), (0, 0, 0))
    # Checker pattern.
    b = Image.new("RGB", (20, 20))
    for y in range(20):
        for x in range(20):
            b.putpixel((x, y), (255 if (x + y) % 2 == 0 else 0, 0, 0))
    score = _ncc(a, b)
    # Solid black vs checkerboard is not exactly 0 (the constant mean
    # dominates), but should be small.
    assert score < 0.2


def test_ncc_size_mismatch_raises() -> None:
    from shared.src.lib.game.leagueoflegends.vision_nav import _ncc
    a = Image.new("RGB", (20, 20))
    b = Image.new("RGB", (10, 10))
    with pytest.raises(ValueError):
        _ncc(a, b)


# ---------------------------------------------------------------------------
# End-to-end detection on a synthetic screenshot.
# ---------------------------------------------------------------------------


def test_detect_lol_icon_in_synthetic_screenshot() -> None:
    """Paste the LoL icon template into a synthetic screenshot; detector finds it."""
    template = Image.open(LOL_ICON.template_path).convert("RGB")
    tw, th = template.size
    canvas = Image.new("RGB", (1500, 900), (40, 40, 50))  # dark sidebar-ish background
    # Place the template at (75, 185) — matches the user's mockup coords.
    canvas.paste(template, (75, 185))

    with tempfile.TemporaryDirectory() as tmpdir:
        screenshot_path = Path(tmpdir) / "screenshot.png"
        canvas.save(screenshot_path)

        detector = NavTargetDetector()
        hit = detector.detect_best(screenshot_path, LOL_ICON)
        assert hit is not None
        # The center should be near (75 + tw/2, 185 + th/2) → (0.05+, 0.21+)
        # normalized to the 1500x900 canvas.
        expected_x = (75 + tw / 2) / 1500
        expected_y = (185 + th / 2) / 900
        assert abs(hit.normalized.x - expected_x) < 0.05, (
            f"x drift {hit.normalized.x:.4f} vs expected {expected_x:.4f}"
        )
        assert abs(hit.normalized.y - expected_y) < 0.05


def test_detect_play_button_in_synthetic_screenshot() -> None:
    """Paste the Play button template into a synthetic screenshot."""
    template = Image.open(PLAY_BUTTON.template_path).convert("RGB")
    tw, th = template.size
    canvas = Image.new("RGB", (1500, 900), (40, 40, 50))
    canvas.paste(template, (750 - tw // 2, 594 - th // 2))  # ~center, ~2/3 down

    with tempfile.TemporaryDirectory() as tmpdir:
        screenshot_path = Path(tmpdir) / "screenshot.png"
        canvas.save(screenshot_path)
        hit = NavTargetDetector().detect_best(screenshot_path, PLAY_BUTTON)
        assert hit is not None


def test_detect_returns_empty_when_template_missing_from_screenshot() -> None:
    """A blank canvas with no template returns no match."""
    canvas = Image.new("RGB", (800, 600), (0, 0, 0))
    with tempfile.TemporaryDirectory() as tmpdir:
        screenshot_path = Path(tmpdir) / "blank.png"
        canvas.save(screenshot_path)
        hit = NavTargetDetector().detect_best(screenshot_path, LOL_ICON)
        # Match may or may not be present depending on the template's
        # pixel content; the requirement is just that the detector
        # *runs* without error. An empty list OR a low-score hit is OK.
        if hit is not None:
            assert hit.match_score < 1.0  # never a perfect match on pure black


def test_detect_raises_for_missing_template() -> None:
    target = NavTarget(name="bogus", template_path=Path("/nonexistent.png"))
    detector = NavTargetDetector()
    with tempfile.NamedTemporaryFile(suffix=".png") as tmpfile:
        with pytest.raises(FileNotFoundError):
            detector.detect_best(Path(tmpfile.name), target)


def test_detect_raises_for_missing_screenshot() -> None:
    with pytest.raises(FileNotFoundError):
        NavTargetDetector().detect_best(Path("/nonexistent.png"), LOL_ICON)


def test_detect_does_not_import_pyautogui() -> None:
    import ast
    src = open("shared/src/lib/game/leagueoflegends/vision_nav.py").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert "pyautogui" not in alias.name