#!/usr/bin/env python3
"""
Tetris showcase on any platform (TASK-33 phase 3 / TASK-51): one script for
web, Switch (G5), Android (G6). The device specifics live in the tetris-*
userinterface; the game specifics (rotation system, gravity, hard drop)
live in a game profile (jakesgordon / guideline). The runner reads the board
from the page's JS state (default) or from captured frames (--perception
vision) and plans placements with the El-Tetris heuristic.

G3 (vision mode): --perception vision reads a frame per piece, uses JS as
the oracle for accuracy KPIs, and demands >= 99% vision-cell-match.
G4 (predictive loop): --predict plans from the predicted court after each
placement; a mismatch with the next read forces a resync. Per-piece time
no longer includes the frame capture lag.
"""
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.game.tetris.profiles import rules_by_name
from shared.src.lib.game.tetris.runner import (UI_NAME, TetrisRunner, VptIO,
                                               kpi_metadata, resolve_profile,
                                               resolve_userinterface,
                                               resolve_vision_profile, summary)

_script_args = [
    "--userinterface:str:auto",
    "--perception:str:js:js|vision",
    "--profile:str:auto",
    "--predict:bool:false",
    "--max_pieces:int:100000",
    "--max_duration:int:3600",
    "--min_rows:int:10",
]
_script_description = "Play Tetris on any platform (web today, Switch / Android under the tetris-* family), using JS or vision as the state source."
_arg_descriptions = {
    'userinterface': "auto picks the tetris-* userinterface matching the device model (today: tetris-web for web/host_vnc).",
    'perception': "js: read state from the page (fast, web only); vision: read a captured frame and use JS as the oracle (any platform).",
    'profile': "auto picks the game profile from the userinterface (tetris-web -> jakesgordon; tetris-switch / tetris-android-mobile -> guideline).",
    'predict': "Plan the next piece from the predicted court after each placement. With --perception vision, frames confirm; without --predict, frames gate. Default off.",
    'max_pieces': "Piece budget: the run stops there and passes (rows floor only applies to full games); e.g. 50 for a quick test.",
    'max_duration': "Hard stop in seconds: reaching it fails the run.",
    'min_rows': "Pass floor for the rows cleared in a full game.",
}


@script("game_tetris",
        "Tetris showcase: real-time play on any platform with --userinterface auto and --perception js|vision",
        default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    userinterface = resolve_userinterface(args.userinterface, device.device_model, context.team_id)
    if not userinterface:
        context.error_message = f"No tetris-* userinterface matches device model '{device.device_model}'"
        context.overall_success = False
        context.execution_summary = summary({"device_model": device.device_model}, False, context.error_message)
        return False
    context.userinterface = userinterface
    context.userinterface_name = userinterface

    profile_name = args.profile if args.profile != "auto" else resolve_profile(userinterface)
    rules = rules_by_name(profile_name)
    vision_profile = resolve_vision_profile(profile_name) if args.perception == "vision" else None

    tree = device.navigation_executor.load_navigation_tree(userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = f"Navigation tree loading failed: {tree.get('error', 'unknown error')}"
        context.overall_success = False
        context.execution_summary = summary({"userinterface": userinterface, "profile": profile_name},
                                            False, context.error_message)
        return False
    context.tree_id = tree["tree_id"]

    io = VptIO(device, context, context.tree_id, userinterface)
    data = TetrisRunner(io, context, int(args.max_pieces), int(args.max_duration), int(args.min_rows),
                        perception=args.perception, rules=rules, vision_profile=vision_profile,
                        predict=bool(args.predict)).run()

    context.metadata = kpi_metadata(data)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "Tetris run failed"
    context.execution_summary = summary(data, context.overall_success, context.error_message or "")
    return context.overall_success


main._script_args = _script_args
# The web Tetris runs on a host's VNC host target (host_vnc / device_id="host");
# `tetris-switch` and `tetris-android-mobile` would target a real device. Allow both
# so the API /server/script/execute does not reject `host_name:host-clone-1 / host`.
main._target_rules = {
    "target_type": "all",
    "host_os": "all",
    "device_model": "all",
    # The web Tetris plays in this run's OWN Chrome (its own debug port and profile), the
    # same path the video checks use. Declaring it makes this run take one of the host's
    # browser slots instead of consuming a browser nobody counts - which is how one run an
    # hour piled up nine of them on host-clone-2 while the cap reported "0 running"
    # (BUG-0760).
    "browser_isolated": True,
}

if __name__ == "__main__":
    main()