#!/usr/bin/env python3
"""
Run a drone demo (hide and seek, or the find-the-object race) from the command line.

Default: against two in-process Tello simulators on loopback, no hardware, HTML report.
--real: no simulators; drone i is reached at 10.200.i.2 (or --ip1/--ip2) with the production client.

  python3 test_scripts/drone/local/run_local.py --game race --target sofa --seed 1
  python3 test_scripts/drone/local/run_local.py --game hide --perception aruco
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.src.lib.drone.agents import HiderAgent, LlmAgent, ScanAgent  # noqa: E402
from shared.src.lib.drone.games import KILL_FILE, HideAndSeekGame, ObjectRaceGame  # noqa: E402
from shared.src.lib.drone.io import LocalDroneIO  # noqa: E402
from shared.src.lib.drone.perception import (ArucoDetector, CocoDetector, SimColorDetector, VlmDetector,  # noqa: E402
                                             sim_scene_hint)
from shared.src.lib.drone.referee import Referee  # noqa: E402
from shared.src.lib.drone.report import HtmlReporter  # noqa: E402
from shared.src.lib.drone.roommap import RoomMap  # noqa: E402
from shared.src.lib.drone.safety import SafetyLimits  # noqa: E402
from shared.src.lib.drone.sim.world import HIDE_SPOTS, START_SPOTS, Pose, default_room  # noqa: E402
from shared.src.lib.drone.tello import TelloClient, tello_endpoints  # noqa: E402
from shared.src.lib.drone.video import FrameGrabber  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", choices=["hide", "race"], default="race")
    ap.add_argument("--target", default="sofa", help="race target (sofa, tv, plant, chair, table)")
    ap.add_argument("--perception", choices=["auto", "aruco", "color", "coco", "vlm"], default="auto")
    ap.add_argument("--agent", choices=["scan", "llm"], default="scan")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--report_dir", default=None, help="default /tmp/vpt-drone-reports/<timestamp>")
    ap.add_argument("--drones", type=int, choices=[1, 2], default=2, help="race only: 1 = single-drone race")
    ap.add_argument("--sim_speed", type=float, default=4.0, help="simulator motion speed multiplier")
    ap.add_argument("--real", action="store_true", help="real drones, no simulators")
    ap.add_argument("--ip1", default=None)
    ap.add_argument("--ip2", default=None)
    ap.add_argument("--start1", default=None, help="x,y,yaw of drone 1 (default sim START_SPOTS)")
    ap.add_argument("--start2", default=None)
    ap.add_argument("--room_map", default=None,
                    help="JSON room map with obstacles (see room_example.json). Default: the simulated room's map; "
                         "REQUIRED with --real")
    ap.add_argument("--room_w", type=float, default=None, help="default: the room map's width (600)")
    ap.add_argument("--room_d", type=float, default=None, help="default: the room map's depth (500)")
    ap.add_argument("--max_height", type=float, default=150)
    ap.add_argument("--hide_s", type=float, default=None, help="default 60 real, 20 simulated")
    ap.add_argument("--seek_s", type=float, default=180)
    ap.add_argument("--timeout_s", type=float, default=180, help="race timeout")
    ap.add_argument("--penalty_s", type=float, default=3.0)
    ap.add_argument("--kill_file", default=KILL_FILE, help="create this file to cut the motors of every drone")
    ap.add_argument("--countdown_s", type=int, default=5, help="--real: countdown before takeoff")
    ap.add_argument("--ai_usage", default="vision.drone",
                    help="AI usage for --perception vlm / --agent llm (a server without vision.drone yet: vision)")
    ap.add_argument("--env_file", default=os.path.join(REPO_ROOT, ".env"),
                    help="loaded for --perception vlm / --agent llm (server URL and key of the AI gateway)")
    args = ap.parse_args(argv)
    if (args.perception == "vlm" or args.agent == "llm") and os.path.exists(args.env_file):
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    return args


def _pose(spec, default):
    if not spec:
        return default
    x, y, yaw = (float(v) for v in spec.split(","))
    return Pose(x, y, 0, yaw)


def build_perception(args):
    """(agent perception, referee, label). The referee verifier is stricter than the agent's."""
    kind = args.perception
    if kind == "auto":
        kind = "aruco" if args.game == "hide" else ("coco" if args.real else "color")
    if args.game == "hide" and kind in ("color", "coco"):
        raise SystemExit(f"--perception {kind} cannot find a drone: use aruco or vlm for --game hide")
    if kind == "aruco":
        return ArucoDetector(8), Referee(ArucoDetector(12), min_confidence=0.8), kind
    if kind == "color":
        return SimColorDetector(600), Referee(SimColorDetector(1500), min_confidence=0.35), kind
    if kind == "coco":
        return CocoDetector(min_conf=0.35), Referee(CocoDetector(min_conf=0.5), min_confidence=0.5), kind
    hint = "" if args.real else sim_scene_hint()
    return (VlmDetector(0.5, args.ai_usage, hint),
            Referee(VlmDetector(0.8, args.ai_usage, hint), min_confidence=0.8), kind)


def build_agent(args, perception, limits):
    scan = ScanAgent(perception, limits, claim_conf=0.85 if perception.name == "aruco" else 0.5)
    return LlmAgent(limits, scan, usage=args.ai_usage) if args.agent == "llm" else scan


def preflight(ios, limits, countdown_s):
    """--real: show battery and temperature of every drone, refuse on a failed gate, then count down."""
    bad = []
    for io in ios:
        end = time.time() + 5
        while not io.telemetry() and time.time() < end:
            time.sleep(0.2)
        t = io.telemetry()
        bat, temp = t.get("bat"), t.get("temph")
        print(f"{io.name}: battery {bat}%  temperature {temp}C")
        if bat is None or bat < limits.bat_takeoff:
            bad.append(f"{io.name}: battery {bat}% below {limits.bat_takeoff}%")
        if temp is None or temp >= limits.temp_max:
            bad.append(f"{io.name}: temperature {temp}C (limit {limits.temp_max}C)")
    if bad:
        raise SystemExit("pre-flight failed, not taking off: " + "; ".join(bad))
    for i in range(countdown_s, 0, -1):
        print(f"takeoff in {i} ... (touch {KILL_FILE} to cut the motors)", flush=True)
        time.sleep(1)


def main(argv=None) -> dict:
    args = parse_args(argv)
    n = 2 if args.game == "hide" else args.drones
    if args.real and not args.room_map:
        raise SystemExit("--real needs --room_map <json>: the guard must know the furniture before it flies "
                         "(copy test_scripts/drone/local/room_example.json and edit it)")
    room = default_room()
    room_map = RoomMap.load(args.room_map) if args.room_map else RoomMap.from_sim_room(room)
    limits = SafetyLimits(room_w=args.room_w or room_map.width, room_d=args.room_d or room_map.depth,
                          max_h=args.max_height, room_map=room_map)
    out_dir = args.report_dir or os.path.join("/tmp/vpt-drone-reports", datetime.now().strftime("%Y%m%d-%H%M%S"))
    if os.path.exists(args.kill_file):
        print(f"removing stale kill file {args.kill_file}")
        os.remove(args.kill_file)
    sims, ios = [], []
    try:
        if args.real:
            endpoints = [tello_endpoints(i) for i in range(1, n + 1)]
            for i, ip in ((1, args.ip1), (2, args.ip2)):
                if ip and i <= n:
                    endpoints[i - 1]["ip"] = ip
            local_ip, urls = "0.0.0.0", [f"udp://0.0.0.0:{e['video_port']}" for e in endpoints]
        else:
            from shared.src.lib.drone.sim.tello_sim import SimRegistry, TelloSim, sim_ip
            reg = SimRegistry()
            endpoints = [dict(tello_endpoints(i, sim_ip(i))) for i in range(1, n + 1)]
            local_ip, urls = "127.0.0.1", [f"udp://127.0.0.1:{e['video_port']}" for e in endpoints]
            for i, e in enumerate(endpoints, 1):
                s = TelloSim(room, i, e["ip"], state_port=e["state_port"], video_port=e["video_port"],
                             seed=args.seed + i, registry=reg, start_pose=_pose(getattr(args, f"start{i}", None),
                                                                              START_SPOTS[i]).copy(),
                             time_scale=args.sim_speed)
                s.speed = 50.0 * args.sim_speed
                s.start()
                sims.append(s)
        start_poses = {i: _pose(getattr(args, f"start{i}", None), START_SPOTS[i]) for i in (1, 2)}
        for i, (e, url) in enumerate(zip(endpoints, urls), 1):
            grabber = FrameGrabber(url)
            grabber.start()
            client = TelloClient(e["ip"], e["cmd_port"], e["state_port"], local_ip=local_ip, name=f"drone{i}")
            client.connect()
            client.send("streamon")
            ios.append(LocalDroneIO(client, grabber, f"drone{i}", i))
        if args.real:
            preflight(ios, limits, args.countdown_s)
        perception, referee, kind = build_perception(args)
        reporter = HtmlReporter(out_dir)
        common = dict(limits=limits, reporter=reporter, referee=referee, perception=perception,
                      start_poses=start_poses, kill_file=args.kill_file)
        if args.game == "race":
            agents = [build_agent(args, perception, limits) for _ in ios]
            game = ObjectRaceGame(ios, agents, target=args.target, timeout_s=args.timeout_s,
                                  penalty_s=args.penalty_s, **common)
        else:
            # The simulator's hiding spots are sim-room coordinates; a real room uses the map instead.
            hider = HiderAgent(limits, start_poses[2], None if args.real else HIDE_SPOTS, start=start_poses[1])
            seeker = build_agent(args, perception, limits)
            hide_s = args.hide_s if args.hide_s is not None else (60 if args.real else 20)
            game = HideAndSeekGame(ios[0], ios[1], hider, seeker, hide_s=hide_s, seek_s=args.seek_s, **common)
        kpis = game.run()
        print(json.dumps(kpis, indent=2, default=str))
        print(f"report: {kpis.get('report')}")
        return kpis
    finally:
        for io in ios:
            io.close()
        for s in sims:
            s.stop()


if __name__ == "__main__":
    main()
