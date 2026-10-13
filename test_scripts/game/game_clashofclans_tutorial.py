#!/usr/bin/env python3
"""
Clash of Clans tutorial driver (§81.1.10) — dedicated bot skill for fresh accounts.

Wraps the existing ``GameRunner`` with a runner config tuned to clear
the Supercell tutorial:

* ``--max_runtime 1800`` (30 min) — long enough for the full tutorial
  including the manual attack handoff.
* ``--max_cycles 60`` — the tutorial has ~10 driver steps, each takes
  a few cycles, so 60 cycles gives plenty of slack.
* ``--attack_opt_in false`` — the §R1 lock stays on; the tutorial
  attack is the operator's job (see ``tutorial.attack_tutorial``).
* ``--idle_minutes 30`` — the driver parks on manual-handoff steps
  instead of going idle.

The script logs every step transition + manual handoff to the run
report (via ``runner.log``) so the operator can see exactly where the
bot stopped and what to do next.

Usage::

    POST /server/script/execute script=game_clashofclans_tutorial \
        userinterface=clashofclans-android-mobile

When the driver reaches ``complete`` the script exits with
``overall_success=True`` and the next ``game_clashofclans`` run on the
same device can take over with the §81.1.2 chain.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context, get_device

try:
    from shared.src.lib.game.clashofclans.runner import (
        GameRunner,
        RunnerConfig,
        kpi_metadata,
        resolve_userinterface,
        summary,
    )
    _HAS_RUNNER = True
    _IMPORT_ERROR = ""
except ImportError as _exc:
    GameRunner = None
    RunnerConfig = None
    kpi_metadata = None
    resolve_userinterface = None
    summary = None
    _HAS_RUNNER = False
    _IMPORT_ERROR = str(_exc)


_script_args = [
    "--userinterface:str:auto",
    "--max_runtime:int:1800",
    "--max_cycles:int:60",
    "--donate_policy:str:always:always|on_requested|never",
    "--collect_policy:str:ready:ready|aggressive|never",
    "--attack_opt_in:bool:false",     # §R1: tutorial attack is MANUAL only
    "--dry_run:bool:false",
]
_script_description = (
    "Clash of Clans tutorial driver (TASK-81 §81.1.10): progresses a "
    "fresh village through Supercell's welcome / build / place / attack "
    "tutorial dialogs. Manual handoff on the first attack (§R1) and on "
    "the clan join step (§81.1.10). When the script succeeds the next "
    "game_clashofclans run on this device can use the §81.1.2 chain."
)
_arg_descriptions = {
    "userinterface": "auto picks the clashofclans-android-mobile bundle",
    "max_runtime": "Hard stop in seconds (default 30 min covers tutorial)",
    "max_cycles": "Max cycles (~6x the 10 driver steps for slack)",
    "donate_policy": "ignored on tutorial accounts (no clan yet)",
    "collect_policy": "ignored on tutorial accounts (collect starts post-tutorial)",
    "attack_opt_in": "FALSE — the §81.1.10 tutorial attack is MANUAL only",
    "dry_run": "Walk the tree without invoking real actions (smoke test)",
}


@script("game_clashofclans_tutorial", _script_description, default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    if not _HAS_RUNNER:
        context.error_message = (
            "shared.src.lib.game.clashofclans.runner not available: "
            + _IMPORT_ERROR)
        context.overall_success = False
        context.execution_summary = (
            "GAME_CLASHOFCLANS_TUTORIAL SUMMARY\n"
            "Runner module missing.")
        return False

    userinterface = resolve_userinterface(args.userinterface,
                                          device.device_model,
                                          context.team_id)
    if not userinterface:
        context.error_message = (
            f"No clashofclans-* userinterface matches device model "
            f"'{device.device_model}'")
        context.overall_success = False
        context.execution_summary = summary({"device_model": device.device_model},
                                             False, context.error_message)
        return False
    context.userinterface = userinterface
    context.userinterface_name = userinterface

    tree = device.navigation_executor.load_navigation_tree(
        userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = (
            f"Navigation tree loading failed: {tree.get('error', 'unknown')}")
        context.overall_success = False
        context.execution_summary = summary({"userinterface": userinterface},
                                             False, context.error_message)
        return False
    context.tree_id = tree["tree_id"]

    # Configure for tutorial: long runtime, low cycles, NEVER auto-attack.
    data = GameRunner(
        device, context, userinterface, context.tree_id,
        config=RunnerConfig(
            max_runtime_s=int(args.max_runtime),
            max_cycles=int(args.max_cycles),
            donate_policy="auto",
            collect_policy="auto",
            attack_opt_in=False,           # §R1
            dry_run=bool(args.dry_run),
            shop_free_claim=False,
        ),
    ).run()

    context.metadata = kpi_metadata(data)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "Tutorial run failed"
    context.execution_summary = summary(data, context.overall_success,
                                        context.error_message or "")

    # §81.1.10 success gating: we want the tutorial driver to have
    # reached "complete" before we call this a success.
    if not data.get("tutorial_complete"):
        context.overall_success = False
        if not context.error_message:
            context.error_message = (
                f"tutorial did not reach complete (stopped at "
                f"{data.get('tutorial_current_step', '?')!r})")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}


if __name__ == "__main__":
    main()
