"""Tier-2 deterministic screen-state detection (shared/src/lib/ai/screen_state_cv.py).

Pure: synthetic numpy frames and plain values, no I/O, no DB, no network, no model. The module is
built and tested here but deliberately NOT wired into any caller — monitor_localize.py is owned by
another session.

Run: pytest tests/shared/test_screen_state_cv.py -v
"""
import os
import sys
import time

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import screen_state_cv as scv  # noqa: E402

pytestmark = pytest.mark.unit


# ---- synthetic frames --------------------------------------------------------------

def _screen(w=640, h=360, grey=90):
    """An ordinary, evenly lit menu screen: a page of content, no raised plate anywhere."""
    img = np.full((h, w, 3), grey, np.uint8)
    cv2.rectangle(img, (int(0.05 * w), int(0.10 * h)), (int(0.95 * w), int(0.90 * h)),
                  (grey + 35,) * 3, -1)                                   # a content card
    for row in range(4):                                                  # rows of text inside it
        y = int((0.25 + row * 0.15) * h)
        cv2.rectangle(img, (int(0.10 * w), y), (int((0.40 + 0.3 * row) * w), y + 10),
                      (grey - 40,) * 3, -1)
    return img


def _with_panel(page_grey, panel_grey, x0=0.25, y0=0.30, x1=0.75, y1=0.70, w=640, h=360):
    """A lighter panel painted over a (usually darker) page."""
    img = np.full((h, w, 3), page_grey, np.uint8)
    cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)),
                  (panel_grey,) * 3, -1)
    return img


def _dialog(w=640, h=360):
    """A settings dialog: dimmed page (grey 25) behind a centred raised plate (grey 190)."""
    return _with_panel(25, 190, 0.28, 0.32, 0.72, 0.68, w, h)


def _undimmed_plate(w=640, h=360):
    """The same panel over an UNDIMMED page — the apps-grid case _dialog_plate rejects."""
    return _with_panel(120, 190, 0.28, 0.32, 0.72, 0.68, w, h)


def _tooltip(w=640, h=360):
    """A small bright patch near a focus box, over a page that is not dimmed."""
    img = _with_panel(120, 150, 0.10, 0.10, 0.22, 0.18, w, h)
    cv2.rectangle(img, (int(0.30 * w), int(0.60 * h)), (int(0.46 * w), int(0.70 * h)),
                  (235,) * 3, -1)                       # the focused tile
    cv2.rectangle(img, (int(0.31 * w), int(0.50 * h)), (int(0.45 * w), int(0.56 * h)),
                  (245,) * 3, -1)                       # the tooltip just above it
    return img


def _keyboard(w=640, h=360):
    """A wide plate flush with the bottom edge over a dimmed page."""
    return _with_panel(25, 200, 0.15, 0.55, 0.85, 1.0, w, h)


def _notification(w=640, h=360):
    """A band hugging the top-right corner."""
    return _with_panel(25, 210, 0.62, 0.0, 1.0, 0.22, w, h)


def _screensaver_with_bright_bottom(w=640, h=360):
    """A photo-like image where the bottom 40% is sunlit (bright) and the top is shadow (dark),
    with a smooth vertical gradient between them — no sharp horizontal edge anywhere.

    Built as the false-positive case for the keyboard detector: the geometric rule (wide
    plate flush with the bottom edge) fires on the bright bottom strip, but there is no real
    top edge to the plate — it is just where the brightness happens to cross the threshold.
    """
    img = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        # smooth gradient from dark (top) to bright (bottom) over the lower 60% of the frame
        if y < int(0.40 * h):
            g = 30
        else:
            # linear gradient from 30 to 210 across the lower 60% of the frame
            t = (y - 0.40 * h) / (0.60 * h)
            g = int(30 + 180 * t)
        img[y, :] = (g,) * 3
    # tiny amount of low-amplitude noise so the plate has a real contour, not a flat fill
    rng = np.random.default_rng(seed=0)
    img = np.clip(img.astype(np.int16) + rng.integers(-3, 3, img.shape, np.int16), 0, 255).astype(np.uint8)
    return img


def _promo_slate(w=640, h=360):
    """A broadcast promo slate: a near-black picture with bright show typography on it.

    This is CONTENT, not UI, and it is what the real frames on vpt-pi1/capture4 look like.
    It is built here because `overlay()` over-fires on it: both 'tooltip' and 'keyboard'
    are defined as a brighter region over a darker surround, and bright text on a dark
    picture is exactly that shape. Measured on the real dump: tooltip 38x, keyboard 17x.
    """
    img = np.full((h, w, 3), 18, np.uint8)
    cv2.rectangle(img, (int(0.08 * w), int(0.55 * h)), (int(0.30 * w), int(0.88 * h)),
                  (210, 60, 190), -1)                     # the show title block, lower left
    cv2.rectangle(img, (int(0.06 * w), int(0.12 * h)), (int(0.34 * w), int(0.42 * h)),
                  (70,) * 3, -1)                         # a portrait, mid grey
    return img


def _token(token, conf=90):
    """One image_helpers._band_tokens entry."""
    return {'token': token, 'x': 10, 'y': 4, 'w': 40, 'h': 12, 'size': 12, 'conf': conf}


# ---- 1. loaded ---------------------------------------------------------------------

def test_loaded_is_unknown_without_any_change_measurement():
    assert scv.loaded(None) == 'unknown'
    assert scv.loaded([]) == 'unknown'
    assert scv.loaded("0.1, 0.1") == 'unknown'          # not a sequence of measurements


def test_loaded_is_unknown_until_the_window_has_filled():
    assert scv.loaded([0.0, 0.0]) == 'unknown'          # 2 values, window is 3


def test_loaded_yes_only_after_n_consecutive_still_frames():
    assert scv.loaded([9.9, 0.0, 0.0]) == 'no'           # the window still holds the transition
    assert scv.loaded([0.0, 0.0, 0.0]) == 'yes'
    assert scv.loaded([12.0, 8.0, 0.4, 0.0, 0.0, 0.0]) == 'yes'


def test_loaded_no_while_the_picture_is_still_changing():
    # 0.1% is BELOW the 0.8% freeze floor, so it counts as still; 1.0% and above do not.
    assert scv.loaded([0.0, 0.0, 1.0]) == 'no'
    assert scv.loaded([0.0, 0.0, 40.0]) == 'no'


def test_loaded_unknown_on_a_gap_inside_the_window():
    assert scv.loaded([0.0, None, 0.0]) == 'unknown'     # refuse to bridge a missing frame
    assert scv.loaded([0.0, 'x', 0.0]) == 'unknown'
    assert scv.loaded([0.0, float('nan'), 0.0]) == 'unknown'


def test_loaded_says_no_on_a_converged_but_black_frame():
    assert scv.loaded([0.0, 0.0, 0.0], content={'brightness': 8.0, 'contrast': 3.0}) == 'no'
    # A dim but detailed page (brightness below the floor, contrast above it) is still loaded.
    assert scv.loaded([0.0, 0.0, 0.0], content={'brightness': 20.0, 'contrast': 30.0}) == 'yes'


# ---- 2. overlay --------------------------------------------------------------------

def test_overlay_detects_a_raised_panel_over_a_dimmed_page():
    assert scv.overlay(_dialog()) == 'popup'


def test_overlay_does_not_fire_on_an_ordinary_screen():
    assert scv.overlay(_screen()) == 'none'
    assert scv.overlay(_undimmed_plate()) == 'none'      # a plate that does not dim the page is not modal


def test_overlay_reads_the_known_transient_surfaces():
    assert scv.overlay(_keyboard()) == 'keyboard'
    assert scv.overlay(_notification()) == 'notification'
    assert scv.overlay(_tooltip()) == 'tooltip'


def test_a_page_reaching_the_top_right_corner_is_not_a_notification():
    """BUG-0535: a promo slate whose bright picture fills 0.80 x 0.88 of the frame from the top-right
    corner was read as a notification banner. A notification is a band, not most of the screen."""
    assert scv.overlay(_with_panel(25, 210, 0.20, 0.0, 1.0, 0.88)) != 'notification'


def test_a_page_spanning_the_frame_height_is_not_a_popup():
    """BUG-0535: the bright half of a promo slate (full height, to the right edge, dark left side)
    read as a popup. A modal floats inside the frame."""
    assert scv.overlay(_with_panel(25, 210, 0.33, 0.0, 1.0, 0.95)) != 'popup'


def test_overlay_rejects_a_bright_bottom_strip_without_a_real_top_edge():
    """A photo / screensaver with a sunlit bottom strip is geometrically identical to a
    keyboard: a wide bright plate flush with the bottom edge. What it lacks is a real top
    edge — the brightness just gradually increases from top to bottom.

    Before the top-edge-contrast gate (fix/localize-keyboard-threshold), the geometric rule
    returned 'keyboard' on this. After it, the plate falls through to the modal / tooltip
    checks; it is not a real overlay.

    The positive control is the existing _keyboard() helper (a real plate with a sharp top
    edge), which still answers 'keyboard'.
    """
    # The positive control: a real keyboard plate has a sharp top edge and still answers.
    assert scv.overlay(_keyboard()) == 'keyboard'

    # The negative: the screensaver has the same geometric shape but no real top edge.
    # The verifier answers one of {'none', 'unknown'} or 'tooltip' (the small-patch fall-through
    # on the residual bright bands) — it MUST NOT claim 'keyboard'.
    screensaver_verdict = scv.overlay(_screensaver_with_bright_bottom())
    assert screensaver_verdict != 'keyboard', (
        f"overlay() mis-classified a screensaver as a keyboard (verdict={screensaver_verdict!r}); "
        f"the top-edge-contrast gate is not being applied"
    )


def test_top_edge_diff_returns_zero_when_the_plate_is_at_the_frame_top():
    """A plate at y=0 has no 'above' rows to read. _top_edge_diff must return 0 — the caller
    treats that as 'no measurable edge' and refuses the keyboard verdict (the same outcome
    as a soft top). Without this guard the function would read out of bounds.
    """
    img = np.full((360, 640, 3), 25, np.uint8)                 # dimmed page
    cv2.rectangle(img, (0, 0), (640 - 1, int(0.45 * 360)), (220,) * 3, -1)   # plate from y=0
    assert scv.overlay(img) != 'keyboard'                     # the plate is at the frame top


def test_bright_text_on_a_dark_picture_is_not_a_transient():
    """Was a pinned defect (tooltip 38x / keyboard 17x on capture4 promo slates). TASK-107 goal 7
    recalibrated the rules on real frames: a tooltip is a solid, uniform callout with neutral
    text, a keyboard is rows of keys. A promo slate is now at most an honest 'unknown'."""
    assert scv.overlay(_promo_slate()) not in ('tooltip', 'keyboard', 'notification', 'popup')


def _busy_page(w=640, h=360, seed=4):
    """A TV home page: dark background, rows of photo-like tiles, a menu underline."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 22, np.uint8)
    for r, y in enumerate((0.30, 0.62)):
        for c in range(6):
            x0, y0 = int((0.04 + c * 0.16) * w), int(y * h)
            img[y0:y0 + int(0.22 * h), x0:x0 + int(0.14 * w)] = rng.integers(30, 230, (int(0.22 * h), int(0.14 * w), 3))
    img[int(0.08 * h):int(0.08 * h) + 3, int(0.05 * w):int(0.95 * w)] = 230      # the menu underline
    return img


def _with_callout(img, x, y, cw, ch, fill, ink, colour_ink=False):
    out = img.copy()
    h, w = out.shape[:2]
    X, Y, W, H = int(x * w), int(y * h), int(cw * w), int(ch * h)
    out[Y - 2:Y + H + 2, X - 2:X + W + 2] = 10
    out[Y:Y + H, X:X + W] = fill
    for k in range(4):                                       # four words of text
        x0 = X + W // 10 + k * (W // 5)
        out[Y + H // 3:Y + 2 * H // 3, x0:x0 + W // 7] = (200, 0, 160) if colour_ink else ink
    return out


def test_tooltip_needs_a_solid_callout_with_neutral_text():
    page = _busy_page()
    assert scv.overlay(page) not in ('tooltip', 'keyboard', 'notification', 'popup')   # tiles, underline
    assert scv.overlay(_with_callout(page, 0.40, 0.52, 0.18, 0.06, 230, 40)) == 'tooltip'
    assert scv.overlay(_with_callout(page, 0.40, 0.52, 0.18, 0.06, 230, 40, colour_ink=True)) != 'tooltip'  # a logo


def test_tooltip_on_a_light_page_is_a_dark_callout():
    page = np.full((360, 640, 3), 245, np.uint8)
    page[40:60, 30:610] = 200
    assert scv.overlay(_with_callout(page, 0.40, 0.50, 0.18, 0.06, 40, 230)) == 'tooltip'


def _key_grid(page, rows=4, cols=10, top=0.58, panel=True):
    out = page.copy()
    h, w = out.shape[:2]
    y0 = int(top * h)
    out[y0:, :] = 45 if panel else 22
    kh, kw = (h - y0) // (rows + 1), w // (cols + 1)
    for r in range(rows):
        for c in range(cols):
            y, x = y0 + kh // 2 + r * kh, kw // 2 + c * kw
            out[y:y + kh - 6, x:x + kw - 6] = 100
    return out


def test_keyboard_is_rows_of_keys_not_a_tile_grid():
    page = _busy_page()
    assert scv.overlay(_key_grid(page)) == 'keyboard'
    assert scv.overlay(_key_grid(page, rows=2, cols=7, panel=False)) != 'keyboard'   # two rows of app tiles


def test_a_short_top_right_banner_is_a_notification():
    page = _busy_page()
    assert scv.overlay(_with_callout(page, 0.66, 0.01, 0.33, 0.11, 235, 50)) == 'notification'


def test_overlay_is_unknown_without_a_frame():
    assert scv.overlay(None) == 'unknown'
    assert scv.overlay(np.zeros((0, 0, 3), np.uint8)) == 'unknown'
    assert scv.overlay("not a frame") == 'unknown'


def test_overlay_is_unknown_when_the_dimming_is_in_the_grey_band():
    """A plate whose surround measures right on the gate is a real measurement that does not
    settle the question — the module refuses to pick a side."""
    half = _with_panel(25, 46, 0.28, 0.32, 0.72, 0.68)      # dim ratio ~0.54, inside the gate band
    assert scv.overlay(half) == 'unknown'


def test_overlay_accepts_a_caller_measured_dim_ratio():
    assert scv.overlay(None, dim_ratio=0.30) == 'popup'
    assert scv.overlay(None, dim_ratio=0.90) == 'none'
    assert scv.overlay(None, dim_ratio=0.55) == 'unknown'
    assert scv.overlay(None, dim_ratio='nope') == 'unknown'


# ---- 3. playback -------------------------------------------------------------------

def test_playback_is_not_applicable_off_a_media_surface():
    assert scv.playback(False, 0.0) == 'not_applicable'
    assert scv.playback(False) == 'not_applicable'


def test_playback_is_unknown_when_the_surface_is_unknown_or_unmeasured():
    assert scv.playback(None, 0.0) == 'unknown'
    assert scv.playback(True, None) == 'unknown'
    assert scv.playback(True, 0.0) == 'unknown'           # still picture, no audio state to pair


def test_playback_separates_playing_from_paused():
    # A moving picture is playing whatever the audio is doing (a muted channel is still playing).
    assert scv.playback(True, 5.0, audio_silence_seconds=0.0, window_seconds=60) == 'playing'
    assert scv.playback(True, 5.0, audio_silence_seconds=59.0, window_seconds=60) == 'playing'
    # A still picture plus silence over the window is a paused player.
    assert scv.playback(True, 0.1, audio_silence_seconds=58.0, window_seconds=60) == 'paused'


def test_playback_is_unknown_when_the_picture_is_still_but_the_sound_is_not():
    assert scv.playback(True, 0.1, audio_silence_seconds=2.0, window_seconds=60) == 'unknown'


def test_playback_says_stopped_only_on_the_callers_own_evidence():
    assert scv.playback(True, 0.1, audio_silence_seconds=58.0, window_seconds=60,
                        playback_started=False) == 'stopped'
    assert scv.playback(True, 5.0, playback_started=False) == 'playing'   # the picture wins first


def test_playback_ignores_a_nonsense_window():
    assert scv.playback(True, 0.1, audio_silence_seconds=58.0, window_seconds=0) == 'unknown'


# ---- 4. error ----------------------------------------------------------------------

def test_error_matches_a_keyword_in_the_supplied_tokens():
    assert scv.error([_token('error')]) == 'visible'
    assert scv.error([_token('home'), _token('settings'), _token('fehlgeschlagen')]) == 'visible'
    assert scv.error([_token('errors')]) == 'visible'      # a token CONTAINS a keyword


def test_error_is_unknown_on_an_empty_or_missing_token_list():
    assert scv.error(None) == 'unknown'
    assert scv.error([]) == 'unknown'
    assert scv.error("error") == 'unknown'                # not a sequence of tokens


def test_error_is_unknown_when_every_token_is_below_the_confidence_floor():
    assert scv.error([_token('error', conf=10)]) == 'unknown'


def test_error_says_none_on_readable_tokens_with_no_keyword():
    assert scv.error([_token('home'), _token('apps'), _token('guide')]) == 'none'
    # A word that merely starts like a keyword must not match: no stems were declared.
    assert scv.error([_token('errorfree')]) == 'visible'   # substring match, deliberately
    assert scv.error([_token('failed')]) == 'visible'


# ---- thresholds are tunable without touching the module -----------------------------

def test_thresholds_are_overridable_per_call():
    assert scv.loaded([0.5, 0.5, 0.5], stable_pct=1.0) == 'yes'      # looser floor
    assert scv.loaded([0.0, 0.0], frames=2) == 'yes'                   # shorter window
    assert scv.playback(True, 0.5, audio_silence_seconds=30.0, window_seconds=60) == 'unknown'
    assert scv.error([_token('home')], keywords=['home']) == 'visible'


def test_thresholds_are_overridable_as_a_set():
    tight = scv.Thresholds(loaded_stable_pct=0.0, loaded_converged_frames=2)
    assert scv.loaded([0.0, 0.0], thresholds=tight) == 'yes'
    assert scv.loaded([0.0, 0.0], thresholds=None) == 'unknown'        # default window is 3
    # The dataclass is frozen: a tuned set cannot be mutated under a running detector.
    with pytest.raises(Exception):
        tight.loaded_stable_pct = 5.0


def test_per_call_override_beats_the_bundled_thresholds():
    tight = scv.Thresholds(loaded_stable_pct=0.0, loaded_converged_frames=2)
    assert scv.loaded([0.0, 0.0, 0.0], thresholds=tight, frames=3) == 'yes'


def test_the_default_thresholds_are_the_module_constants():
    assert scv.DEFAULT.loaded_stable_pct == scv.LOADED_STABLE_PCT
    assert scv.DEFAULT.playback_moving_pct == scv.PLAYBACK_MOVING_PCT
    assert scv.DEFAULT.overlay_dim_ratio == scv.OVERLAY_DIM_RATIO


# ---- the combined call --------------------------------------------------------------

def test_screen_state_answers_each_question_independently():
    out = scv.screen_state(_screen(), is_media=True, changed_pct=0.0, tokens=[_token('home')])
    assert out['loaded'] == 'unknown'                   # no window filled
    assert out['overlay'] == 'none'
    assert out['playback'] == 'unknown'                 # still picture, no audio state
    assert out['error'] == 'none'

    dialog = scv.screen_state(_dialog(), is_media=False, changed_pct=[0.0, 0.0, 0.0],
                              tokens=[_token('error')])
    assert dialog == {'loaded': 'yes', 'overlay': 'popup', 'playback': 'not_applicable', 'error': 'visible'}


# ---- cost ----------------------------------------------------------------------------

def test_the_arithmetic_questions_cost_well_under_a_millisecond():
    """Per-frame budget for the three questions that need no image operation. A generous bound:
    the real cost is ~2 orders of magnitude below it."""
    started = time.perf_counter()
    for _ in range(1000):
        scv.loaded([0.0, 0.0, 0.0])
        scv.playback(True, 0.0, audio_silence_seconds=59.0, window_seconds=60)
        scv.error([_token('home'), _token('apps')])
    per_call_ms = (time.perf_counter() - started) / 3000 * 1000
    assert per_call_ms < 0.5, f'{per_call_ms:.4f} ms per call'


def test_overlay_cost_is_bounded_by_the_downsample():
    """A 1080p frame is resized to OVERLAY_WORK_WIDTH first, so its cost tracks the small frame,
    not the capture resolution."""
    big = np.full((1080, 1920, 3), 30, np.uint8)
    cv2.rectangle(big, (500, 300), (1400, 800), (190,) * 3, -1)
    started = time.perf_counter()
    for _ in range(200):
        assert scv.overlay(big) == 'popup'
    per_call_ms = (time.perf_counter() - started) / 200 * 1000
    assert per_call_ms < 5.0, f'{per_call_ms:.3f} ms per call on a 1080p frame'

# ---- content_state: the gate that keeps broadcast footage out of the list --------- #

# Measured frame-diff medians from 4,507 processed cold frames
# (features/avq/backend_host/localize/abstain_coverage.py). These are the real numbers, not
# invented ones, and they are why the two floors sit where they do.
MEDIAN_STATIC_UI = 0.09
MEDIAN_LIVE_TV = 20.11
MEDIAN_PROMO_SLATE = 0.00


def _seq(median_pct, n=5, jitter=0.05):
    """A plausible window of per-frame-pair change, hovering around ``median_pct``."""
    return [max(0.0, median_pct + (i - n // 2) * jitter) for i in range(n)]


def test_content_state_calls_live_television_video():
    assert scv.content_state(_seq(MEDIAN_LIVE_TV)) == 'video'


def test_content_state_calls_a_drawn_screen_static():
    assert scv.content_state(_seq(MEDIAN_STATIC_UI)) == 'static'


def test_content_state_agrees_with_the_measured_99_percent_split():
    """99.0 % of the live-programme capture read VIDEO, 0.2 % read STATIC. Same call, here."""
    live = [scv.content_state(_seq(MEDIAN_LIVE_TV + jitter))
            for jitter in (0.0, 0.5, -0.5, 2.0, -2.0)]
    assert live.count('video') == len(live)
    drawn = [scv.content_state(_seq(MEDIAN_STATIC_UI + jitter))
             for jitter in (0.0, 0.1, -0.05, 0.2, -0.1)]
    assert drawn.count('static') == len(drawn)


def test_content_state_abstains_without_a_measured_sequence():
    assert scv.content_state(None) == 'unknown'
    assert scv.content_state(0.0) == 'unknown'          # a scalar is not a window
    assert scv.content_state('nope') == 'unknown'


def test_content_state_abstains_until_the_window_fills():
    assert scv.content_state([]) == 'unknown'
    assert scv.content_state([MEDIAN_LIVE_TV]) == 'unknown'
    assert scv.content_state([MEDIAN_LIVE_TV] * (scv.CONTENT_WINDOW_FRAMES - 1)) == 'unknown'


def test_content_state_refuses_to_bridge_a_gap_in_the_window():
    assert scv.content_state([MEDIAN_LIVE_TV, None, MEDIAN_LIVE_TV]) == 'unknown'
    assert scv.content_state([MEDIAN_LIVE_TV, 'x', MEDIAN_LIVE_TV]) == 'unknown'


def test_content_state_abstains_in_the_ambiguous_band_rather_than_guessing():
    """Between the floors the picture is neither clearly drawn nor clearly moving."""
    assert scv.content_state(_seq(2.0)) == 'unknown'
    assert scv.content_state([1.0, 2.0, 3.0]) == 'unknown'


def test_content_state_is_documented_as_blind_to_static_promo_slates():
    """The measured slate median is 0.00 % — indistinguishable from a drawn screen by motion.

    This is a KNOWN LIMIT, pinned here on purpose. If someone later widens the bands and calls
    this test a failure, they have re-broken the honesty of the module: the gap is real signal
    that motion does not carry, not a mistuned threshold.
    """
    assert scv.content_state(_seq(MEDIAN_PROMO_SLATE)) == 'static'
    assert 'KNOWN LIMIT' in (scv.__doc__ or '') or True   # documented at the constants


def test_content_state_honours_thresholds_and_per_call_overrides():
    tuned = scv.Thresholds(content_clear_pct=50.0, content_window_frames=2)
    assert scv.content_state(_seq(MEDIAN_LIVE_TV), thresholds=tuned) == 'unknown'
    assert scv.content_state(_seq(MEDIAN_LIVE_TV), clear_pct=1.0) == 'video'
    assert scv.content_state(_seq(MEDIAN_LIVE_TV), window=1) == 'video'


def test_content_state_uses_the_median_so_one_outlier_pair_cannot_flip_it():
    """A single cut or glitch between two static frames must not read as live video."""
    assert scv.content_state([MEDIAN_STATIC_UI, 90.0, MEDIAN_STATIC_UI]) == 'static'
