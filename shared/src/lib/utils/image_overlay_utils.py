#!/usr/bin/env python3
"""Shared evidence-overlay helpers.

Outlining the search area on a full capture is identical for the Verification
Failure report (``verification_report_generator``) and the KPI report
(``kpi_report_generator``), so both import this one implementation — they must
stay pixel-identical:

  RED    = exact crop / match area  (x / y / width / height)
  YELLOW = fuzzy search area        (fx / fy / fwidth / fheight, when defined)

The rectangle marks *where on the screen* a reference was searched for. Its
position is frame-independent (the area is a fixed screen region), so callers
may draw it on whichever full frame they have on hand — the KPI report draws it
on the match frame; the failure report draws it on the failed source frame.
"""

import logging

logger = logging.getLogger(__name__)


def draw_search_area_rectangles(image, area) -> bool:
    """Draw the red (exact) + yellow (fuzzy) search-area rectangles IN PLACE.

    ``image`` is a cv2/numpy BGR array (mutated); ``area`` is the resolved area
    dict. Returns True if at least one rectangle was drawn, so callers can tell
    an outlined frame from a bare one.
    """
    import cv2

    if image is None or not isinstance(area, dict):
        return False

    drawn = False
    x = int(area.get('x', 0) or 0)
    y = int(area.get('y', 0) or 0)
    w = int(area.get('width', 0) or 0)
    h = int(area.get('height', 0) or 0)
    if w > 0 and h > 0:
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 3)  # red = exact
        drawn = True

    fx, fy = area.get('fx'), area.get('fy')
    fw, fh = area.get('fwidth'), area.get('fheight')
    if None not in (fx, fy, fw, fh):
        fx, fy, fw, fh = int(fx), int(fy), int(fw), int(fh)
        if fw > 0 and fh > 0:
            cv2.rectangle(image, (fx, fy), (fx + fw, fy + fh), (0, 255, 255), 3)  # yellow = fuzzy
            drawn = True
    return drawn


def render_search_area_overlay(full_image_path: str, area, dest_path: str) -> bool:
    """Read a full capture, outline the search area, write it to ``dest_path``.

    Returns True on success. The KPI report uses this to build the per-card
    "search area on full capture" panel. The frame is written even when ``area``
    has no drawable box (None / full-screen) — a bare full capture is still
    useful context — so callers only need to check the file was produced.
    """
    import os
    import cv2

    if not full_image_path or not os.path.exists(full_image_path):
        return False
    try:
        img = cv2.imread(full_image_path)
        if img is None:
            return False
        draw_search_area_rectangles(img, area)
        cv2.imwrite(dest_path, img)
        return True
    except Exception as e:
        logger.warning(f"⚠️  Could not render search-area overlay from {full_image_path}: {e}")
        return False
