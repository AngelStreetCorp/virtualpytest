# Drone demos on your laptop (no drone)

`run_local.py` runs the hide-and-seek and find-the-object-race demos against two in-process Tello
simulators (`shared/src/lib/drone/sim/`) on loopback, with the production `TelloClient` and ffmpeg frame
grabber, and writes an HTML report (frames + timeline). Needs `ffmpeg`, `numpy`, `opencv` (with `aruco`).

```bash
python3 test_scripts/drone/local/run_local.py --game race --target sofa --seed 1
python3 test_scripts/drone/local/run_local.py --game hide --perception aruco --seed 1
python3 test_scripts/drone/local/run_local.py --game race --drones 1          # single-drone race
python3 test_scripts/drone/local/run_local.py --game race --agent llm --perception vlm   # LLM waypoint planner + vision model (usage vision.drone)
```

With `--perception vlm` the vision model only sees scan frames (one per heading), downscaled to 640 px. The KPIs split AI use into `agent_*` (planner) and `perception_*` (vision) calls and tokens, and list the routed models in `ai_models`.

It prints the KPI JSON and the report path (default `/tmp/vpt-drone-reports/<timestamp>/index.html`).

| Option | Meaning |
|---|---|
| `--game hide\|race`, `--target` | hide and seek (drone 1 hides, drone 2 seeks) or race to the target object |
| `--perception auto\|aruco\|color\|coco\|vlm` | auto = aruco for hide, colour classes in the simulator / COCO on `--real` for race. `coco` needs `DRONE_COCO_MODEL` (an ONNX model path; nothing is downloaded) |
| `--agent scan\|llm` | scan agent (45 degree scans + nearest unvisited waypoint, free), or `llm`: the same scan agent, with a text-only model choosing the next waypoint from the room map, the candidates and what the last scan saw (one call per waypoint; a bad answer falls back to the nearest waypoint) |
| `--ai_usage`, `--env_file` | AI usage key for `llm` / `--perception vlm` (use `vision` on a server that does not know `vision.drone` yet) and the `.env` with the AI gateway URL and key |
| `--sim_speed` | simulator motion speed multiplier (default 4) |
| `--room_map` | JSON room map: size plus furniture boxes (`room_example.json` is the simulated room). The guard refuses/clips moves within 30 cm of an obstacle and the agents plan A* routes around it. Default: the sim room's map; **required with `--real`** |
| `--room_w/--room_d/--max_height` | safety limits (default: map size, 600 x 500 x 150 cm, 50 cm margin) |
| `--hide_s/--seek_s/--timeout_s/--penalty_s` | phase lengths and the false-claim penalty |
| `--kill_file` | operator kill: creating this file (default `/tmp/vpt-drone-kill`) sends `emergency` to every drone and stops |

## Real drones

`--real` starts no simulator: drone i is reached at `10.200.i.2` (state port 8889+i, video port 11110+i)
or at `--ip1/--ip2`. It prints each drone's battery and temperature, refuses to fly if a gate fails, then
counts down 5 s. Ctrl-C or any error lands every drone; the kill file cuts the motors.

```bash
python3 test_scripts/drone/local/run_local.py --real --game race --drones 1 --ip1 192.168.10.1 --room_map my_room.json
```

Tests: `python3 -m pytest tests/drone -q` (the end-to-end test is skipped without ffmpeg).
