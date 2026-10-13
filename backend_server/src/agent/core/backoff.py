"""
Back-off for a model step of a background worker (Sherlock's Jev and LLM steps).

A provider that is down (no credits, HTTP 5xx, unreachable) is not called again for 1 h after a failure,
then 5 h after the next one, then 24 h for every later one; one success resets it. State is in memory:
a worker restart probes the provider once. Env: ``ANALYZER_BACKOFF_S`` = comma-separated seconds.
"""

import os
import time
from typing import Optional, Tuple

DEFAULT_STEPS = (3600, 18000, 86400)


def _steps_from_env() -> Tuple[int, ...]:
    try:
        steps = tuple(int(s) for s in os.getenv("ANALYZER_BACKOFF_S", "").split(",") if s.strip())
        return steps if steps and all(s > 0 for s in steps) else DEFAULT_STEPS
    except ValueError:
        return DEFAULT_STEPS


class Backoff:
    def __init__(self, name: str, steps: Optional[Tuple[int, ...]] = None, clock=time.time):
        self.name = name
        self.steps = steps or _steps_from_env()
        self.clock = clock
        self.failures = 0
        self.blocked_until = 0.0
        self.last_error = ""

    def blocked(self) -> bool:
        return self.clock() < self.blocked_until

    def remaining_s(self) -> int:
        return max(0, int(self.blocked_until - self.clock()))

    def failed(self, error: str) -> int:
        """Record a provider failure; returns the pause in seconds."""
        pause = self.steps[min(self.failures, len(self.steps) - 1)]
        self.failures += 1
        self.blocked_until = self.clock() + pause
        self.last_error = (error or "")[:200]
        return pause

    def succeeded(self) -> None:
        self.failures = 0
        self.blocked_until = 0.0
        self.last_error = ""

    def describe(self) -> str:
        until = time.strftime("%H:%M UTC", time.gmtime(self.blocked_until))
        return f"{self.name} paused until {until} after {self.failures} failure(s) in a row: {self.last_error}"
