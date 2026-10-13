# game_tetris — real-time Tetris on a web host (TASK-33 phase 3)

VirtualPyTest plays [Jake Gordon's JavaScript Tetris](https://jakesgordon.com/games/tetris/) unattended in
the browser of a web host (`host_vnc`). Rows, score and speed are recorded as KPIs. Unlike 2048, the
piece keeps falling while VPT decides and types, so input has to keep up with the game.

| Part | Where | What |
|---|---|---|
| Script | `test_scripts/game/game_tetris.py` (id `game/game_tetris`) | loads the tree, runs the runner, stores the KPIs |
| Game library | `shared/src/lib/game/tetris/` | `board.py` (rules + El-Tetris placement), `reader.py` (pixel court reader), `runner.py` (real-time loop, report, KPIs), `ui.py` (builds the userinterface) |
| Userinterface | `tetris-web` (models `web`) | built by `python -m shared.src.lib.game.tetris.ui --out <dir>` |
| Local run | `test_scripts/game/local/tetris_vpt_local.py` | the same runner and tree actions in a local Chromium, no host |
| Tests | `tests/shared/test_tetris.py` | rules, placement, pixel reader on a JPEG frame, the runner against a simulated page |

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

## How a piece is played

1. **Read the page state.** One `execute_javascript` action returns `playing`, `score`, `rows`, `step`
   (seconds per row), the current piece (colour, x, y, rotation), the next piece and the court as 200
   characters. The page has no piece id, so the script tags each piece object with `__vpt`.
2. **Decide.** `best_placement` tries every reachable rotation and column and scores the result with the
   El-Tetris weights: landing height, rows cleared, row and column transitions, holes, wells. The page
   rotates in place with no wall kicks, so a placement is reachable when every rotation and every shift
   fits at the spawn row.
3. **Act.** `placement_keys` returns the rotations, the shifts, one DOWN per row and one extra DOWN that
   locks the piece; the page locks a piece when DOWN can't move it. The runner sends these keys **in one
   batch through the action executor** (`ExecutionOrchestrator.execute_actions`) with `wait_time` 0. The
   key actions come from the tree's action nodes, read once at the start. Going through the navigation
   tree would cost ~60 ms per key.

The page handles one queued key per frame and drops its queue when a piece lands. When gravity moves
the piece down while the keys are on their way, the extra DOWNs land on the next piece; the next state
read shows that piece where it really is.

## End of a run and the pixel check

- **Game over:** the page stops (`playing` false). **Piece budget** (`--max_pieces`): the runner presses
  `quit` (Esc), which ends the game the same way.
- `game_over` is then checked through the navigation tree.
- With the court frozen, a captured frame is read by `reader.py` and compared with the page's court
  **plus the current piece**, which the page keeps drawing but doesn't store in `blocks`.
  - The court is found by its dark 2 px border (the only dark outline with a 1:2 aspect).
  - A cell is filled when the median colour of its centre is saturated. All seven piece colours are;
    the pale empty-cell texture isn't.
  - Any difference fails the run (`reader_match`, `reader_diff_cells`).

## Arguments

| Argument | Default | Meaning |
|---|---|---|
| `--userinterface` | `tetris-web` | the Tetris userinterface |
| `--max_pieces` | `100000` | piece budget; the run stops there and passes. The rows floor only applies to full games |
| `--max_duration` | `3600` | hard stop in seconds; reaching it fails the run |
| `--min_rows` | `10` | pass floor for the rows of a full game |

## Outputs (`script_results.metadata`)

- `pieces`, `rows`, `score`, `max_speed_s` (the page's seconds per row at the end), `stop_reason`
  (`game_over`, `piece_limit`, `time_cap`, `no_placement`, …), `pieces_by_type`, `key_presses`.
- Timing: `piece_ms_p50` / `piece_ms_p95` (state read + decision + keys), `keys_ms_per_key`,
  `state_ms_p50`, `decision_ms_p50` / `decision_ms_max`.
- `missed_pieces`: pieces that spawned and locked between two reads, never played.
- `reader_match`, `reader_diff_cells`, `final_court`, `play_duration_s`.

The report has one step per 25 pieces (rows, score, speed, court, screenshot) and a final KPI step.

## Measured (2026-10-01)

On the host-clone-1 web host: 400 pieces, 158 rows, at top speed (0.1 s/row), 382 ms per piece
(p50), 18 ms per key, 0 missed pieces, pixel court = page (`2d357af5-957e-4e48-b0fb-53e641df0f34`).
Local runs and details: `docs/tasks/TASK-33-2048-game-showcase.md` §000.
