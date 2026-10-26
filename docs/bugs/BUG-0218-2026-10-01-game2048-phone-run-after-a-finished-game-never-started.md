# BUG-0218 — 2048 on the phone: a run started right after a finished game never began playing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0218                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared / game2048 (TASK-33)                                  |
| Fixed in  | build 90145 |
| Commit    | `6560e68a8`                                                  |

---

## Symptom

On the S21 FE (vpt-pi1 `device1`), the first `game/game_2048` run after a game that had ended
failed within 17 s with `stop_reason=menu_not_ready`, "No fresh 2048 board found on screen"
(script result `dc4ea601-ef59-4a51-9609-fbe24cf5a0fe`). Afterwards the phone showed a brand-new
game at score 0.

## Root cause

- The runner opens `game` and looks for a fresh two-tile board. The previous game's final board is
  still on screen, so it doesn't find one and navigates to `new_game`.
- On the phone, `new_game` taps **New Game**, then clicks **OK** on the "start a new game?" dialog.
  The page only asks that question mid-game. After game over the tap starts a new game straight away,
  so `click_element "OK"` fails ("Element 'OK' not found") and the navigation reports a failure.
- `GameRunner.run()` (`shared/src/lib/game2048/runner.py`) only read the board when `new_game`
  succeeded, so it gave up even though the new game was already on screen.

## Fix

`GameRunner.run()` now reads the board after `new_game` whatever the navigation reports. The screen
is what decides: a fresh two-tile board means the game has started, and "no fresh board" still fails
the run as before.

Regression test: `test_runner_starts_after_a_finished_game` in `tests/shared/test_game2048.py`
starts the simulated device on a finished board, with `new_game` resetting the game but reporting a
failure. It fails on the old runner and passes on the new one.

## Verification

- `pytest tests/shared/test_game2048.py`: 6 passed (OpenCV in a throwaway venv). The new test fails
  on the old runner.
- On the device, 2026-10-01: a 10-move run started right after a finished game, with "Game over!" on
  screen. Its `new_game` step logged `Element 'OK' not found`, and the run then found the fresh board and
  **passed**: 10 moves, 0 resyncs (`160c6958-f3b0-478b-98dc-9350803eca43`).
