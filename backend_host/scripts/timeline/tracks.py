"""Reduce one 10-min metadata chunk (1 fps frames) to Timeline tracks and per-tile flags.

Bands: `ad` (profile event `events.ad_break`, TASK-90 ad_meter), `freeze`, `blackscreen`.
Per-tile flags (30 s tiles): fraction of the tile's seconds in each state, for the grid's edge colour.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

TRACK_LABELS = {'ad': 'AD', 'freeze': 'FREEZE', 'blackscreen': 'BLACK'}


def _naive(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '')).replace(tzinfo=None)
    except ValueError:
        return None


def _merge(points: List[float], gap_s: float = 2.5) -> List[Tuple[float, float]]:
    spans = []
    for t in sorted(points):
        if spans and t - spans[-1][1] <= gap_s:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return [(s, e + 1.0) for s, e in spans]   # a frame covers its own second


def reduce_chunk(meta: dict, *, chunk_start: float, levels: dict = None) -> dict:
    """`chunk_start` is epoch seconds (from the archive manifest); frames are placed by their
    own timestamp, falling back to their index (1 fps) when the stamp is missing."""
    frames = meta.get('frames', []) or []
    stamps = [_naive(fr.get('timestamp')) for fr in frames]
    first = next((x for x in stamps if x is not None), None)
    pts: Dict[str, List[float]] = {'ad': [], 'freeze': [], 'blackscreen': []}
    ad_kind: Dict[float, str] = {}
    for i, fr in enumerate(frames):
        # Host-local naive stamps: only their DIFFERENCES are used (zone-free), anchored on the manifest
        # clock. A chunk with lost frames (588 of 600) keeps its gaps. No stamp: 1 fps by index.
        t = chunk_start + ((stamps[i] - first).total_seconds() if first is not None and stamps[i] is not None else i)
        ev = fr.get('events') or {}
        ab = ev.get('ad_break')
        if ab:
            pts['ad'].append(t)
            if isinstance(ab, dict) and ab.get('kind'):
                ad_kind[t] = ab['kind']
        if fr.get('freeze'):
            pts['freeze'].append(t)
        if fr.get('blackscreen'):
            pts['blackscreen'].append(t)
    tracks = []
    for tid, points in pts.items():
        spans = [{'s': int(s * 1000), 'e': int(e * 1000), 'label': TRACK_LABELS[tid]} for s, e in _merge(points)]
        if tid == 'ad' and ad_kind:
            kinds = sorted(ad_kind.items())
            for sp in spans:
                ks = [k for t, k in kinds if sp['s'] <= t * 1000 <= sp['e']]
                if ks:
                    sp['kind'] = ks[-1]
        tracks.append({'id': tid, 'kind': 'band', 'label': TRACK_LABELS[tid], 'spans': spans})
    # per-tile flags for each level ({step_s: count}): the share of the tile's seconds in each state
    tiles = {}
    for step_s, count in (levels or {30: 20}).items():
        rows = []
        for i in range(count):
            a, b = chunk_start + i * step_s, chunk_start + (i + 1) * step_s
            rows.append({tid: round(min(1.0, sum(1 for t in points if a <= t < b) / float(step_s)), 2)
                         for tid, points in pts.items()})
        tiles[str(step_s)] = rows
    return {'chunk_start': chunk_start, 'tracks': tracks, 'tiles': tiles}


def load_meta(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
