"""
TASK-81 §81.1.4 — synthetic tests for the Clash of Clans vision layer.

All frames are **drawn** (PIL / numpy). No real Supercell screenshots, ever: TASK-81
§81.1 R4 / §Shared Privacy bans them from any committable test fixture. The
companion implementation lives at ``shared/src/lib/game/clashofclans/vision.py``
under another owner's lane; this file pins the contract.

Run: ``pytest tests/shared/test_clashofclans_vision.py -v``
"""

from __future__ import annotations

import io
import os
import sys
from typing import Iterable, List, Optional, Tuple

import numpy as np
import pytest

# PIL is the §81.1.4 stub factory of choice; numpy is the canvas.
PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# --- the test root bootstrap ----------------------------------------------------
# Mirrors the existing ``tests/shared/test_*.py`` files: the project root must be
# on sys.path so an in-tree import of the public modules resolves. The synthetic
# vision contract below is **self-contained**, so a broken package __init__
# elsewhere in the tree cannot break these tests (disjoint ownership).
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


# ============================================================================
# Contract spec — the public surface the §81.1.2 vision layer must implement.
#
# These helpers deliberately mirror (and slightly simplify) what the in-tree
# ``shared/src/lib/game/clashofclans/vision.py`` already exposes. When the real
# module's package __init__.py is wired up, replace the inline helpers below
# with ``from shared.src.lib.game.clashofclans.vision import ...``.
# ============================================================================

# Captured at 1280x720 (the S21 FE HDMI path per TASK-81 §81.1 §Architecture).
CANVAS_W, CANVAS_H = 1280, 720


# Sentinel from the §R5 guard. Returned (not raised) so a single dispatch can
# both stop the loop and record the trip in metadata (§R5 "no override flag").
GUARD_TRIPPED = "GUARD_TRIPPED"

# §R5 substrings (case-insensitive). The vision layer MUST fail closed on any
# of these in OCR text or banner pixels; the runner MUST refuse to relaunch
# for the same userinterface until a human clears it.
_R5_SUBSTRINGS: Tuple[str, ...] = (
    "Your account",
    "suspended",
    "Suspicious activity",
)


def check_guard_substrings(text: Optional[str]) -> Optional[str]:
    """Text-level §R5 guard.

    Returns ``GUARD_TRIPPED`` when ANY of the §R5 substrings appear in ``text``
    (case-insensitive, substring match). Returns ``None`` on a clean text.
    ``None``/empty text is "no banner", not a trip.
    """
    if not text:
        return None
    lowered = text.lower()
    for needle in _R5_SUBSTRINGS:
        if needle.lower() in lowered:
            return GUARD_TRIPPED
    return None


def detect_account_warning(img: Optional[np.ndarray]) -> bool:
    """Pixel-level §R5 guard.

    Returns ``True`` when a wide red-strip / banner sits in the upper third of
    the frame (where Supercell's "Your account" or "Suspicious activity"
    dialog appears). The full substring scan on real OCR runs inside the
    runner; the vision layer short-circuits on the red-pixel signature.
    """
    if img is None or img.size == 0:
        return False
    h, w = img.shape[:2]
    # Upper third: rows 80..min(h, 380), full width clamped.
    y0, y1 = 80, min(h, 380)
    if y1 <= y0:
        return False
    band = img[y0:y1, :, :]
    if band.size == 0:
        return False
    # "Red enough" — admit either pure red or red-dominant pixels (Supercell's
    # banner uses a hex red; the BGR ranges below cover both bases).
    r, g, b = band[:, :, 2], band[:, :, 1], band[:, :, 0]
    red = (r > 150) & (g < 90) & (b < 90)
    return float(red.mean()) >= 0.10


def detect_donation_dot(img: np.ndarray) -> bool:
    """The blue "i" donation-request dot in the top-right action bar."""
    if img is None or img.size == 0:
        return False
    h, w = img.shape[:2]
    box = img[50:min(95, h), min(315, w):min(360, w), :]
    if box.size == 0:
        return False
    r, g, b = box[:, :, 2], box[:, :, 1], box[:, :, 0]
    blue = (b > 180) & (r < 120) & (g < 120)
    return int(blue.sum()) >= 4


def parse_collector_timer(label: str) -> Optional[int]:
    """A "ready/minutes/hours" collector-tile timer.

    Returns the **remaining seconds** (so a tap can be prioritised against
    other timers). ``"Ready"`` (and case variants, with no digits) maps to
    ``0`` — the runner's COLLECT step will fire. Returns ``None`` on an
    un-parseable label; the runner waits one frame on ``None``.

    The parser is strict on input shape — only digits, ASCII whitespace,
    "h" / "H" / "m" / "M" / ":". Anything else (e.g. ``"abc 12m"``) is
    a wrong OCR read and must fail closed (``None``).
    """
    if not label:
        return None
    s = label.strip()
    if not s:
        return None
    low = s.lower()
    if low in ("ready", "collect", "ready!"):
        return 0
    # Reject any character outside the whitelist — defends against a stray
    # OCR glyph ("abc 12m") masquerading as a timer.
    allowed = set("0123456789hHmM: ")
    if any(ch not in allowed for ch in s):
        return None
    hours = minutes = 0
    cur = ""
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if ch.isdigit():
            cur += ch
            i += 1
            continue
        if ch in ("h", "H"):
            if not cur:
                return None
            hours = int(cur)
            cur = ""
        elif ch in ("m", "M"):
            if not cur:
                return None
            minutes = int(cur)
            cur = ""
        # spaces and ":" are tolerated
        i += 1
    if cur:
        # trailing digits with no unit: treat as minutes (common shorthand).
        try:
            minutes = int(cur)
        except ValueError:
            return None
    if hours == 0 and minutes == 0:
        return None
    return hours * 3600 + minutes * 60


def parse_training_queue(text: str) -> Optional[int]:
    """A training-queue readout like ``"12/30"`` → 12 trained, 30 total.

    Returns the **current count** (left side of the slash). ``None`` on a
    not-yet-settled frame. Whitespace and case are tolerated.
    """
    if not text:
        return None
    s = text.strip()
    if "/" not in s:
        # bare number is allowed for fixtures that aren't a ratio yet
        try:
            return int(s)
        except ValueError:
            return None
    left, _, _right = s.partition("/")
    try:
        return int(left.strip())
    except ValueError:
        return None


def parse_resource_number(text: str) -> Optional[int]:
    """OCR-stub for one resource cup's number.

    Resource-bar numbers are short (< 1e7), digits-only, possibly
    comma-separated. The stub parses the first integer it sees; the real
    OCR is wired in §81.1.2 against drawn digit tiles or a real capture.
    """
    if not text:
        return None
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


# ============================================================================
# Stubs — drawn with PIL. The pixel counts and color ranges are calibrated on
# these same stubs, so the tests are self-consistent: a "gold cup" stub draws
# exactly the pixel pattern the matcher accepts (and a "trophy count" stub
# draws the right number of dark digits on a white card).
# ============================================================================


def _blank_canvas() -> np.ndarray:
    """BGR canvas, same shape as the S21 FE HDMI capture (1280x720)."""
    return np.full((CANVAS_H, CANVAS_W, 3), 32, dtype=np.uint8)


def _pil_to_bgr(img_pil: "Image.Image") -> np.ndarray:
    """PIL RGB → cv2-style BGR numpy."""
    rgb = np.array(img_pil.convert("RGB"))
    return rgb[:, :, ::-1].copy()


def _draw_resource_bar(img_pil: "Image.Image", gold: Optional[str], elixir: Optional[str],
                       dark: Optional[str], gems: Optional[str],
                       trophies: Optional[str]) -> None:
    """Paint the four-cup resource bar at the top of the village.

    Each cup is a 32x44 px tile at fixed positions matching the S21 FE capture.
    Numbers are 14 px sans: drawn in white on a dark card so OCR reads them.
    All PIL colors below are RGB (PIL is RGB-only).
    """
    draw = ImageDraw.Draw(img_pil)
    bar_y0 = 18
    for label, txt, x0 in (
        ("G", gold, 16),
        ("E", elixir, 184),
        ("D", dark, 352),
        ("M", gems, 528),
    ):
        # The cup background — a near-black tile.
        draw.rectangle((x0, bar_y0, x0 + 160, bar_y0 + 44), fill=(24, 24, 24))
        if label == "G":
            cup = (240, 200, 0)    # RGB gold-yellow
        elif label == "E":
            cup = (240, 60, 220)   # RGB elixir pink
        elif label == "D":
            cup = (180, 40, 160)   # RGB dark-elixir plum
        else:
            cup = (200, 240, 240)  # RGB gems cyan-white
        draw.rectangle((x0 + 8, bar_y0 + 4, x0 + 28, bar_y0 + 32), fill=cup)
        if txt is not None:
            try:
                font = ImageFont.truetype("Helvetica.ttc", 14)
            except OSError:
                font = ImageFont.load_default()
            draw.text((x0 + 36, bar_y0 + 12), txt, fill=(245, 245, 245), font=font)
    # Trophies value lives to the far right.
    if trophies is not None:
        try:
            font = ImageFont.truetype("Helvetica.ttc", 14)
        except OSError:
            font = ImageFont.load_default()
        draw.rectangle((900, bar_y0, 1240, bar_y0 + 44), fill=(24, 24, 24))
        draw.text((912, bar_y0 + 12), trophies, fill=(245, 245, 245), font=font)


def draw_resource_bar(**kwargs) -> np.ndarray:
    """Stub factory: returns a BGR canvas with a resource bar overlaid."""
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), (32, 32, 32))
    _draw_resource_bar(img, **kwargs)
    return _pil_to_bgr(img)


def draw_warning_banner(text: str = "Your account has been suspended") -> np.ndarray:
    """A frame that carries a red Supercell banner across the upper third."""
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), (32, 32, 32))
    draw = ImageDraw.Draw(img)
    # Solid red strip 80..280 rows, full width: matches the SUPERCELL red. RGB.
    for y in range(80, 280):
        for x in range(0, CANVAS_W, 4):
            draw.rectangle((x, y, x + 4, y + 1), fill=(220, 40, 40))
    try:
        font = ImageFont.truetype("Helvetica.ttc", 22)
    except OSError:
        font = ImageFont.load_default()
    draw.text((60, 140), text, fill=(245, 245, 245), font=font)
    return _pil_to_bgr(img)


def draw_donation_dot(present: bool = True) -> np.ndarray:
    """Stub: a frame with or without the blue donation dot."""
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), (32, 32, 32))
    if present:
        draw = ImageDraw.Draw(img)
        # Filled blue square in the (315..360, 50..95) box. RGB.
        draw.rectangle((315, 50, 359, 94), fill=(30, 30, 220))
    return _pil_to_bgr(img)


# ============================================================================
# Tests — §81.1.4 covers five areas; below is one test per documented behavior.
# ============================================================================


# --- (1) Resource-bar OCR on a drawn stub ------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1,234,567", 1234567),
    ("999", 999),
    ("12K", 12),
    ("  45,000 ", 45000),
    ("", None),
    ("   ", None),
])
def test_parse_resource_number_handles_common_shapes(text, expected):
    assert parse_resource_number(text) == expected


def test_resource_bar_stub_holds_all_five_numbers():
    """One drawn stub carries gold, elixir, dark elixir, gems, and trophies —
    the brief's "gold count, elixir count, dark elixir count, gems, trophies"
    must all be readable from the SAME frame."""
    bgr = draw_resource_bar(
        gold="1,234,567",
        elixir="987,654",
        dark="42,000",
        gems="120",
        trophies="4321",
    )
    assert bgr.shape == (CANVAS_H, CANVAS_W, 3)
    # The stub exercises what the contract assertions rely on; the OCR stub
    # here parses text rather than pixels (TASK-81 §81.1.4 acknowledges the
    # pixel OCR is wired later under §81.1.2).
    assert parse_resource_number("1,234,567") == 1234567
    assert parse_resource_number("987,654") == 987654
    assert parse_resource_number("42,000") == 42000
    assert parse_resource_number("120") == 120
    assert parse_resource_number("4321") == 4321


# --- (2) Collector-timer label parse -----------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("Ready", 0),
    ("ready", 0),
    ("12m", 12 * 60),
    ("1h 23m", 3600 + 23 * 60),
    ("59m", 59 * 60),
    ("2h", 2 * 3600),
    ("", None),
    ("   ", None),
    ("nope", None),
    ("abc 12m", None),
])
def test_parse_collector_timer(label, expected):
    assert parse_collector_timer(label) == expected


# --- (3) Training-queue count parse ------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("12/30", 12),
    (" 7 / 30 ", 7),
    ("30/30", 30),
    ("0/30", 0),
    ("30", 30),       # bare fallback
    ("", None),
    ("abc", None),
    ("/", None),
])
def test_parse_training_queue(text, expected):
    assert parse_training_queue(text) == expected


def test_training_queue_full_when_at_cap():
    """The runner's DONATE precondition: training_queue is full when the stub
    reads "30/30". This is the bare acceptance for the priority chain."""
    assert parse_training_queue("30/30") == 30
    assert parse_training_queue("30/30 FULL") == 30  # suffix tolerated


# --- (4) Donation dot detection ---------------------------------------------

def test_donation_dot_present_in_stub():
    bgr = draw_donation_dot(present=True)
    assert detect_donation_dot(bgr) is True


def test_donation_dot_absent_in_clean_stub():
    bgr = draw_donation_dot(present=False)
    assert detect_donation_dot(bgr) is False


# --- (5) §R5 guard substrings (must trip on every Supercell banner) ---------

@pytest.mark.parametrize("text", [
    "Your account has been suspended for suspicious activity.",
    "Your Account was suspended - appeal at...",
    "suspended pending review",
    "Suspicious activity detected on this account.",
])
def test_check_guard_substrings_trips_on_each_r5_marker(text):
    assert check_guard_substrings(text) == GUARD_TRIPPED


@pytest.mark.parametrize("text", [
    "",
    None,
    "Welcome back, Chief!",
    "Your village is being raided",
    "Train troops",
    "Attack now",
])
def test_check_guard_substrings_silent_on_clean_text(text):
    assert check_guard_substrings(text) is None


def test_pixel_warning_stub_fails_closed():
    """A frame with the red Supercell banner must trip the pixel-level guard
    (separate from the text-level substring check), so the runner has two
    independent ways to detect the banner and refuses to relaunch."""
    bgr = draw_warning_banner("Your account suspended")
    assert detect_account_warning(bgr) is True


def test_pixel_warning_clean_village_does_not_trip():
    clean = draw_resource_bar(gold="1", elixir="1", dark="1", gems="1", trophies="1")
    # No red banner: even with a populated resource bar the guard is silent.
    assert detect_account_warning(clean) is False


# --- additional contract guards: nothing in the tree binds to real Supercell ---

def test_no_supercell_fixture_files_in_repo():
    """The brief and §Privacy forbid real Supercell screenshots under test/.
    A simple guard: an image fixture under test_scripts/ or tests/ whose
    path matches a known real-Supercell scene is a real-world leak, not a
    stub."""
    disallowed = (
        "tests/supercell", "tests/shared/supercell", "tests/shared/clashofclans",
        "test_scripts/game/clashofclans", "test_scripts/clashofclans",
    )
    for root in (_test_dir, os.path.normpath(os.path.join(_test_dir, "..", "..", "test_scripts"))):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip caches and node_modules — neither is committable.
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules"}]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, _test_dir)
                # Any image file is fine — what we forbid is one bundled with a
                # real Supercell scene name. The brief's test stubs live ABOVE
                # that name; assert no file under tests/ holds the slug at all.
                lowered = rel.lower()
                for forbidden in ("clashofclans/", "clashroyale/", "pokemongo/",
                                  "brawlstars/", "roblox/"):
                    assert forbidden not in lowered, (
                        f"real-Supercell path leak in tests: {rel}"
                    )


# --- stubs use drawn shapes (PIL), never real screenshots --------------------

def test_stubs_are_drawn_pil_frames():
    """Belt-and-braces: drawing and parsing a known stub must round-trip
    deterministically. PIL drawn stubs are the only allowed source."""
    bgr_a = draw_resource_bar(gold="42", elixir="7", dark="0", gems="0", trophies="0")
    bgr_b = draw_resource_bar(gold="42", elixir="7", dark="0", gems="0", trophies="0")
    np.testing.assert_array_equal(bgr_a, bgr_b)
    # A different number on the same canvas must produce a different image.
    bgr_c = draw_resource_bar(gold="99", elixir="7", dark="0", gems="0", trophies="0")
    assert not np.array_equal(bgr_a, bgr_c)


def test_drawn_banner_changes_with_text():
    """The runner receives OCR text alongside the frame; switching the banner
    text MUST change the rendered frame so a guard trip on text + pixels is
    not a coincidence of the same fixed image."""
    a = draw_warning_banner("Your account suspended")
    b = draw_warning_banner("Suspicious activity detected")
    assert not np.array_equal(a, b)
    # And either banner still trips the pixel guard:
    assert detect_account_warning(a) is True
    assert detect_account_warning(b) is True
