"""Stage 3 tracker ``scoreboard`` — read a sport score bug and keep a trustworthy score.

The identify call locates the bug; after that only a crop of it is read, on the profile's
cadence. Reads are noisy, so ``ScoreStabiliser`` accepts a scoring step of the sport (soccer +1,
rugby +2/+3/+5/+7, basketball +1/+2/+3, from the profile) after two agreeing reads and records
its event when the step has one; anything else needs three reads. The clock never runs backwards
(or forwards, for a countdown clock).

The fixture it produces has the shape of Labox's ``ScoreFixture``
(labox-website/src/lib/scoresFixtures.ts), plus ``status='paused'`` while the bug is hidden.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

ROI_PROMPT = (
    "This is a crop of a TV sports score bug. Answer ONLY with JSON: "
    '{"visible": true|false, "home_team": str|null, "away_team": str|null, '
    '"home_score": int|null, "away_score": int|null, "clock": str|null, "period": str|null}. '
    "home_team is the team shown first/left. clock exactly as shown (e.g. \"34:12\", \"45+2\"). "
    "period only if shown (e.g. \"HT\", \"2nd\"). visible=false when no score bug is in the crop."
)

STEP_READS = 2     # agreeing reads to accept one scoring step (a goal, a try...)
OTHER_READS = 3    # agreeing reads to accept any other change (VAR, misread correction)
PAUSE_MISSES = 2   # reads without a visible bug before the card shows 'paused'

_CLOCK_RE = re.compile(r"(\d{1,3})\s*(?:[:'.]\s*(\d{1,2}))?\s*(?:\+\s*(\d{1,2}))?")


def parse_clock(clock: Optional[str]) -> Optional[int]:
    """Match minute from a clock string: '34:12' -> 34, '45+2' -> 47, "90'" -> 90."""
    if not clock:
        return None
    m = _CLOCK_RE.search(str(clock))
    if not m:
        return None
    minute = int(m.group(1)) + (int(m.group(3)) if m.group(3) else 0)
    return minute if 0 <= minute <= 150 else None


def clock_seconds(clock: Optional[str]) -> Optional[int]:
    """Clock position in seconds, for ordering reads: '5:32' -> 332, '45+2' -> 2820."""
    m = _CLOCK_RE.search(str(clock or ""))
    if not m:
        return None
    return (int(m.group(1)) + int(m.group(3) or 0)) * 60 + int(m.group(2) or 0)


def _int(value: Any) -> Optional[int]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 250 else None

# Soccer: every score change is a +1 goal.
SOCCER_STEPS: dict[int, Optional[str]] = {1: "goal"}
FINISHED_PERIODS = ("FT", "FULL TIME", "FINAL", "END")


class ScoreStabiliser:
    """Turns noisy scoreboard reads into a score, a clock and scoring events.

    ``steps`` maps each points value one score can add to its event type (None: no event, e.g.
    basketball baskets are too frequent to list). ``clock_up`` is False for a countdown clock
    (basketball, rugby league periods): the minute is then shown as read, never extrapolated.
    """

    def __init__(self, home_team: Optional[str] = None, away_team: Optional[str] = None,
                 steps: Optional[dict[int, Optional[str]]] = None, clock_up: bool = True):
        self.steps = dict(steps or SOCCER_STEPS)
        self.clock_up = clock_up
        self.home_team = home_team
        self.away_team = away_team
        self.score: Optional[tuple[int, int]] = None
        self.minute: Optional[int] = None
        self.clock: Optional[str] = None
        self.period: Optional[str] = None
        self.clock_at: Optional[float] = None
        self._clock_s: Optional[int] = None
        self.events: list[dict] = []
        self.status = "scheduled"
        self._pending: Optional[tuple[int, int]] = None
        self._pending_n = 0
        self._misses = 0

    def feed(self, read: Optional[dict], now: Optional[float] = None) -> bool:
        """Apply one read. Returns True when the displayed fixture changed."""
        now = time.time() if now is None else now
        before = self.snapshot()
        if not read or not read.get("visible"):
            self._misses += 1
            if self.score is not None and self._misses >= PAUSE_MISSES:
                self.status = "paused"
            return self.snapshot() != before
        self._misses = 0
        self.home_team = self.home_team or read.get("home_team") or None
        self.away_team = self.away_team or read.get("away_team") or None
        home, away = _int(read.get("home_score")), _int(read.get("away_score"))
        if home is not None and away is not None:
            self._feed_score((home, away), read)
        period = read.get("period") or self.period
        minute, secs = parse_clock(read.get("clock")), clock_seconds(read.get("clock"))
        if minute is not None and secs is not None:
            # A new period restarts the clock; within one, it only moves in its own direction.
            new_period = period != self.period
            forward = self._clock_s is None or (secs >= self._clock_s if self.clock_up else secs <= self._clock_s)
            if new_period or forward:
                self.minute, self.clock, self.clock_at, self._clock_s = minute, str(read.get("clock")), now, secs
        self.period = period
        if self.score is not None:
            self.status = "finished" if (self.period or "").upper() in FINISHED_PERIODS else "live"
        return self.snapshot() != before

    def _feed_score(self, candidate: tuple[int, int], read: dict) -> None:
        if candidate == self._pending:
            self._pending_n += 1
        else:
            self._pending, self._pending_n = candidate, 1
        if self.score is None:
            if self._pending_n >= STEP_READS:
                self.score = candidate
            return
        if candidate == self.score:
            return
        dh, da = candidate[0] - self.score[0], candidate[1] - self.score[1]
        one_side = (dh == 0) != (da == 0)
        delta = dh or da
        step = one_side and delta in self.steps
        if self._pending_n < (STEP_READS if step else OTHER_READS):
            return
        event = self.steps.get(delta) if step else None
        if event:
            self.events.append({"minute": parse_clock(read.get("clock")) or self.minute or 0,
                                "type": event, "home": dh != 0, "points": delta, "player": None})
        elif one_side and -delta in self.steps and self.steps[-delta]:
            # Disallowed score (VAR / TMO): drop the latest event of that side and value.
            side_home = dh != 0
            for i in range(len(self.events) - 1, -1, -1):
                e = self.events[i]
                if e["home"] == side_home and e.get("points") == -delta:
                    del self.events[i]
                    break
        self.score = candidate

    def snapshot(self) -> tuple:
        return (self.home_team, self.away_team, self.score, self.minute, self.status, len(self.events))

    def fixture(self, fixture_id: str, league: str = "", now: Optional[float] = None) -> dict:
        """Labox ScoreFixture shape. The minute advances with wall time between reads while live."""
        now = time.time() if now is None else now
        minute = self.minute
        if minute is not None and self.status == "live" and self.clock_at and self.clock_up:
            minute = min(minute + int((now - self.clock_at) // 60), 150)
        home, away = self.score if self.score is not None else (0, 0)
        return {
            "id": fixture_id,
            "league": league,
            "homeTeam": self.home_team or "",
            "awayTeam": self.away_team or "",
            "homeScore": home,
            "awayScore": away,
            "minute": minute,
            "clock": self.clock,
            "period": self.period,
            "status": self.status,
            "events": list(self.events),
        }
