#!/usr/bin/env python3
"""Shared playback evaluator for web Playwright video checks.

Consumes a list of samples produced by WEB_JS_VIDEO_STATUS (see
local_debug_playwright_js.py) and decides whether the <video> element is
actually playing. The native decoded-frame counter is authoritative: if
totalVideoFrames climbs across samples, the pipeline is presenting frames —
true even for looping/short clips and live streams, where the currentTime
delta is unreliable. When the frame counter is unavailable (older WebKit),
it falls back to summed forward currentTime motion.
"""

from typing import Any, Dict, List, Tuple


def calc_playback_progress(samples: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """Return (progress_seconds, playing) from WEB_JS_VIDEO_STATUS samples.

    progress_seconds is the total forward currentTime motion (backward jumps
    from looping are ignored), kept for reporting. playing is the authoritative
    "is the video advancing" boolean.
    """
    found = [s for s in samples if s and s.get("found")]
    if not found:
        return 0.0, False

    progress = 0.0
    prev = None
    for s in found:
        cur = s.get("currentTime", 0) or 0
        if prev is not None and cur > prev:
            progress += float(cur - prev)
        prev = cur

    not_paused = any(not s.get("paused", True) for s in found)

    frames = [
        s.get("totalVideoFrames")
        for s in found
        if isinstance(s.get("totalVideoFrames"), (int, float))
    ]
    frames_advancing = len(frames) >= 2 and frames[-1] > frames[0]

    playing = frames_advancing or (not_paused and progress > 0)
    return progress, playing


def is_video_playing(samples: List[Dict[str, Any]]) -> bool:
    """Convenience boolean wrapper around calc_playback_progress."""
    _, playing = calc_playback_progress(samples)
    return playing
