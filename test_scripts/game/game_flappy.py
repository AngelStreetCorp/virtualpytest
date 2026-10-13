#!/usr/bin/env python3
"""
Flappy Bird showcase (TASK-33 phase 3c): VirtualPyTest flies Flappy Bird in real time on a web
host and reports pipes passed and loop latency as KPIs.

The device specifics live in the flappy-web userinterface (page, start, game-over check). Each
step of the loop (shared/src/lib/game/flappy/runner.py) is one execute_javascript action that
reads the bird, predicts its fall with the game's physics and schedules the next jump.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.game.flappy.runner import MARGIN_PX, UI_NAME, FlappyRunner, VptIO, kpi_metadata, summary

_script_args = [
    "--userinterface:str:" + UI_NAME,
    "--max_pipes:int:30",
    "--max_duration:int:180",
    "--min_pipes:int:10",
    f"--margin:int:{MARGIN_PX}",
]
_script_description = "Fly Flappy Bird in real time on a web host and report pipes and loop latency as KPIs."
_arg_descriptions = {
    'userinterface': f"The Flappy Bird userinterface ({UI_NAME})",
    'max_pipes': 'Pipe budget: the run stops steering there and passes',
    'max_duration': 'Hard stop in seconds: reaching it fails the run',
    'min_pipes': 'Pass floor for a run that ends with the bird dying',
    'margin': 'Pixels kept between the bird and the lower pipe when planning a jump',
}


@script("game_flappy", "Flappy Bird showcase: real-time play on a web host, pipes and latency as KPIs", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()
    context.userinterface = args.userinterface
    context.userinterface_name = args.userinterface

    tree = device.navigation_executor.load_navigation_tree(args.userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = f"Navigation tree loading failed: {tree.get('error', 'unknown error')}"
        context.overall_success = False
        context.execution_summary = summary({}, False, context.error_message)
        return False
    context.tree_id = tree["tree_id"]

    io = VptIO(device, context, context.tree_id, args.userinterface)
    data = FlappyRunner(io, context, int(args.max_pipes), int(args.max_duration), int(args.min_pipes),
                        int(args.margin)).run()

    context.metadata = kpi_metadata(data)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "Flappy Bird run failed"
    context.execution_summary = summary(data, context.overall_success, context.error_message or "")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "host_vnc",
}

if __name__ == "__main__":
    main()
