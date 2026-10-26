"""TASK-131: which enemy minions died next to the player, and did the player get the last hit (read-only).

Fed once per captured frame with the enemy minion health bars (``perception.find_bars`` on a full-resolution grab,
the same reader the bot uses) and the exact HUD CS (``cs_reader``). A bar is followed from frame to frame; a bar that
vanishes while low on health and near the champion (camera locked on him, so he stays at the screen centre) is a
minion death. The death is *ours* when the CS counter rose within ``CS_WINDOW`` seconds of it, *missed* otherwise.

Type: ``cannon`` when ``Bar.minion_type`` says so (wider bar frame); melee and caster minions have the same bar, so
they cannot be told apart and are ``minion`` (valued at their mean by ``scorecard.minion_gold``).

NOT validated on real footage yet: the saved run videos (1280x800, 10 fps, compressed) wash the bars out so
``find_bars`` finds none, and the saved screenshots are 20 s apart. Needs full-resolution frames at >= 2 Hz (the
``auto_record`` watcher and the bot tick provide them); the 20-deaths-by-hand check is open (TASK-131 goal 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

REACH_PX = 330.0       # body-to-champion distance (1920x1200 grab) counted as "near Garen" (attack range)
DEATH_MAX_FRAC = 0.45  # a vanishing bar this full or less is a death; fuller = left vision or walked away
MATCH_PX = 70.0        # a bar may move this far between two frames (the whole scene moves with the champion)
LOST_AFTER_S = 0.9     # a track unseen this long is over
MIN_SEEN = 2
DUP_PX = 14.0          # bars closer than this in one frame are the same minion
CS_WINDOW = (-0.5, 0.7)


@dataclass
class _Track:
    x: float
    y: float
    frac: float
    kind: str
    first: float
    last: float
    seen: int = 1


class MinionWatcher:
    def __init__(self, player_xy: Tuple[float, float] = (868.0, 545.0)):  # perception.PLAYER_XY
        self.player = player_xy
        self.tracks: List[_Track] = []
        self.cs: List[Tuple[float, int]] = []
        self.pending: List[Dict[str, Any]] = []   # deaths waiting for the CS window to close
        self.deaths: List[Dict[str, Any]] = []
        self._used: set = set()  # CS rises (index into self.cs) already credited to a death

    def update(self, t: float, bars: Sequence[Any], cs: Optional[int] = None) -> None:
        """``bars``: enemy ``Bar`` objects (kind == "minion" ones are used)."""
        if cs is not None:
            self.cs.append((t, cs))
        free: List[Any] = []
        for b in bars:  # two bars on top of each other are one minion (frame edge, double draw)
            if b.kind == "minion" and all(abs(b.x - o.x) > DUP_PX or abs(b.y - o.y) > DUP_PX for o in free):
                free.append(b)
        for tr in self.tracks:
            best, bd = None, MATCH_PX
            for b in free:
                d = ((b.x - tr.x) ** 2 + (b.y - tr.y) ** 2) ** 0.5
                if d < bd:
                    best, bd = b, d
            if best is not None:
                free.remove(best)
                tr.x, tr.y, tr.frac, tr.last, tr.seen = best.x, best.y, best.frac, t, tr.seen + 1
                if best.minion_type == "cannon":
                    tr.kind = "cannon"
        self.tracks += [_Track(b.x, b.y, b.frac, "cannon" if b.minion_type == "cannon" else "minion", t, t) for b in free]
        alive = []
        for tr in self.tracks:
            if t - tr.last <= LOST_AFTER_S:
                alive.append(tr)
                continue
            body = (tr.x, tr.y + 50)
            near = ((body[0] - self.player[0]) ** 2 + (body[1] - self.player[1]) ** 2) ** 0.5 <= REACH_PX
            if tr.seen >= MIN_SEEN and tr.frac <= DEATH_MAX_FRAC and near:
                self.pending.append({"t": round(tr.last, 2), "kind": tr.kind, "frac": round(tr.frac, 2), "x": round(tr.x), "y": round(tr.y)})
        self.tracks = alive
        self._resolve(t)

    def _resolve(self, now: float, final: bool = False) -> None:
        """Close deaths whose CS window has passed. One CS rise credits ONE death (the nearest in time): a minion
        tracked twice (a duplicate bar) or two minions dying in one frame cannot both be ours for a single CS."""
        keep, ready = [], []
        for d in self.pending:
            (ready if final or now >= d["t"] + CS_WINDOW[1] else keep).append(d)
        for d in sorted(ready, key=lambda d: d["t"]):
            best = None
            for i, ((_ta, a), (tb, b)) in enumerate(zip(self.cs, self.cs[1:])):
                if b > a and i not in self._used and d["t"] + CS_WINDOW[0] <= tb <= d["t"] + CS_WINDOW[1]:
                    if best is None or abs(tb - d["t"]) < abs(self.cs[best + 1][0] - d["t"]):
                        best = i
            d["ours"] = best is not None
            if best is not None:
                self._used.add(best)
            self.deaths.append(d)
        self.pending = keep

    def finish(self, now: float) -> List[Dict[str, Any]]:
        """Close every track and open CS window at the end of the game; all deaths, oldest first."""
        self.update(now + LOST_AFTER_S + 1, [], None)
        self._resolve(now + 10, final=True)
        return sorted(self.deaths, key=lambda d: d["t"])
