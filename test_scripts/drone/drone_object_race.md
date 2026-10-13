# Drone Object Race (`drone_object_race`)

## Purpose

Two Ryze/DJI Tello drones, two ordinary VirtualPyTest devices (model `tello`), search the room for the same
object at the same time (TASK-32). A drone that sees the target claims it; the platform referee re-checks a
**fresh** frame from that drone, and the first confirmed claim wins. A rejected claim costs the drone a 3 s
penalty and counts as a false claim.

The build is the one described in `drone_hide_and_seek.md` (same `platform_io.py` bridge, same `tello`
controller, same host setup, same arguments for room, ceiling, start spots and agent). Only the game and
the perception differ.

## Usage

```bash
python test_scripts/drone/drone_object_race.py --room_map my_room.json --target sofa
python test_scripts/drone/drone_object_race.py --room_map my_room.json --target tv --timeout_s 120 --agent llm
DRONE_COCO_MODEL=/opt/models/yolov8n.onnx python test_scripts/drone/drone_object_race.py --room_map my_room.json --target plant
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--device` | string | `device1` | Drone 1 (framework parameter) |
| `--peer_device` | string | `device2` | Drone 2; a second `tello` device from the host `.env` |
| `--target` | string | `sofa` | Object to find: `sofa`, `tv`, `plant`, `chair`, `table` (`couch`, `potted plant`, `dining table`, ... map to the COCO names) |
| `--room_map` | str | (required) | Path of the room map JSON: room size plus the furniture as boxes (`name,x0,x1,y0,y1,h`, cm, top height `h`). The guard refuses or clips moves within 30 cm of an obstacle (unless flying 30 cm above it) and the agents plan routes around it. Start from `test_scripts/drone/local/room_example.json`; `sim` = the simulator room |
| `--room_w` / `--room_d` | int | `600` / `500` | Room size in cm. The geofence is the room minus a 50 cm margin |
| `--max_height` | int | `150` | Ceiling in cm |
| `--perception` | `auto` \| `coco` \| `vlm` | `auto` | `auto` = the COCO detector when `DRONE_COCO_MODEL` points at an ONNX model file, otherwise the vision model (`vision.drone`). Nothing is downloaded automatically |
| `--agent` | `scan` \| `llm` | `scan` | `scan` turns 45 degrees at a time through 360 degrees, then flies to the nearest unvisited waypoint (A* around the furniture), no model. `llm` keeps all that motion but asks a text-only model which reachable waypoint to search next (room map, visited waypoints, what the camera saw, commonsense); about one short call per waypoint, and an unusable answer falls back to the nearest waypoint |
| `--timeout_s` | int | `180` | Seconds before the race ends with no winner |
| `--start1` / `--start2` | `x,y,yaw` | `100,100,180` / `500,100,180` | Start spots in cm and degrees. Empty = default |

## Result

`overall_success` is true only for a winner the referee confirmed with both drones confirmed landed. No
winner before the timeout, an operator kill (`/tmp/vpt-drone-kill`), a guard landing or an error fails the run.

KPIs in `script_results.metadata`: `game`, `winner`, `target`, `time_to_win_s`, `turns_by_drone`, `claims`,
`false_claims`, `commands_sent`, `guard_blocks`, `battery_start`, `battery_end`, `perception`, `agent`,
`ai_calls`, `tokens_in`, `tokens_out`, `landed`, `killed`, `room_cm`, `game_duration_s`.

The report has one step per drone turn, one step per claim with the referee verdict and the annotated frame
(the detection box drawn on it), and a final "Winner" step.

## Cost

`scan` with the COCO detector costs nothing. The vision model (`--perception vlm` or `--agent llm`) is the
AI usage `vision.drone`; the KPI step reports `ai_calls`, `tokens_in` and `tokens_out`.
