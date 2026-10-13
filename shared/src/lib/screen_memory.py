"""Screen memory (TASK-84): "have we seen this screen, and was it an incident?"

Pure logic, no I/O. The host fingerprints the frame of a freeze alert (``fingerprint_frame``),
matches it against the rows of that device (``match_screen``) and stamps ``metadata.screen_id``;
the triage worker records its verdict on the row (``apply_ai_verdict``) and discards later alerts
on a screen it trusts (``is_trusted_expected``). Rows live in ``screen_fingerprints``
(``shared/src/lib/database/screen_fingerprints_db.py``).

Only the dHash of the full frame and of its centre are used (no OCR, no node fingerprints): a match needs
the full frame to be tight, and the centre too whenever both centres carry signal, so a taskbar or dock alone
can never make two different busy screens "the same". Sparse screens get a proportionally tighter tolerance.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib.utils.image_hash import dhash_hamming, dhash_hex, dhash_popcount

GRID = 16
BITS = 256
CENTER = (0.22, 0.78, 0.20, 0.80)   # same centre region as ImageHelpers.FP_V5_REGIONS['center']
MIN_BITS = 8                         # a hash with fewer set bits is flat (black / no signal): not keyable
REL_TOL = 0.4                        # a match may differ by at most this share of the stored hash's set bits

MODES = ("off", "dryrun", "on")
KEYED_TYPES = ("freeze",)            # blackscreen frames all look alike: never keyed


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def mode() -> str:
    """ALERT_SCREEN_MEMORY = off | dryrun | on (default off; anything else is off)."""
    value = os.getenv("ALERT_SCREEN_MEMORY", "off").strip().lower() or "off"
    return value if value in MODES else "off"


def tolerance() -> Tuple[int, int]:
    """(full, center) maximum hamming distance in bits out of 256."""
    return _env_int("ALERT_SCREEN_FULL_MAX", 12), _env_int("ALERT_SCREEN_CENTER_MAX", 12)


def ai_votes_needed() -> int:
    return max(1, _env_int("ALERT_SCREEN_AI_VOTES", 2))


def min_seen() -> int:
    """Sightings a new fingerprint needs before it becomes a screen row (splash screens never get there)."""
    return max(1, _env_int("ALERT_SCREEN_MIN_SEEN", 5))


PENDING_TTL_S = 3600     # a candidate not seen for this long is forgotten
PENDING_MAX = 50         # per scope + incident type, oldest dropped first


class PendingScreens:
    """Candidate fingerprints seen fewer than ``min_seen()`` times, kept in memory on the host.

    A fingerprint only becomes a screen row (and gets a verdict) after it has been seen repeatedly, so a splash
    screen or a frame that drifts slightly each time never fills the table with unknown rows. A host restart
    forgets the candidates, which only delays promotion."""

    def __init__(self):
        self._items: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def see(self, key: Tuple[str, str], fp: Dict[str, str], now: float, sample: Optional[str] = None
            ) -> Optional[Dict[str, Any]]:
        """Count one sighting. Returns the candidate (with its ``count``) once it reached ``min_seen()``, else None."""
        items = [c for c in self._items.get(key, []) if now - c["last"] < PENDING_TTL_S]
        found = match_screen(fp, items)
        if found:
            cand = found[0]
            cand["count"] += 1
            cand["last"] = now
        else:
            cand = {"dhash": fp["dhash"], "region_center": fp["region_center"], "count": 1, "last": now,
                    "sample": sample}
            items.append(cand)
            items = sorted(items, key=lambda c: c["last"])[-PENDING_MAX:]
        if cand["count"] >= min_seen():
            items = [c for c in items if c is not cand]
            self._items[key] = items
            return cand
        self._items[key] = items
        return None


def audit_every() -> int:
    """Every Nth sighting of a trusted screen still goes to the model (0 = never audit)."""
    return max(0, _env_int("ALERT_SCREEN_AUDIT_EVERY", 20))


def fingerprint_frame(img_bgr) -> Optional[Dict[str, str]]:
    """``{'dhash', 'region_center'}`` of a frame, or None when it cannot identify a screen (empty or flat)."""
    import cv2
    if img_bgr is None or not getattr(img_bgr, "size", 0):
        return None
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    h, w = gray.shape
    y0, y1, x0, x1 = CENTER
    crop = gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if not crop.size:
        return None
    full = dhash_hex(gray, GRID, BITS)
    center = dhash_hex(crop, GRID, BITS)
    if dhash_popcount(full) < MIN_BITS:   # the centre may be flat (a desktop wallpaper); only the whole frame must carry signal
        return None
    return {"dhash": full, "region_center": center}


def match_screen(fp: Dict[str, str], rows: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], int]]:
    """Closest row whose full AND centre hashes are both within tolerance: ``(row, distance)`` or None.

    The distance is the larger of the two, so the closest row is the one that is tight on both."""
    full_max, center_max = tolerance()
    best: Optional[Tuple[Dict[str, Any], int]] = None
    for row in rows:
        # a sparse screen (a flat desktop with a few icons) has few set bits, so the same absolute tolerance
        # would match almost anything: scale it down to REL_TOL of the stored hash's signal
        full_cap = min(full_max, max(1, int(REL_TOL * dhash_popcount(row["dhash"]))))
        d_full = dhash_hamming(fp["dhash"], row["dhash"])
        if d_full > full_cap:
            continue
        d_center = 0
        # the centre only counts when both centres carry signal (a wallpaper centre is flat and says nothing)
        if dhash_popcount(fp["region_center"]) >= MIN_BITS and dhash_popcount(row["region_center"]) >= MIN_BITS:
            d_center = dhash_hamming(fp["region_center"], row["region_center"])
            if d_center > min(center_max, max(1, int(REL_TOL * dhash_popcount(row["region_center"])))):
                continue
        dist = max(d_full, d_center)
        if best is None or dist < best[1]:
            best = (row, dist)
    return best


def is_trusted_expected(row: Optional[Dict[str, Any]]) -> bool:
    """A screen whose alerts may be discarded without a model call."""
    return bool(row) and row.get("verdict") == "expected"


def should_audit(row: Dict[str, Any], alert_seen: Optional[int] = None) -> bool:
    """True when this sighting of a trusted screen must still go to the model.

    ``alert_seen`` is the sighting number the host stamped on the alert (``metadata.screen_seen``). The row's own
    ``seen_count`` keeps growing while the worker is busy, so several alerts polled together would all see the same
    (usually non-multiple) number and the audit would almost never fire."""
    n = audit_every()
    seen = alert_seen if alert_seen else int(row.get("seen_count") or 0)
    return bool(n) and seen % n == 0


def apply_ai_verdict(row: Dict[str, Any], verdict: str) -> Dict[str, Any]:
    """Row fields to write after the model judged an alert on this screen ({} = nothing to change).

    ``verdict`` is the triage word: real | expected | false_alarm. A human verdict is never touched;
    one ``real`` makes the screen ``bad`` and clears the expected votes; ``expected`` needs
    ``ai_votes_needed()`` agreeing verdicts and never turns a ``bad`` screen back (a human does that)."""
    if row.get("source") == "human":
        return {}
    exp, bad = int(row.get("ai_votes_expected") or 0), int(row.get("ai_votes_bad") or 0)
    if verdict == "real":
        return {"verdict": "bad", "source": "ai", "ai_votes_expected": 0, "ai_votes_bad": bad + 1}
    exp += 1
    fields: Dict[str, Any] = {"ai_votes_expected": exp}
    if row.get("verdict") != "bad" and exp >= ai_votes_needed():
        fields.update({"verdict": "expected", "source": "ai"})
    return fields
