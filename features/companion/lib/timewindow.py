"""Stage 3 tracker ``time_window`` — how far into the programme we are.

The channel banner gives the broadcast slot ("20:50 - 22:45"); with the wall clock that is the
elapsed / remaining time of a film or episode on linear TV. No slot (VOD, no banner seen yet):
no progress, the card just omits the bar.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

_HHMM = re.compile(r"^\s*(\d{1,2})[:h.](\d{2})\s*$")
# A slot that ended longer ago than this is a stale banner, not the programme on screen.
STALE_AFTER_END_MIN = 15


def _at(hhmm: Optional[str], day: datetime) -> Optional[datetime]:
    m = _HHMM.match(hhmm or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return day.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)


def progress(start: Optional[str], end: Optional[str], now: Optional[datetime] = None) -> Optional[dict]:
    """Elapsed / remaining minutes of the slot ``start``-``end`` (local "HH:MM"), or None."""
    now = now or datetime.now()
    begin, finish = _at(start, now), _at(end, now)
    if begin is None or finish is None:
        return None
    if finish <= begin:                      # crosses midnight
        if now < finish:
            begin -= timedelta(days=1)
        else:
            finish += timedelta(days=1)
    elif begin - now > timedelta(hours=12):  # e.g. 23:30 slot seen at 00:10
        begin, finish = begin - timedelta(days=1), finish - timedelta(days=1)
    total = int((finish - begin).total_seconds() // 60)
    elapsed = int((now - begin).total_seconds() // 60)
    if total <= 0 or elapsed < 0 or elapsed > total + STALE_AFTER_END_MIN:
        return None
    elapsed = min(elapsed, total)
    return {"start": start, "end": end, "total_min": total, "elapsed_min": elapsed,
            "remaining_min": total - elapsed}


def same_programme(banner_title: Optional[str], title: Optional[str]) -> bool:
    """Loose match between a banner's programme name and the identified title."""
    if not banner_title or not title:
        return not banner_title  # an untitled slot is accepted, a different title is not
    a = re.sub(r"[^a-z0-9]+", " ", banner_title.lower()).strip()
    b = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return bool(a and b) and (a in b or b in a)
