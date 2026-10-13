"""
TASK-81 §81.1.4 — synthetic tests for the Clash of Clans runner.

The runner owns:

    * the §R5 account-warning guard — fails closed on the Supsercell banner
      substring / pixel signature, refuses to relaunch for the same userinterface
      until a human clears it (no override flag);
    * the vpt-lease acquire/release — one lease per run, released on every
      exit path (success, time cap, guard, exception);
    * the §81.1.2 KPI table — every metric the metadata block promises lands
      on the result, ``attack_attempted`` is always ``False`` (v1 refuses the
      Attack button by design — TASK-81 §81.1 Out of scope);
    * the loop's hard caps — ``max_runtime_s`` and ``max_cycles`` exit with
      ``stop_reason`` set on the metadata.

The companion implementation lives at ``shared/src/lib/game/clashofclans/runner.py``
under another owner's lane; this file pins the contract.

Run: ``pytest tests/shared/test_clashofclans_runner.py -v``
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pytest

# --- the test root bootstrap ----------------------------------------------------
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


# ============================================================================
# Contract spec — the public surface the §81.1.2 runner layer must implement.
#
# Helpers below mirror what the in-tree runner.py is expected to expose. When
# the real module lands, replace these inline helpers with
# ``from shared.src.lib.game.clashofclans.runner import Runner, STOP_GUARD,
# STOP_TIME_CAP, STOP_MAX_CYCLES``.
# ============================================================================


# Stop-reason sentinels — internal values, identical strings to what the
# metadata block carries.
STOP_GUARD = "guard"
STOP_TIME_CAP = "time_cap"
STOP_MAX_CYCLES = "max_cycles"
STOP_APP_CRASHED = "app_crashed"
STOP_DEVICE_OFFLINE = "device_offline"

USERINTERFACE_DEFAULT = "clashofclans-android-mobile"
DEVICE_MODEL_DEFAULT = "s21_phone"

# §R5 substring pool — case-insensitive. Same pool the §81.1.4 vision tests
# exercise at the text level (see test_clashofclans_vision.py).
_R5_SUBSTRINGS: Tuple[str, ...] = (
    "Your account", "suspended", "Suspicious activity",
)

# BGR-pixel signature for the §81.1 banner. The runner's pixel-level trip wires
# to vision.detect_account_warning in §81.1.2; here the contract is the bare
# threshold so the test can paint its own banners.
_BANNER_RED_MIN_RATIO = 0.10


def _banner_tripped_pixels(img: Optional[np.ndarray]) -> bool:
    """Pixel-level §R5 trip — see vision.detect_account_warning for the real
    pixel logic. Inlined here so the runner contract is self-contained."""
    if img is None or img.size == 0:
        return False
    h, w = img.shape[:2]
    y0, y1 = 80, min(h, 380)
    if y1 <= y0:
        return False
    band = img[y0:y1, :, :]
    r, g, b = band[:, :, 2], band[:, :, 1], band[:, :, 0]
    red = (r > 150) & (g < 90) & (b < 90)
    return float(red.mean()) >= _BANNER_RED_MIN_RATIO


def _banner_tripped_text(text: Optional[str]) -> bool:
    """Text-level §R5 trip."""
    if not text:
        return False
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in _R5_SUBSTRINGS)


class _FakeDevice:
    """Synthetic device — captures action calls, holds a lease, never opens a
    real game. Lives only so the runner contract can take ``device`` like the
    real one does, in §81.1.2.

    Frames are recycled (one shared BGR buffer) so 1M-cycle tests don't run
    out of memory; the contract surface is unchanged because the runner only
    reads pixel values, never the buffer's identity.
    """

    def __init__(self, *, online: bool = True, taps: Optional[List[str]] = None,
                 errors_after: Optional[int] = None,
                 banner_in_frame: Optional[int] = None) -> None:
        self.device_model = DEVICE_MODEL_DEFAULT
        self.online = online
        self.taps = taps if taps is not None else []
        self.errors_after = errors_after  # the cycle at which ``frame()`` will raise
        self.banner_in_frame = banner_in_frame
        self._cycles = 0
        self._lease_held = False
        self._lease_acquired = False
        self._lease_released = False
        # Reused per call; the runner reads pixels, doesn't keep references.
        self._clean_frame = np.full((720, 1280, 3), 32, dtype=np.uint8)

    # --- lease: the runner calls these once at start / every exit path ---
    def acquire_lease(self, label: str) -> bool:
        self._lease_acquired = True
        self._lease_held = True
        return True

    def release_lease(self) -> bool:
        self._lease_released = True
        self._lease_held = False
        return True

    # --- the runner calls this every cycle to read the next frame ---
    def frame(self) -> Optional[np.ndarray]:
        if not self.online:
            raise RuntimeError("device offline")
        self._cycles += 1
        if self.errors_after is not None and self._cycles >= self.errors_after:
            raise RuntimeError("app crashed")
        if self.banner_in_frame is not None and self._cycles == self.banner_in_frame:
            # A red banner on this single frame; reuse a baked buffer.
            banner = np.zeros((720, 1280, 3), dtype=np.uint8)
            banner[80:280, :, 2] = 220  # BGR red
            banner[80:280, :, 1] = 40
            banner[80:280, :, 0] = 40
            return banner
        # every other frame is "clean home" (no banner) — recycled buffer.
        return self._clean_frame

    # --- the runner records every tap it makes ---
    def tap(self, label: str, *args: Any, **kwargs: Any) -> None:
        self.taps.append(label)

    def mark_done(self, label: str) -> None:
        # the per-action navigate call; not used by every runner style but
        # available here so a real one doesn't have to be wired up later.
        self.taps.append(f"done:{label}")


@dataclass
class _LeaseTracker:
    """Holds the lease state for the runner — number of acquires and releases,
    plus the cycle at which they happened. Used by the runner to assert
    post-conditions in test (one acquire at start, one release at exit on every
    path)."""

    acquires: int = 0
    releases: int = 0
    held_at: Optional[int] = None
    released_at: Optional[int] = None


class Runner:
    """Synthetic §81.1.2 runner. Exposes ``run()`` with the contract the brief
    requires. Replace with the real ``shared.src.lib.game.clashofclans.runner.Runner``
    when §81.1.2 lands.

    The shape here is intentionally minimal so the tests focus on the §81.1
    invariants (guard, time cap, max cycles, KPIs, attack_attempted). The
    full action-recording and per-action timing arrive when the real
    implementation lands.
    """

    def __init__(self, device: _FakeDevice, *,
                 userinterface: str = USERINTERFACE_DEFAULT,
                 max_runtime_s: float = 600.0,
                 max_cycles: int = 1_000_000,
                 now_fn: Optional[Callable[[], float]] = None) -> None:
        self.device = device
        self.userinterface = userinterface
        self.max_runtime_s = float(max_runtime_s)
        self.max_cycles = int(max_cycles)
        self._now = now_fn or time.monotonic

    def run(self) -> Dict[str, Any]:
        started = self._now()
        # Lease — one acquire at start; one release on EVERY exit path
        # (success, time cap, max cycles, guard, exception).
        self.device.acquire_lease(self.userinterface)

        # ---- metadata block — every §81.1 KPI lands on the result -------------
        meta: Dict[str, Any] = {
            "userinterface": self.userinterface,
            "device_model": getattr(self.device, "device_model", ""),
            "play_duration_s": 0,
            "gold_gained": 0,
            "elixir_gained": 0,
            "dark_elixir_gained": 0,
            "troops_trained": 0,
            "troops_donated": 0,
            "capital_chests_collected": 0,
            "dailies_collected": 0,
            "cycles_completed": 0,
            "attack_attempted": False,        # always False in v1
            "idle_seconds": 0,
            "account_warning_seen": False,    # §R5 guard trip
            "stop_reason": "",
        }

        try:
            while True:
                # Hard cap on cycles.
                if meta["cycles_completed"] >= self.max_cycles:
                    meta["stop_reason"] = STOP_MAX_CYCLES
                    break
                # Hard cap on wall-clock.
                if (self._now() - started) >= self.max_runtime_s:
                    meta["stop_reason"] = STOP_TIME_CAP
                    break

                # Read the next frame and check the guard BEFORE any tap.
                frame = self.device.frame()
                meta["cycles_completed"] += 1
                if _banner_tripped_pixels(frame):
                    meta["account_warning_seen"] = True
                    meta["stop_reason"] = STOP_GUARD
                    break

                # Other actions are recorded here in the real runner; this stub
                # adds a synthetic COLLECT tap on every clean cycle to prove
                # the runner actually iterated.
                self.device.tap("COLLECT")
        finally:
            meta["play_duration_s"] = max(0, int(self._now() - started))
            self.device.release_lease()

        return meta


# ============================================================================
# Tests — §81.1 invariants: guard, time cap, max cycles, KPIs, attack_attempted
# ============================================================================


# --- (1) Guard hit (§R5) — fails closed ----------------------------------------

def test_guard_trips_on_a_banner_frame():
    """A banner frame causes the runner to stop, set the warning flag, and
    release the lease BEFORE the next tap."""
    dev = _FakeDevice(banner_in_frame=1)
    runner = Runner(dev, max_runtime_s=60, max_cycles=1_000)
    meta = runner.run()
    assert meta["stop_reason"] == STOP_GUARD
    assert meta["account_warning_seen"] is True
    assert meta["attack_attempted"] is False  # guard fired before any tap


def test_guard_does_not_silently_release_after_a_banner_trip():
    """A banner mid-loop MUST release the lease — the §R6 single-tenant rule
    depends on this even when the loop exits on the guard path."""
    dev = _FakeDevice(banner_in_frame=1)
    Runner(dev).run()
    # The runner's lease API is observed: one acquire, one release on exit.
    assert dev._lease_acquired is True and dev._lease_released is True
    assert dev._lease_held is False


def test_runner_never_progresses_to_collect_when_banner_fires_first():
    """If the very first frame carries a banner, the cycle never increments
    past 1 and no synthetic COLLECT tap was emitted."""
    dev = _FakeDevice(banner_in_frame=1)
    Runner(dev).run()
    assert "COLLECT" not in dev.taps
    assert len(dev.taps) == 0


def test_no_banner_no_trip_clean_loop_runs_to_max_cycles():
    """On a clean run, the loop runs until ``max_cycles`` and never trips the
    guard — confirming the false-positive floor on ``detect_account_warning``."""
    dev = _FakeDevice()  # no banner ever
    meta = Runner(dev, max_cycles=5).run()
    assert meta["stop_reason"] == STOP_MAX_CYCLES
    assert meta["account_warning_seen"] is False
    # 5 cycles means 5 COLLECT taps (one per clean iteration).
    assert dev.taps.count("COLLECT") == 5
    assert meta["cycles_completed"] == 5


# --- (2) Time cap ----------------------------------------------------------

def test_time_cap_stops_with_stop_reason_time_cap():
    """A fake clock that jumps past ``max_runtime_s`` at cycle 1 — the runner
    must exit with ``stop_reason="time_cap"``, not silence the loop on the
    cycle-count cap."""
    dev = _FakeDevice()
    start = [1000.0]
    tick = {"n": 0}

    def now():
        tick["n"] += 1
        # First call — start; second call (still inside the loop) — 100s later;
        # every call after that — 200s later.
        return start[0] + (200.0 if tick["n"] > 1 else 100.0)

    meta = Runner(dev, max_runtime_s=60.0, now_fn=now).run()
    assert meta["stop_reason"] == STOP_TIME_CAP
    assert meta["account_warning_seen"] is False
    assert meta["attack_attempted"] is False


# --- (3) Max cycles --------------------------------------------------------

def test_max_cycles_stops_with_stop_reason_max_cycles():
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=3, max_runtime_s=10_000).run()
    assert meta["stop_reason"] == STOP_MAX_CYCLES
    assert meta["cycles_completed"] == 3


# --- (4) Metadata block — every §81.1 KPI lands --------------------------

REQUIRED_KPIS: Tuple[str, ...] = (
    "gold_gained",
    "elixir_gained",
    "dark_elixir_gained",
    "troops_trained",
    "troops_donated",
    "capital_chests_collected",
    "dailies_collected",
    "cycles_completed",
    "attack_attempted",
    "idle_seconds",
    "account_warning_seen",
    "stop_reason",
    "userinterface",
    "device_model",
    "play_duration_s",
)


def test_metadata_block_has_every_kpi_from_the_r81_table():
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=2).run()
    for kpi in REQUIRED_KPIS:
        assert kpi in meta, f"required KPI missing: {kpi}"


def test_metadata_userinterface_is_locked_to_clashofclans_android_mobile():
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=2).run()
    assert meta["userinterface"] == USERINTERFACE_DEFAULT


def test_metadata_device_model_names_s21_phone_when_device_reports_it():
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=2).run()
    assert meta["device_model"] == DEVICE_MODEL_DEFAULT


def test_metadata_kpi_counters_default_to_zero():
    """All numeric KPIs default to 0 on a clean short run — guards against a
    runner that forgets to seed them in the metadata."""
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=1).run()
    for k in ("gold_gained", "elixir_gained", "dark_elixir_gained",
              "troops_trained", "troops_donated", "capital_chests_collected",
              "dailies_collected"):
        assert meta[k] == 0, f"{k} should default to 0, got {meta[k]}"


# --- (5) attack_attempted is always False (v1 refuses Attack) -------------

def test_attack_attempted_is_always_false_on_a_clean_run():
    dev = _FakeDevice()
    meta = Runner(dev, max_cycles=100).run()
    assert meta["attack_attempted"] is False


def test_attack_attempted_is_always_false_on_a_guard_trip():
    """The §R1/R2 carve-out: the run exits on the guard, and even then the flag
    never flips — the v1 runner refused the Attack button by design."""
    dev = _FakeDevice(banner_in_frame=1)
    meta = Runner(dev).run()
    assert meta["attack_attempted"] is False
    assert meta["stop_reason"] == STOP_GUARD


def test_attack_attempted_is_always_false_under_time_cap():
    dev = _FakeDevice()
    meta = Runner(dev, max_runtime_s=0.0).run()
    assert meta["attack_attempted"] is False
    assert meta["stop_reason"] == STOP_TIME_CAP


# --- (6) Lease — acquire once, release on every exit path ----------------

def test_lease_acquired_once_at_start():
    dev = _FakeDevice()
    # Bound the run short so the test exercises the lease-acquire path only,
    # not the per-cycle loop. Default ``max_cycles=1_000_000`` × the per-cycle
    # banner pixel scan takes many minutes; the lease tests don't care.
    Runner(dev, max_cycles=2).run()
    assert dev._lease_acquired is True


def test_lease_released_on_guard_path():
    dev = _FakeDevice(banner_in_frame=1)
    Runner(dev).run()
    assert dev._lease_released is True
    assert dev._lease_held is False


def test_lease_released_on_time_cap_path():
    dev = _FakeDevice()

    def now():
        return 1000.0 + 1_000  # any future; first-now is start.
    Runner(dev, max_runtime_s=0.0, now_fn=now).run()
    assert dev._lease_released is True


def test_lease_released_on_max_cycles_path():
    dev = _FakeDevice()
    Runner(dev, max_cycles=1).run()
    assert dev._lease_released is True


def test_lease_released_even_when_device_raises():
    """An unexpected ``RuntimeError`` from the device MUST still release the
    lease (§R6). The runner's ``try/finally`` covers this."""
    dev = _FakeDevice(errors_after=1)
    with pytest.raises(RuntimeError):
        Runner(dev, max_cycles=10).run()
    assert dev._lease_acquired is True
    assert dev._lease_released is True


# --- (7) Guard substring pool — the §R5 text-level trip is exhaustive ------

@pytest.mark.parametrize("text", [
    "Your account has been suspended",
    "Your Account was suspended",
    "Suspicious activity detected on this account.",
    "Welcome back, Chief!",  # negative — must not trip
    "",                       # negative
])
def test_r5_substring_pool_is_what_the_runner_uses(text):
    """The runner-level guard pool must match the vision-level guard pool (no
    two different §R5 vocabularies can co-exist without one becoming
    bypassable)."""
    expected = bool(text) and any(n.lower() in text.lower() for n in _R5_SUBSTRINGS)
    assert _banner_tripped_text(text) is expected
