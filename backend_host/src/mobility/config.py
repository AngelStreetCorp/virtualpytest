"""
Mobility configuration — env-driven, fail-safe defaults.

Every value is read through :meth:`MobilityConfig.from_env`, which returns a
fresh dataclass on every call. There is no global mutable state; tests can
``monkeypatch.setenv`` and observe the change immediately.

Garbage values (``"abc"``, ``""`` after the key is present) fall back to the
fail-safe default and emit a WARNING to stderr. This is the same pattern the
host uses for ``HOST_PORT`` and friends.

Default philosophy
------------------
Defaults are *small* (slow speeds, short durations, narrow geofence) so a
deployment that forgets to override anything stays inside a conservative
envelope. A rover that breaks because the operator forgot to tune a value is
a much smaller incident than a rover that breaks because the default was too
generous.

Namespacing
-----------
All env keys live under ``VPT_MOBILITY_*``. Don't reuse the prefix for any
other feature; ``VPT_HOST_*``, ``DEVICE*``, and ``BACKEND_HOST_*`` are taken.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Optional

# Defaults — kept here so unit tests can import them without going through env.
DEFAULTS = {
    "enabled": False,
    "max_speed_mps": 1.5,
    "max_turn_radps": 0.5,
    "max_duration_s": 30.0,
    "geofence_min_x": 0.0,
    "geofence_max_x": 200.0,
    "geofence_min_y": 0.0,
    "geofence_max_y": 50.0,
    "heartbeat_timeout_ms": 2000,
    "require_auth_token": True,
    "auth_token_max_age_s": 5,
    "nonce_window": 100,
}

_TRUE_TOKENS = ("1", "true", "yes", "on")


def _parse_float(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        print(
            f"[mobility:config] WARNING: {env_var}={raw!r} is not a float; "
            f"using default {default}",
            file=sys.stderr,
        )
        return default
    if not math.isfinite(value):
        print(
            f"[mobility:config] WARNING: {env_var}={raw!r} is not finite; "
            f"using default {default}",
            file=sys.stderr,
        )
        return default
    return value


def _parse_int(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(
            f"[mobility:config] WARNING: {env_var}={raw!r} is not an int; "
            f"using default {default}",
            file=sys.stderr,
        )
        return default


def _parse_bool(env_var: str, default: bool) -> bool:
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUE_TOKENS


@dataclass(frozen=True)
class MobilityConfig:
    """Snapshot of the mobility configuration at one moment in time.

    Frozen so a config value can't be mutated under a long-running command.
    Build a new instance with :meth:`from_env` if the env changes.
    """

    enabled: bool
    max_speed_mps: float
    max_turn_radps: float
    max_duration_s: float
    geofence_min_x: float
    geofence_max_x: float
    geofence_min_y: float
    geofence_max_y: float
    heartbeat_timeout_ms: int
    require_auth_token: bool
    auth_token_max_age_s: int
    nonce_window: int

    @classmethod
    def from_env(cls) -> "MobilityConfig":
        """Read all ``VPT_MOBILITY_*`` env vars and return a fresh snapshot."""
        return cls(
            enabled=_parse_bool("VPT_MOBILITY_ENABLED", DEFAULTS["enabled"]),
            max_speed_mps=_parse_float(
                "VPT_MOBILITY_MAX_SPEED_MPS", DEFAULTS["max_speed_mps"]
            ),
            max_turn_radps=_parse_float(
                "VPT_MOBILITY_MAX_TURN_RADPS", DEFAULTS["max_turn_radps"]
            ),
            max_duration_s=_parse_float(
                "VPT_MOBILITY_MAX_DURATION_S", DEFAULTS["max_duration_s"]
            ),
            geofence_min_x=_parse_float(
                "VPT_MOBILITY_GEOFENCE_MIN_X", DEFAULTS["geofence_min_x"]
            ),
            geofence_max_x=_parse_float(
                "VPT_MOBILITY_GEOFENCE_MAX_X", DEFAULTS["geofence_max_x"]
            ),
            geofence_min_y=_parse_float(
                "VPT_MOBILITY_GEOFENCE_MIN_Y", DEFAULTS["geofence_min_y"]
            ),
            geofence_max_y=_parse_float(
                "VPT_MOBILITY_GEOFENCE_MAX_Y", DEFAULTS["geofence_max_y"]
            ),
            heartbeat_timeout_ms=_parse_int(
                "VPT_MOBILITY_HEARTBEAT_TIMEOUT_MS",
                DEFAULTS["heartbeat_timeout_ms"],
            ),
            require_auth_token=_parse_bool(
                "VPT_MOBILITY_REQUIRE_AUTH_TOKEN",
                DEFAULTS["require_auth_token"],
            ),
            auth_token_max_age_s=_parse_int(
                "VPT_MOBILITY_AUTH_TOKEN_MAX_AGE_S",
                DEFAULTS["auth_token_max_age_s"],
            ),
            nonce_window=_parse_int(
                "VPT_MOBILITY_NONCE_WINDOW", DEFAULTS["nonce_window"]
            ),
        )

    # Convenience accessors ---------------------------------------------------

    @property
    def geofence_configured(self) -> bool:
        """A geofence is considered configured when at least one bound is non-zero.

        The default rectangle is 0..200 / 0..50 (a real 200m sidewalk
        segment). Treating "all zero" as unconfigured lets an operator
        ``unset`` the bounds to force the gate to fail-closed rather than
        silently grant a "no geofence" override.
        """
        return not (
            self.geofence_min_x == 0.0
            and self.geofence_max_x == 0.0
            and self.geofence_min_y == 0.0
            and self.geofence_max_y == 0.0
        )

    def is_inside_geofence(self, x: float, y: float) -> bool:
        """True iff (x, y) is inside the configured rectangle (inclusive bounds)."""
        if not self.geofence_configured:
            return False  # Unconfigured -> nothing is "inside".
        return (
            self.geofence_min_x <= x <= self.geofence_max_x
            and self.geofence_min_y <= y <= self.geofence_max_y
        )