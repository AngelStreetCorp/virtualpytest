# game_tetris — real-time Tetris on any platform (TASK-33 phase 3 / TASK-51)

VirtualPyTest plays Tetris unattended on every platform VPT drives: the
web host today (jakesgordon.com), Nintendo Switch and Android in later
slices of TASK-51. One script, one game loop, one set of KPIs. What
changes between platforms is small and lives in two places: the
**userinterface** (device-specific keys / buttons) and the **game
profile** (rotation system, gravity, hard drop). Vision is the source of
truth on every platform; the page's JS state is the oracle on the web.

| Part | Where | What |
|---|---|---|
| Script | `test_scripts/game/game_tetris.py` (id `game/game_tetris`) | resolves userinterface + profile, runs the runner, stores the KPIs |
| Game library | `shared/src/lib/game/tetris/` | `board.py` (rules + El-Tetris placement), `profiles.py` (Rules + SRS kicks + VisionProfile), `reader.py` (profile-driven frame reader), `runner.py` (real-time loop, predictive loop, report, KPIs), `ui.py` (builds the userinterface) |
| Userinterfaces | `tetris-*` (today: `tetris-web` for `web`) | built by `python -m shared.src.lib.game.tetris.ui --out <dir>`; Switch and Android UIs ship with G5 / G6 |
| Local run | `test_scripts/game/local/tetris_vpt_local.py` | the same runner and tree actions in a local Chromium, no host |
| Tests | `tests/shared/test_tetris.py` | rules, placement, SRS kicks, vision reader on JPEG frames, the runner against a simulated page (with and without the predictive loop) |

## Userinterface `tetris-web`

```text
Entry -> game --+-- start / rotate / left / right / down / quit   (action nodes: one press_key each)
                +-- game_over                                       (checked; no-op action)
```

| Node | Action / check |
|---|---|
| Entry → game | `open_browser`, `navigate_to_url` https://jakesgordon.com/games/tetris/; check `#canvas` |
| start, rotate, left, right, down, quit | `press_key` SPACE, UP, LEFT, RIGHT, DOWN, ESCAPE |
| game_over | check `#start:not([style*="hidden"])`: the "Press Space to Play." line is hidden with an inline `visibility: hidden` while a game runs, and the web check passes on any element with a layout box, hidden ones included |

## Game profiles

Two profiles today (`shared/src/lib/game/tetris/profiles.py`):

| Profile | Rotation | Spawn | Hard drop | Hold | Previews | Used by |
|---|---|---|---|---|---|---|
| `jakesgordon` | in place, no kicks | (3, 0) | no (DOWN per row + 1 to lock) | no | 1 | `tetris-web` |
| `guideline` (SRS) | SRS, 5 kick positions | (3, 0) | yes | no (v1) | 5 | `tetris-switch`, `tetris-android-mobile` (planned) |

Both profiles share the same 4x4 rotation masks (jakesgordon's page uses the
same ones SRS does). What differs is **reachability**: jakesgordon rotates in
place, SRS tries five kick offsets per rotation step. `best_placement` calls
the rules-aware `reachable()`. `placement_keys` emits `down`-per-row for
jakesgordon and a single `hard_drop` for guideline.

## State source: `--perception js|vision`

The runner reads the page in two ways:

- **`js`** (default, web): one `execute_javascript` action returns
  `playing`, `score`, `rows`, `step`, the active piece (colour, x, y,
  rotation), the next piece and the court as 200 characters. The page has no
  piece id; the runner tags each piece object with `__vpt`. Fast (one HTTP
  hop, ~5 ms in browser). This is the original TASK-33 path.
- **`vision`** (TASK-51 G3): a captured frame goes through a profile-driven
  `VisionReader`. The reader locates the court (jakesgordon: auto-detect the
  1:2 dark-bordered component; guideline / Switch: fixed ROI), reads each
  cell's saturation, identifies the next queue by *shape* (the 4-cell mask
  names the tetromino — colour never matters), and ignores the ghost
  piece (translucent → below the fill threshold). JS still runs as the
  oracle: it gives the active piece's position and id, and it supplies the
  score / rows for accuracy KPIs.

## Predictive loop: `--predict`

With `--predict`, the runner keeps a `predicted_court` that mirrors what
the rules say will happen after each placement. The next placement plans
on the prediction, never on a frame. Frames still arrive to **confirm**;
a mismatch (garbage in Tetris 99, a missed key, an animation frame)
triggers a resync — the prediction is replaced with the next observed
court. Per-piece time stops including the frame capture lag.

Measured locally: with a 1 s frame delay injected into the capture helper,
`piece_ms_p50` stays under 500 ms (the test
`test_predictive_loop_decouples_per_piece_time_from_frame_delay` enforces
this). Without `--predict`, every per-piece time would include the
capture delay.

## How a piece is played

1. **Read the page state.** `js` mode runs `JS_STATE`; `vision` mode also
   reads a frame and subtracts the active piece's cells (the frame shows
   the locked stack + the active piece; JS gives the position).
2. **Decide.** `best_placement` tries every reachable rotation and column
   and scores with the El-Tetris weights. In `--predict` mode, planning
   uses the predicted court; otherwise the read court. Either way the
   planner sees the locked stack.
3. **Act.** `placement_keys` returns the rotations, the shifts, one
   `down` per row (jakesgordon) or one `hard_drop` (guideline). The
   runner sends these in one batch through `ExecutionOrchestrator.execute_actions`
   with `wait_time` 0. The key actions come from the tree's action nodes,
   read once at the start. Going through the navigation tree would cost
   ~60 ms per key.
4. **Update the prediction.** `place()` returns the court after the piece
   locks and any full rows clear — the same operation the page runs.
   `--predict` uses it to update `predicted_court`. Frames later compare
   to it; mismatch → resync.

The page handles one queued key per frame and drops its queue when a piece
lands. When gravity moves the piece down while the keys are on their way,
the extra `down`s land on the next piece; the next state read shows that
piece where it really is.

## End of a run and the pixel check

- **Game over:** the page stops (`playing` false). **Piece budget** (`--max_pieces`):
  the runner presses `quit` (Esc), which ends the game the same way.
- `game_over` is then checked through the navigation tree.
- With the court frozen, a captured frame is read by `reader.py` (or the
  `VisionReader` if `--perception vision`) and compared with the page's
  court **plus the current piece**, which the page keeps drawing but
  doesn't store in `blocks`. Any difference fails the run
  (`reader_match`, `reader_diff_cells`).

## Arguments

| Argument | Default | Meaning |
|---|---|---|
| `--userinterface` | `auto` | the `tetris-*` userinterface matching the device model (today: `tetris-web` for `host_vnc`) |
| `--perception` | `js` | `js` reads from the page; `vision` reads a captured frame and uses JS as the oracle |
| `--profile` | `auto` | the game profile (today: `jakesgordon` for `tetris-web`, `guideline` for the planned Switch / Android UIs) |
| `--predict` | `false` | predictive loop: plan the next piece from the predicted court (works best with `--perception vision`) |
| `--max_pieces` | `100000` | piece budget; the run stops there and passes. The rows floor only applies to full games |
| `--max_duration` | `3600` | hard stop in seconds; reaching it fails the run |
| `--min_rows` | `10` | pass floor for the rows of a full game |

## Outputs (`script_results.metadata`)

- `perception`, `predict`, `pieces`, `rows`, `score`, `max_speed_s`
  (page's seconds per row at the end), `stop_reason` (`game_over`,
  `piece_limit`, `time_cap`, `no_placement`, …), `pieces_by_type`,
  `key_presses`.
- Timing: `piece_ms_p50` / `piece_ms_p95` (planner + key batch, *not* the
  state read), `keys_ms_per_key`, `state_ms_p50`, `decision_ms_p50` /
  `decision_ms_max`.
- `missed_pieces`: pieces that spawned and locked between two reads, never played.
- `reader_match`, `reader_diff_cells`, `vision_match_pct` (cells that match
  the JS oracle over the run, `--perception vision` only),
  `vision_frames_read`, `vision_resyncs`, `final_court`, `play_duration_s`.

The report has one step per 25 pieces (rows, score, speed, court, screenshot)
and a final KPI step.

## Measured (2026-10-18)

Local Playwright + simulated page (`tests/shared/test_tetris.py`):

- `js` mode, 150 pieces, 0 missed, pixel court = page (`test_runner_plays_to_the_piece_limit`).
- `vision` mode, 800 pieces, 100% vision-match, 0 resyncs
  (`test_runner_plays_via_vision_with_js_oracle`).
- Predictive loop with a 1 s frame delay: 20 pieces, `piece_ms_p50` < 500 ms,
  0 resyncs, 100% vision-match (`test_predictive_loop_decouples_per_piece_time_from_frame_delay`).
- Predictive loop with a forced garbage row: resync triggered once, run
  continued (`test_predictive_loop_resyncs_when_state_diverges`).