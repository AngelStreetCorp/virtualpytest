#!/usr/bin/env python3
"""
Tetris showcase (TASK-33 phase 3): VirtualPyTest plays Tetris in real time on a web host and
reports rows, score and speed as KPIs.

The device specifics live in the tetris-web userinterface (keys in action nodes, checks on the
game / game_over nodes). The game loop (shared/src/lib/game/tetris/runner.py) reads the page
state once per piece, picks the placement with a fixed heuristic, and sends the keys in one
batch through the action executor. At the end the court is read from the captured pixels and
compared with the page.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.game.tetris.runner import UI_NAME, TetrisRunner, VptIO, kpi_metadata, summary

_script_args = [
    "--userinterface:str:" + UI_NAME,
    "--max_pieces:int:100000",
    "--max_duration:int:3600",
    "--min_rows:int:10",
]
_script_description = "Play Tetris in real time on a web host and report rows, score and speed as KPIs."
_arg_descriptions = {
    'userinterface': f"The Tetris userinterface ({UI_NAME})",
    'max_pieces': 'Piece budget: the run stops there and passes (the rows floor only applies to full games); e.g. 50 for a quick test',
    'max_duration': 'Hard stop in seconds: reaching it fails the run',
    'min_rows': 'Pass floor for the rows cleared in a full game',
}


@script("game_tetris", "Tetris showcase: real-time play on a web host, rows and speed as KPIs", default_device="device1")
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
    data = TetrisRunner(io, context, int(args.max_pieces), int(args.max_duration), int(args.min_rows)).run()

    context.metadata = kpi_metadata(data)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "Tetris run failed"
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
