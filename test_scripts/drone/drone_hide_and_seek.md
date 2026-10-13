# Drone Hide and Seek (`drone_hide_and_seek`)

## Purpose

Two Ryze/DJI Tello drones play hide and seek, each one an ordinary VirtualPyTest device (model `tello`)
driven by its own agent (TASK-32). It shows that the platform drives an aircraft through the same stack as
a set-top box: a video stream into an AV controller, discrete commands through a remote controller, and a
verdict judged from captured frames.

## How it is built

| Piece | Where | Role |
|---|---|---|
| Script | `test_scripts/drone/drone_hide_and_seek.py` | Builds both drones, runs the game, writes KPIs. No flight code |
| Game, agents, referee, safety | `shared/src/lib/drone/` (`games.py`, `agents.py`, `referee.py`, `safety.py`, `perception.py`) | The same code the local runner flies against the simulator |
| Platform bridge | `shared/src/lib/drone/platform_io.py` | `PlatformDroneIO` (commands through `ExecutionOrchestrator.execute_actions`, frames from the device captures) and `PlatformReporter` (`record_step_immediately`) |
| Controller | `backend_host/src/controllers/remote/tello.py` | `tello` remote: plain UDP SDK, every move guarded, keepalive, land on error |
| Video | `rtsp_stream` AV controller with `DEVICE<n>_VIDEO=udp://0.0.0.0:<video_port>` | `vpt-stream` ingests the drone's H.264 like any live feed; the script never opens the video port |

The second drone (`--peer_device`) is built by the script from the same `.env` with
`create_host_from_environment([peer])`, because the framework only builds the selected device.

## The game

1. Both drones start landed on their start spots (`--start1`, `--start2`).
2. **Hide phase** (`--hide_s`): the hider takes off and flies to a hiding spot out of the seeker's start view.
3. **Seek phase** (`--seek_s`): the seeker takes off and searches (agent `scan` or `llm`); the hider holds
   position (keepalive only).
4. The seeker only **claims**. The referee takes a fresh frame from the seeker and looks for the hider's
   ArUco marker (4x4, 5 cm, id = drone number, taped on the drone's top shell) with a stricter check.
   A confirmed claim ends the game; a rejected one is counted as a false claim.
5. The hider wins at the timeout. Both drones land (also on any error, Ctrl-C or script stop).

## Usage

```bash
python test_scripts/drone/drone_hide_and_seek.py --room_map my_room.json            # device1 = drone 1, device2 = drone 2
python test_scripts/drone/drone_hide_and_seek.py --room_map my_room.json --hider peer --seek_s 120           # drone 2 hides
python test_scripts/drone/drone_hide_and_seek.py --room_map my_room.json --room_w 400 --room_d 400 --start1 80,80,0 --start2 320,80,0
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--device` | string | `device1` | Drone 1 (framework parameter) |
| `--peer_device` | string | `device2` | Drone 2; a second `tello` device from the host `.env` |
| `--hider` | `self` \| `peer` | `self` | Which drone hides |
| `--room_map` | str | (required) | Path of the room map JSON: room size plus the furniture as boxes (`name,x0,x1,y0,y1,h`, cm, top height `h`). The guard refuses or clips moves within 30 cm of an obstacle (unless flying 30 cm above it) and the agents plan routes around it. Start from `test_scripts/drone/local/room_example.json`; `sim` = the simulator room |
| `--room_w` / `--room_d` | int | `600` / `500` | Room size in cm. The geofence is the room minus a 50 cm margin |
| `--max_height` | int | `150` | Ceiling in cm |
| `--perception` | `auto` \| `aruco` \| `vlm` | `auto` | `auto` = ArUco marker. `vlm` uses the vision model (`vision.drone`) |
| `--agent` | `scan` \| `llm` | `scan` | `scan` needs no model and costs nothing: 45 degree scans, then the nearest unvisited waypoint. `llm` keeps that motion but asks a text-only model which waypoint to search next (it is told the hider hides behind tall furniture or in a far corner); about one short call per waypoint, falling back to the nearest one |
| `--hide_s` / `--seek_s` | int | `60` / `180` | Phase budgets in seconds |
| `--start1` / `--start2` | `x,y,yaw` | `100,100,180` / `500,100,180` | Start spots in cm and degrees (yaw 0 = +y, clockwise positive). Empty = default |

## Result

`overall_success` is true when the referee confirmed a result (the find, or the hider holding out to the
timeout), the operator did not kill the run and both drones are confirmed landed. A kill file
(`/tmp/vpt-drone-kill`), a guard landing a drone or an error is an aborted run and fails.

KPIs in `script_results.metadata`: `game`, `winner`, `target`, `time_to_win_s`, `turns_by_drone`, `claims`,
`false_claims`, `commands_sent`, `guard_blocks`, `battery_start`, `battery_end`, `perception`, `agent`,
`ai_calls`, `tokens_in`, `tokens_out`, `hiding_spot`, `landed`, `killed`, `hider`, `seeker`, `room_cm`,
`game_duration_s`.

The report has one step per drone turn (frame, action, guard verdict), one step per claim with the
referee verdict and the annotated frame, and a final "Winner" step.

## Host setup

Two `tello` devices in the host `.env` (see `backend_host/src/.env.example` and the arrival-day runbook
`docs/tasks/TASK-32-arrival-day-runbook.md`). With the network-namespace layout
(`scripts/drone/tello_netns.sh`):

```
DEVICE6_NAME=Tello 1
DEVICE6_MODEL=tello
DEVICE6_TELLO_IP=10.200.1.2
DEVICE6_TELLO_STATE_PORT=8890
DEVICE6_TELLO_VIDEO_PORT=11111
DEVICE6_VIDEO=udp://0.0.0.0:11111
DEVICE6_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture6
DEVICE7_NAME=Tello 2
DEVICE7_MODEL=tello
DEVICE7_TELLO_IP=10.200.2.2
DEVICE7_TELLO_STATE_PORT=8891
DEVICE7_TELLO_VIDEO_PORT=11112
DEVICE7_VIDEO=udp://0.0.0.0:11112
DEVICE7_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture7
```

The drone link opens on the first command, in the process that flies (the script), not when `vpt-host`
starts, so the script and the host never compete for the state port. Do not drive a drone from the Remote
panel while a game is running.
