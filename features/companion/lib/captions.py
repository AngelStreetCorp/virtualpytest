"""Caption watcher — the broadcaster's text in the lower part of the frame.

Talk shows and news name a person with a caption only for a few seconds, when the camera cuts to
them (L'Équipe du Soir, 2026-09-30: a 60 s identify never saw one). So a profile with a
``captions`` block reads just the lower band of the frame every ``interval_s`` seconds, and
skips the read when the band has not changed since the last one (a static wide shot with the same
strap). Skipping only ever happens on an unchanged band, so no new caption is missed because of it.

Output feeds the speaker roster (``name`` captions) and a strap timeline (``strap``: the topic line
talk shows change with every subject).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Optional

from .identify import extract_json

# Lower band of the frame, as fractions of its height: captions, straps and tickers live here.
BAND = (0.60, 0.97)
# Mean absolute grey-level difference (0-255) on a small copy of the band below which the band
# counts as unchanged and the read is skipped.
UNCHANGED_DIFF = 4.0
MAX_TIMELINE = 20

CAPTIONS_PROMPT = (
    "This is the lower part of a TV frame. List the text graphics the channel shows (not text that is part "
    "of the filmed scene). Answer ONLY with JSON: "
    '{"captions": [{"kind": "name"|"strap"|"ticker"|"subtitle"|"other", "text": "exact text", '
    '"name": "person named, for kind=name", "role": "their title/role, or null"}]}. '
    "kind=name: a caption naming a PERSON on screen (a first and last name), never a programme, channel or "
    "logo; strap: the headline/topic bar; ticker: the scrolling line; subtitle: dialogue subtitles (what "
    "someone is saying, usually 1-2 centred lines). Read exactly, do not guess. "
    '{"captions": []} when there is none.'
)


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text if text and text.lower() not in ("null", "none", "n/a", "unknown") else None


def parse(content: str) -> Optional[list[dict]]:
    raw = extract_json(content)
    if raw is None or not isinstance(raw.get("captions"), list):
        return None
    out = []
    for c in raw["captions"]:
        if not isinstance(c, dict):
            continue
        kind = c.get("kind") if c.get("kind") in ("name", "strap", "ticker", "subtitle", "other") else "other"
        item = {"kind": kind, "text": _clean(c.get("text")), "name": _clean(c.get("name")), "role": _clean(c.get("role"))}
        if kind == "name" and not item["name"]:
            item["name"] = item["text"]
        if item["text"] or item["name"]:
            out.append(item)
    return out


def _key(text: str) -> str:
    """Lowercase letters and digits only, accents folded (É -> e)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


SAME_RATIO = 0.88


def same_text(a: str, b: str) -> bool:
    """Same on-screen text read twice with OCR slips: dropped letters (IMBROGLO / IMBROGLIO),
    swapped letters (OBRANIAC / OBRANIAT) or a split word (OBRANI AK). Accents, case and spacing
    are ignored, then the two must be at least 88 % similar."""
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return False
    return ka == kb or SequenceMatcher(None, ka, kb).ratio() >= SAME_RATIO


NOT_A_NAME = re.compile(r"[()\[\]?!:*«»\"0-9]")
# Words of channel / audio idents, never of a person's name. SRF INFO shows "* Audio Radio SRF 1 *"
# under its radio simulcast, and identify returned it as the lower third naming the person.
CHANNEL_WORDS = {"srf", "rts", "rsi", "ard", "zdf", "orf", "bbc", "cnn", "radio", "audio", "tv", "hd", "live",
                 "direct", "direkt", "replay", "info", "news", "channel", "chaine", "sender"}


def is_person(name: str, not_names: list[str]) -> bool:
    """A name caption must look like a person: 2-4 words, no brackets / ?!:* / digits, no channel word
    (SRF, Radio, Audio, TV...), and not a programme, channel or strap seen on this channel. On L'Équipe
    du Soir the model returned the show logo and a clip title ("OLISE GOLAZO (LA PREUVE EN IMAGE)") as
    name captions."""
    words = name.split()
    if not 2 <= len(words) <= 4 or NOT_A_NAME.search(name):
        return False
    if any(_key(word) in CHANNEL_WORDS for word in words):
        return False
    key = _key(name)
    for other in not_names:
        k = _key(other or "")
        if k and (k in key or key in k or same_text(name, other)):
            return False
    return True


def add_to_timeline(timeline: list[dict], text: str, at: float) -> list[dict]:
    """Strap timeline, newest first: a strap seen again only refreshes ``last_seen``."""
    for item in timeline:
        if same_text(item["text"], text):
            item["last_seen"] = at
            return timeline
    return ([{"text": text, "first_seen": at, "last_seen": at}] + timeline)[:MAX_TIMELINE]
