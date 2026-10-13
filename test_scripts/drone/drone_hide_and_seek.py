#!/usr/bin/env python3
"""
Drone hide and seek (TASK-32): two Ryze/DJI Tello drones are two ordinary VirtualPyTest devices
(model `tello`). One drone hides, the other searches; the platform judges the result from a fresh
captured frame. Commands go through the remote controller (every move guarded), frames come from the
device captures, and each drone is driven by its own agent. See drone_hide_and_seek.md.
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
from shared.src.lib.drone.agents import HiderAgent
from shared.src.lib.drone.games import HideAndSeekGame
from shared.src.lib.drone.referee import Referee

_script_args = [
    "--peer_device:str:device2",
    "--hider:str:self:self|peer",
    "--room_map:str:",
    "--room_w:int:600",
    "--room_d:int:500",
    "--max_height:int:150",
    "--perception:str:auto:auto|aruco|vlm",
    "--agent:str:scan:scan|llm",
    "--hide_s:int:60",
    "--seek_s:int:180",
    "--start1:str:",
    "--start2:str:",
]
_script_description = "Two Tello drones play hide and seek; the referee confirms the find from a fresh frame."
_arg_descriptions = {
    "peer_device": "The second drone's device id (device_model tello); the selected --device is drone 1",
    "hider": "Which drone hides: self (the selected device, drone 1) or peer (--peer_device, drone 2)",
    "room_map": "Path of the room map JSON (walls and furniture the guard keeps the drones away from), or sim for the simulator. Required",
    "room_w": "Room width in cm (x); the geofence is the room minus a 50 cm margin",
    "room_d": "Room depth in cm (y)",
    "max_height": "Ceiling in cm for both drones",
    "perception": "How the seeker and the referee recognise the hider: auto/aruco (marker taped on the drone) or vlm (vision model)",
    "agent": "scan: rotate in 45 degree steps, then fly to the nearest unvisited waypoint; no model, no cost. llm: same scan, but a text-only model picks WHICH waypoint to search next from the room map and what the camera saw (falls back to the nearest one)",
    "hide_s": "Seconds the hider has to reach its hiding place",
    "seek_s": "Seconds the seeker has to find it",
    "start1": "Drone 1 start spot 'x,y,yaw' in cm and degrees (empty: 100,100,0). Both drones start landed",
    "start2": "Drone 2 start spot 'x,y,yaw' (empty: 500,100,0)",
}


def _fail(context, message):
    context.error_message = message
    context.overall_success = False
    context.execution_summary = f"Drone hide and seek: {message}"
    print(f"[drone_hide_and_seek] {message}")
    return False


@script("drone_hide_and_seek", "Two Tello drones play hide and seek, judged from captured frames", default_device="device1")
def main():
    args, context, device = get_args(), get_context(), get_device()
    ios = []
    try:
        ios, spots, limits, reporter = pio.setup_drones(context, device, args, count=2)
        hider_io, seeker_io = (ios[0], ios[1]) if args.hider == "self" else (ios[1], ios[0])
        detector, ref_detector, ref_conf = pio.make_perception(args.perception, "hide")
        game = HideAndSeekGame(
            hider_io, seeker_io,
            HiderAgent(limits, seeker_start=spots[seeker_io.index], start=spots[hider_io.index]),
            pio.make_seek_agent(args.agent, detector, limits),
            detector, Referee(ref_detector, min_confidence=ref_conf), reporter, limits,
            hide_s=args.hide_s, seek_s=args.seek_s, start_poses=spots)
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
    kpis["hider"] = hider_io.name
    kpis["seeker"] = seeker_io.name
    kpis["room_cm"] = [args.room_w, args.room_d]
    context.metadata = kpis
    # A confirmed result: the seeker's find confirmed by the referee, or the hider holding out until
    # the timeout. Aborted runs (kill file, guard landing, error) have no winner and fail.
    context.overall_success = bool(kpis.get("winner")) and bool(kpis.get("landed")) and not kpis.get("killed")
    if not context.overall_success and not context.error_message:
        context.error_message = ("aborted: " + ("operator kill" if kpis.get("killed") else "a drone was landed by a guard or error")
                                 if not kpis.get("winner") else "drones not confirmed landed")
    if kpis.get("winner") == seeker_io.name:
        outcome = f"{seeker_io.name} found {hider_io.name} in {kpis.get('time_to_win_s')}s"
    elif kpis.get("winner"):
        outcome = f"{hider_io.name} stayed hidden for {args.seek_s}s"
    else:
        outcome = "no result"
    context.execution_summary = (f"Drone hide and seek: {outcome} | commands {kpis.get('commands_sent')} | "
                                 f"guard blocks {kpis.get('guard_blocks')} | claims {kpis.get('claims')} "
                                 f"(false {kpis.get('false_claims')}) | perception {kpis.get('perception')}")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {"target_type": "device", "host_os": "all", "device_model": "tello"}

if __name__ == "__main__":
    main()
