"""Pure verdict logic: expected cue(s) at time t vs what OCR read. No I/O."""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .srt import Cue, normalize

# issue types
MISSING = 'missing_subtitle'
UNEXPECTED = 'unexpected_subtitle'
STUCK = 'stuck_subtitle'
WRONG_TEXT = 'wrong_text'
TRUNCATED = 'truncated_line'
LATE = 'late_cue'
EARLY = 'early_cue'
WRONG_LANG = 'wrong_language'
OVERLAP = 'overlap'
CONTRAST = 'unreadable_contrast'
ISSUE_TYPES = [MISSING, UNEXPECTED, STUCK, WRONG_TEXT, TRUNCATED, LATE, EARLY, WRONG_LANG, OVERLAP, CONTRAST]

BOUNDARY = 0.3        # s around a cue edge where present/absent are both acceptable
CER_OK = 0.20         # character error rate under which the text counts as matching
MIN_CONTRAST = 3.0    # WCAG contrast ratio of subtitle text vs its surroundings (3:1 large text)
STUCK_WINDOW = 6.0    # s after a cue ends in which its text still showing = stuck


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(expected: str, got: str) -> float:
    exp, g = normalize(expected), normalize(got)
    if not exp:
        return 0.0 if not g else 1.0
    return levenshtein(exp, g) / len(exp)


def word_diff(expected: str, got: str):
    """(missing words, extra words) as multiset difference on normalised words."""
    e, g = normalize(expected).split(), normalize(got).split()
    ge = list(g)
    missing = []
    for w in e:
        if w in ge:
            ge.remove(w)
        else:
            missing.append(w)
    return missing, ge


@dataclass
class OcrResult:
    text: str = ''
    words: int = 0            # words kept after the confidence filter
    mean_conf: float = 0.0
    contrast: Optional[float] = None  # text vs surroundings, None when no text found
    lang: Optional[str] = None        # langdetect 2-letter code, None when too short


@dataclass
class Verdict:
    ok: bool
    state: str                    # expected: present | absent | boundary
    issue: Optional[str] = None
    flags: List[str] = field(default_factory=list)  # secondary issues (e.g. contrast)
    cer: Optional[float] = None
    missing_words: List[str] = field(default_factory=list)
    extra_words: List[str] = field(default_factory=list)
    matched_cue: Optional[int] = None
    expected_text: str = ''
    note: str = ''


def active_cues(cues: Sequence[Cue], t: float, margin: float = 0.0) -> List[Cue]:
    return [c for c in cues if c.start + margin <= t <= c.end - margin]


def _near_any_edge(cues: Sequence[Cue], t: float, boundary: float = BOUNDARY) -> bool:
    return any(abs(t - c.start) < boundary or abs(t - c.end) < boundary for c in cues)


MAX_SUBTITLE_WORDS = 16   # more than two lines of text in the band = picture text (credits), not a subtitle


def has_text(ocr: OcrResult) -> bool:
    """A subtitle is on screen: one real word (>= 3 letters, confident) or two words, but not a wall of text."""
    if ocr.words < 1 or ocr.words > MAX_SUBTITLE_WORDS:
        return False
    letters = sum(ch.isalpha() for ch in ocr.text)
    return letters >= 3 and ocr.mean_conf >= 60 and (ocr.words >= 2 or ocr.mean_conf >= 75)


def best_cue(cues: Sequence[Cue], text: str):
    best, best_cer = None, 9.9
    for c in cues:
        v = cer(c.text, text)
        if v < best_cer:
            best, best_cer = c, v
    return best, best_cer


def judge_sample(t: float, cues: Sequence[Cue], ocr: OcrResult, expected_lang: Optional[str] = None,
                 edge: float = BOUNDARY) -> Verdict:
    """Verdict for one frame. `cues` is the ground-truth track in the language shown. `edge` = seconds around a cue
    edge where present/absent are both accepted (device capture paths add up to ~1 s of timing jitter)."""
    inside = active_cues(cues, t, edge)
    boundary = _near_any_edge(cues, t, edge)
    shown = has_text(ocr)
    flags = []
    if shown and ocr.contrast is not None and ocr.contrast < MIN_CONTRAST:
        flags.append(CONTRAST)

    if inside:
        exp = inside[0]
        expected_text = exp.text.replace('\n', ' ')
        if not shown:
            return Verdict(False, 'present', MISSING, flags, expected_text=expected_text, matched_cue=exp.index,
                           note='no subtitle text found while a cue is active')
        c_exp = min(cer(c.text, ocr.text) for c in inside)
        miss, extra = word_diff(exp.text, ocr.text)
        if c_exp <= CER_OK:
            v = Verdict(not flags, 'present', flags[0] if flags else None, flags, c_exp, miss, extra, exp.index,
                        expected_text)
            return v
        # not the expected text: what is it?
        prev_cues = [c for c in cues if c.end <= exp.start and c.index != exp.index]
        other, other_cer = best_cue([c for c in cues if c.index != exp.index], ocr.text)
        if other is not None and other_cer <= CER_OK:
            issue = STUCK if other.end <= exp.start else WRONG_TEXT
            return Verdict(False, 'present', issue, flags, c_exp, miss, extra, other.index, expected_text,
                           note=f'shows the text of cue {other.index}')
        # two cues' text in one frame (overlap)?
        pair_txt = None
        for other_c in cues:
            if other_c.index == exp.index:
                continue
            both = min(cer(exp.text + ' ' + other_c.text, ocr.text), cer(other_c.text + ' ' + exp.text, ocr.text))
            if both <= CER_OK and both < c_exp:
                pair_txt = other_c
                break
        if pair_txt is not None:
            return Verdict(False, 'present', OVERLAP, flags, c_exp, miss, extra, exp.index, expected_text,
                           note=f'cue {exp.index} and cue {pair_txt.index} shown together')
        if expected_lang and ocr.lang and ocr.lang != expected_lang:
            return Verdict(False, 'present', WRONG_LANG, flags, c_exp, miss, extra, exp.index, expected_text,
                           note=f'text language {ocr.lang}, expected {expected_lang}')
        e_norm, g_norm = normalize(exp.text), normalize(ocr.text)
        if g_norm and len(g_norm) < 0.85 * len(e_norm) and not extra and len(miss) >= 1 and (
                e_norm.startswith(g_norm[: max(4, int(0.8 * len(g_norm)))]) or
                e_norm.endswith(g_norm[-max(4, int(0.8 * len(g_norm))):])):
            return Verdict(False, 'present', TRUNCATED, flags, c_exp, miss, extra, exp.index, expected_text,
                           note='text is a prefix/suffix of the expected line')
        return Verdict(False, 'present', WRONG_TEXT, flags, c_exp, miss, extra, exp.index, expected_text)

    if boundary:
        if shown:
            near = [c for c in cues if abs(t - c.start) < edge * 4 or abs(t - c.end) < edge * 4]
            c_best, v = best_cue(near or cues, ocr.text)
            if v > 0.5:
                return Verdict(False, 'boundary', WRONG_TEXT, flags, v, matched_cue=c_best.index if c_best else None,
                               expected_text=c_best.text.replace('\n', ' ') if c_best else '',
                               note='text at a cue edge matches no nearby cue')
        return Verdict(not flags, 'boundary', flags[0] if flags else None, flags, note='cue edge: present or absent accepted')

    # no cue should be on screen
    if shown:
        prior = [c for c in cues if 0 < t - c.end <= STUCK_WINDOW]
        c_best, v = best_cue(prior, ocr.text) if prior else (None, 9.9)
        if c_best is not None and v <= CER_OK:
            return Verdict(False, 'absent', STUCK, flags, v, matched_cue=c_best.index,
                           expected_text='', note=f'cue {c_best.index} still shown {t - c_best.end:.1f}s after its end')
        return Verdict(False, 'absent', UNEXPECTED, flags, 1.0, extra_words=normalize(ocr.text).split(),
                       note='subtitle text on screen where no cue is defined')
    return Verdict(True, 'absent')


@dataclass
class CueTiming:
    cue: int
    srt_start: float
    srt_end: float
    seen_first: Optional[float] = None
    seen_last: Optional[float] = None
    audio_start: Optional[float] = None
    lag_srt: Optional[float] = None    # seen_first - srt_start
    lag_audio: Optional[float] = None  # seen_first - audio_start
    issue: Optional[str] = None
    note: str = ''


def judge_timing(cue: Cue, seen_first: Optional[float], seen_last: Optional[float], audio_start: Optional[float],
                 tol: float = 1.0, srt_tol: float = 0.6, step: float = 0.25) -> CueTiming:
    """Late/early cue. Basis = audio when a transcript match exists, else the SRT.
    `step` is the sampling resolution around edges; it is added to the tolerance."""
    ct = CueTiming(cue.index, cue.start, cue.end, seen_first, seen_last, audio_start)
    if seen_first is None:
        return ct
    ct.lag_srt = seen_first - cue.start
    if audio_start is not None:
        ct.lag_audio = seen_first - audio_start
        if ct.lag_audio > tol + step:
            ct.issue, ct.note = LATE, f'shown {ct.lag_audio:.2f}s after the speech starts'
        elif ct.lag_audio < -(tol + step):
            ct.issue, ct.note = EARLY, f'shown {-ct.lag_audio:.2f}s before the speech starts'
    if ct.issue is None:
        if ct.lag_srt > srt_tol + step:
            ct.issue, ct.note = LATE, f'first seen {ct.lag_srt:.2f}s after the SRT start'
        elif ct.lag_srt < -(srt_tol + step):
            ct.issue, ct.note = EARLY, f'first seen {-ct.lag_srt:.2f}s before the SRT start'
    return ct


TRANSIENT = (MISSING, WRONG_TEXT, TRUNCATED)


def downgrade_transient(rows: list, cues: Sequence[Cue]) -> int:
    """A text defect must hold for the whole cue. When another sample of the same cue read the text
    correctly (CER <= CER_OK), a bad read at a sample is OCR noise (busy scene, thin glyphs), not a defect:
    the issue is cleared and the note says why. Stuck / overlap / unexpected / language issues are untouched.
    `rows` are dicts with 't' and 'verdict' (a dict from Verdict.__dict__). Returns how many were cleared."""
    cleared = 0
    for c in cues:
        mine = [r for r in rows if r['verdict']['matched_cue'] == c.index and r['verdict']['state'] == 'present']
        good = [r for r in mine if r['verdict']['cer'] is not None and r['verdict']['cer'] <= CER_OK]
        if not good:
            continue
        for r in mine:
            v = r['verdict']
            if v['issue'] in TRANSIENT:
                v['note'] = f"OCR noise: {v['issue']} at this sample, {len(good)} other sample(s) of cue {c.index} read it correctly"
                v['issue'], v['ok'] = None, not v['flags']
                cleared += 1
    return cleared
