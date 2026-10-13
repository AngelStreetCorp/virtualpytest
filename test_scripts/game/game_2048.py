#!/usr/bin/env python3
"""
2048 showcase (TASK-33): VirtualPyTest plays 2048 on any device and reports the score as a KPI.

One script for every platform. The device-specific parts live in the userinterface
(game2048-web: keyboard in a browser; game2048-android-mobile: swipes in Chrome on a
phone) and the device is driven only through the navigation executor. The board is read
from captured frames (shared/src/lib/game2048/reader.py), and each move is chosen by an
LLM (AI usage text.game_2048) or by a fixed heuristic.
"""

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.game2048.player import heuristic_decide, make_llm_decider
from shared.src.lib.game2048.runner import GameRunner, kpi_metadata, resolve_userinterface, summary

_script_args = [
    "--userinterface:str:auto",
    "--player:str:llm:llm|heuristic",
    "--max_moves:int:3000",
    "--max_duration:int:3600",
    "--min_score:int:500",
    "--min_tile:int:64",
]
_script_description = "Play 2048 on any device (web or phone) and report score, moves and AI usage as KPIs."
_arg_descriptions = {
    'userinterface': "auto picks the game2048-* userinterface matching the device model (game2048-web, game2048-android-mobile)",
    'player': 'llm: the model routed for AI usage text.game_2048 picks each move; heuristic: fixed LEFT>DOWN>RIGHT>UP',
    'max_moves': 'Move budget: the run stops there and passes (floors only apply to full games); e.g. 10 for a quick test',
    'max_duration': 'Hard stop in seconds: reaching it fails the run',
    'min_score': 'Pass floor for the final score of a full game',
    'min_tile': 'Pass floor for the highest tile of a full game',
}


@script("game_2048", "2048 showcase: play on any device, score and AI usage as KPIs", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    userinterface = resolve_userinterface(args.userinterface, device.device_model, context.team_id)
    if not userinterface:
        context.error_message = f"No game2048-* userinterface matches device model '{device.device_model}'"
        context.overall_success = False
        context.execution_summary = summary({"device_model": device.device_model}, False, context.error_message)
        return False
    context.userinterface = userinterface
    context.userinterface_name = userinterface

    tree = device.navigation_executor.load_navigation_tree(userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = f"Navigation tree loading failed: {tree.get('error', 'unknown error')}"
        context.overall_success = False
        context.execution_summary = summary({"userinterface": userinterface}, False, context.error_message)
        return False
    context.tree_id = tree["tree_id"]

    decide = make_llm_decider(context.team_id) if args.player == "llm" else heuristic_decide
    data = GameRunner(
        device, context, userinterface, context.tree_id, decide, args.player,
        int(args.max_moves), int(args.max_duration), int(args.min_score), int(args.min_tile),
    ).run()

    context.metadata = kpi_metadata(data)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "2048 run failed"
    context.execution_summary = summary(data, context.overall_success, context.error_message or "")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
