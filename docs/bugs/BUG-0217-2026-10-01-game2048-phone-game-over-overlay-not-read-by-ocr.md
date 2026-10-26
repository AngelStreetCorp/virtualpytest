# BUG-0217 — 2048 on the phone failed its screen checks: OCR on the full frame missed "Game over!" and sometimes "2048"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0217                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | userinterface / game2048 (TASK-33)                           |
| Fixed in  | build 90145 |
| Commit    | `6560e68a8`                                                  |

---

## Symptom

With the BUG-0213 board fix in place, a full heuristic game of `game/game_2048` on the S21 FE
(vpt-pi1 `device1`) played to the end: 262 moves, score 3196, max tile 256, 1 resync, and a final board
with no legal move. The run still failed with `stop_reason=game_over_not_confirmed`
(script result `f0a6d6e1-3c88-4e4a-94f2-866eebd3baf7`).

The `game → game_over` check (`waitForTextToAppear` "Game over", 5 s) OCR'd six fresh frames between
13:23:47 and 13:23:55 UTC and read only `2048` on each. The "Game over!" overlay was already on those
frames: the capture at 13:23:48 shows it clearly.

The next full game (after the first fix below) stopped with `board_lost` after 66 moves
(`ca4ce4fa-a90f-4902-a194-fbd780a5e4a1`). The navigator re-checks the `game` screen
(`waitForTextToAppear` "2048" on the full frame), and that check read an empty string on about 20
frames in a row, all of which show the page normally with "2048" in its title. An earlier failed check
at 88 s made the navigator re-enter the game with `open_url`, which opened a second Chrome tab.

## Root cause

It's not a timing problem. On the phone's HDMI capture (1280×720, mostly black bars), the simple OCR
path (`TextHelpers.detect_text_in_area`, greyscale → binary threshold 127 → tesseract) on the **full
frame** returns only the large "2048" title, and tesseract's page layout skips the overlay text.

Measured on the overlay frame with that same pipeline:

| OCR input | Threshold 127 |
|---|---|
| full frame | `2048` |
| phone screen (332×720) | page header text, no "Game over" |
| board (258×258) | `Game over!` |
| board + 20 px margin (300×300) | `Game over!` |
| board + 20 px margin, frame without the overlay | (empty) |

The same OCR on the full frame is unstable for "2048" too. On near-identical frames from the
`board_lost` run it returned `ic-play2048.co … 2048 …`, `2048 How to play -G`, `2048` or `''`. Cropped
to the header (320×120), all 8 test frames read `2048 …`.

## Fix

Both phone checks now OCR an area of the capture, set in `scripts/game2048_ui.py`, each with a margin:
- `game_over` ("Game over") reads `MOBILE_CAPTURE_BOARD_AREA = {x: 490, y: 290, width: 300, height: 300}`,
  the board.
- `game` ("2048") reads `MOBILE_CAPTURE_HEADER_AREA = {x: 480, y: 180, width: 320, height: 120}`, the
  title row.

The `game2048-android-mobile` user interface was rebuilt and re-imported into the DB (new id
`5b4c482a-a076-4482-82fd-86d809434050`). The web interface is unchanged: it checks the DOM
(`.game-over`).

The area is in capture pixels and fits the S21 FE on vpt-pi1, just as the tree's swipe and tap
coordinates already do. A phone with another resolution or another capture needs its own values.

## Verification

- The OCR results above were measured on the runs' real frames on vpt-pi1.
- On the device, 2026-10-01: a full heuristic game on the S21 **passed** with `stop_reason=game_over`,
  the "Game over" check confirmed: 87 moves, score 656, max tile 64, 1 resync
  (`f9c2c3eb-82bd-486a-8386-9f6f107d8e30`). The `game` check passed on every probe.
