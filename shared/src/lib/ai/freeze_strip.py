"""
Freeze "strip" builder (TASK-27 step 4g).

One frame cannot show a freeze: a human or a model needs several frames spread over
time, each with its time. A freeze alert already carries that evidence, so this
builds one JPEG from frames that are still on the host disk, with no new capture:

- the current (analysed) frame: ``freeze_comparisons[*].current_capture_path``;
- the earlier frames the detector compared: ``freeze_comparisons[*].previous_capture_path``
  and ``last_3_filenames``;
- the frame where the freeze started, ``current - freeze_event_duration_ms * fps``, and
  frames around the midpoint, found by capture number in the same folder. Hot storage
  keeps 180 s of captures, so at alert time (30 s into a freeze) they are still there.

Time of a frame: its capture number divided by the capture FPS. Within one ffmpeg run
the captures are numbered one per frame at a constant 5 fps (``run_ffmpeg.sh``,
``get_device_fps``); a restart only jumps the numbering forward. When a file name has
no capture number, the file mtime is used for every frame instead.

Pure apart from reading the frame files. ``build_freeze_strip`` never raises: it
returns ``(jpeg_bytes, meta)`` or None when fewer than two frames at least
``MIN_GAP_MS`` apart exist.
"""

import logging
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

import cv2
import numpy as np
from shared.src.lib.utils import cv2_io

logger = logging.getLogger(__name__)

MIN_GAP_MS = 500          # frames of a strip are at least this far apart
MAX_LONG_SIDE = 1280      # the whole strip, like every training image
DEFAULT_FPS = 5           # get_device_fps() is 5 on every standard pipeline
MAX_FRAMES = 3
MIDDLE_SEARCH = 25        # capture numbers probed on each side of the midpoint (5 s at 5 fps)
FOOTER_H = 40
JPEG_QUALITY = 90         # record_sample re-encodes at its own quality

_NUM_RE = re.compile(r'^(?P<prefix>.*_)(?P<num>\d+)(?P<ext>\.jpg)$', re.IGNORECASE)


def _capture_number(path: str) -> Optional[int]:
    m = _NUM_RE.match(os.path.basename(path or ''))
    return int(m.group('num')) if m else None


def _numbered_path(template: str, number: int) -> Optional[str]:
    """``.../capture_000000188.jpg`` + 150 -> ``.../capture_000000150.jpg`` (same width)."""
    base = os.path.basename(template)
    m = _NUM_RE.match(base)
    if not m or number < 0:
        return None
    name = f"{m.group('prefix')}{str(number).zfill(len(m.group('num')))}{m.group('ext')}"
    return os.path.join(os.path.dirname(template), name)


def current_frame_path(metadata: Mapping[str, Any]) -> Optional[str]:
    """Full path of the analysed frame: from ``freeze_comparisons``, else ``filename``
    next to the ``last_3_filenames`` frames. None when neither gives a path."""
    for comp in metadata.get('freeze_comparisons') or []:
        if isinstance(comp, Mapping) and comp.get('current_capture_path'):
            return str(comp['current_capture_path'])
    filename = metadata.get('filename')
    last_3 = [p for p in (metadata.get('last_3_filenames') or []) if p]
    if filename and last_3:
        return os.path.join(os.path.dirname(str(last_3[0])), os.path.basename(str(filename)))
    return None


def _evidence_paths(metadata: Mapping[str, Any]) -> List[str]:
    paths: List[str] = []
    current = current_frame_path(metadata)
    if current:
        paths.append(current)
    for comp in metadata.get('freeze_comparisons') or []:
        if isinstance(comp, Mapping) and comp.get('previous_capture_path'):
            paths.append(str(comp['previous_capture_path']))
    paths.extend(str(p) for p in (metadata.get('last_3_filenames') or []) if p)
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def select_frames(metadata: Mapping[str, Any], fps: float = DEFAULT_FPS,
                  min_gap_ms: int = MIN_GAP_MS) -> Tuple[List[Tuple[str, float]], str]:
    """Pick up to ``MAX_FRAMES`` frames on disk, oldest first, at least ``min_gap_ms``
    apart: the earliest, the current (latest), and one near the middle.

    Returns ``([(path, t_s), ...], time_source)`` where ``t_s`` is an absolute time in
    seconds on the chosen scale and ``time_source`` is ``'capture_number'`` or
    ``'mtime'``. Fewer than two frames means there is no strip."""
    fps = float(fps) if fps and fps > 0 else float(DEFAULT_FPS)
    gap_s = min_gap_ms / 1000.0
    existing = [p for p in _evidence_paths(metadata) if os.path.isfile(p)]
    current = current_frame_path(metadata)

    numbers = {p: _capture_number(p) for p in existing}
    if existing and all(n is not None for n in numbers.values()):
        time_source = 'capture_number'
        cand: Dict[int, str] = {numbers[p]: p for p in existing}
        template = current or existing[0]
        cur_n = _capture_number(template) if current and os.path.isfile(current) else max(cand)
        # The frame where the freeze started, if it is still on disk.
        try:
            duration_ms = float(metadata.get('freeze_event_duration_ms') or 0)
        except (TypeError, ValueError):
            duration_ms = 0.0
        if cur_n is not None and duration_ms > 0:
            start_n = cur_n - int(round(duration_ms * fps / 1000.0))
            start_path = _numbered_path(template, start_n)
            if start_path and os.path.isfile(start_path):
                cand[start_n] = start_path
        first_n, last_n = min(cand), max(cand)
        # Frames near the midpoint, by capture number, if they are still on disk.
        mid = (first_n + last_n) // 2
        for delta in range(0, MIDDLE_SEARCH + 1):
            for n in {mid - delta, mid + delta}:
                if first_n < n < last_n and n not in cand:
                    path = _numbered_path(template, n)
                    if path and os.path.isfile(path):
                        cand[n] = path
            if any(first_n < n < last_n and (n - first_n) / fps >= gap_s and (last_n - n) / fps >= gap_s
                   for n in cand):
                break
        timed = sorted((n / fps, p) for n, p in cand.items())
    else:
        time_source = 'mtime'
        timed = sorted((t, p) for p, t in ((p, _mtime(p)) for p in existing) if t is not None)

    if len(timed) < 2:
        return [], time_source
    first, last = timed[0], timed[-1]
    if last[0] - first[0] < gap_s:
        return [], time_source
    picked = [first]
    target = (first[0] + last[0]) / 2.0
    middles = [x for x in timed[1:-1] if x[0] - first[0] >= gap_s and last[0] - x[0] >= gap_s]
    if middles and MAX_FRAMES >= 3:
        picked.append(min(middles, key=lambda x: abs(x[0] - target)))
    picked.append(last)
    return [(p, t) for t, p in picked], time_source


def _put_label(img: np.ndarray, text: str, org: Tuple[int, int], scale: float) -> None:
    thickness = max(1, int(round(scale * 2)))
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = org
    cv2.rectangle(img, (x - 4, y - h - 6), (x + w + 4, y + base + 2), (0, 0, 0), -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def _fmt_rel(t: float) -> str:
    return f"+{t:.1f} s"


def _footer_text(duration_ms: Any, diffs: Any) -> str:
    parts = []
    try:
        if duration_ms is not None and float(duration_ms) > 0:
            parts.append(f"frozen {float(duration_ms) / 1000.0:.1f} s")
    except (TypeError, ValueError):
        pass
    values = []
    for d in diffs or []:
        try:
            values.append(float(d))
        except (TypeError, ValueError):
            continue
    if values:
        parts.append(f"diff {max(values):.2f}%")
    # Hershey fonts are ASCII only, so no middle dot.
    return ' | '.join(parts) if parts else 'freeze'


def render_strip(frames: List[Tuple[np.ndarray, float]], footer: str,
                 max_long_side: int = MAX_LONG_SIDE) -> Optional[bytes]:
    """Frames side by side, each labelled with its relative time, and a footer line.
    ``frames`` is ``[(bgr_image, t_rel_s), ...]``. Returns JPEG bytes or None."""
    if not frames:
        return None
    cell_w = max(1, max_long_side // len(frames))
    tiles = []
    cell_h = None
    for img, _t in frames:
        h, w = img.shape[:2]
        if cell_h is None:
            cell_h = max(1, int(round(cell_w * h / float(w))))
        tiles.append(cv2.resize(img, (cell_w, cell_h), interpolation=cv2.INTER_AREA))
    scale = max(0.45, cell_w / 640.0 * 0.9)
    for tile, (_img, t) in zip(tiles, frames):
        _put_label(tile, _fmt_rel(t), (10, int(28 * scale / 0.9) + 6), scale)
    body = np.hstack(tiles)
    footer_band = np.zeros((FOOTER_H, body.shape[1], 3), dtype=np.uint8)
    cv2.putText(footer_band, footer, (10, FOOTER_H - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2, cv2.LINE_AA)
    strip = np.vstack([body, footer_band])
    ok, buf = cv2.imencode('.jpg', strip, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return buf.tobytes() if ok else None


def build_freeze_strip(metadata: Mapping[str, Any], fps: float = DEFAULT_FPS,
                       min_gap_ms: int = MIN_GAP_MS) -> Optional[Tuple[bytes, Dict[str, Any]]]:
    """One JPEG for a freeze alert: 2-3 frames at least ``min_gap_ms`` apart, oldest
    first, each labelled "+t s", and a footer "frozen D s | diff X%".

    Returns ``(jpeg_bytes, meta)``, ``meta = {frames: [{file, t_rel_s}], duration_ms,
    diffs, event_start, time_source, fps}``, or None when there is no such pair of
    frames. Never raises."""
    try:
        if not isinstance(metadata, Mapping):
            return None
        picked, time_source = select_frames(metadata, fps, min_gap_ms)
        loaded = []
        for path, t in picked:
            img = cv2_io.imread(path, cv2.IMREAD_COLOR)
            if img is not None and img.size:
                loaded.append((path, t, img))
        if len(loaded) < 2 or (loaded[-1][1] - loaded[0][1]) * 1000.0 < min_gap_ms:
            return None
        t0 = loaded[0][1]
        frames = [(img, round(t - t0, 1)) for _p, t, img in loaded]
        duration_ms = metadata.get('freeze_event_duration_ms')
        diffs = list(metadata.get('freeze_diffs') or [])
        jpeg = render_strip(frames, _footer_text(duration_ms, diffs))
        if jpeg is None:
            return None
        meta = {
            'frames': [{'file': os.path.basename(p), 't_rel_s': round(t - t0, 1)} for p, t, _img in loaded],
            'duration_ms': duration_ms,
            'diffs': diffs,
            'event_start': metadata.get('freeze_event_start'),
            'time_source': time_source,
            'fps': fps,
        }
        return jpeg, meta
    except Exception as e:
        logger.warning(f"[freeze_strip] could not build the strip: {e}")
        return None
