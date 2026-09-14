"""
Locale Probe — runtime detection of the device's UI language.

Used at validation script start so variant resolution at unified-graph build
time can apply the right `locale` overlay (en/de/fr/it). The probe is one
single OCR step; failure falls back to None and the resolver simply uses base.

The probe deliberately picks a region whose text differs across locales
(unlike "Home" which is identical en/de). For Example example TV this is the
"Filme & Serien" / "MOVIES & SERIES" / "Films et séries" / "Film e serie" tab —
each locale renders a distinct string.

Usage:
    from shared.src.lib.utils.locale_probe import detect_locale
    locale = detect_locale(device)  # 'en' | 'de' | 'fr' | 'it' | None
    if locale:
        device.device_locale = locale
"""

from typing import Optional


# Map locale code → list of substrings (case-insensitive, regex-free) that
# uniquely identify that locale on a Example example TV home screen.
# Order matters only for tie-breaking (longest match wins on ambiguity).
_LOCALE_SIGNALS = [
    ('de', ['Filme & Serien', 'Filme', 'Aufnahmen', 'TV Shop']),
    ('en', ['MOVIES & SERIES', 'MOVIES', 'RECORDINGS']),
    ('fr', ['Films et séries', 'Films', 'Enregistrements']),
    ('it', ['Film e serie', 'Film', 'Registrazioni']),
]

# Default region (1280×720, 1280-wide capture) covering the middle/right of the
# home tab strip — wide enough to catch the longest locale word in each variant.
# x=550 .. x=1100, y=40 .. y=80
_DEFAULT_PROBE_AREA = {'x': 550, 'y': 40, 'width': 550, 'height': 50}


def _normalize(s: str) -> str:
    return ''.join(c for c in s.lower() if c.isalnum() or c.isspace()).strip()


def detect_locale(device, area: Optional[dict] = None) -> Optional[str]:
    """Probe the home screen via OCR to determine the active locale.

    Args:
        device: shared.lib.models.device.Device — must have an AV controller
            (for screenshot capture) and a text verification controller (for OCR).
        area: optional override of the OCR rectangle. Defaults to the home
            tab strip middle/right where locale-distinct words live.

    Returns:
        Locale code ('en'|'de'|'fr'|'it') or None if the probe couldn't
        confidently identify the locale (in which case the resolver falls
        back to base verifications, identical to today's behaviour).
    """
    # Device's public API is _get_controller (single, private) + get_controllers (plural).
    # AV: take the first av controller. Text: pick the verification controller of type 'text'.
    av_list = device.get_controllers('av')
    av = av_list[0] if av_list else None
    text_ctrls = device.get_controllers('verification')
    text = next((c for c in (text_ctrls or []) if getattr(c, 'verification_type', None) == 'text'), None)
    if av is None or text is None:
        print("[@locale_probe] Skipping: device missing av or text-verification controller")
        return None

    # Take a fresh capture so we're not racing the runtime grabber.
    capture_path = av.take_screenshot()
    if not capture_path:
        print("[@locale_probe] Skipping: failed to take screenshot")
        return None

    extracted, _lang, _lang_conf = text._extract_text_from_area(capture_path, area or _DEFAULT_PROBE_AREA)
    if not extracted:
        print("[@locale_probe] Skipping: OCR returned empty string")
        return None

    norm = _normalize(extracted)
    print(f"[@locale_probe] OCR text: '{extracted.strip()}' (normalized: '{norm}')")

    # Score each locale by how many of its signal substrings appear in the OCR text.
    best_locale = None
    best_score = 0
    for locale, signals in _LOCALE_SIGNALS:
        score = sum(1 for sig in signals if _normalize(sig) in norm)
        if score > best_score:
            best_score = score
            best_locale = locale
    if best_score == 0:
        print(f"[@locale_probe] No locale signal matched OCR text — leaving locale unset")
        return None
    print(f"[@locale_probe] Detected locale={best_locale} (matched {best_score} signal(s))")
    return best_locale
