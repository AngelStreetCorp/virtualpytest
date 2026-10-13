# BUG-0213 — 2048 on the phone misread the board and stopped mid-game: the reader took a piece of the grid for the board

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0213                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared / game2048 (TASK-33)                                  |
| Fixed in  | Unreleased                                                   |
| Commit    | `0cda45490`                                                  |

---

## Symptom

The first full game of `game/game_2048` on the S21 FE (vpt-pi1 `device1`, heuristic player) failed
after 170 moves with `stop_reason=input_not_applied`, score 1896, 14 board resyncs and 4.0 s per
move (script result `4baba4b4-83f7-4047-9c66-b5e470e5cb61`). The 10-move check on the same device
had just passed with 0 resyncs.

- From time to time a move was never confirmed, and the runner fell back to a blind read. That read
  returned a board that wasn't on screen, e.g. `[[0,0,0,0],[4,0,2,2],[4,0,4,2],[8,0,4,0]]`, while the
  phone showed `[[0,0,0,0],[8,0,0,0],[16,4,2,2],[32,8,4,0]]` (move 33). Later reads were close to
  `[[…],[…],[4,4,2,2],[4,4,2,2]]`.
- The last misread (move 171) gave a board that could still move LEFT, when the real board could not.
  The runner swiped LEFT three times, nothing changed on screen, and it stopped with
  `input_not_applied`. The game was not over: the screen showed score 1728 and a legal DOWN move.

## Root cause

`locate_board()` in `shared/src/lib/game2048/reader.py` finds the board on every frame. It masks the
pixels close to the board background colour (the grid lines between tiles) and tries the colour
thresholds 40, 60, 80 and 100 in turn. It used to return the **first** threshold whose largest blob
was near-square and at least 120 px wide.

On the S21 HDMI capture the background is shifted by +17..+27 per channel, a distance of 35–44 from
the reference: right at the strictest threshold. JPEG noise then splits the grid at threshold 40, and
one piece is square on its own. Measured on the run's frames:

| Frame | Threshold 40 | Thresholds 60–100 |
|---|---|---|
| move 33 | `(572, 384, 188, 176)` | `(511, 310, 258, 258)` |
| last move | `(636, 320, 124, 123)` | `(511, 310, 258, 258)` |

The reader then sampled the 16 cells inside that corner piece, which explains the shrunken and
repeating boards. The 10-move check passed because it was over before a split frame came up.

## Fix

`locate_board()` now tries every threshold and keeps the biggest near-square match
(`shared/src/lib/game2048/reader.py`). The board's real outline only grows with the threshold, while
a piece of it is always smaller, so the biggest square is the board.

Regression test: `test_locate_board_ignores_a_square_piece_of_the_grid` in
`tests/shared/test_game2048.py` builds a board where only one corner passes the strictest threshold.
It fails on the old reader and passes on the new one.

## Verification

- Offline, with OpenCV in a throwaway venv: `pytest tests/shared/test_game2048.py` gives 5 passed
  (91 s). The new test fails on the old `locate_board`.
- On the run's real frames: the move-33 frame and the last frame both locate `(511, 310, 258, 258)`,
  and the move-33 frame reads exactly the board on screen. Frames from the 440-move web game on
  vpt-pi4 still locate `(495, 251, 275, 275)`.
- On the device, 2026-10-01: with only `reader.py` copied to vpt-pi1, a full S21 game played 262 moves
  with 1 resync to a board with no legal move (`f0a6d6e1-3c88-4e4a-94f2-866eebd3baf7`). That run then
  failed on the separate game-over OCR check, BUG-0217. The game that passed, `f9c2c3eb-…`, had 1 resync
  in 87 moves.
