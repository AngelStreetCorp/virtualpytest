# game_flappy — real-time Flappy Bird on a web host (TASK-33 phase 3c)

VirtualPyTest flies the open-source [Floppy Bird](https://nebezb.com/floppybird/) (github.com/nebez/floppybird)
in the browser of a web host (`host_vnc`). The pipes passed and the loop latency are the KPIs. The jump
window is ~3 game frames (~50 ms), about two executor actions' worth on a host, so the loop plans when to
jump instead of reacting.

| Part | Where |
|---|---|
| Script | `test_scripts/game/game_flappy.py` (id `game/game_flappy`) |
| Library | `shared/src/lib/game/flappy/`: `runner.py` (planned-jump loop, report, KPIs), `ui.py` (builds `flappy-web`) |
| Local run | `test_scripts/game/local/flappy_vpt_local.py`: the same runner and tree in a local Chromium (`--url` for a local copy of the game) |
| Tests | `tests/shared/test_flappy.py` |

## Userinterface `flappy-web`

| Node | Action / check |
|---|---|
| Entry → game | `open_browser`, `navigate_to_url` https://nebezb.com/floppybird/; check `#gamescreen` |
| start (action node) | `navigate_to_url` again (a fresh game, no replay screen), then `press_key` SPACE: the game starts with a jump |
| game_over | check `#scoreboard`, which is `display: none` (no layout box) until the bird dies |

## One step of the loop

One `execute_javascript` action per step, about 25 ms on a host:
1. Read the bird box and the next gap, with the same maths as the page's `gameloop()`.
2. Simulate the next frames with the page's physics (gravity +0.25 px/frame², a jump sets the speed
   to −4.6) over the **lookahead**, which is the runner's measured loop time in frames, plus 2.
3. Find the frame where the bird would drop below the gap's bottom minus `--margin`, and schedule
   Space (a keydown sent to the page's own handler) for the frame before it. A jump whose ~42 px
   rise would hit the upper pipe is never planned. At most one jump per frame.
4. Cancel the previous step's pending press, so each step's plan uses the freshest reading.

The runner, not the page, sets the margin and the lookahead on every step: the decision rule is
VirtualPyTest's, and the browser only applies it at the moment of reading. While the bird flies there
are no screenshots (they would stall the loop); there is one report step per 10 pipes and a screenshot at
the start and the end.

## Arguments

| Argument | Default | Meaning |
|---|---|---|
| `--max_pipes` | 30 | pipe budget: steering stops there (the bird then falls) and the run passes |
| `--max_duration` | 180 | hard stop in seconds; reaching it fails the run |
| `--min_pipes` | 10 | pass floor for a run that ends with the bird dying |
| `--margin` | 6 | pixels kept between the bird and the lower pipe |

## Outputs (`script_results.metadata`)

- `pipes`, `jumps`, `steps`, `stop_reason` (`pipe_limit`, `died`, `time_cap`).
- Timing: `loop_ms_p50`, `loop_ms_p95`, `loop_ms_max`, `lookahead_frames_p50`, `play_duration_s`.
- `last_readings`: the last 12 steps (bird top/bottom, speed, gap, planned frame), to see why a run died.

## Measured (2026-10-01)

host-clone-1 web host, `--max_pipes 30`: PASS, 30 pipes, loop 49 / 88 / 144 ms (p50 / p95 / max),
lookahead 5 frames (`31f60b99-b23e-47c4-83ea-5c7dc5184e66`). Local runs and the comparison with
unplanned loops: `docs/tasks/TASK-33-2048-game-showcase.md` §000.
