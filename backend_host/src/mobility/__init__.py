"""
VPT Mobility — opt-in foundation (TASK-78 PR 1).

A self-contained backend_host service that lets a simulated (and later,
physical) rover run a deterministic sidewalk-accessibility mission through
a uniform controller interface, guarded by an explicit SafetyGate.

PR 1 ships:
- the configuration loader,
- the data models (RoverCommand, RoverState, MobilityMission, MobilityResult,
  MobilityObservation),
- the SafetyGate (every rule, every edge case),
- the controller Protocol + BaseMobilityController,
- the deterministic FakeMobilityController,
- a thin Flask blueprint (`/host/mobility/*`) registered only when
  `VPT_MOBILITY_ENABLED=true`.

It deliberately does NOT add a "mobility" slot to DEVICE_CONTROLLER_MAP,
does NOT touch the device model, and does NOT add new top-level deps.

Activation flag
---------------
``VPT_MOBILITY_ENABLED`` is read on every call to :func:`is_enabled` (the
gate evaluates the flag at evaluation time, not at import time — env flags
are process-scoped by definition). Default: ``false``.

Lazy imports
------------
Importing this package MUST NOT import ROS 2, Gazebo, or any other optional
heavyweight dependency. The Gazebo/ROS 2 adapter (PR 2) will live in its
own submodule and will only be loaded when the user opts in to it.

Namespacing
-----------
Every key (`VPT_MOBILITY_*` env var, route prefix `/host/mobility`,
permission `mobility:run`, log tag `[mobility]`, metric prefix) is namespaced
under ``mobility`` so a future feature flag cannot collide with this one.
"""
from __future__ import annotations

import os
from typing import Optional

# Public surface — re-exported lazily to keep `import backend_host.src.mobility`
# a no-op when the flag is off (the heavy modules aren't loaded unless asked
# for explicitly).
#
# Note: the function ``current_config`` deliberately does NOT share a name
# with the ``config`` submodule; Python rebinds the package attribute to
# the submodule on `from .config import ...`, which would silently shadow
# the function. Callers that want the helper should ``import
# backend_host.src.mobility as m; m.current_config()``.
__all__ = [
    "is_enabled",
    "current_config",
    # model / safety / adapter symbols are intentionally NOT imported here;
    # callers reach them through the submodules so an accidental import of the
    # package cannot trigger a heavyweight load.
]

# Default value used when the env var is unset. Fail-safe defaults are
# documented in MobilityConfig below.
_ENABLED_DEFAULTS = ("1", "true", "yes", "on")


def _read_enabled() -> bool:
    """Read ``VPT_MOBILITY_ENABLED`` from the process env on every call.

    Process-scoped (matches how every other env flag in the platform works:
    a runtime change requires a restart). Reading on every call keeps the
    helper testable with ``monkeypatch.setenv`` and gives the gate a single,
    obvious place to branch on.
    """
    raw = os.environ.get("VPT_MOBILITY_ENABLED", "")
    if not raw:
        return False
    return raw.strip().lower() in _ENABLED_DEFAULTS


def is_enabled() -> bool:
    """Return whether the mobility feature is enabled in this process."""
    return _read_enabled()


# Lazy config singleton. Re-read on every call so a unit test can monkeypatch
# env vars and observe the change without re-importing the package.
def current_config() -> "MobilityConfig":
    """Build a fresh MobilityConfig from the current process environment.

    Returns a new instance on every call (cheap; just env reads + int/float
    parsing). Callers that need a long-lived copy should hold it themselves.
    """
    from .config import MobilityConfig  # local import to avoid circular

    return MobilityConfig.from_env()