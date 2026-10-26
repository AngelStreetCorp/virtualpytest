"""TASK-132: follow enemy minion health bars from tick to tick (pure).

The camera is locked on the champion, so the whole scene moves with him; a bar may move up to ``MATCH_PX`` between two ticks.
A track keeps its last few (time, health fraction) samples; :meth:`MinionTracker.drop_rate` is how fast the minion is losing
health (allied minions and turrets hitting it), which the last-hit rule uses to predict its health at the moment our hit lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

MATCH_PX = 70.0
HEALTH_UP_TOL = 0.04  # a bar fuller than the previous one by more than this is another minion
KILL_MARK_TOL = 0.05  # kill-marker shares differing by more than this are different minion types
KEEP_S = 2.5  # history kept per track
LOST_AFTER_S = 1.0


@dataclass
class Track:
    x: float
    y: float
    hist: List[Tuple[float, float]] = field(default_factory=list)  # (time, fraction)
    last: float = 0.0
    poked: bool = False  # v2w: one set-up auto per minion, then wait for the kill marker


class MinionTracker:
    def __init__(self) -> None:
        self.tracks: List[Track] = []

    def update(self, t: float, bars: Sequence[Any]) -> None:
        """``bars``: enemy minion ``Bar`` objects (anything with x, body, frac)."""
        free = list(bars)
        for tr in self.tracks:
            best, bd = None, MATCH_PX
            for b in free:
                d = ((b.x - tr.x) ** 2 + (b.body[1] - tr.y) ** 2) ** 0.5
                if d < bd:
                    best, bd = b, d
            if best is not None:
                free.remove(best)
                tr.x, tr.y, tr.last = best.x, best.body[1], t
                tr.hist = [(ts, f) for ts, f in tr.hist if t - ts <= KEEP_S] + [(t, best.frac)]
        for b in free:
            self.tracks.append(Track(b.x, b.body[1], [(t, b.frac)], t))
        self.tracks = [tr for tr in self.tracks if t - tr.last <= LOST_AFTER_S]

    def track_of(self, bar: Any) -> Optional[Track]:
        best, bd = None, MATCH_PX
        for tr in self.tracks:
            d = ((bar.x - tr.x) ** 2 + (bar.body[1] - tr.y) ** 2) ** 0.5
            if d < bd:
                best, bd = tr, d
        return best

    def drop_rate(self, bar: Any, window_s: float = 1.2) -> float:
        """Health fraction lost per second over the last ``window_s`` (0 when unknown or healing)."""
        tr = self.track_of(bar)
        if tr is None or len(tr.hist) < 2:
            return 0.0
        t1, f1 = tr.hist[-1]
        older = [(ts, f) for ts, f in tr.hist if t1 - ts >= 0.3 and t1 - ts <= window_s]
        if not older:
            return 0.0
        t0, f0 = older[0]
        return max(0.0, (f0 - f1) / (t1 - t0))


def match_bar(pos: Tuple[float, float], frac: float, kill_mark: float, bars: Sequence[Any], radius: float = 75.0) -> Optional[Any]:
    """Next-frame bar of the same minion: nearest within ``radius`` that is consistent with it.

    Health only goes down (a bar fuller than before by more than 0.04 is another minion) and the kill-marker share of a minion is
    constant (melee about 0.17, caster 0.29, cannon 0.10) until less than one auto is left, when the whole fill is the dark segment."""
    best, bd = None, radius
    dark_only = frac <= kill_mark + 0.02
    for b in bars:
        if b.kind != "minion":
            continue
        d = ((b.x - pos[0]) ** 2 + (b.body[1] - pos[1]) ** 2) ** 0.5
        if d >= bd:
            continue
        if b.frac > frac + HEALTH_UP_TOL:
            continue
        if not dark_only and getattr(b, "kill_mark", 0.0) > 0 and kill_mark > 0 and abs(b.kill_mark - kill_mark) > KILL_MARK_TOL:
            continue
        best, bd = b, d
    return best


@dataclass
class IdTrack:
    id: int
    samples: List[Tuple[float, float, float, float, float]] = field(default_factory=list)  # (t, frac, kill_mark, x, y)
    last_t: float = 0.0
    ended: bool = False  # True once the bar has been gone for more than ``IdTracker.keep_s``


class IdTracker:
    """Frame-to-frame minion tracker with stable ids, for offline analysis and the elite-replay extractor (5 Hz or any rate).

    ``update(t, bars)`` takes the enemy minion ``Bar`` list of one frame and returns the tracks seen in that frame. A bar continues a track when
    it is the nearest within ``radius`` px (:func:`match_bar`: health only goes down, the kill-marker share stays constant); a track survives
    ``keep_s`` seconds of missed frames. Unmatched bars start new ids. ``tracks`` keeps every track ever started (ended ones included)."""

    def __init__(self, radius: float = 75.0, keep_s: float = 0.6) -> None:
        self.radius, self.keep_s = radius, keep_s
        self.tracks: List[IdTrack] = []
        self._active: List[IdTrack] = []
        self._next_id = 1

    def update(self, t: float, bars: Sequence[Any]) -> List[IdTrack]:
        free = [b for b in bars if b.kind == "minion"]
        seen: List[IdTrack] = []
        still: List[IdTrack] = []
        for tr in self._active:
            _, f, km, x, y = tr.samples[-1]
            nxt = match_bar((x, y), f, km, free, self.radius)
            if nxt is not None:
                free.remove(nxt)
                tr.samples.append((t, nxt.frac, nxt.kill_mark if getattr(nxt, "kill_mark", 0.0) > 0 else km, nxt.x, nxt.body[1]))
                tr.last_t = t
                seen.append(tr)
                still.append(tr)
            elif t - tr.last_t <= self.keep_s:
                still.append(tr)
            else:
                tr.ended = True
        for b in free:
            tr = IdTrack(self._next_id, [(t, b.frac, getattr(b, "kill_mark", 0.0), b.x, b.body[1])], t)
            self._next_id += 1
            self.tracks.append(tr)
            seen.append(tr)
            still.append(tr)
        self._active = still
        return seen
