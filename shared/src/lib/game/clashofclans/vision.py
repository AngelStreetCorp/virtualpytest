"""
Pure pixel reads for the Clash of Clans home village and overlay screens.

Reads apply only to **synthetic, drawn, or already-known-pixels** inputs --
never to real Supercell captures (TASK-81 §81.1 R4). Every threshold is a
named constant with the synthetic measurement pinned in its comment. Each
public function returns ``None`` (not a guess) when the frame is mid-
transition, too dark, or otherwise unreadable (GAME_BOTS §2 rules 2 and 3).

The numeric OCR for the resource bar (``gold``, ``elixir``, ...) is left as
a stub: the runner wires it in later against drawn digit tiles or a real
capture. Until then, the structural pixel reads (collector ready, donation
dot, training queue, clan-capital bell, daily badge, account-warning
banner) are enough to drive the priority chain.

Bound box coordinates target a **1280x720** capture stream (the S21 FE
HDMI path) so the runner can run on synthetic fixtures drawn at the same
size. Adapters for other sizes live with the UI tree, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Named constants: pixel boxes and color ranges, measured on the live
# S21 FE capture path (1280x720 host capture → BGR ndarray).
# ---------------------------------------------------------------------------

# The home resource bar at the top-right of the village: three cups (gold,
# elixir, gems) on a dark-brown strip. The capture has black letterbox at
# top (y<70) and bottom (y>660); the resource bar starts ~y=85 just below
# the letterbox. Pin: columns 1065..1255, rows 80..230. Live.
RESOURCE_BAR_BOX: Tuple[int, int, int, int] = (1065, 80, 1255, 230)

# Bottom-left army readout: the training queue plate. The live capture has
# the action bar near the bottom edge but above the bottom letterbox. The
# training plate (white "Army" tab) lands at rows 605..660, columns
# 80..230. Live.
TRAINING_QUEUE_BOX: Tuple[int, int, int, int] = (80, 605, 230, 660)

# The "i" clan-donation dot in the top action bar. The action bar sits
# above the home village, between the resource bar (right) and the gear
# (top-left). Pin: rows 70..120, columns 240..310 (just right of the gear).
# Live.
DONATION_DOT_BOX: Tuple[int, int, int, int] = (240, 70, 310, 120)

# Clan-capital bell / chest icon (top-right). The bell is just to the
# LEFT of the resource bar (the live capture has them side-by-side at the
# top of the screen). Pin: rows 90..160, columns 950..1040. Live.
CLAN_CAPITAL_BOX: Tuple[int, int, int, int] = (950, 90, 1040, 160)

# Daily-reward star badge — sits in the action bar above the village, to
# the right of the chat-bubble icon and to the left of the troops button.
# The action-bar row is roughly y=80..160. Pin: columns 320..420, rows
# 90..150. Live.
DAILY_BOX: Tuple[int, int, int, int] = (320, 90, 420, 150)

# Account-warning banner region (R5 guard). Pin: a Supercell dialog or red
# strip lands somewhere in the upper third, across nearly the full width.
# Live: same shape as synthetic — 40..1240, 80..380.
ACCOUNT_WARNING_BOX: Tuple[int, int, int, int] = (40, 80, 1240, 380)

# CoC "Anyone there? / Reload game" disconnect dialog. The Supercell
# modal is roughly centre-right of the screen. On the live S21 FE 1280x720
# capture the modal's white text was measured at x in [408..884],
# y in [183..339]. The box covers the modal plus a generous margin so
# a localised dialog variant still trips the detector.
DISCONNECT_DIALOG_BOX: Tuple[int, int, int, int] = (300, 150, 1000, 420)

# §81.1.10: CoC tutorial dialog bubble. The Welcome Chief dialog is a
# light-grey-fill rounded-rect in the centre-left of the screen, with a
# yellow border, a triangular pointer on the left, and dark text inside.
# Box format is ``(x0, y0, x1, y1)`` matching ``vision._box``. Measured
# on the live S21 FE tutorial capture (see the commit message of
# fix/coc-bubble-detection-v2): the bubble body occupies x in
# [210..510], y in [345..430] on the 1280x720 capture; we add a small
# margin so localised dialog variants still trip the detector. The
# runner reads from the vpt-host capture stream which is always
# 1280x720 -- the device screencap is 2340x1080 but it's not what the
# runner sees, the host stream downsamples.
TUTORIAL_BUBBLE_BOX: Tuple[int, int, int, int] = (200, 340, 530, 440)

# Middle-of-village grass patch (used to confirm "home" vs. a modal). The
# central playable canvas runs roughly y=180..650, x=40..1240. Pin:
# columns 250..1050, rows 280..550 (the densest grass region — excludes
# building shadows and the chief's character on the left). Live.
HOME_GRASS_BOX: Tuple[int, int, int, int] = (250, 280, 1050, 550)

# Collector-tile band where the green "ready" tick sits when a mine /
# collector / drill finishes. The collector tiles in the tutorial village
# (gold mine, elixir collector) sit roughly y=240..430. Pin: 90..1200, 240..430.
# Live.
COLLECTOR_BAND_BOX: Tuple[int, int, int, int] = (90, 240, 1200, 430)

# Yellow-amber pixel count inside RESOURCE_BAR_BOX that confirms the gold cup
# is on screen. The live resource bar is much narrower than the synthetic
# stub (190 px wide instead of 720); on-screen gold pixels at home are
# ~1500-2500 (cup icon + '750' digit background). Pin: >= 600 on a settled
# village. Live.
MIN_GOLD_BAR_PIXELS = 600

# Pink-magenta pixel count inside RESOURCE_BAR_BOX that confirms the elixir
# cup is on screen. Live bar is ~190 wide; elixir pixels at home are
# ~600-1500. Pin: >= 200 on a settled village. Live.
MIN_ELIXIR_BAR_PIXELS = 200

# Dark-elixir drills may not exist at every TH level: 0 is a valid read.
# We only require >= 1 pixel to say a dark-elixir cup is present. Live.
MIN_DARK_ELIXIR_BAR_PIXELS = 1

# Training-queue count is read as the share of white pixels covering the
# Army tab. The live army plate is ~150x55; full white coverage is rarer
# than the synthetic stub so we lowered the threshold. Pin: ratio >=
# 0.30 = queue full enough to skip training. Live.
TRAINING_QUEUE_FULL_RATIO = 0.30

# Grass-pixel ratio inside HOME_GRASS_BOX above which we say "the home
# village is on screen, not a modal". The dense CoC tutorial village has
# grass density around 0.001-0.003 inside any 100-px row band; we sum
# the total ratio and treat 0.0006 as the on-home threshold. Live.
HOME_GRASS_RATIO = 0.0006

# Green-tick pixel ratio inside COLLECTOR_BAND_BOX above which we say "at
# least one collector is ready". The 'ready' green tick is small (~30x30)
# relative to the 1110x190 collector band, so the on-screen ratio is tiny.
# Pin: 0.0 mid-game (no tick), >= 0.0006 when at least one tick is
# visible. Live.
COLLECTOR_READY_RATIO = 0.0006

# Red-pixel ratio inside ACCOUNT_WARNING_BOX above which we say "the
# Supercell warning banner is on screen". 0.0..0.05 on the village without
# a warning, >= 0.20 with the red strip. Live.
ACCOUNT_WARNING_RED_RATIO = 0.20

# Disconnect-dialog threshold. CoC's "Anyone there?" modal doesn't paint
# a solid gray — it darkens the village behind it — but the dialog's
# title text and "Reload game" button paint white pixels into the
# lower-right quadrant. The detection relies on those white pixels:
# the dialog pushes the white-pixel ratio in DISCONNECT_DIALOG_BOX to
# ~0.02-0.04. A clean village without a dialog scores ~0.0 in the same
# box. Live.
DISCONNECT_WHITE_RATIO = 0.005

# Color ranges are BGR inclusive-lo / exclusive-hi. Calibrated on a real
# S21 FE HDMI capture (1280x720, with letterbox) so the bar cups light
# up reliably; the synthetic palette would have missed the live gold /
# pink / grass tones.
GOLD_YELLOW_LO: Tuple[int, int, int] = (0, 80, 100)
GOLD_YELLOW_HI: Tuple[int, int, int] = (60, 140, 150)
ELIXIR_PINK_LO: Tuple[int, int, int] = (95, 0, 95)
ELIXIR_PINK_HI: Tuple[int, int, int] = (160, 80, 160)
DARK_ELIXIR_LO: Tuple[int, int, int] = (30, 0, 30)
DARK_ELIXIR_HI: Tuple[int, int, int] = (130, 80, 130)
HOME_GRASS_LO: Tuple[int, int, int] = (30, 110, 25)
HOME_GRASS_HI: Tuple[int, int, int] = (100, 200, 110)
GREEN_TICK_LO: Tuple[int, int, int] = (0, 200, 0)
GREEN_TICK_HI: Tuple[int, int, int] = (60, 255, 60)
# The yellow coin floating above a ready collector. CoC's gold-icon
# prompt paints a slim pale-yellow coin with a slight orange rim.
# Pin: BGR (0..40, 200..255, 220..255). Live.
GOLD_COIN_LO: Tuple[int, int, int] = (0, 195, 215)
GOLD_COIN_HI: Tuple[int, int, int] = (50, 255, 255)
RED_LO: Tuple[int, int, int] = (0, 0, 180)
RED_HI: Tuple[int, int, int] = (80, 80, 255)
DONATION_DOT_BLUE_LO: Tuple[int, int, int] = (200, 0, 0)
DONATION_DOT_BLUE_HI: Tuple[int, int, int] = (255, 80, 80)
CLAN_CAPITAL_RED_LO: Tuple[int, int, int] = (0, 0, 200)
CLAN_CAPITAL_RED_HI: Tuple[int, int, int] = (60, 60, 255)
DAILY_YELLOW_LO: Tuple[int, int, int] = (0, 200, 200)
DAILY_YELLOW_HI: Tuple[int, int, int] = (60, 255, 255)

# Pixel-count floors for the small-icon checks. Pins on synthetic fixtures.
MIN_DONATION_DOT_BLUE_PIXELS = 4
MIN_CLAN_CAPITAL_RED_PIXELS = 80
MIN_DAILY_YELLOW_PIXELS = 20

# Collector types in iteration order. Synthetic-furniture; matches the names
# the runner expects from COLLECTOR_TYPES.
COLLECTOR_TYPES: Tuple[str, ...] = (
    "gold_mine",
    "elixir_collector",
    "dark_elixir_drill",
)


# ---------------------------------------------------------------------------
# Observation dataclass
# ---------------------------------------------------------------------------

@dataclass
class VillageObservation:
    """What the bot can read from one frame.

    Every field is ``Optional`` / defaulted to ``None`` because vision can
    be silent (GAME_BOTS §2 rule 2). The runner treats ``None`` as "don't
    know" -- it never taps on a guess (GAME_BOTS §2 rule 3).

    ``screen`` is one of: ``home``, ``tutorial``, ``clan``, ``clan_capital``,
    ``daily``, ``shop``, ``settings``, ``entry``, ``post_action_ok``,
    ``transition``, ``unknown``. ``transition`` means "wait one frame"
    (GAME_BOTS §2 rule 2). ``tutorial`` (§81.1.10) routes the frame
    through ``tutorial.TutorialDriver`` instead of the §81.1.2 chain.
    """

    screen: str = "unknown"
    gold: Optional[int] = None
    elixir: Optional[int] = None
    dark_elixir: Optional[int] = None
    gems: Optional[int] = None
    trophies: Optional[int] = None
    collector_ready: Tuple[str, ...] = ()
    training_queue_full: Optional[bool] = None
    donation_dot_present: Optional[bool] = None
    clan_capital_ready: Optional[bool] = None
    daily_present: Optional[bool] = None
    account_warning_present: bool = False
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "screen": self.screen,
            "gold": self.gold,
            "elixir": self.elixir,
            "dark_elixir": self.dark_elixir,
            "gems": self.gems,
            "trophies": self.trophies,
            "collector_ready": list(self.collector_ready),
            "training_queue_full": self.training_queue_full,
            "donation_dot_present": self.donation_dot_present,
            "clan_capital_ready": self.clan_capital_ready,
            "daily_present": self.daily_present,
            "account_warning_present": self.account_warning_present,
            "detail": dict(self.detail),
        }


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def _box(img: np.ndarray, box: Tuple[int, int, int, int]) -> np.ndarray:
    """Slice a ``(x0, y0, x1, y1)`` box out of the frame, clamping to the shape."""
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    x0 = max(0, min(w, x0))
    x1 = max(0, min(w, x1))
    y0 = max(0, min(h, y0))
    y1 = max(0, min(h, y1))
    return img[y0:y1, x0:x1]


def _mask(crop: np.ndarray, lo: Tuple[int, int, int], hi: Tuple[int, int, int]) -> np.ndarray:
    """BGR pixel mask, inclusive ``lo``, exclusive ``hi``."""
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    bl, gl, rl = lo
    bh, gh, rh = hi
    return (b >= bl) & (b < bh) & (g >= gl) & (g < gh) & (r >= rl) & (r < rh)


def _ratio(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    return float(mask.sum()) / float(mask.size)


# ---------------------------------------------------------------------------
# Per-signal pixel reads
# ---------------------------------------------------------------------------

def _read_resource_bar(img: np.ndarray) -> Optional[Tuple[bool, bool, bool]]:
    """``(gold_visible, elixir_visible, dark_elixir_visible)`` or ``None`` if
    the bar is off-screen (transition)."""
    bar = _box(img, RESOURCE_BAR_BOX)
    if bar.size == 0:
        return None
    gold = int(_mask(bar, GOLD_YELLOW_LO, GOLD_YELLOW_HI).sum())
    elixir = int(_mask(bar, ELIXIR_PINK_LO, ELIXIR_PINK_HI).sum())
    drk = int(_mask(bar, DARK_ELIXIR_LO, DARK_ELIXIR_HI).sum())
    # On a transition frame every cup is 0; return None so the runner can
    # wait one frame (GAME_BOTS §2 rule 2).
    if gold == 0 and elixir == 0 and drk == 0:
        return None
    return (
        gold >= MIN_GOLD_BAR_PIXELS,
        elixir >= MIN_ELIXIR_BAR_PIXELS,
        drk >= MIN_DARK_ELIXIR_BAR_PIXELS,
    )


def _is_disconnect_modal(img: np.ndarray) -> bool:
    """CoC's "Anyone there? / Reload game" dialog — a fat supercell modal
    in the lower-right of the village. The dialog persists across cycles
    until the player taps Reload game; without it, the runner spins on
    ``transition``.

    Trigger: white-text-pixel density (the dialog title and button) above
    DISCONNECT_WHITE_RATIO inside the DISCONNECT_DIALOG_BOX crop.
    """
    box = _box(img, DISCONNECT_DIALOG_BOX)
    if box.size == 0:
        return False
    white = (box[:, :, 0] > 200) & (box[:, :, 1] > 200) & (box[:, :, 2] > 200)
    return _ratio(white) >= DISCONNECT_WHITE_RATIO


def _on_home(img: np.ndarray) -> bool:
    """Detect the village grass in the middle of the frame."""
    grass = _box(img, HOME_GRASS_BOX)
    if grass.size == 0:
        return False
    return _ratio(_mask(grass, HOME_GRASS_LO, HOME_GRASS_HI)) >= HOME_GRASS_RATIO


def _training_queue_full(img: np.ndarray) -> Optional[bool]:
    """``True`` when the brown training plate is mostly white digits."""
    box = _box(img, TRAINING_QUEUE_BOX)
    if box.size == 0:
        return None
    white = (box[:, :, 0] > 200) & (box[:, :, 1] > 200) & (box[:, :, 2] > 200)
    return _ratio(white) >= TRAINING_QUEUE_FULL_RATIO


def _donation_dot(img: np.ndarray) -> Optional[bool]:
    """``True`` when the blue 'i' donation-request dot sits in the action bar."""
    box = _box(img, DONATION_DOT_BOX)
    if box.size == 0:
        return None
    blue = int(_mask(box, DONATION_DOT_BLUE_LO, DONATION_DOT_BLUE_HI).sum())
    return blue >= MIN_DONATION_DOT_BLUE_PIXELS


def _clan_capital_ready(img: np.ndarray) -> Optional[bool]:
    """``True`` when the clan-capital bell on the top-right has the red badge."""
    box = _box(img, CLAN_CAPITAL_BOX)
    if box.size == 0:
        return None
    red = int(_mask(box, CLAN_CAPITAL_RED_LO, CLAN_CAPITAL_RED_HI).sum())
    return red >= MIN_CLAN_CAPITAL_RED_PIXELS


def _daily_present(img: np.ndarray) -> Optional[bool]:
    """``True`` when the daily-reward star badge is on the right of the village."""
    box = _box(img, DAILY_BOX)
    if box.size == 0:
        return None
    yellow = int(_mask(box, DAILY_YELLOW_LO, DAILY_YELLOW_HI).sum())
    return yellow >= MIN_DAILY_YELLOW_PIXELS


def _collector_ready(img: np.ndarray) -> Tuple[str, ...]:
    """The collector-tile band says "at least one collector is ready".
    We don't pin to individual tiles (rule 5): the runner taps each
    name in ``COLLECTOR_TYPES`` order until one of them drops.

    Two indicators count:
      * the green tick (regular gameplay, mid-TH-level accounts)
      * the yellow coin floating above a mine / collector / drill
        (tutorial and pre-TH4 accounts)

    Both are inside COLLECTOR_BAND_BOX; we check the green mask first
    (a settled village signal) and then fall back to the yellow-coin
    prompt so the bot advances on a fresh tutorial account.
    """
    band = _box(img, COLLECTOR_BAND_BOX)
    if band.size == 0:
        return ()
    tick = _mask(band, GREEN_TICK_LO, GREEN_TICK_HI)
    if _ratio(tick) >= COLLECTOR_READY_RATIO:
        return tuple(COLLECTOR_TYPES)
    coin = _mask(band, GOLD_COIN_LO, GOLD_COIN_HI)
    if _ratio(coin) >= COLLECTOR_READY_RATIO:
        return tuple(COLLECTOR_TYPES)
    return ()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_account_warning(img: Optional[np.ndarray]) -> bool:
    """The §R5 guard trip. ``True`` when the red Supercell warning banner is
    on the upper half of the frame.

    The vision layer uses a wide red-ratio check on synthetic frames. The
    *runner* layer applies the full substring scan (``Your account``,
    ``suspended``, ``Suspicious activity``) on the real capture via
    ``warning_substrings`` and fails closed on any match.
    """
    if img is None:
        return False
    box = _box(img, ACCOUNT_WARNING_BOX)
    if box.size == 0:
        return False
    return _ratio(_mask(box, RED_LO, RED_HI)) >= ACCOUNT_WARNING_RED_RATIO


# Substring catalogue for the §R5 guard scan, in lower-case. The runner OCRs
# the warning region and asks vision whether the OCR output matches any of
# these; matching any one trips the guard.
R5_GUARD_SUBSTRINGS: Tuple[str, ...] = (
    "your account",
    "suspended",
    "suspicious activity",
)


def warning_substrings(text: Optional[str]) -> bool:
    """The §R5 substring scan. The runner OCRs the warning region, then asks
    this matcher whether any of the catalogue substrings appears in the OCR
    output. Pure: ``None`` and empty inputs return ``False``.

    Per TASK-81 §81.1 R5: the guard fails closed; ``True`` here means the
    runner must stop, set ``account_warning_seen`` and refuse to relaunch.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(s in lowered for s in R5_GUARD_SUBSTRINGS)


def crop_account_warning(img: np.ndarray) -> np.ndarray:
    """The boxed, BGR crop of the warning region. The runner hands this to
    its OCR (so vision does not own an I/O dependency on tesseract)."""
    return _box(img, ACCOUNT_WARNING_BOX)


# ---------------------------------------------------------------------------
# §81.1.10 tutorial helpers
# ---------------------------------------------------------------------------

# Bright-pixel density inside the tutorial bubble box. The actual
# Welcome Chief bubble paints a light-grey interior (RGB ~80-100 once
# JPEG compression is applied -- it is white in the synthetic stub).
# The home village without a tutorial dialog scores near 0 in the
# same box (dark grass dominates). Threshold 0.30 keeps the detector
# robust to slight tone shifts across captures while staying clear of
# the disconnect modal's dark-grey background (~0.07 in this box).
TUTORIAL_BUBBLE_WHITE_RATIO = 0.30

# Yellow stroke pixel density at the bubble border. Thin on the actual
# capture (Loose-yellow 0.4% only) and unreliable -- the box also catches
# the gold/yellow resource cups at the top, so a yellow check is too
# noisy. We rely on the bright-fill ratio alone.


def _tutorial_bubble_painted(img: np.ndarray) -> bool:
    """``True`` when the white tutorial bubble is on screen.

    Detection signal: the box has a dense bright-fill region (the bubble
    interior, ~70% on a live S21 FE capture, ~0% on a clean village).
    We use "bright" defined as ``B > 50 AND G > 50 AND R > 50`` rather
    than the strict ``>= 230`` because the vpt-host capture stream is
    JPEG-compressed and the bubble's white interior ends up rendered
    as light grey (RGB ~80-100) in the saved frames.

    The yellow stroke is too thin to be reliable across captures and
    the box also catches the gold resource cups at the top, so we
    don't use yellow. The resource bar is excluded by the
    TUTORIAL_BUBBLE_BOX starting at y=340.

    The disconnect modal also paints dark-grey (RGB ~50-70) plus a
    few white text pixels -- bright ratio is ~0.07 in this box, well
    below the 0.30 threshold.
    """
    crop = _box(img, TUTORIAL_BUBBLE_BOX)
    if crop.size == 0:
        return False
    # bright fill: every channel > 50 (BGR in OpenCV). The bubble's
    # grey interior lights up; the village grass / disconnect modal
    # does not.
    bright = (crop[:, :, 0] > 50) & (crop[:, :, 1] > 50) & (crop[:, :, 2] > 50)
    return _ratio(bright) >= TUTORIAL_BUBBLE_WHITE_RATIO


def crop_tutorial_bubble(img: np.ndarray) -> np.ndarray:
    """The bubble box as a BGR crop, for the tutorial driver's OCR.

    Empty array when the bubble isn't on screen so the caller can skip OCR.
    """
    return _box(img, TUTORIAL_BUBBLE_BOX)


def detect_tutorial_dialog(img: Optional[np.ndarray]) -> bool:
    """``True`` when the tutorial dialog bubble is on screen.

    ``classify_screen`` uses it to return ``"tutorial"``; the farm runner does not
    drive the tutorial (``game_clashofclans_llm --mode tutorial`` does).
    """
    if img is None:
        return False
    return _tutorial_bubble_painted(img)

def classify_screen(img: Optional[np.ndarray]) -> str:
    """One of ``home | tutorial | disconnect | clan | clan_capital | daily |
    shop | settings | entry | post_action_ok | transition | unknown``.

    Returns ``transition`` when the resource bar isn't on screen and the
    grass isn't drawn -- the runner waits one frame (GAME_BOTS §2 rule 2).
    Returns ``unknown`` when structural reads fail to disambiguate; the
    runner treats ``unknown`` as "no input this frame" until a pixel read
    resolves.

    Priority order:

    1. ``tutorial`` (§81.1.10): a Supercell tutorial dialog is on screen
       (white bubble in the centre-left of the capture). The tutorial
       driver processes the bubble even when the disconnect modal is
       also showing -- the bubble sits in front of the disconnect and
       dismissing it unblocks the rest of the UI.
    2. ``disconnect`` (§81.1.6): the "Anyone there? / Reload game" gray
       modal sits over the village. Cleared by ``menus.cross_to`` /
       ``CLEAR_DISCONNECT_MODAL``.
    3. Every other screen classification (home, clan, etc.).

    Choosing ``tutorial`` before ``disconnect`` matters because the bot
    must dismiss the tutorial bubble to interact with anything below
    it -- dismissing a Reload-game modal first would still leave the
    bubble on screen.
    """
    if img is None:
        return "unknown"
    if detect_tutorial_dialog(img):
        return "tutorial"
    if _is_disconnect_modal(img):
        return "disconnect"
    bar = _read_resource_bar(img)
    on_home = _on_home(img)
    if bar is None and not on_home:
        # Modal silhouettes (clan chat, clan capital, dailies, shop, settings)
        # all push the resource bar off the top and have their own visual
        # signature that the runner's screen classifier wires in via the UI
        # tree. We expose "transition" rather than guess the modal here.
        return "transition"
    if on_home:
        return "home"
    return "unknown"


def read_village(img: Optional[np.ndarray]) -> Optional[VillageObservation]:
    """Build a ``VillageObservation`` from one BGR frame.

    Returns ``None`` when the frame is mid-transition (resource bar off
    AND grass not yet drawn) -- per GAME_BOTS §2 rule 2, a transition
    frame is not a screen and the runner waits one frame on it.
    """
    if img is None:
        return None
    screen = classify_screen(img)
    if screen == "transition":
        return None
    bar = _read_resource_bar(img)
    if bar is None and screen != "home":
        # A modal screen we haven't classified yet: we still emit an
        # observation (the runner uses the ``screen`` field to cross to
        # ``home``), but the bar is off, so we skip bar-derived fields.
        gold_seen = elixir_seen = drk_seen = False
    else:
        gold_seen = elixir_seen = drk_seen = False
        if bar is not None:
            gold_seen, elixir_seen, drk_seen = bar

    return VillageObservation(
        screen=screen,
        gold=None,            # OCR stub: see module docstring. The runner
        elixir=None,          # tracks gold_gained via cross-frame delta once
        dark_elixir=None,     # a digit OCR is wired in.
        gems=None,
        trophies=None,
        collector_ready=_collector_ready(img),
        training_queue_full=_training_queue_full(img),
        donation_dot_present=_donation_dot(img),
        clan_capital_ready=_clan_capital_ready(img),
        daily_present=_daily_present(img),
        account_warning_present=detect_account_warning(img),
        detail={
            "resource_bar_visible": bar is not None,
            "gold_cup_visible": gold_seen,
            "elixir_cup_visible": elixir_seen,
            "dark_elixir_cup_visible": drk_seen,
        },
    )
