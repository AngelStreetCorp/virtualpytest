"""Run N Tello simulators on loopback: python -m shared.src.lib.drone.sim --drones 2"""

import argparse
import time

from .tello_sim import SimRegistry, TelloSim, sim_ip
from .world import START_SPOTS, default_room


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drones", type=int, default=2)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    room, reg = default_room(), SimRegistry()
    sims = []
    for i in range(1, args.drones + 1):
        pose = START_SPOTS[i].copy() if i in START_SPOTS else None
        s = TelloSim(room, i, sim_ip(i), state_port=8889 + i, video_port=11110 + i, fps=args.fps,
                     seed=args.seed, registry=reg, start_pose=pose)
        s.start()
        sims.append(s)
        print(f"drone {i}: cmd {sim_ip(i)}:8889  state->127.0.0.1:{8889 + i}  video->127.0.0.1:{11110 + i}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for s in sims:
            s.stop()


if __name__ == "__main__":
    main()
