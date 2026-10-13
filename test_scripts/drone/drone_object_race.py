#!/usr/bin/env python3
"""
Drone object race (TASK-32): two Ryze/DJI Tello drones, two ordinary VirtualPyTest devices (model
`tello`), search the room for the same object at the same time. A drone claims when it sees it; the
platform referee re-checks a fresh frame from that drone and the first confirmed claim wins.
See drone_object_race.md.
"""

import os
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.drone import platform_io as pio
from shared.src.lib.drone.games import ObjectRaceGame
from shared.src.lib.drone.referee import Referee

_script_args = [
    "--peer_device:str:device2",
    "--target:str:sofa",
    "--room_map:str:",
    "--room_w:int:600",
    "--room_d:int:500",
    "--max_height:int:150",
    "--perception:str:auto:auto|coco|vlm",
    "--agent:str:scan:scan|llm",
    "--timeout_s:int:180",
    "--start1:str:",
    "--start2:str:",
]
_script_description = "Two Tello drones race to find the same object; the referee confirms the first claim from a fresh frame."
_arg_descriptions = {
    "peer_device": "The second drone's device id (device_model tello); the selected --device is drone 1",
    "target": "Object to find: sofa, tv, plant, chair, table (any COCO class name with a COCO model)",
    "room_map": "Path of the room map JSON (walls and furniture the guard keeps the drones away from), or sim for the simulator. Required",
    "room_w": "Room width in cm (x); the geofence is the room minus a 50 cm margin",
    "room_d": "Room depth in cm (y)",
    "max_height": "Ceiling in cm for both drones",
    "perception": "auto: COCO detector when DRONE_COCO_MODEL points at an ONNX model, else the vision model. coco / vlm force one",
    "agent": "scan: rotate in 45 degree steps, then fly to the nearest unvisited waypoint; no model, no cost. llm: same scan, but a text-only model picks WHICH waypoint to search next from the room map and what the camera saw (falls back to the nearest one)",
    "timeout_s": "Seconds before the race ends with no winner",
    "start1": "Drone 1 start spot 'x,y,yaw' in cm and degrees (empty: 100,100,0). Both drones start landed",
    "start2": "Drone 2 start spot 'x,y,yaw' (empty: 500,100,0)",
}


def _fail(context, message):
    context.error_message = message
    context.overall_success = False
    context.execution_summary = f"Drone object race: {message}"
    print(f"[drone_object_race] {message}")
    return False


@script("drone_object_race", "Two Tello drones race to find an object, judged from captured frames", default_device="device1")
def main():
    args, context, device = get_args(), get_context(), get_device()
    ios = []
    try:
        ios, spots, limits, reporter = pio.setup_drones(context, device, args, count=2)
        detector, ref_detector, ref_conf = pio.make_perception(args.perception, "race")
        # One agent per drone: each keeps its own visited cells and waypoint.
        agents = [pio.make_seek_agent(args.agent, detector, limits) for _ in ios]
        game = ObjectRaceGame(ios, agents, detector, Referee(ref_detector, min_confidence=ref_conf), reporter,
                              limits, target=args.target, timeout_s=args.timeout_s, start_poses=spots)
    except ValueError as e:
        pio.release_drones(ios)
        return _fail(context, str(e))
    except Exception as e:
        pio.release_drones(ios)
        return _fail(context, f"setup failed: {e}")

    t0 = time.time()
    kpis = {}
    try:
        kpis = game.run()
    except Exception as e:
        _fail(context, f"game aborted: {e}")
    finally:
        if not kpis.get("landed"):
            for io in ios:
                io.close()  # land on any error, Ctrl-C or script stop
        pio.release_drones(ios)

    kpis["game_duration_s"] = round(time.time() - t0, 1)
    kpis["room_cm"] = [args.room_w, args.room_d]
    context.metadata = kpis
    # A confirmed result only: a winner the referee confirmed, with both drones back on the ground.
    context.overall_success = bool(kpis.get("winner")) and bool(kpis.get("landed")) and not kpis.get("killed")
    if not context.overall_success and not context.error_message:
        context.error_message = ("operator kill" if kpis.get("killed")
                                 else "no confirmed winner before the timeout" if not kpis.get("winner")
                                 else "drones not confirmed landed")
    if kpis.get("winner"):
        outcome = f"{kpis['winner']} found the {args.target} in {kpis.get('time_to_win_s')}s"
    else:
        outcome = f"no winner in {args.timeout_s}s"
    context.execution_summary = (f"Drone object race: {outcome} | commands {kpis.get('commands_sent')} | "
                                 f"guard blocks {kpis.get('guard_blocks')} | claims {kpis.get('claims')} "
                                 f"(false {kpis.get('false_claims')}) | perception {kpis.get('perception')}")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {"target_type": "device", "host_os": "all", "device_model": "tello"}

if __name__ == "__main__":
    main()
