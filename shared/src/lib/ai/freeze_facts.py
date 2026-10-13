"""Pure freeze measurements and the fact lines Jev reads. No I/O apart from the tesseract call.

Shared by the bench (``scripts/jev_freeze``, ``measure`` on a strip) and the host
(``facts_from_frames`` on the alert's own frames, TASK-55).

A strip (``shared/src/lib/ai/freeze_strip.render_strip``) is 2-3 equal tiles side by side, each
with a white "+12.3 s" label in its top-left corner, over a 40 px footer
("frozen 31.2 s | diff 0.42%").
"""
import re
import subprocess
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np

FOOTER_H = 40                # freeze_strip.FOOTER_H
STRIP_LONG_SIDE = 1280       # freeze_strip.MAX_LONG_SIDE
CHANGE_LEVEL = 25            # grey levels: a pixel "changed" above this (after a 3x3 blur)
CELL_LEVEL = 8               # mean grey diff above which a grid cell counts as changed
GRID = 4                     # 4x4 regions
LABEL_W, LABEL_H = 0.30, 0.16  # share of a tile hidden by the time label

_FROZEN_RE = re.compile(r'frozen\s*(\d+(?:[.,]\d+)?)\s*s', re.I)
_DIFF_RE = re.compile(r'diff\s*(\d+(?:[.,]\d+)?)\s*%', re.I)


def split_strip(strip: np.ndarray) -> List[np.ndarray]:
    """The tiles of a strip. A width of exactly ``(1280 // n) * n`` gives n; 2 and 4 both fit 1280,
    so the seam test decides: real tile edges are sharper than neighbouring columns."""
    body = strip[:-FOOTER_H] if strip.shape[0] > FOOTER_H else strip
    width = body.shape[1]
    candidates = [n for n in (2, 3, 4) if (STRIP_LONG_SIDE // n) * n == width] or [2]
    grey = cv2.cvtColor(body, cv2.COLOR_BGR2GRAY).astype(np.float32)
    col_step = np.abs(np.diff(grey, axis=1)).mean(axis=0)  # col_step[x] = |col x+1 - col x|

    def seam_score(n: int) -> float:
        cell = width // n
        seams = [col_step[k * cell - 1] for k in range(1, n)]
        return float(np.mean(seams)) / (float(np.median(col_step)) + 1e-6)

    n = max(candidates, key=seam_score)
    cell = width // n
    return [body[:, k * cell:(k + 1) * cell] for k in range(n)]


def _masked_grey(tile: np.ndarray) -> np.ndarray:
    grey = cv2.GaussianBlur(cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    h, w = grey.shape
    grey[:int(h * LABEL_H), :int(w * LABEL_W)] = 0
    return grey


def dhash64(tile: np.ndarray) -> int:
    small = cv2.resize(_masked_grey(tile), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(sum(1 << i for i, b in enumerate(bits) if b))


def compare(a: np.ndarray, b: np.ndarray) -> Dict[str, Any]:
    """How much changed between two tiles: % of pixels, 4x4 regions, mean diff, dHash bits."""
    ga, gb = _masked_grey(a), _masked_grey(b)
    if ga.shape != gb.shape:
        gb = cv2.resize(gb, (ga.shape[1], ga.shape[0]))
    diff = cv2.absdiff(ga, gb)
    h, w = diff.shape
    cells = [diff[r * h // GRID:(r + 1) * h // GRID, c * w // GRID:(c + 1) * w // GRID].mean()
             for r in range(GRID) for c in range(GRID)]
    return {'changed_pct': round(float((diff > CHANGE_LEVEL).mean() * 100), 2),
            'regions_changed': int(sum(1 for v in cells if v > CELL_LEVEL)),
            'mean_abs_diff': round(float(diff.mean()), 2),
            'dhash_bits': bin(dhash64(a) ^ dhash64(b)).count('1')}


def content(tile: np.ndarray) -> Dict[str, Any]:
    grey = _masked_grey(tile)
    edges = cv2.Canny(grey, 50, 150)
    return {'edge_pct': round(float((edges > 0).mean() * 100), 2),
            'brightness': round(float(grey.mean()), 1), 'contrast': round(float(grey.std()), 1)}


def ocr(img: np.ndarray, psm: int = 6, lang: str = 'deu+eng') -> str:
    """tesseract CLI on an in-memory image (upscaled x2: strip tiles are small)."""
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode('.png', big)
    if not ok:
        return ''
    try:
        from shared.src.lib.utils.tesseract_env import tesseract_env
        env = tesseract_env()
    except Exception:
        env = None
    try:
        out = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', lang, '--psm', str(psm)],
                             input=buf.tobytes(), capture_output=True, timeout=30, env=env)
        return out.stdout.decode('utf-8', 'ignore')
    except (OSError, subprocess.TimeoutExpired):
        return ''


def readable(text: str, limit: int = 20) -> str:
    """The words a viewer would read, in order: letter words of 3+ characters, no OCR debris."""
    seen, out = set(), []
    for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'&-]{2,}", text or ''):
        core = w.replace("'", '').replace('&', '').replace('-', '')
        cased = core.islower() or core.isupper() or (core[:1].isupper() and core[1:].islower())
        if cased and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ' '.join(out[:limit])


def words(text: str) -> set:
    return {w for w in re.findall(r'[A-Za-zÀ-ÿ0-9]{3,}', text.lower())}


def footer_values(text: str) -> Dict[str, Optional[float]]:
    f, d = _FROZEN_RE.search(text or ''), _DIFF_RE.search(text or '')
    return {'frozen_s': float(f.group(1).replace(',', '.')) if f else None,
            'detector_diff_pct': float(d.group(1).replace(',', '.')) if d else None}


def jaccard(a: set, b: set) -> Optional[float]:
    return round(len(a & b) / len(a | b), 2) if (a or b) else None


def fact_lines(m: Dict[str, Any]) -> List[str]:
    """The text Jev reads. Never the label."""
    lines = []
    first_last = m['first_last']
    lines.append(f"Between the first and last frame, {first_last['changed_pct']}% of the picture changed, "
                 f"in {first_last['regions_changed']} of {GRID * GRID} regions "
                 f"(fingerprint {first_last['dhash_bits']} of 64 bits different).")
    if len(m['pairs']) > 1:
        lines.append('Consecutive frames: ' + '; '.join(
            f"{i + 1}->{i + 2}: {p['changed_pct']}% changed" for i, p in enumerate(m['pairs'])) + '.')
    text = m['text']
    if text['words_first'] or text['words_last']:
        overlap = text['overlap']
        lines.append(f"On-screen text: {text['words_first']} words in the first frame, {text['words_last']} in "
                     f"the last; overlap {overlap if overlap is not None else 'n/a'} (1.00 = the same text).")
    else:
        lines.append('No readable on-screen text.')
    if text.get('read_first') or text.get('read_last'):
        lines.append(f'Words read on screen: first frame "{text.get("read_first") or "-"}"; '
                     f'last frame "{text.get("read_last") or "-"}".')
    c = m['content']
    look = ('nearly flat (black or uniform)' if c['edge_pct'] < 0.5 or c['contrast'] < 8
            else 'edge-rich (menu, text or busy picture)' if c['edge_pct'] > 6 else 'moderately detailed')
    lines.append(f"The first frame is {look}: brightness {c['brightness']}, contrast {c['contrast']}, "
                 f"edges {c['edge_pct']}%.")
    fv = m.get('footer') or {}
    if fv.get('frozen_s') is not None:
        lines.append(f"The detector reported the picture frozen for {fv['frozen_s']} s"
                     + (f" (largest frame difference {fv['detector_diff_pct']}%)." if fv.get('detector_diff_pct') is not None else '.'))
    return lines


def _measure_tiles(tiles: List[np.ndarray], with_ocr: bool) -> Dict[str, Any]:
    pairs = [compare(a, b) for a, b in zip(tiles, tiles[1:])]
    first_last = compare(tiles[0], tiles[-1])
    if with_ocr:
        t_first, t_last = ocr(tiles[0]), ocr(tiles[-1])
        w_first, w_last = words(t_first), words(t_last)
        read_first, read_last = readable(t_first), readable(t_last)
    else:
        w_first, w_last = set(), set()
        read_first = read_last = ''
    m = {'n_frames': len(tiles), 'pairs': pairs, 'first_last': first_last,
         'text': {'words_first': len(w_first), 'words_last': len(w_last), 'overlap': jaccard(w_first, w_last),
                  'read_first': read_first, 'read_last': read_last},
         'content': content(tiles[0])}
    m['facts'] = fact_lines(m)
    return m


def measure(strip: np.ndarray, with_ocr: bool = True) -> Dict[str, Any]:
    """Bench: measure a rendered strip (tiles + the footer the detector wrote)."""
    m = _measure_tiles(split_strip(strip), with_ocr)
    footer_text = ocr(strip[-FOOTER_H:], psm=7, lang='eng') if with_ocr and strip.shape[0] > FOOTER_H else ''
    m['footer_text'] = footer_text.strip()
    m['footer'] = footer_values(footer_text)
    m['facts'] = fact_lines(m)
    return m


def facts_from_frames(frames: List[np.ndarray], with_ocr: bool = True) -> Dict[str, Any]:
    """Same dict as ``measure`` (minus the footer) from raw frames, oldest first: the host has the
    frames themselves, no strip. Frames are scaled to the tile size a strip would give them so the
    thresholds and the OCR behave as in the benchmark. Needs at least two frames."""
    if len(frames) < 2:
        raise ValueError('need at least two frames')
    cell_w = max(1, STRIP_LONG_SIDE // len(frames))
    h0, w0 = frames[0].shape[:2]
    cell_h = max(1, int(round(cell_w * h0 / float(w0))))
    tiles = [cv2.resize(f, (cell_w, cell_h), interpolation=cv2.INTER_AREA) for f in frames]
    return _measure_tiles(tiles, with_ocr)


def truth_of(ground_truth: Any) -> Optional[str]:
    gt = ground_truth if isinstance(ground_truth, dict) else {}
    if gt.get('incident_type') == 'freeze':
        return 'freeze'
    if gt.get('static_screen') is True:
        return 'still'
    if gt.get('static_screen') is False:
        return 'moving'
    return None


def best_threshold(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """No-AI baseline: moving if first->last changed_pct >= T, else still. T fitted on ``rows``
    ({changed_pct, truth}), so its accuracy is optimistic."""
    scored = [r for r in rows if r.get('truth') in ('still', 'moving')]
    best = {'threshold': None, 'correct': 0, 'n': len(scored)}
    for t in sorted({r['changed_pct'] for r in scored} | {0.0}):
        correct = sum(1 for r in scored if ('moving' if r['changed_pct'] >= t else 'still') == r['truth'])
        if correct > best['correct']:
            best = {'threshold': t, 'correct': correct, 'n': len(scored)}
    return best


def is_camera(device_model: Any) -> bool:
    """A camera watches a room: its picture is quiet by nature and has no on-screen text to read."""
    return 'camera' in str(device_model or '').lower()
