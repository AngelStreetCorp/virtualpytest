"""Caption playback (TASK-103): WebVTT from a transcript chunk, and the per-minute caption source.

The chunk JSON (transcript/<hour>/chunk_10min_<n>.json) has `segments: [{start, end, text, words?: [{word,start,end}]}]`
with chunk-relative times, the same timebase as the archive chunk MP4. Cues are built from the words; a segment
without words (written before word timestamps were on, or a model that returned none) is split in proportion to
the characters of its words (the fallback of TASK-103 section 6.5).
"""
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Speech starts about 0.4 s before the broadcaster's subtitle (TASK-103 section 6.4): every cue is shifted by this.
CAPTION_SHIFT_S = 0.4
MACHINE_MARKER = '[auto] '
LINE_CHARS = 42
MAX_LINES = 2
MIN_CUE_S = 1.0
MAX_CUE_S = 6.0
GAP_BREAK_S = 0.8          # a pause this long ends a cue
_SENTENCE_END = re.compile(r'[.!?…]["»”)]*$')

CAPTION_SOURCES = ('machine', 'broadcaster', 'none')

# A minute "carries broadcaster subtitles" when at least this share of the frames the subtitle OCR looked at had them,
# and at least MIN_OCR_FRAMES frames (the subtitle OCR looks at 2-11 frames of a minute on vpt-pi1) were looked at (frames skipped for freeze / black / no audio do not count).
SUBTITLE_MINUTE_SHARE = 0.5
MIN_OCR_FRAMES = 3


def _fmt(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def _words_of(segments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for seg in segments:
        words = seg.get('words')
        if words:
            out.extend({'word': w['word'], 'start': float(w['start']), 'end': float(w['end'])} for w in words if w.get('word'))
            continue
        toks = (seg.get('text') or '').split()
        if not toks:
            continue
        start, end = float(seg.get('start', 0)), float(seg.get('end', 0))
        total = sum(len(t) for t in toks) or 1
        at = start
        for t in toks:
            nxt = at + (end - start) * len(t) / total
            out.append({'word': t, 'start': at, 'end': nxt})
            at = nxt
    return out


def _wrap(words: List[str], first_prefix: str = '') -> Optional[List[str]]:
    """Greedy wrap into lines of LINE_CHARS; None when it needs more than MAX_LINES."""
    lines: List[str] = []
    cur = first_prefix.rstrip()
    for w in words:
        trial = f'{cur} {w}'.strip() if cur else w
        if len(trial) <= LINE_CHARS or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
        if len(lines) >= MAX_LINES:
            return None
    lines.append(cur)
    return lines if len(lines) <= MAX_LINES else None


def build_cues(segments: List[Dict[str, Any]], shift_s: float = CAPTION_SHIFT_S, marker: str = MACHINE_MARKER) -> List[Tuple[float, float, List[str]]]:
    """[(start, end, lines)]: at most MAX_LINES lines of LINE_CHARS, MIN_CUE_S..MAX_CUE_S long, shifted by shift_s."""
    words = _words_of(segments)
    cues: List[Tuple[float, float, List[str]]] = []
    group: List[Dict[str, Any]] = []

    def flush():
        if not group:
            return
        lines = _wrap([g['word'] for g in group], marker)
        start = group[0]['start'] + shift_s
        end = max(group[-1]['end'] + shift_s, start + MIN_CUE_S)
        cues.append((max(0.0, start), end, lines or [marker + ' '.join(g['word'] for g in group)]))
        group.clear()

    for w in words:
        if group:
            gap = w['start'] - group[-1]['end']
            too_long = (w['end'] - group[0]['start']) > MAX_CUE_S
            no_fit = _wrap([g['word'] for g in group] + [w['word']], marker) is None
            if gap > GAP_BREAK_S or too_long or no_fit or _SENTENCE_END.search(group[-1]['word']):
                flush()
        group.append(w)
    flush()
    # a minimum-length cue must not run into the next one
    fixed = []
    for i, (s, e, lines) in enumerate(cues):
        if i + 1 < len(cues):
            e = min(e, max(s + 0.2, cues[i + 1][0] - 0.02))
        fixed.append((s, e, lines))
    return fixed


def build_vtt(chunk: Optional[Dict[str, Any]], source_language: Optional[str] = None) -> str:
    """WebVTT for one chunk JSON (None / empty chunk: just the header).

    A translated chunk (caption_translate) can hold `untranslated` segments: they keep the source text and their cues are
    marked `[auto <source_language>]` so the viewer sees the language honestly."""
    segments = (chunk or {}).get('segments') or []
    own = [s for s in segments if not s.get('untranslated')]
    left = [s for s in segments if s.get('untranslated')]
    cues = build_cues(own)
    if left:
        cues = sorted(cues + build_cues(left, marker=f'[auto {source_language or "?"}] '), key=lambda c: c[0])
    out = ['WEBVTT', '', 'NOTE machine-generated captions (caption_playback)', '']
    if (chunk or {}).get('machine_translated'):
        out[2] += ' machine-translated'
    for s, e, lines in cues:
        out.append(f'{_fmt(s)} --> {_fmt(e)}')
        out.extend(lines)
        out.append('')
    return '\n'.join(out)


def minute_coverage(chunk: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{minute, caption_source, ready}] for minutes 0-9 from a chunk JSON's minute_statuses. `ready` = the minute was processed."""
    statuses = (chunk or {}).get('minute_statuses') or {}
    out = []
    for m in range(10):
        st = statuses.get(str(m)) or {}
        source = st.get('caption_source') or ('machine' if st.get('has_audio') else 'none')
        out.append({'minute': m, 'caption_source': source if source in CAPTION_SOURCES else 'none',
                    'ready': bool(st.get('processed'))})
    return out


# ---- goal 7: only where there are no broadcaster subtitles -------------------------------------------------

def decide_subtitle_minute(flags: List[Optional[bool]]) -> Tuple[bool, int, int]:
    """flags = one entry per frame JSON of the minute: True / False = subtitle OCR result, None = OCR did not look
    (skipped or pending). Returns (broadcaster_has_subtitles, frames_with_subtitles, frames_checked)."""
    checked = [f for f in flags if f is not None]
    with_sub = sum(1 for f in checked if f)
    return (len(checked) >= MIN_OCR_FRAMES and with_sub / len(checked) >= SUBTITLE_MINUTE_SHARE), with_sub, len(checked)


def subtitle_flags_for_window(metadata_dir: str, t_start: float, t_end: float, limit: int = 40) -> List[Optional[bool]]:
    """has_subtitles of the frame JSONs in metadata_dir written between t_start and t_end (epoch s), at most `limit`
    evenly spread. Reading is cheap: only the picked files are opened."""
    import json
    try:
        entries = [e for e in os.scandir(metadata_dir) if e.name.startswith('capture_') and e.name.endswith('.json')]
    except OSError:
        return []
    inside = sorted((e for e in entries if t_start <= e.stat().st_mtime <= t_end), key=lambda e: e.name)
    if len(inside) > limit:
        step = len(inside) / limit
        inside = [inside[int(i * step)] for i in range(limit)]
    flags: List[Optional[bool]] = []
    for e in inside:
        try:
            with open(e.path, 'r') as f:
                sa = (json.load(f) or {}).get('subtitle_analysis')
        except (OSError, ValueError):
            continue
        if not isinstance(sa, dict) or sa.get('skipped'):
            flags.append(None)
        else:
            flags.append(bool(sa.get('has_subtitles')))
    return flags
