"""Pure scoring for the Jev screen review (TASK-38 goal 6): the host's image and text checks
run offline on a stored frame, and the one-line facts Jev reads.

No DB, no network. tesseract is only called by ``ocr_area``.

The host's own code is loaded by file path (``image_helpers.py`` / ``text_helpers.py``: no
backend_host package import). When that import fails (a box without their dependencies) the
``_Local*`` classes below re-implement the branches the review needs, with the same numbers:

* image: ``ImageVerificationController._match_template`` (verification/image.py ~1993) and
  ``ImageHelpers.smart_fuzzy_search`` / ``_l1_match_*`` (image_helpers.py ~246, ~330-470)
* text:  ``TextHelpers._normalize_for_match`` / ``text_match_score`` (text_helpers.py, word-boundary scorer)
"""
from __future__ import annotations

import contextlib
import functools
import importlib.util
import io
import os
import re
import subprocess
import tempfile
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
VERIFICATION_DIR = os.path.join(REPO_ROOT, 'backend_host', 'src', 'controllers', 'verification')
BASE_SIZE = (1280, 720)          # capture pixels the areas are stored in
DEFAULT_THRESHOLD = 0.8
AREA_KEYS = ('x', 'y', 'width', 'height', 'fx', 'fy', 'fwidth', 'fheight')
MAX_SHOWN_CHECKS = 3
IMAGE_APPEAR, IMAGE_DISAPPEAR, TEXT_APPEAR = 'waitForImageToAppear', 'waitForImageToDisappear', 'waitForTextToAppear'


# ---- host helpers (loaded by path) -----------------------------------------------------------

class _LocalImage:
    """smart_fuzzy_search of ImageHelpers (image_helpers.py ~246) with its L1 matcher for small
    templates (~330-470): same constants, guards and scores."""
    SMALL = 1000
    STD_FLOOR, STD_RATIO = 20.0, 0.6
    COLOR_TOL, COV_FLOOR = 40, 0.7

    def _guards_ok(self, window, ref) -> bool:
        ref_std = float(ref.std())
        if ref_std >= self.STD_FLOOR and float(window.std()) < self.STD_RATIO * ref_std:
            return False
        within = (cv2.absdiff(window, ref) <= self.COLOR_TOL).all(axis=2)
        return float(within.mean()) >= self.COV_FLOOR

    def _l1(self, window, ref) -> float:
        if window.shape != ref.shape or not self._guards_ok(window, ref):
            return 0.0
        return 1.0 - float(cv2.absdiff(window, ref).mean()) / 255.0

    def _l1_in_region(self, region, ref) -> Tuple[float, Tuple[int, int]]:
        rh, rw = ref.shape[:2]
        if region.shape[0] < rh or region.shape[1] < rw:
            return 0.0, (0, 0)
        best, loc = -1.0, (0, 0)
        for y in range(region.shape[0] - rh + 1):
            for x in range(region.shape[1] - rw + 1):
                s = 1.0 - float(cv2.absdiff(region[y:y + rh, x:x + rw], ref).mean()) / 255.0
                if s > best:
                    best, loc = s, (x, y)
        window = region[loc[1]:loc[1] + rh, loc[0]:loc[0] + rw]
        return (max(best, 0.0) if self._guards_ok(window, ref) else 0.0), loc

    def smart_fuzzy_search(self, source, ref, exact, fuzzy, threshold=DEFAULT_THRESHOLD):
        rh, rw = ref.shape[:2]
        ex, ey, ew, eh = (int(exact[k]) for k in ('x', 'y', 'width', 'height'))
        fx, fy, fw, fh = (int(fuzzy[k]) for k in ('fx', 'fy', 'fwidth', 'fheight'))
        small = rh * rw <= self.SMALL
        exact_conf = 0.0
        region = source[ey:ey + eh, ex:ex + ew]
        if region.shape[:2] == (eh, ew):
            exact_conf = (self._l1(region, ref) if small
                          else float(cv2.matchTemplate(region, ref, cv2.TM_CCOEFF_NORMED)[0][0]))
            if exact_conf >= threshold:
                return True, exact_conf, {'x': ex, 'y': ey, 'width': rw, 'height': rh}
        search = source[fy:fy + fh, fx:fx + fw]
        if search.shape[0] < rh or search.shape[1] < rw:
            return False, exact_conf, {'x': ex, 'y': ey, 'width': rw, 'height': rh}
        if small:
            best, loc = self._l1_in_region(search, ref)
        else:
            _, best, _, loc = cv2.minMaxLoc(cv2.matchTemplate(search, ref, cv2.TM_CCOEFF_NORMED))
        return best >= threshold, best, {'x': fx + loc[0], 'y': fy + loc[1], 'width': rw, 'height': rh}


class _LocalText:
    """text_match_score of TextHelpers (text_helpers.py, word-boundary scorer)."""

    @staticmethod
    def _normalize_for_match(s: str) -> str:
        s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
        return ' '.join(re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE).replace('_', ' ').split()).lower()

    _UNSPACED = re.compile('[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff]')

    def text_match_score(self, extracted_text: str, target_text: str) -> float:
        if not extracted_text or not target_text:
            return 0.0
        ext, tgt = self._normalize_for_match(extracted_text), self._normalize_for_match(target_text)
        if not ext or not tgt:
            return 0.0
        unspaced = bool(self._UNSPACED.search(tgt) or self._UNSPACED.search(ext))
        if (tgt in ext) if unspaced else (f' {tgt} ' in f' {ext} '):
            return 1.0
        if not unspaced:
            words, k, best = ext.split(), len(tgt.split()), 0.0
            for win in range(max(1, k - 1), k + 2):
                win = min(win, len(words))
                for i in range(len(words) - win + 1):
                    best = max(best, SequenceMatcher(None, tgt, ' '.join(words[i:i + win]), autojunk=False).ratio())
            return best
        n, m = len(tgt), len(ext)
        if m <= n:
            return SequenceMatcher(None, tgt, ext, autojunk=False).ratio()
        best = 0.0
        for win in range(max(1, n - 2), min(m, n + 2) + 1):
            for i in range(m - win + 1):
                best = max(best, SequenceMatcher(None, tgt, ext[i:i + win], autojunk=False).ratio())
                if best >= 1.0:
                    return best
        return best


def _load_host(filename: str, cls: str, args: tuple, fallback):
    try:
        spec = importlib.util.spec_from_file_location(f'jev_review_host_{cls}', os.path.join(VERIFICATION_DIR, filename))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, cls)(*args)
    except Exception:
        return fallback()


@functools.lru_cache(maxsize=None)
def image_helpers():
    """The host's ``ImageHelpers`` (or its local re-implementation)."""
    return _load_host('image_helpers.py', 'ImageHelpers', ('', None), _LocalImage)


@functools.lru_cache(maxsize=None)
def text_helpers():
    """The host's ``TextHelpers`` (or its local re-implementation)."""
    return _load_host('text_helpers.py', 'TextHelpers', ('',), _LocalText)


# ---- geometry --------------------------------------------------------------------------------

def frame_scale(width: int, height: int) -> Tuple[float, float]:
    """Factors from the stored area space (1280x720) to a frame."""
    return width / BASE_SIZE[0], height / BASE_SIZE[1]


def scale_area(area: Optional[Mapping[str, Any]], sx: float, sy: float) -> Optional[dict]:
    if not area:
        return None
    out = dict(area)
    for key in AREA_KEYS:
        if isinstance(area.get(key), (int, float)):
            out[key] = round(area[key] * (sx if key in ('x', 'width', 'fx', 'fwidth') else sy))
    return out


def _crop_box(area: Mapping[str, Any], frame_shape) -> Tuple[int, int, int, int]:
    h, w = frame_shape[:2]
    x, y = max(0, int(area['x'])), max(0, int(area['y']))
    return x, y, min(int(area['width']), w - x), min(int(area['height']), h - y)


# ---- image -----------------------------------------------------------------------------------

def match_image(ref, source, area: Optional[dict] = None, threshold: float = DEFAULT_THRESHOLD,
                helpers=None) -> Tuple[bool, float, Optional[dict]]:
    """``ImageVerificationController._match_template``: fuzzy keys -> search the reference in the
    fuzzy window; an area only -> fraction of grey pixels within 10 of the resized reference;
    no area -> full-frame TM_CCOEFF_NORMED. Returns (found, score, location)."""
    helpers = helpers or image_helpers()
    try:
        if area and area.get('fx') is not None:
            exact = {k: area[k] for k in ('x', 'y', 'width', 'height')}
            fuzzy = {k: area[k] for k in ('fx', 'fy', 'fwidth', 'fheight')}
            with contextlib.redirect_stdout(io.StringIO()):  # the host helper prints its trace
                found, score, loc = helpers.smart_fuzzy_search(source, ref, exact, fuzzy, threshold)
            return bool(found), float(score), loc
        if area:
            x, y, w, h = int(area['x']), int(area['y']), int(area['width']), int(area['height'])
            crop = source[y:y + h, x:x + w]
            if crop.size == 0:
                return False, 0.0, None
            resized = cv2.resize(ref, (crop.shape[1], crop.shape[0])) if crop.shape != ref.shape else ref
            diff = cv2.absdiff(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY))
            score = float(np.sum(diff <= 10)) / (crop.shape[0] * crop.shape[1])
            return score >= threshold, score, {'x': x, 'y': y, 'width': w, 'height': h}
        result = cv2.matchTemplate(source, ref, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        return bool(score >= threshold), float(score), {'x': loc[0], 'y': loc[1], 'width': ref.shape[1], 'height': ref.shape[0]}
    except Exception:
        return False, 0.0, None


def check_image(frame, ref, area: Optional[dict], threshold: float, disappear: bool = False,
                helpers=None) -> Dict[str, Any]:
    """One image verification on a frame. Areas are in 1280x720; a frame of another size scales
    the area and the reference with it. ``disappear``: the score is inverted (1 - match) and the
    check passes when the match stays under the threshold."""
    sx, sy = frame_scale(frame.shape[1], frame.shape[0])
    if (sx, sy) != (1.0, 1.0):
        area = scale_area(area, sx, sy)
        ref = cv2.resize(ref, (max(1, round(ref.shape[1] * sx)), max(1, round(ref.shape[0] * sy))))
    found, score, _ = match_image(ref, frame, area, threshold, helpers)
    if disappear:
        return {'kind': 'image', 'score': round(1.0 - score, 3), 'threshold': threshold,
                'passed': not found, 'inverted': True}
    return {'kind': 'image', 'score': round(score, 3), 'threshold': threshold, 'passed': found, 'inverted': False}


# ---- text ------------------------------------------------------------------------------------

def alternatives(expected: str) -> List[str]:
    """``"Settings|Einstellungen"`` -> the terms (the host tries each and keeps the best)."""
    return [t.strip() for t in str(expected or '').split('|') if t.strip()]


def score_text(extracted: str, expected: str, helpers=None) -> float:
    """Best ``text_match_score`` of the extracted text against any ``|`` alternative."""
    helpers = helpers or text_helpers()
    return max((helpers.text_match_score(extracted, t) for t in alternatives(expected)), default=0.0)


def ocr_area(frame, area: Optional[dict], lang: str = 'deu+eng', timeout: int = 30) -> str:
    """``TextHelpers.detect_text_in_area`` (simple path): crop to the area, grey, binary threshold
    127, tesseract CLI (one OpenMP thread, as on the host). '' when tesseract fails."""
    from shared.src.lib.utils.tesseract_env import tesseract_env
    sx, sy = frame_scale(frame.shape[1], frame.shape[0])
    area = scale_area(area, sx, sy)
    img = frame
    if area:
        x, y, w, h = _crop_box(area, frame.shape)
        img = frame[y:y + h, x:x + w]
    if img.size == 0:
        return ''
    _, binary = cv2.threshold(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 127, 255, cv2.THRESH_BINARY)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        path = tmp.name
    try:
        cv2.imwrite(path, binary)
        out = subprocess.run(['tesseract', path, 'stdout', '-l', lang], capture_output=True, text=True,
                             timeout=timeout, env=tesseract_env())
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def check_text(extracted: str, expected: str, threshold: float, helpers=None) -> Dict[str, Any]:
    score = round(score_text(extracted, expected, helpers), 3)
    return {'kind': 'text', 'score': score, 'threshold': threshold, 'passed': score >= threshold, 'inverted': False}


# ---- seed frame ------------------------------------------------------------------------------

def seed_bits(frame_hash: Optional[str], seed_hash: Optional[str]) -> Optional[int]:
    """dHash Hamming distance in bits (0 = identical), or None when either hash is missing."""
    if not frame_hash or not seed_hash:
        return None
    from shared.src.lib.utils.image_hash import dhash_hamming
    return dhash_hamming(frame_hash, seed_hash)


# ---- facts ------------------------------------------------------------------------------------

def _check_text(c: Mapping[str, Any]) -> str:
    name, score, thr = c['name'], f"{c['score']:.2f}", f"{c['threshold']:.2f}"
    verdict = 'pass' if c['passed'] else 'fail'
    if c['kind'] == 'image':
        if c.get('inverted'):
            return f"image check '{name}' absence {score} (inverted: {verdict} when the match stays under {thr})"
        return f"image check '{name}' {score} ({verdict} at {thr})"
    return f"text '{name}' found {score}" if c['passed'] else f"text '{name}' best {score} ({verdict} at {thr})"


def format_facts(checks: Sequence[Mapping[str, Any]], seed_distance: Optional[int], seed_total: int = 256) -> str:
    """ONE short line: the best checks first (passed, then score), at most ``MAX_SHOWN_CHECKS``,
    then the seed-frame distance. No check and no seed: "no reference evidence"."""
    ranked = sorted(checks, key=lambda c: (not c['passed'], -float(c['score'])))
    parts = [_check_text(c) for c in ranked[:MAX_SHOWN_CHECKS]]
    if len(ranked) > MAX_SHOWN_CHECKS:
        parts.append(f"{len(ranked) - MAX_SHOWN_CHECKS} more checks, lower")
    if seed_distance is not None:
        parts.append(f"seed frame {seed_distance} of {seed_total} bits away")
    return '; '.join(parts) if parts else 'no reference evidence'


def best_score(checks: Sequence[Mapping[str, Any]], kind: str) -> Optional[float]:
    scores = [float(c['score']) for c in checks if c['kind'] == kind and not c.get('inverted')]
    return max(scores) if scores else None
