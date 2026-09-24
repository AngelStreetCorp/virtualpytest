#!/usr/bin/env python3
"""
KPI measurement confidence — how much a single KPI number can be trusted.

A KPI is `matched frame mtime − action timestamp` (kpi_executor._process_measurement),
with no interpolation. So the value is quantised to whatever the gap between the two
frames around the transition happened to be, and that gap is not constant:

- hot storage runs at 5 fps  → ±200 ms
- the cold hour-folder archive runs at 1-2 fps → ±500-1000 ms, and a window older
  than hot's retention is served from there

Nothing recorded which of the two a given measurement came from, so 1227 ms could
mean ±200 ms or ±1000 ms and the report showed both identically. That is what made
the numbers arguable. This module turns the frames the scan already holds into the
evidence: effective fps, how many frames went missing, and the interval the
transition is provably inside.

A note on what is NOT a drop signal: the number in `capture_NNNNNNNNN.jpg` comes from
ffmpeg's image2 muxer, which increments by exactly 1 per frame it WRITES. A frame lost
upstream leaves no gap in the numbering — the counter just advances more slowly in
wall-clock time. Number jumps mean an ffmpeg restart (run_ffmpeg.sh next_start_number)
or an archiver deletion, and the cold archive renumbers by time of day entirely. So the
only honest drop signal is the spacing of the mtimes, which is what this module uses.

Pure: stdlib only, no PIL, no network, no DB.
"""

from typing import Dict, List, Optional

# Nominal capture rate of hot storage (run_ffmpeg.sh pins `fps=5` in the capture
# branch of the filter graph; storage_path_utils.get_device_fps agrees).
HOT_FPS = 5.0
HOT_INTERVAL_MS = 1000.0 / HOT_FPS  # 200 ms

# Classifying a frame's storage by its spacing. Hot is pinned at 5 fps, so anything
# spaced wider than this is not the live buffer; the archive may run at 1 or 2 fps
# (ARCHIVE_CAPTURES_FPS), which is why the test is "not hot" rather than a second
# threshold. Frames are pulled hot-first and cold only for the part of the window
# older than hot's coverage (kpi_executor._discover_window_captures), so a window is
# hot, cold, or cold-then-hot — never interleaved.
HOT_MAX_INTERVAL_MS = 400.0  # <= this is the 5 fps grid; above it is the archive

# A gap counts as a real capture interruption once it exceeds this multiple of the
# window's own median spacing. 1.5x is the midpoint between "one frame late" and
# "one frame never arrived", so it fires on a true drop without firing on jitter
# (measured p95 on a healthy Pi is ~216 ms against a 200 ms median).
GAP_FACTOR = 1.5


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = int(round((len(sorted_vals) - 1) * pct))
    return sorted_vals[max(0, min(k, len(sorted_vals) - 1))]


def _median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def measurement_confidence(
    all_captures: List[Dict],
    match_index: Optional[int],
    action_timestamp: float,
    probe_outcomes: Optional[Dict[int, bool]] = None,
    algorithm: str = '',
    captures_scanned: int = 0,
) -> Dict:
    """Describe how precisely one KPI value could have been measured.

    Args:
        all_captures: the scan's frames, ordered, each {'path', 'timestamp'}.
        match_index: index of the matched frame in `all_captures`, None on no-match.
        action_timestamp: the press instant the KPI is measured from.
        probe_outcomes: FULL idx -> passed map of the frames the verifier ran on
            (not the report-capped copy), used to bracket the transition.
        algorithm / captures_scanned: carried through for the report and the DB.

    Returns a dict that is safe to JSON-serialise and store. `precision_ms` is the
    headline: the KPI is `value ± precision_ms`.
    """
    conf: Dict = {
        'frames_in_window': 0,
        'fps_effective': None,
        'interval_ms_median': None,
        'interval_ms_p95': None,
        'interval_ms_max': None,
        'frames_missed': 0,
        'gaps': 0,
        'precision_ms': None,
        'source': 'unknown',
        'verified_bracket_ms': None,
        'algorithm': algorithm,
        'captures_scanned': captures_scanned,
        'has_frame_evidence': True,
    }
    if not all_captures or match_index is None or match_index <= 0:
        # No frames, or the match is the very first frame (nothing before it to
        # measure an interval against) — say so rather than inventing a bound.
        conf['frames_in_window'] = len(all_captures or [])
        return conf

    # The window that actually produced the number: the action, then every frame
    # up to and including the match. Frames after the match tell us nothing about
    # when the transition happened.
    start_idx = next((i for i, c in enumerate(all_captures)
                      if c['timestamp'] >= action_timestamp), 0)
    start_idx = min(start_idx, match_index)
    window = all_captures[start_idx:match_index + 1]
    conf['frames_in_window'] = len(window)
    if len(window) < 2:
        # A single frame between the press and the match: the transition is
        # bracketed by the press itself, which is the best we can say.
        conf['precision_ms'] = round((all_captures[match_index]['timestamp']
                                      - action_timestamp) * 1000.0, 1)
        return conf

    intervals = [(b['timestamp'] - a['timestamp']) * 1000.0
                 for a, b in zip(window, window[1:])]
    span = window[-1]['timestamp'] - window[0]['timestamp']
    median = _median(intervals)
    s = sorted(intervals)

    conf['fps_effective'] = round((len(window) - 1) / span, 2) if span > 0 else None
    conf['interval_ms_median'] = round(median)
    conf['interval_ms_p95'] = round(_percentile(s, 0.95))
    conf['interval_ms_max'] = round(s[-1])

    # Split the window where the storage changes, so each part is judged against its
    # OWN spacing. Without this a cold->hot window reports the step from 1000 ms down
    # to 200 ms as a pile of dropped frames, and every long measurement looks broken.
    # The split is the start of the trailing all-hot run, and it only counts as a
    # storage change when what precedes it really is archive-spaced — otherwise a
    # stall inside hot would be excused as "that part was cold".
    split = len(intervals)
    while split > 0 and intervals[split - 1] <= HOT_MAX_INTERVAL_MS:
        split -= 1
    head, tail = intervals[:split], intervals[split:]
    if not (head and _median(head) > HOT_MAX_INTERVAL_MS):
        head, tail = intervals, []

    segments = [seg for seg in (head, tail) if seg]
    for seg in segments:
        seg_median = _median(seg)
        if seg_median <= 0:
            continue
        conf['gaps'] += sum(1 for d in seg if d > GAP_FACTOR * seg_median)
        conf['frames_missed'] += sum(max(0, int(round(d / seg_median)) - 1) for d in seg)

    # The quantisation bound: the transition happened somewhere between the frame
    # before the match and the match itself.
    conf['precision_ms'] = round(intervals[-1])

    # Which storage served this window, judged on the segment medians above so a
    # single stall cannot masquerade as the archive.
    if len(segments) == 2:
        conf['source'] = 'mixed'
    elif segments:
        conf['source'] = 'hot' if _median(segments[0]) <= HOT_MAX_INTERVAL_MS else 'cold'

    # The defensible statement: the match frame proved the target PRESENT, and the
    # newest frame the verifier proved ABSENT sits before it, so the transition is
    # inside that bracket. Wider than precision_ms whenever the scan skipped frames
    # (the coarse-to-fine grid, or the exhaustive scan's subsampling).
    if probe_outcomes:
        absent = [i for i, ok in probe_outcomes.items() if not ok and i < match_index]
        if absent:
            last_absent = max(absent)
            conf['verified_bracket_ms'] = round(
                (all_captures[match_index]['timestamp']
                 - all_captures[last_absent]['timestamp']) * 1000.0)
    return conf


def no_frame_evidence(reason: str) -> Dict:
    """Confidence block for a KPI that never scanned frames at all.

    The live-verifier fast path (kpi_executor: `request.kpi_timestamp` set) returns a
    value without opening a single capture. That is not a worse measurement, but it
    is a DIFFERENT one, and until now it was indistinguishable in the database from a
    scanned measurement. Mark it explicitly.
    """
    return {
        'frames_in_window': 0, 'fps_effective': None,
        'interval_ms_median': None, 'interval_ms_p95': None, 'interval_ms_max': None,
        'frames_missed': 0, 'gaps': 0, 'precision_ms': None, 'source': 'none',
        'verified_bracket_ms': None, 'algorithm': reason, 'captures_scanned': 0,
        'has_frame_evidence': False,
    }


def format_precision(conf: Dict) -> str:
    """'±200ms' for the report header, or '' when there is nothing to claim."""
    p = conf.get('precision_ms')
    return f"±{int(round(p))}ms" if p else ''


def confidence_warnings(conf: Dict) -> List[str]:
    """Plain-language reasons this particular measurement is weaker than usual."""
    out: List[str] = []
    if not conf.get('has_frame_evidence'):
        out.append('measured by the live verifier, not from captured frames — '
                   'no frame evidence to re-check')
        return out
    src = conf.get('source')
    if src == 'cold':
        out.append('frames came from the archive, not the live buffer — '
                   f'{conf.get("interval_ms_median")}ms between frames instead of '
                   f'{int(HOT_INTERVAL_MS)}ms')
    elif src == 'mixed':
        out.append('the window spans the live buffer and the archive, so precision '
                   'varies across it')
    if conf.get('frames_missed'):
        out.append(f'{conf["frames_missed"]} frame(s) missing from the capture stream '
                   f'in {conf.get("gaps")} gap(s)')
    bracket = conf.get('verified_bracket_ms')
    precision = conf.get('precision_ms')
    if bracket and precision and bracket > precision * 1.5:
        out.append(f'the scan skipped frames: the change is only proven to be within '
                   f'{bracket}ms, not {int(precision)}ms')
    if (conf.get('algorithm') or '').endswith('+unsustained'):
        out.append('the matched screen did not hold — the match may be a transient')
    return out
