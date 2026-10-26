"""Nav-target vision detector for the League of Legends vision agent (TASK-121 §8).

This module finds the clickable UI elements the orchestrator needs to
drive the launcher chain:

* The **LoL launcher icon** in the Riot Client's left sidebar (the
  gold ``L`` that, when clicked, spawns the League of Legends client).
* The **Play button** on the League Client's main page (the gold
  rounded ``▶ Play`` button that, when clicked, enters a queue).

The detector uses **OpenCV's** ``cv2.matchTemplate`` with the
``TM_CCOEFF_NORMED`` method (normalized correlation coefficient).
OpenCV's implementation is C-optimized: ~30ms for a 1500x900
screenshot with a 168x130 template, with **pixel-accurate** peak
localization (no stride artifacts).

The templates live in :mod:`nav_templates` (co-shipped with this
module):

* ``nav_templates/lol_icon.png`` — the gold ``L`` LoL launcher icon.
* ``nav_templates/play_button.png`` — the gold ``▶ Play`` button.

Hard policy (TASK-121 §6 FR-13)
--------------------------------

* The detector is **read-only** — it never moves the cursor, never
  sends input, never modifies the desktop. The orchestrator handles
  the click separately via :mod:`click_executor`.
* The detector MUST NEVER import ``pyautogui`` or any League-process
  helper.
* The detector's templates are co-shipped **as data**, not as code,
  so a future change to the Riot Client UI requires a re-capture but
  not a re-deploy of the agent's runtime.

What this module is NOT
-----------------------

* This is not a general-purpose OCR / vision system. It only matches
  against the two pre-saved templates.
* This is not a face detector, edge detector, or feature extractor.
  The matching is a normalized correlation — robust to global
  brightness changes, sensitive to rotation / scale changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from shared.src.lib.game.leagueoflegends.contracts_decision import Point


# ---------------------------------------------------------------------------
# Public data shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NavTarget:
    """One clickable UI element the orchestrator wants to find.

    Attributes:
        name: human-readable identifier (e.g. ``"lol_icon"``).
        template_path: absolute or package-relative path to the
            template image (PNG).
        min_match_score: 0.0..1.0 — match scores below this are
            treated as "not found". Default 0.85 (strict).
    """

    name: str
    template_path: Path
    min_match_score: float = 0.85


@dataclass(frozen=True)
class NavHit:
    """The result of a successful template match.

    Attributes:
        target_name: copied from :attr:`NavTarget.name`.
        normalized: the click-target point in ``[0.0, 1.0]`` — the
            *center* of the matched region, normalized to the
            screenshot's pixel dimensions.
        match_score: 0.0..1.0 — the match score (higher is better).
        bbox: ``(left, top, right, bottom)`` in pixels of the matched
            region within the screenshot.
    """

    target_name: str
    normalized: Point
    match_score: float
    bbox: Tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Public template anchors.
# ---------------------------------------------------------------------------


_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "nav_templates"


LOL_ICON = NavTarget(
    name="lol_icon",
    template_path=_TEMPLATES_DIR / "lol_icon.png",
    min_match_score=0.95,
)

JOIN_TEAM2 = NavTarget(  # Practice Tool lobby, Team 2 "Join" button (TASK-132: the lobby API cannot switch teams)
    name="join_team2",
    template_path=_TEMPLATES_DIR / "join_team2.png",
    min_match_score=0.95,
)

PLAY_BUTTON = NavTarget(
    name="play_button",
    template_path=_TEMPLATES_DIR / "play_button.png",
    min_match_score=0.95,
)


# ---------------------------------------------------------------------------
# The detector.
# ---------------------------------------------------------------------------


class NavTargetDetector:
    """Match a :class:`NavTarget` template against a screenshot."""

    # Default scale sweep: covers the vpt-windows box's GDI capture
    # (typically 0.5x-1.0x of native 3440x1440) plus a generous
    # bracket for screenshots captured at a different DPI than the
    # template. 6 fractions keep the match pass under 200ms total.
    DEFAULT_SCALE_FACTORS: Tuple[float, ...] = (
        0.4, 0.55, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.6,
    )

    def __init__(
        self,
        *,
        max_matches_per_target: int = 1,
        scale_factors: Optional[Tuple[float, ...]] = None,
    ) -> None:
        """Construct a detector.

        ``max_matches_per_target`` caps matches reported per call
        (default 1 — orchestrator wants the single best click point).

        ``scale_factors`` overrides the multi-scale sweep. Each
        factor is the multiplier applied to the template's pixel
        dimensions before matching; the match heatmap is computed
        at each scale and the single best peak is kept.
        """
        self._max_matches = max(1, max_matches_per_target)
        self._scale_factors: Tuple[float, ...] = (
            scale_factors if scale_factors is not None
            else self.DEFAULT_SCALE_FACTORS
        )

    def detect(
        self, screenshot_path: Path, target: NavTarget
    ) -> List[NavHit]:
        """Find all matches of ``target`` template in ``screenshot_path``.

        Returns up to ``max_matches_per_target`` matches, sorted by
        score descending. An empty list means "not found".

        Uses ``cv2.matchTemplate`` with ``TM_CCOEFF_NORMED``. The
        score is in ``[0.0, 1.0]`` (correlated to clip the negative
        half of NCC's range — the detector is "feature-present vs
        not" rather than "anti-correlated").

        Multi-scale: the operator's vpt-windows box captures
        screenshots at one GDI scale while the template was captured
        at another (1920x1200 capture vs 3440x1440 native). Pure
        single-scale matching fails with a low score even when the
        icon is plainly visible. This method re-sizes the template at
        ``scale_factors`` (default 6 fractions from 0.4x to 1.6x)
        and keeps the single best peak across all scales.

        OpenCV finds the EXACT peak position with no stride artifact.
        For multi-match cases we currently report only the single
        best peak; raising ``max_matches_per_target`` would require
        a non-maxima-suppression pass which is out of scope for
        phase 0 (only one click target per step).
        """
        if not target.template_path.exists():
            raise FileNotFoundError(f"template not found: {target.template_path}")
        if not screenshot_path.exists():
            raise FileNotFoundError(f"screenshot not found: {screenshot_path}")

        screenshot = np.asarray(Image.open(screenshot_path).convert("RGB"))
        template = np.asarray(Image.open(target.template_path).convert("RGB"))

        sw, sh = screenshot.shape[1], screenshot.shape[0]
        tw, th = template.shape[1], template.shape[0]
        if tw > sw or th > sh:
            return []  # template is bigger than the screenshot

        best_score: float = -1.0
        best_loc: Tuple[int, int] = (0, 0)
        best_size: Tuple[int, int] = (tw, th)

        for scale in self._scale_factors:
            new_w = max(8, int(round(tw * scale)))
            new_h = max(8, int(round(th * scale)))
            if new_w > sw or new_h > sh:
                continue  # scaled template would be larger than the screenshot
            resized = cv2.resize(
                template, (new_w, new_h), interpolation=cv2.INTER_AREA
            )
            result = cv2.matchTemplate(
                screenshot, resized, cv2.TM_CCOEFF_NORMED
            )
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_size = (new_w, new_h)

        if best_score < target.min_match_score:
            return []

        x, y = best_loc
        bw, bh = best_size
        return [
            NavHit(
                target_name=target.name,
                normalized=Point(
                    x=(x + bw // 2) / sw,
                    y=(y + bh // 2) / sh,
                ),
                match_score=float(best_score),
                bbox=(x, y, x + bw, y + bh),
            )
        ][: self._max_matches]

    def detect_best(
        self, screenshot_path: Path, target: NavTarget
    ) -> Optional[NavHit]:
        """Return the single best match, or ``None`` if below threshold."""
        hits = self.detect(screenshot_path, target)
        return hits[0] if hits else None


def _ncc(crop: Image.Image, template: Image.Image) -> float:
    """Single-position NCC using OpenCV. Public for testing.

    Kept as a fallback for tests that don't need a full cv2.matchTemplate
    pass. Returns the same ``TM_CCOEFF_NORMED`` score that ``detect``
    would compute at the same position.
    """
    if crop.size != template.size:
        raise ValueError(f"size mismatch: {crop.size} vs {template.size}")
    a = np.asarray(crop, dtype=np.float32)
    b = np.asarray(template, dtype=np.float32)
    # Reshape to (1, h, w, 3) for matchTemplate and call.
    score = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    return float(score[0][0])


__all__ = [
    "NavTarget",
    "NavHit",
    "JOIN_TEAM2",
    "LOL_ICON",
    "PLAY_BUTTON",
    "NavTargetDetector",
]