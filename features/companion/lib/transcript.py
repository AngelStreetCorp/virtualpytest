"""Read the device's live transcript: the lines spoken in the last few minutes.

The transcript accumulator (vpt-transcript, ENABLE_TRANSCRIPTION) merges each transcribed minute
into ``<capture>/transcript/<hour>/chunk_10min_<index>.json``. A segment's ``start`` is in seconds
from the chunk's start (hour:index*10, local time). The live feed lags ~60-90 s behind the picture.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Callable, Optional

ChunkPath = Callable[[int, int], str]  # (hour, chunk_index) -> path


def _chunk_start(now: datetime, back: int) -> datetime:
    """Start of the 10-minute chunk ``back`` chunks before the one containing ``now``."""
    start = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
    return start - timedelta(minutes=10 * back)


def recent_lines(chunk_path: ChunkPath, window_s: int, now: Optional[datetime] = None) -> list[dict]:
    """``[{t, text}]`` of the segments spoken in the last ``window_s`` seconds, oldest first."""
    now = now or datetime.now()
    since = now - timedelta(seconds=window_s)
    lines: list[dict] = []
    for back in range(window_s // 600 + 2, -1, -1):
        start = _chunk_start(now, back)
        if start + timedelta(minutes=10) < since:
            continue
        path = chunk_path(start.hour, start.minute // 10)
        try:
            # The chunk files are a 24 h ring (<hour>/chunk_10min_<n>): a file last written before
            # its slot began is yesterday's. Right after 13:00 the meter read yesterday's 13:00 chunk
            # (French, another channel) as BBC News (stb4, 2026-10-05).
            if os.path.getmtime(path) < start.timestamp():
                continue
            with open(path, encoding="utf-8") as f:
                chunk = json.load(f)
        except (OSError, ValueError):
            continue
        for seg in chunk.get("segments") or []:
            text = (seg.get("text") or "").strip()
            try:
                at = start + timedelta(seconds=float(seg.get("start") or 0))
            except (TypeError, ValueError):
                continue
            if text and since <= at <= now + timedelta(seconds=5):
                lines.append({"t": at.timestamp(), "text": text})
    lines.sort(key=lambda line: line["t"])
    return lines


def device_chunk_path(device_id: str) -> ChunkPath:
    from shared.src.lib.utils.storage_path_utils import get_capture_folder_from_device_id, get_transcript_chunk_path
    folder = get_capture_folder_from_device_id(device_id)
    return lambda hour, index: get_transcript_chunk_path(folder, hour, index)
