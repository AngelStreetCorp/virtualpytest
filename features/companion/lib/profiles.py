"""Category profiles: what to identify, which facts to look up, what to track, how to render.

One JSON file per profile in ``profiles/``. A profile is matched by ``category`` and optional
``subcategory`` (``sport`` + ``soccer``); the most specific one wins. A playback category with
no profile still gets a genre label, just no facts or live values.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

# Screen types (TASK-36 taxonomy): one flat, mutually exclusive label.
SCREENS = ("home", "menu", "settings", "live_tv", "vod_playback", "advertisement", "loading", "error_no_signal")
PLAYBACK_SCREENS = ("live_tv", "vod_playback")
# Content categories, only meaningful on a playback screen.
# debate: talk shows, panels, debates and interviews (sport talk shows included).
CATEGORIES = ("sport", "movie", "series", "news", "debate", "documentary", "music", "kids", "game_show", "other")

# Tracker types and render templates the code implements. A profile naming anything else is
# rejected at load time rather than silently ignored.
TRACKERS = ("scoreboard", "time_window", "transcript_window")
TEMPLATES = ("match", "title", "summary", "debate", "label")

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


@dataclass(frozen=True)
class Profile:
    id: str
    category: str
    subcategory: Optional[str]
    hints: str
    entity: tuple[str, ...]
    facts: dict[str, str] = field(default_factory=dict)
    enrich_source: Optional[str] = None
    track: Optional[dict] = None
    render: str = "label"
    # Seconds between identify calls while this kind of programme is on (a zap, a motion or
    # screen change still re-identifies at once). None: the host default (COMPANION_INTERVAL_S).
    identify_interval_s: Optional[float] = None
    # Caption watcher running next to the main tracker ({"interval_s": 6}): reads the lower band
    # for name captions and topic straps (lib/captions.py). None: off.
    captions: Optional[dict] = None

    @property
    def tracker(self) -> Optional[str]:
        return (self.track or {}).get("type")

    @property
    def scoring_steps(self) -> dict[int, Optional[str]]:
        """Points one score can add -> event type (scoreboard tracker)."""
        return {int(k): v for k, v in ((self.track or {}).get("steps") or {"1": "goal"}).items()}

    @property
    def clock_up(self) -> bool:
        return (self.track or {}).get("clock", "up") != "down"


def _parse(data: dict, source: str) -> Profile:
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"{source}: unknown category '{category}'")
    track = data.get("track")
    if track and track.get("type") not in TRACKERS:
        raise ValueError(f"{source}: unknown tracker '{track.get('type')}' (known: {', '.join(TRACKERS)})")
    if track and track.get("type") == "scoreboard":
        steps = track.get("steps") or {}
        if not all(str(k).isdigit() and int(k) > 0 for k in steps):
            raise ValueError(f"{source}: scoreboard steps must be positive point values")
        if track.get("clock", "up") not in ("up", "down"):
            raise ValueError(f"{source}: scoreboard clock must be 'up' or 'down'")
    if track and track.get("type") == "transcript_window" and track.get("digest", "news") not in ("news", "debate"):
        raise ValueError(f"{source}: transcript_window digest must be 'news' or 'debate'")
    render = data.get("render") or "label"
    if render not in TEMPLATES:
        raise ValueError(f"{source}: unknown render template '{render}' (known: {', '.join(TEMPLATES)})")
    enrich = data.get("enrich") or {}
    if enrich and enrich.get("source") != "web":
        raise ValueError(f"{source}: enrich.source must be 'web'")
    return Profile(
        id=data["id"],
        category=category,
        subcategory=data.get("subcategory"),
        hints=data.get("hints") or "",
        entity=tuple(data.get("entity") or ()),
        facts=dict(enrich.get("facts") or {}),
        enrich_source=enrich.get("source"),
        track=track,
        render=render,
        identify_interval_s=float(data["identify_interval_s"]) if data.get("identify_interval_s") else None,
        captions=dict(data["captions"]) if isinstance(data.get("captions"), dict) else None,
    )


_cache: Optional[dict[str, Profile]] = None


def load_profiles(directory: str = _DIR) -> dict[str, Profile]:
    """All profiles by id. Cached for the default directory."""
    global _cache
    if directory == _DIR and _cache is not None:
        return _cache
    profiles: dict[str, Profile] = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as f:
                profile = _parse(json.load(f), name)
            profiles[profile.id] = profile
    if directory == _DIR:
        _cache = profiles
    return profiles


def profile_for(category: Optional[str], subcategory: Optional[str],
                profiles: Optional[dict[str, Profile]] = None) -> Optional[Profile]:
    """The most specific profile for a category (+ subcategory), or None."""
    profiles = load_profiles() if profiles is None else profiles
    candidates = [p for p in profiles.values() if p.category == category]
    exact = [p for p in candidates if subcategory and p.subcategory == subcategory]
    if exact:
        return exact[0]
    general = [p for p in candidates if not p.subcategory]
    return general[0] if general else None
