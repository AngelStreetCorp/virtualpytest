"""Tier-2 deterministic screen-state detection: the four mechanical questions that need no model.

The localization cascade is Tier 1 fingerprint ``identify_screen`` (closed-set -> node_id) ->
**this module** -> Tier 3 local model (offline only). Tier 2 exists because the biggest part of
Tier 1's abstentions are not model questions at all: they are "has the UI finished drawing", "is
something on top of the page", "is the video running", "is an error on screen".

Design rules this module obeys:

1. **Abstain honestly.** Every question returns ``unknown`` when its inputs do not support an
   answer. A wrong answer costs a wrong localization step; ``unknown`` only escalates to Tier 3.
2. **No I/O, no DB, no network, no files, no model inference.** Pure arithmetic over values the
   caller already measured.
3. **Cheap.** These run per frame. Everything except :func:`overlay` (which is only reached on a
   Tier-1 abstain, and downsamples first) is arithmetic on numbers ``capture_monitor`` already
   computes for freeze detection.
4. **The caller knows more than we do.** The matched node, whether it is a media surface and
   whether playback was ever started are passed in — never re-detected from the picture.

Thresholds: every one is a module constant with its provenance. ``TAKEN`` means the value already
exists in the codebase and is cited; ``NEW`` means it is a first guess here and **needs tuning
against real captures**. :class:`Thresholds` bundles them so a caller can tune a whole set without
editing this file, and each function also takes the individual knobs as keyword arguments.

Public API::

    loaded(changed_pct, *, stable_pct=None, frames=None, thresholds=None)
        -> 'yes' | 'no' | 'unknown'

    overlay(frame_bgr, *, focus_box=None, dim_ratio=None, work_width=None, thresholds=None)
        -> 'none' | 'popup' | 'tooltip' | 'keyboard' | 'notification' | 'unknown'

    playback(is_media, changed_pct, *, audio_silence_seconds=None, window_seconds=60.0,
             playback_started=None, thresholds=None)
        -> 'playing' | 'paused' | 'stopped' | 'not_applicable' | 'unknown'

    error(tokens, *, keywords=None, min_conf=None, thresholds=None)
        -> 'none' | 'visible' | 'unknown'

    screen_state(frame_bgr=None, *, is_media=None, changed_pct=None, tokens=None, ...)
        -> {'loaded': ..., 'overlay': ..., 'playback': ..., 'error': ...}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# --------------------------------------------------------------------------- #
# loaded                                                                         #
# --------------------------------------------------------------------------- #
# A frame is "not moving" when fewer than this % of pixels differ from its predecessor — the
# exact rule backend_host/scripts/detector.py applies per pair (its FREEZE_THRESHOLD = 0.8).
# A UI that has finished drawing stops changing, so the same number doubles as the convergence
# floor here. TAKEN.
LOADED_STABLE_PCT = 0.8

# Consecutive below-floor frames required before we call a screen loaded. At the 5 fps capture
# rate this is ~0.6 s of stillness, which is short enough for navigation waits and long enough to
# ride out a dropped frame. NEW — needs tuning against real captures: on a stb3 a settings page
# takes noticeably longer than a home-screen re-render.
LOADED_CONVERGED_FRAMES = 3

# A converged but black frame is a device that is not showing anything, not a loaded UI. Same
# grey-level gates image_helpers.classify_special_state uses for 'blackscreen'
# (FP_BLACK_MEAN_MAX / FP_BLACK_STD_MAX). TAKEN.
LOADED_BLACK_MEAN_MAX = 25.0
LOADED_BLACK_STD_MAX = 12.0

# --------------------------------------------------------------------------- #
# overlay                                                                        #
# --------------------------------------------------------------------------- #
# A "raised plate" is a region above OVERLAY_PLATE_GRAY_MIN; the modal test then requires the
# surround to be materially DARKER than the plate. Grey level, minimum width / height / maximum
# area, centre window and the dim ratio are the constants of
# features/avq/backend_host/localize/auto_build_mcp_live.py::_dialog_plate, re-declared here
# because shared/ must not import from features/ (the dependency runs the other way). TAKEN.
OVERLAY_PLATE_GRAY_MIN = 40        # cv2.threshold level of _dialog_plate
OVERLAY_PLATE_MIN_W = 0.25         # plate must be >= this fraction of frame width
OVERLAY_PLATE_MIN_H = 0.15         # … and >= this fraction of frame height
OVERLAY_PLATE_MAX_AREA = 0.80      # … and <= this fraction of the frame (rejects full-screen UI)
OVERLAY_PLATE_CENTER_X = (0.30, 0.70)   # a modal's centre must sit in this x window
OVERLAY_PLATE_CENTER_Y = (0.20, 0.85)
OVERLAY_DIM_RATIO = 0.55           # DIALOG_DIM_RATIO: surround < 0.55 * plate => modal

# Inside this band around OVERLAY_DIM_RATIO the dimming is inconclusive (a light page behind a
# light panel, a screenshot of a dialog, compression noise). We answer 'unknown' instead of
# guessing either way. NEW — needs tuning; 0.10 grey-ratio is a first guess.
OVERLAY_DIM_UNKNOWN_BAND = 0.10

# An on-screen keyboard sits flush against the bottom edge and is wide. NEW — needs tuning
# against real captures (measured on a TV remote keyboard and a Gboard overlay would be ideal).
OVERLAY_KEYBOARD_BOTTOM_FRAC = 0.02
OVERLAY_KEYBOARD_MIN_W = 0.50

# A real on-screen keyboard has a sharp horizontal top edge (a border, shadow, or solid colour
# change where the keyboard begins). A screensaver / photo that happens to be bright across the
# bottom has a soft "top" that is just where the brightness threshold happens to be crossed; the
# rows above and below that crossing are nearly the same. Requiring that contrast rejects those
# false positives. NEW — measured against screensaver (top_diff=2.2) vs the Clash of Clans modal
# with a number pad (top_diff=71.7) and a real TV remote keyboard (top_diff=~30).
OVERLAY_KEYBOARD_TOP_DIFF_MIN = 20.0

# A transient banner/notification hugs a corner: here top-right (Android toast and TV system UI
# both render there). NEW — needs tuning; a bottom-centre toast is deliberately NOT claimed.
OVERLAY_NOTIFICATION_TOP_FRAC = 0.03
OVERLAY_NOTIFICATION_RIGHT_FRAC = 0.02

# A tooltip is a small bright patch that does NOT dim its page. NEW — needs tuning. The area gate
# is deliberately far below OVERLAY_PLATE_MIN_W * OVERLAY_PLATE_MIN_H so a tooltip can never be
# mistaken for a modal, and the contrast gate keeps a dark box from reading as a tooltip.
OVERLAY_TOOLTIP_MAX_AREA = 0.08    # fraction of the frame
OVERLAY_TOOLTIP_CONTRAST_MIN = 20.0  # grey levels the patch outshines its surround by

# Side length the frame is downsampled to before contour work. Overlay is reached only on a Tier-1
# abstain, but it still must not cost a millisecond of full-resolution Canny-level work. NEW.
OVERLAY_WORK_WIDTH = 480

# --------------------------------------------------------------------------- #
# playback                                                                       #
# --------------------------------------------------------------------------- #
# "The picture is moving" is the same test as the freeze detector's: >= FREEZE_THRESHOLD % of
# pixels differ between consecutive frames. TAKEN.
PLAYBACK_MOVING_PCT = 0.8

# Silence over a measurement window, as a fraction of that window, at or above which we call the
# audio silent. AVQ records ``silence_seconds`` per minute (quality_metrics) and derives
# ``audio_availability = 1 - silence_seconds / window_seconds``; 0.10 availability is the mirror
# of 0.90 silence. NEW — needs tuning against real channels (a long silent scene reads as silence).
PLAYBACK_SILENT_FRACTION = 0.90

# --------------------------------------------------------------------------- #
# content                                                                        #
# --------------------------------------------------------------------------- #
# "Is this a moving picture rather than a drawn screen?" — the gate that keeps
# broadcast footage out of the unknown-screen list. It asks the same question as
# the freeze detector and gets its numbers from the same per-frame-pair
# ``changed_pct``, so it costs nothing extra to ask.
#
# The two floors come straight from measurement over 4,507 processed cold frames
# (see features/avq/backend_host/localize/abstain_coverage.py):
#
#   static UI      frame-diff p50 = 0.09 %
#   broadcast slates           0.00 %
#   live TV                    20.11 %
#
# MEASURED ACCURACY on the abstain bucket: 99.0 % of the live-programme run
# reads 'video'; 0.2 % of it reads 'static'.
#
# KNOWN LIMIT — read this before trusting 'static'. Broadcast promo slates are
# genuinely static (0.00 % frame-diff) and are therefore indistinguishable from a
# drawn UI screen by motion alone. content_state() deliberately refuses to guess
# about them: it answers 'video' or 'static', and a promo break lands on
# 'static'. Filtering slates needs a signal this function does not have. Do not
# widen the bands to try — the gap is real, not a threshold that is merely
# mistuned.
CONTENT_MOVING_PCT = 0.8        # >= this fraction changed between pairs -> moving
CONTENT_CLEAR_PCT = 5.0         # >= this -> unambiguously video, well clear of any UI
CONTENT_WINDOW_FRAMES = 3       # consecutive pairs before answering at all

# --------------------------------------------------------------------------- #
# error                                                                          #
# --------------------------------------------------------------------------- #
# Words that mean "something went wrong" on a TV / STB / phone screen. Kept per language because
# the OCR is the device's own language (title_pivot is the layer that normalizes those strings).
# NEW — needs tuning against real error screens; deliberately no stems ('fail') so that
# 'failed' / 'failure' do not fire on an unrelated word.
ERROR_KEYWORDS = (
    'error', 'errors', 'errore', 'erreur', 'fehler', 'fehlgeschlagen',
    'failed', 'failure', 'unable', 'cannot', 'exception', 'crash', 'panic',
)

# Per-word OCR confidence floor, the same one image_helpers._band_tokens applies. TAKEN.
ERROR_MIN_CONF = 50

_NON_WORD = re.compile(r'[^0-9a-z]+')


def _norm(text: Any) -> str:
    """Lowercase, strip everything that is not a letter or digit. Same shape as
    image_helpers._band_tokens' own normalization (it keeps a-z0-9A-Za-z\u00c0-\u00ff)."""
    return _NON_WORD.sub('', str(text or '').lower())


# --------------------------------------------------------------------------- #
# Thresholds                                                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Thresholds:
    """The whole tunable set of this module in one value.

    Pass ``thresholds=Thresholds(...)`` (or a modified copy of :data:`DEFAULT`) to any question to
    retune it at runtime; any single knob may still be overridden per call, which wins over the
    bundled value. Nothing here needs a source edit to tune.
    """

    loaded_stable_pct: float = LOADED_STABLE_PCT
    loaded_converged_frames: int = LOADED_CONVERGED_FRAMES
    loaded_black_mean_max: float = LOADED_BLACK_MEAN_MAX
    loaded_black_std_max: float = LOADED_BLACK_STD_MAX

    overlay_dim_ratio: float = OVERLAY_DIM_RATIO
    overlay_dim_unknown_band: float = OVERLAY_DIM_UNKNOWN_BAND
    overlay_keyboard_bottom_frac: float = OVERLAY_KEYBOARD_BOTTOM_FRAC
    overlay_keyboard_min_w: float = OVERLAY_KEYBOARD_MIN_W
    overlay_keyboard_top_diff_min: float = OVERLAY_KEYBOARD_TOP_DIFF_MIN
    overlay_notification_top_frac: float = OVERLAY_NOTIFICATION_TOP_FRAC
    overlay_notification_right_frac: float = OVERLAY_NOTIFICATION_RIGHT_FRAC
    overlay_tooltip_max_area: float = OVERLAY_TOOLTIP_MAX_AREA
    overlay_tooltip_contrast_min: float = OVERLAY_TOOLTIP_CONTRAST_MIN
    overlay_plate_gray_min: int = OVERLAY_PLATE_GRAY_MIN
    overlay_work_width: int = OVERLAY_WORK_WIDTH

    playback_moving_pct: float = PLAYBACK_MOVING_PCT
    playback_silent_fraction: float = PLAYBACK_SILENT_FRACTION

    content_moving_pct: float = CONTENT_MOVING_PCT
    content_clear_pct: float = CONTENT_CLEAR_PCT
    content_window_frames: int = CONTENT_WINDOW_FRAMES

    error_min_conf: float = ERROR_MIN_CONF
    error_keywords: Tuple[str, ...] = ERROR_KEYWORDS


DEFAULT = Thresholds()


def _pick(override: Any, bundled: Any, default: Any) -> Any:
    """Per-call ``override`` wins, else the ``Thresholds`` attribute, else the module constant."""
    return bundled if override is None else override


def _num(value: Any) -> Optional[float]:
    """A finite float, or None. Booleans are numbers in Python but never a measurement."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


# --------------------------------------------------------------------------- #
# 1. loaded                                                                      #
# --------------------------------------------------------------------------- #
def loaded(changed_pct: Optional[Sequence[Any]],
           *, content: Optional[Dict[str, Any]] = None,
           stable_pct: Optional[float] = None,
           frames: Optional[int] = None,
           thresholds: Optional[Thresholds] = None) -> str:
    """'yes' / 'no' / 'unknown': has the current screen finished drawing?

    ``changed_pct`` is the recent sequence of ``freeze_facts.compare()['changed_pct']`` values,
    oldest first, newest last — the exact numbers freeze detection already produces per frame pair.
    The screen is loaded once the last ``frames`` of them are all at or below ``stable_pct``;
    it is *not* loaded as soon as one of them is above, because a screen mid-render flickers.

    'unknown' when: no sequence is supplied, fewer than ``frames`` usable values are in it (the
    window has not filled yet — this is the common case right after a screen change), or a value
    in the window is missing or non-numeric.

    ``content`` is optional: when it carries ``brightness`` / ``contrast`` (``freeze_facts
    .content()``) a converged-but-black frame answers 'no' instead of 'yes' — a device that is
    showing nothing has not loaded a UI. Absent or incomplete content is simply not used.
    """
    t = thresholds or DEFAULT
    floor = float(_pick(stable_pct, t.loaded_stable_pct, LOADED_STABLE_PCT))
    window = int(_pick(frames, t.loaded_converged_frames, LOADED_CONVERGED_FRAMES))
    if window < 1:
        return 'unknown'
    if not isinstance(changed_pct, (list, tuple)):
        return 'unknown'                      # no measured change -> no evidence either way
    values = [_num(v) for v in changed_pct]
    if len(values) < window:
        return 'unknown'                      # window not full yet
    recent = values[-window:]
    if any(v is None for v in recent):
        return 'unknown'                      # a gap inside the window: refuse to bridge it
    if any(v > floor for v in recent):
        return 'no'                           # still moving -> still drawing
    if content and _num(content.get('brightness')) is not None:
        brightness = float(content['brightness'])
        contrast = _num(content.get('contrast'))
        black_mean = float(_pick(None, t.loaded_black_mean_max, LOADED_BLACK_MEAN_MAX))
        black_std = float(_pick(None, t.loaded_black_std_max, LOADED_BLACK_STD_MAX))
        if brightness < black_mean and (contrast is None or contrast < black_std):
            return 'no'                       # converged, but black: nothing is loaded
    return 'yes'


# --------------------------------------------------------------------------- #
# 1b. content                                                                     #
# --------------------------------------------------------------------------- #
def content_state(changed_pct: Optional[Sequence[Any]],
                  *, moving_pct: Optional[float] = None,
                  clear_pct: Optional[float] = None,
                  window: Optional[int] = None,
                  thresholds: Optional[Thresholds] = None) -> str:
    """'video' / 'static' / 'unknown': is this a moving picture rather than a screen?

    This is the gate that keeps broadcast footage out of the unknown-screen list. A device showing
    live TV abstains from fingerprinting constantly, but it is not showing an unrecognised UI — it
    is showing content, and the operator has nothing to name. Splitting the two is what turns 15
    genuinely-unknown screens into 4.

    ``changed_pct`` is the recent sequence of ``freeze_facts.compare()['changed_pct']`` values,
    oldest first — the same numbers :func:`loaded` consumes. Nothing extra is computed to ask this.

    Answers 'video' when the window's median is at or above ``clear_pct``: live programme footage
    sits an order of magnitude clear of any drawn screen, so the band between ``moving_pct`` and
    ``clear_pct`` is left as 'unknown' rather than guessed. Answers 'static' when the median is at
    or below ``moving_pct``.

    'unknown' when: no sequence is supplied, the window has not filled, a value is missing or
    non-numeric, or the median lands in the band between the two floors.

    Read the KNOWN LIMIT above the constants before using 'static' to conclude anything. Static
    broadcast promo slates land here too, and this function cannot tell them from a drawn screen.
    """
    t = thresholds or DEFAULT
    moving = float(_pick(moving_pct, t.content_moving_pct, CONTENT_MOVING_PCT))
    clear = float(_pick(clear_pct, t.content_clear_pct, CONTENT_CLEAR_PCT))
    span = int(_pick(window, t.content_window_frames, CONTENT_WINDOW_FRAMES))
    if span < 1:
        return 'unknown'
    if not isinstance(changed_pct, (list, tuple)):
        return 'unknown'
    values = [_num(v) for v in changed_pct]
    if len(values) < span:
        return 'unknown'
    recent = values[-span:]
    if any(v is None for v in recent):
        return 'unknown'                      # a gap inside the window: refuse to bridge it
    ordered = sorted(recent)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2.0)
    if median >= clear:
        return 'video'
    if median <= moving:
        return 'static'
    return 'unknown'                          # in the ambiguous band: abstain rather than guess


# --------------------------------------------------------------------------- #
# 2. overlay                                                                     #
# --------------------------------------------------------------------------- #
def _regions(gray: np.ndarray, plate_gray_min: int) -> Tuple[List[Tuple[int, int, int, int]],
                                                                List[Tuple[int, int, int, int]]]:
    """Raised regions of the frame, split into (big plates, small patches), biggest first.

    Two passes, because one absolute threshold cannot segment every frame:

    * **big plates** — the ``_dialog_plate`` mask, at the fixed ``plate_gray_min``. This is the
      modal path and it only means anything while the page is DIMMED, i.e. still below that level;
      a lit page floods the mask into one full-frame region, which the size gates reject.
    * **small patches** — thresholded relative to the frame's OWN median
      (``median + tooltip_contrast_min``). This is what finds a tooltip or a callout on an
      ordinary, evenly lit UI page, where the absolute mask sees nothing.

    RETR_LIST rather than RETR_EXTERNAL: a dimmed page that is still lit above the threshold makes
    the plate a HOLE in the page contour, and only RETR_EXTERNAL would miss it entirely. That is the
    one deliberate deviation from ``_dialog_plate``; the size gates are unchanged.
    """
    h, w = gray.shape[:2]
    _, mask = cv2.threshold(gray, plate_gray_min, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    big = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area_frac = (bw * bh) / float(w * h)
        if area_frac <= OVERLAY_TOOLTIP_MAX_AREA:
            continue
        if bw < OVERLAY_PLATE_MIN_W * w or bh < OVERLAY_PLATE_MIN_H * h:
            continue
        if area_frac > OVERLAY_PLATE_MAX_AREA:
            continue
        big.append((x, y, bw, bh))
    big.sort(key=lambda b: b[2] * b[3], reverse=True)

    small = []
    rel_level = float(np.median(gray)) + OVERLAY_TOOLTIP_CONTRAST_MIN
    _, rel_mask = cv2.threshold(gray, rel_level, 255, cv2.THRESH_BINARY)
    rel_contours, _ = cv2.findContours(rel_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in rel_contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if (bw * bh) / float(w * h) <= OVERLAY_TOOLTIP_MAX_AREA:
            small.append((x, y, bw, bh))
    small.sort(key=lambda b: b[2] * b[3], reverse=True)
    return big, small


def _surround_mean(gray: np.ndarray, box: Tuple[int, int, int, int]) -> Tuple[float, float]:
    """Mean grey inside the plate and outside it (the plate pixels are excluded, not zeroed —
    zeroing would bias the surround low and fake the dimming)."""
    x, y, bw, bh = box
    inside = float(gray[y:y + bh, x:x + bw].mean()) if bw and bh else 0.0
    h, w = gray.shape[:2]
    mask = np.ones((h, w), bool)
    mask[y:y + bh, x:x + bw] = False
    outside = float(gray[mask].mean()) if mask.any() else 0.0
    return inside, outside


def _top_edge_diff(gray: np.ndarray, box: Tuple[int, int, int, int]) -> float:
    """Brightness contrast at the plate's top edge.

    Mean of a 2-row strip just above the plate minus mean of a 2-row strip just below the plate's
    top, absolute value. A real overlay (keyboard, modal banner) has a sharp horizontal top edge
    — a border, shadow or solid colour change — so the two strips differ by tens of grey levels. A
    screensaver / photo that happens to be bright across the bottom has a soft "top" that is just
    where the brightness threshold happens to cross; the two strips are nearly identical.

    Returns 0.0 when the plate is too close to the frame top to read a strip above (caller
    treats 0 as "no measurable edge" and refuses the keyboard verdict, the same outcome as a
    soft top).
    """
    h, _w = gray.shape[:2]
    x, y, bw, _bh = box
    if y < 4 or y + 4 > h or bw < 4:
        return 0.0
    above = float(gray[y - 3:y - 1, x:x + bw].mean())
    below = float(gray[y + 1:y + 3, x:x + bw].mean())
    return abs(above - below)


def _classify_plate(gray: np.ndarray, box: Tuple[int, int, int, int], inside: float, outside: float,
                    th: Thresholds) -> str:
    h, w = gray.shape[:2]
    x, y, bw, bh = box
    dim_ratio = (outside / inside) if inside > 0 else 1.0

    # Edge-anchored transient surfaces first: a keyboard and a banner are geometrically distinct
    # from a centred modal and are not dimming-gated (neither dims the page in practice).
    if (y + bh) >= (1.0 - th.overlay_keyboard_bottom_frac) * h and bw >= th.overlay_keyboard_min_w * w:
        # Geometric match (wide + flush with the bottom edge) is not enough on its own: a
        # screensaver or photo that is bright across the bottom produces the same contour. A real
        # keyboard has a sharp top edge — a border, shadow or solid colour change — that
        # separates the keys from the page above. Require that contrast so the dark / soft-top
        # case falls through to the modal / tooltip checks.
        if _top_edge_diff(gray, box) >= th.overlay_keyboard_top_diff_min:
            return 'keyboard'
    if (y <= th.overlay_notification_top_frac * h
            and (x + bw) >= (1.0 - th.overlay_notification_right_frac) * w):
        return 'notification'

    # A modal: centred, and the page behind it is materially darker than the plate. A ratio
    # inside the unknown band is a real measurement that does not settle the question.
    cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
    centred = (OVERLAY_PLATE_CENTER_X[0] <= cx <= OVERLAY_PLATE_CENTER_X[1]
               and OVERLAY_PLATE_CENTER_Y[0] <= cy <= OVERLAY_PLATE_CENTER_Y[1])
    if centred:
        if abs(dim_ratio - th.overlay_dim_ratio) <= th.overlay_dim_unknown_band:
            return 'unknown'
        if dim_ratio < th.overlay_dim_ratio:
            return 'popup'
    return 'ambiguous'


def overlay(frame_bgr: Optional[np.ndarray], *, focus_box: Optional[Sequence[float]] = None,
            dim_ratio: Optional[float] = None, work_width: Optional[int] = None,
            thresholds: Optional[Thresholds] = None) -> str:
    """What, if anything, is drawn on top of the page.

    'popup'        a centred raised plate over a DIMMED page (the ``_dialog_plate`` rule).
    'tooltip'      a small bright patch that does not dim the page.
    'keyboard'     a wide plate flush with the bottom edge (on-screen keyboard).
    'notification' a band hugging the top-right corner (system banner / toast).
    'none'         the frame was inspected and carries no such surface.
    'unknown'      no frame was supplied, or a candidate was found that the dimming test could
                   not settle, or a candidate matches no known surface.

    ``focus_box`` (x, y, w, h as fractions of the frame, the box ``_focus_signature`` already
    finds) is accepted for callers that have it; it is not required and is currently only used to
    document the intent — the classification itself needs no reference box.
    ``dim_ratio`` lets a caller pass a measured surround/plate ratio instead of having us measure
    it. Frames are downsampled to ``work_width`` first, so the cost is bounded regardless of
    capture resolution.
    """
    t = thresholds or DEFAULT
    width = int(_pick(work_width, t.overlay_work_width, OVERLAY_WORK_WIDTH))
    plate_gray_min = int(_pick(None, t.overlay_plate_gray_min, OVERLAY_PLATE_GRAY_MIN))
    if dim_ratio is not None:
        # Caller-supplied measurement: apply the same gate, nothing to inspect.
        ratio = _num(dim_ratio)
        if ratio is None:
            return 'unknown'
        if abs(ratio - t.overlay_dim_ratio) <= t.overlay_dim_unknown_band:
            return 'unknown'
        return 'popup' if ratio < t.overlay_dim_ratio else 'none'
    if not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0 or frame_bgr.ndim not in (2, 3):
        return 'unknown'                      # nothing to look at -> honest abstain
    h0, w0 = frame_bgr.shape[:2]
    if width > 0 and w0 > width:
        scale = width / float(w0)
        small = cv2.resize(frame_bgr, (width, max(1, int(round(h0 * scale)))), interpolation=cv2.INTER_AREA)
    else:
        small = frame_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    if gray.size == 0:
        return 'unknown'
    big, small = _regions(gray, plate_gray_min)
    for box in big:
        inside, outside = _surround_mean(gray, box)
        verdict = _classify_plate(gray, box, inside, outside, t)
        if verdict != 'ambiguous':
            return verdict
    # No modal: a small patch that is materially brighter than its page, without dimming it, is a
    # tooltip. Looked at only after the plates, so a tooltip can never shadow a real modal.
    for box in small:
        inside, outside = _surround_mean(gray, box)
        if (inside - outside) >= t.overlay_tooltip_contrast_min:
            return 'tooltip'
    if big:
        return 'unknown'                      # raised plates, none of them explained
    # No plate and no patch. That is a clean 'none' only if the frame was actually legible enough
    # for the scan to mean something; a flat black frame was never inspected for an overlay.
    if float(gray.std()) <= t.overlay_tooltip_contrast_min:
        return 'unknown'
    return 'none'


# --------------------------------------------------------------------------- #
# 3. playback                                                                    #
# --------------------------------------------------------------------------- #
def playback(is_media: Optional[bool], changed_pct: Optional[Any] = None, *,
             audio_silence_seconds: Optional[Any] = None, window_seconds: Any = 60.0,
             playback_started: Optional[bool] = None,
             thresholds: Optional[Thresholds] = None) -> str:
    """'playing' / 'paused' / 'stopped' / 'not_applicable' / 'unknown'.

    ``is_media`` is the caller's knowledge that the matched node is a media surface — it is
    passed in, never re-detected. ``not_applicable`` for anything else.

    On a media surface the picture decides first: ``changed_pct`` at or above the freeze detector's
    own moving threshold means video is running, whatever the audio is doing (a muted channel is
    still playing). A still picture then needs the audio: silence over the measurement window is a
    paused player, a picture that is still while the sound is not is neither state we can name, and
    answers 'unknown' — that combination is a freeze or a different surface, not a playback state.

    ``audio_silence_seconds`` / ``window_seconds`` consume AVQ ``quality_metrics.silence_seconds``
    over that row's window; no audio work is done here. ``playback_started`` is the caller's fact
    that this run ever began playback — 'stopped' is only claimed on that evidence.

    'unknown' when: ``is_media`` is not a known bool, or the surface is a media surface and no
    ``changed_pct`` was supplied, or the picture is still and no audio state is available.
    """
    t = thresholds or DEFAULT
    if is_media is True:
        moving_pct = float(_pick(None, t.playback_moving_pct, PLAYBACK_MOVING_PCT))
        silent_frac = float(_pick(None, t.playback_silent_fraction, PLAYBACK_SILENT_FRACTION))
        change = _num(changed_pct)
        silence = _num(audio_silence_seconds)
        window = _num(window_seconds)
        if change is None:
            return 'unknown'                  # no frame difference -> no evidence either way
        if change >= moving_pct:
            return 'playing'
        if playback_started is False:
            return 'stopped'                  # caller knows playback never began
        if silence is None or window is None or window <= 0:
            return 'unknown'                  # still picture, no audio state to pair with it
        return 'paused' if (silence / window) >= silent_frac else 'unknown'
    if is_media is False:
        return 'not_applicable'
    return 'unknown'


# --------------------------------------------------------------------------- #
# 4. error                                                                       #
# --------------------------------------------------------------------------- #
def error(tokens: Optional[Sequence[Any]], *, keywords: Optional[Sequence[str]] = None,
          min_conf: Optional[float] = None, thresholds: Optional[Thresholds] = None) -> str:
    """'none' / 'visible' / 'unknown' from OCR tokens.

    ``tokens`` is what ``image_helpers._band_tokens`` returns: a list of
    ``{'token', 'x', 'y', 'w', 'h', 'size'}`` dicts, or a list of plain strings. Words whose
    ``conf`` is below the ``_band_tokens`` floor are ignored (that floor is reapplied here for
    callers that pass raw TSV rows), and a token matches when it CONTAINS a keyword, so 'errors'
    and 'Error:' both hit 'error'.

    'unknown' — and this is the point of the question — when there is nothing readable to judge:
    no tokens supplied, an empty list, or a list where every token was dropped by the confidence
    floor. An empty screen is not evidence of a healthy screen. Only a list that yielded usable
    tokens and found no keyword answers 'none'.
    """
    t = thresholds or DEFAULT
    floor = float(_pick(min_conf, t.error_min_conf, ERROR_MIN_CONF))
    words = tuple(_norm(k) for k in (_pick(keywords, t.error_keywords, ERROR_KEYWORDS) or ()))
    words = tuple(w for w in words if w)
    if not isinstance(tokens, (list, tuple)):
        return 'unknown'
    usable = 0
    for item in tokens:
        if isinstance(item, dict):
            conf = _num(item.get('conf'))
            if conf is not None and conf < floor:
                continue
            text = _norm(item.get('token'))
        else:
            text = _norm(item)
        if len(text) < 2:
            continue
        usable += 1
        if any(w in text for w in words):
            return 'visible'
    return 'none' if usable else 'unknown'


# --------------------------------------------------------------------------- #
# all four                                                                       #
# --------------------------------------------------------------------------- #
def screen_state(frame_bgr: Optional[np.ndarray] = None, *, is_media: Optional[bool] = None,
                 changed_pct: Optional[Any] = None, tokens: Optional[Sequence[Any]] = None,
                 content: Optional[Dict[str, Any]] = None,
                 audio_silence_seconds: Optional[Any] = None, window_seconds: Any = 60.0,
                 playback_started: Optional[bool] = None,
                 thresholds: Optional[Thresholds] = None) -> Dict[str, str]:
    """The four answers in one dict, each one abstaining on its own. Each key is independent:
    a screen can be loaded with a popup over it and no error on it."""
    return {
        'loaded': loaded(changed_pct, content=content, thresholds=thresholds),
        'overlay': overlay(frame_bgr, thresholds=thresholds),
        'playback': playback(is_media, changed_pct, audio_silence_seconds=audio_silence_seconds,
                             window_seconds=window_seconds, playback_started=playback_started,
                             thresholds=thresholds),
        'error': error(tokens, thresholds=thresholds),
    }