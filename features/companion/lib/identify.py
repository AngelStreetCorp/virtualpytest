"""Stage 1 — identify: screen type, content category, and exactly what is on.

One vision call per sample. The prompt carries the previous verdict (a sticky prior, so most
calls only confirm "still the same") and the last channel banner the zap detector read, which
names the programme far more reliably than pixels.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .profiles import CATEGORIES, PLAYBACK_SCREENS, SCREENS, Profile

ENTITY_FIELDS = ("title", "home_team", "away_team", "competition", "season", "episode", "year")


def build_prompt(profiles: dict[str, Profile], previous: Optional[dict] = None,
                 banner: Optional[dict] = None) -> str:
    kinds = "\n".join(f"- {p.id}: {p.hints}" for p in profiles.values())
    lines = [
        "You identify what a TV screen shows. Look at the frame and answer ONLY with one JSON object.",
        "",
        f"screen: exactly one of {', '.join(SCREENS)}.",
        "  Classify by dominant intent: a menu/guide panel covering most of the frame is menu/settings;",
        "  video covering most of the frame with a transient channel banner or info bar is still live_tv",
        "  (or vod_playback when a seek bar / on-demand player chrome is visible).",
        f"category: when screen is live_tv or vod_playback, one of {', '.join(CATEGORIES)}; else null.",
        "  news = a bulletin (presenter, several reports, headline straps, ticker); debate = people discussing",
        "  a topic (talk show, panel, debate), sport talk shows included, and an interview: a presenter talking",
        "  at length with one guest (e.g. SRF Tagesgespräch), even on a news channel; sport = a match or race.",
        "subcategory: the kind within the category (e.g. soccer, rugby, tennis for sport), or null.",
        "Known kinds:",
        kinds or "- (none)",
        f"entity: what exactly is on, with keys {', '.join(ENTITY_FIELDS)} (null when not visible).",
        "  For a match fill home_team and away_team (left/first team is home) and competition.",
        "  For a film fill title and year; for a series fill title, season and episode (numbers,",
        "  often in the banner as 'S1, Ep11', 'S2 E7' or 'Staffel 2, Folge 7').",
        "banner: if the channel's programme info bar is visible (channel + programme title, usually with the",
        "  broadcast times; NOT the channel logo alone, NOT a topic strap), {channel_name, channel_number,",
        "  program_name, start_time, end_time, episode, next_program}: start_time/end_time as printed",
        "  ('14:45' and '16:50' for '14:45 - 16:50'), episode as printed ('S1, Ep11'); else null.",
        "on_screen: text the broadcaster shows, read exactly: {lower_third: {name, role} for the caption",
        "  naming the person on screen (null if none), headline: the headline strap, ticker: the scrolling",
        "  line}. Null for anything not visible.",
        "scoreboard: for sport, the on-screen score bug (the small box with team codes, score and",
        "  clock, usually in a top corner): {present, bbox} where bbox is the tight box of the whole",
        "  bug as [x0, y0, x1, y1] in integer coordinates from 0 to 1000 relative to the frame.",
        "  {present: false} when there is none (studio, replay, magazine).",
        "confidence: 0..1.",
        "",
        "Rules: never guess names you cannot read or infer from the banner; use null instead.",
        "A programme title from the banner may be out of date (the schedule flips before the",
        "broadcast does): trust the picture for screen/category, the banner only for names.",
    ]
    if banner:
        lines += ["", "Last channel banner read on this device (may be stale): " + json.dumps(banner, ensure_ascii=False)]
    if previous:
        prior = {k: previous.get(k) for k in ("screen", "category", "subcategory", "entity")}
        lines += ["", "Previous verdict (confirm it, or say what changed): " + json.dumps(prior, ensure_ascii=False)]
    return "\n".join(lines)


def extract_json(text: str) -> Optional[dict]:
    """The last top-level JSON object in ``text`` (models sometimes add prose or fences)."""
    if not text:
        return None
    depth, start, last = 0, None, None
    in_str, escape = False, False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                last = text[start:i + 1]
    if last is None:
        return None
    try:
        value = json.loads(last)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


# A score bug is small: a "bug" box larger than this is a model that could not locate it.
MAX_BUG_W, MAX_BUG_H = 0.6, 0.25


def _bbox(value: Any) -> Optional[list[float]]:
    """[x0, y0, x1, y1] on the 0-1000 grid (Qwen-VL's native one) -> fractions of the frame."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v) / 1000.0)) for v in value)
    except (TypeError, ValueError):
        return None
    if x1 - x0 < 0.01 or y1 - y0 < 0.005 or x1 - x0 > MAX_BUG_W or y1 - y0 > MAX_BUG_H:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in ("null", "none", "unknown", "n/a") else None


def parse(content: str) -> Optional[dict]:
    """Normalised verdict, or None when the answer is unusable."""
    raw = extract_json(content)
    if raw is None or raw.get("screen") not in SCREENS:
        return None
    screen = raw["screen"]
    playback = screen in PLAYBACK_SCREENS
    category = raw.get("category") if playback and raw.get("category") in CATEGORIES else None
    subcategory = _text(raw.get("subcategory")) if category else None
    entity_raw = raw.get("entity") if isinstance(raw.get("entity"), dict) else {}
    entity = {k: _text(entity_raw.get(k)) for k in ENTITY_FIELDS}
    entity = {k: v for k, v in entity.items() if v} if playback else {}
    banner = raw.get("banner") if isinstance(raw.get("banner"), dict) else None
    if banner:
        banner = {k: _text(v) for k, v in banner.items() if _text(v)} or None
    if playback and banner:
        _episode_from_banner(entity, banner)
    board_raw = raw.get("scoreboard") if isinstance(raw.get("scoreboard"), dict) else {}
    scoreboard = None
    if category == "sport" and board_raw.get("present"):
        bbox = _bbox(board_raw.get("bbox"))
        if bbox:
            scoreboard = {"bbox": bbox}
    on_screen = _on_screen(raw.get("on_screen")) if playback else None
    try:
        confidence = round(min(1.0, max(0.0, float(raw.get("confidence", 0.5)))), 2)
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "screen": screen,
        "category": category,
        "subcategory": subcategory.lower() if subcategory else None,
        "entity": entity,
        "banner": banner,
        "scoreboard": scoreboard,
        "on_screen": on_screen,
        "confidence": confidence,
    }


# "S1, Ep11", "S2 E7", "Staffel 2, Folge 7", "Saison 3 Épisode 4"
_EPISODE = re.compile(r"\b(?:Staffel|Saison|Season|S)\s*(\d{1,3})\s*[,./-]?\s*(?:Episode|Épisode|Folge|Ep|E|F)\.?\s*(\d{1,4})\b",
                      re.IGNORECASE)


def _episode_from_banner(entity: dict, banner: dict) -> None:
    """Season / episode from the banner when the model left them out of the entity (3+, The Voice:
    the banner showed « S1, Ep11 » and the entity had neither). Never from next_program: that is the
    following programme's episode."""
    if entity.get("season") and entity.get("episode"):
        return
    for text in (banner.get("episode"), banner.get("program_name")):
        m = _EPISODE.search(text or "")
        if m:
            entity.setdefault("season", m.group(1))
            entity.setdefault("episode", m.group(2))
            return


def _on_screen(raw: Any) -> Optional[dict]:
    """Broadcaster text on screen: the lower third naming a person, the headline, the ticker."""
    if not isinstance(raw, dict):
        return None
    third = raw.get("lower_third") if isinstance(raw.get("lower_third"), dict) else {}
    name, role = _text(third.get("name")), _text(third.get("role"))
    out = {
        "lower_third": {"name": name, "role": role} if name else None,
        "headline": _text(raw.get("headline")),
        "ticker": _text(raw.get("ticker")),
    }
    return out if any(out.values()) else None
