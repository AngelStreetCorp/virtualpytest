"""
Clash of Clans menu-driven farm-bot library (TASK-81 §81.1 v1).

The split mirrors the rest of ``shared/src/lib/game/<name>/``:

* ``vision``  -- pure pixel reads on a BGR frame, says ``None`` when it cannot tell
* ``tactics`` -- ``VillageObservation -> Action``, the priority chain
                 (``collect_ready_collectors`` ... ``idle``), never ``Attack``
* ``menus``   -- ``cross_to(obs, target) -> list[Action]``: a screen-graph
                 navigator that only ever taps safe surfaces
                 (never a buy / purchase / gem / pass / offer / subscribe)
* ``runner``  -- the loop, the KPIs, the §R5 account-warning guard, the lease

Only the runner imports controllers or talks to a device. ``vision``,
``tactics`` and ``menus`` are pure functions and unit-testable on
synthetic frames (per TASK-81 §81.1.4).
"""

from . import menus, runner, tactics, video, vision  # noqa: F401
