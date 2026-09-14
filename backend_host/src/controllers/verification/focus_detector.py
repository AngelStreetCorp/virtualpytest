#!/usr/bin/env python3
"""No-reference focus detector for TV UI screenshots — the SINGLE source of the focus-box logic.

It searches a screenshot for the most likely focus cue (underline/bar, colored/white border or ring,
filled highlight tile) and returns ranked candidate boxes. Heuristic by design: focus is a UI
convention, not one OpenCV object.

This lives in the verification package so production (`image_helpers._focus_crop_hex`, used by the v6
matcher) and the dev CLI (`scripts/no_reference_focus_detector.py`, which re-exports from here) share
ONE implementation — the benchmark and the live matcher must crop identically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np


@dataclass
class FocusCandidate:
    cue_type: str
    box: Tuple[int, int, int, int]  # x, y, w, h
    score: float
    color: str
    details: Dict[str, float]


def _edge_interior_coverage(mask_roi: np.ndarray, edge_frac: float = 0.18) -> Tuple[float, float]:
    h, w = mask_roi.shape[:2]
    if h <= 2 or w <= 2:
        return 0.0, 0.0
    eh = max(1, int(round(h * edge_frac)))
    ew = max(1, int(round(w * edge_frac)))
    ring = np.ones((h, w), dtype=bool)
    if eh < h // 2 and ew < w // 2:
        ring[eh:h - eh, ew:w - ew] = False
    edge_cov = float(mask_roi[ring].mean()) if ring.any() else 0.0
    interior = ~ring
    int_cov = float(mask_roi[interior].mean()) if interior.any() else 0.0
    return edge_cov, int_cov


def _rectangularity_from_edges(gray: np.ndarray, box: Tuple[int, int, int, int]) -> float:
    """How much the crop edges look like a rectangle boundary."""
    x, y, w, h = box
    roi = gray[y:y+h, x:x+w]
    if roi.size == 0 or w < 20 or h < 10:
        return 0.0
    edges = cv2.Canny(roi, 60, 160)
    eh = max(1, int(h * 0.12))
    ew = max(1, int(w * 0.12))
    ring = np.zeros_like(edges, dtype=bool)
    ring[:eh, :] = True
    ring[-eh:, :] = True
    ring[:, :ew] = True
    ring[:, -ew:] = True
    return float((edges > 0)[ring].mean())


def _color_masks(img_bgr: np.ndarray) -> Dict[str, np.ndarray]:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = ((H <= 8) | (H >= 170)) & (S >= 90) & (V >= 100)
    green = (H >= 40) & (H <= 90) & (S >= 50) & (V >= 80)
    blue = (H >= 90) & (H <= 130) & (S >= 70) & (V >= 100)
    magenta = (H >= 135) & (H <= 165) & (S >= 70) & (V >= 100)
    # White/bright focus fills and borders. Avoid grey text by requiring high V.
    white = (S <= 60) & (V >= 170)
    masks = {
        "red": red.astype(np.uint8),
        "green": green.astype(np.uint8),
        "blue": blue.astype(np.uint8),
        "magenta": magenta.astype(np.uint8),
        "white": white.astype(np.uint8),
    }
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    for k in list(masks):
        close_kernel = kernel
        if k == "green":
            close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        masks[k] = cv2.morphologyEx(masks[k], cv2.MORPH_CLOSE, close_kernel, iterations=1)
        masks[k] = cv2.morphologyEx(masks[k], cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    return masks


def _component_candidates(img_bgr: np.ndarray, color: str, mask: np.ndarray) -> List[FocusCandidate]:
    H, W = mask.shape
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out: List[FocusCandidate] = []
    img_area = H * W

    for i in range(1, n):
        x, y, w, h, area = map(int, stats[i])
        if area < 80 or w < 8 or h < 3:
            continue
        if area > 0.18 * img_area:
            continue
        # Ignore tiny bright text fragments unless they form a UI shape.
        extent = area / float(w * h)
        aspect = w / float(h)
        roi_mask = labels[y:y+h, x:x+w] == i
        edge_cov, interior_cov = _edge_interior_coverage(roi_mask)
        rect_edge = _rectangularity_from_edges(gray, (x, y, w, h))
        rel_area = area / img_area

        # cue classification
        cue = "unknown"
        score = 0.0

        # A thin horizontal bar / underline.
        if aspect >= 5.0 and h <= max(8, int(0.025 * H)) and w >= 25:
            cue = "underline"
            # Prefer top/nav-region underlines but allow lower tab underlines.
            top_bonus = 0.20 if y < 0.25 * H else 0.05
            score = 0.65 + top_bonus + min(0.2, w / W)

        # A border/ring: edges active, interior less active. Prefer this over
        # fills because focus borders are very strong signals and logos often
        # look like filled coloured blobs.
        elif edge_cov >= 0.16 and edge_cov > interior_cov * 1.6 and w >= 30 and h >= 30:
            cue = "border_or_ring"
            color_bonus = {"red": 0.38, "green": 0.38, "white": 0.35, "blue": 0.10, "magenta": 0.10}.get(color, 0.0)
            square_bonus = 0.12 if 0.65 <= aspect <= 1.55 else 0.0
            score = 0.62 + color_bonus + square_bonus + min(0.25, edge_cov) + min(0.08, rect_edge * 2)

        # Circular/square coloured avatar ring/fill. The focused avatar is often
        # larger/brighter than the rest. Green profile focus is common in TV UIs.
        elif color in ("green", "blue") and w >= 100 and h >= 100 and 0.85 <= aspect <= 1.20 and extent >= 0.25:
            cue = "avatar_ring_or_fill"
            score = 0.82 + (0.55 if color == "green" else 0.12) + min(0.25, math.sqrt(rel_area) * 5)

        # A filled selected row/button/tile. Require a strong container-like shape.
        # This rejects many logos/poster fragments that are saturated but not UI focus.
        elif w >= 45 and h >= 30 and (extent >= 0.80 or (aspect >= 1.8 and extent >= 0.65)):
            cue = "filled_highlight"
            color_bonus = {"red": 0.30, "white": 0.30, "green": 0.15, "blue": 0.05, "magenta": 0.05}.get(color, 0.0)
            shape_bonus = 0.16 if aspect >= 1.8 else 0.05
            size_bonus = min(0.20, math.sqrt(rel_area) * 4.5)
            score = 0.50 + color_bonus + shape_bonus + size_bonus
            # Prefer controls in the lower/action portion over poster/title artwork.
            if y > 0.45 * H:
                score += 0.12
            if y < 0.18 * H and color == "red":
                score -= 0.25

        if score <= 0:
            continue

        # Penalize obvious video/poster art: very large components away from UI controls.
        if w > 0.65 * W or h > 0.65 * H:
            score *= 0.25
        # Penalize components touching image borders, often background art.
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            score *= 0.75

        out.append(FocusCandidate(
            cue_type=cue,
            box=(x, y, w, h),
            score=round(float(score), 4),
            color=color,
            details={
                "area": float(area),
                "extent": round(float(extent), 3),
                "aspect": round(float(aspect), 3),
                "edge_cov": round(float(edge_cov), 3),
                "interior_cov": round(float(interior_cov), 3),
                "rect_edge": round(float(rect_edge), 3),
            },
        ))
    return out


def detect_focus(img_bgr: np.ndarray, top_k: int = 5) -> List[FocusCandidate]:
    masks = _color_masks(img_bgr)
    cands: List[FocusCandidate] = []
    for color, mask in masks.items():
        cands.extend(_component_candidates(img_bgr, color, mask))

    # Non-maximum suppression across color masks.
    cands = sorted(cands, key=lambda c: c.score, reverse=True)
    kept: List[FocusCandidate] = []
    for c in cands:
        x1, y1, w1, h1 = c.box
        a1 = w1 * h1
        keep = True
        for k in kept:
            x2, y2, w2, h2 = k.box
            ix0, iy0 = max(x1, x2), max(y1, y2)
            ix1, iy1 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
            inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
            a2 = w2 * h2
            if inter / float(min(a1, a2)) > 0.55:
                keep = False
                break
        if keep:
            kept.append(c)
        if len(kept) >= top_k:
            break
    return kept
