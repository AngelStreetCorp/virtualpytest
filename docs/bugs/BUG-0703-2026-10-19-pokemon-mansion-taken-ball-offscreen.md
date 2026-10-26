# BUG-0703 — Pokémon runner walks back and forth on two squares of the Mansion basement

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0703                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Run `20261019-195701` (host-clone-1) stalled `no_progress` on `secret_key` at Pokémon Mansion B1F (216) (18, 22): after
two balls (items 77 and 214) the player moved between (18, 20) and (18, 21) for 5 minutes, fighting wild battles, with no
ball, switch or map change in its events.

## Root cause

`overworld.sprite_list` reports a sprite with image 0xFF as hidden only inside the visible 10 x 9 window; off screen a taken
item ball looks like one still on the floor. The BUG-0699 retry in `runner.mansion_step` (runner.py ~1320) dropped the taken
mark of every listed ball, so the off-screen taken ball (19, 25) became a target again. At (18, 20) it is one row off screen
(target, step south); at (18, 21) it is on screen and hidden (not listed, target the far ball (1, 22), step north).

## Fix

`overworld.screen_sprites` lists the sprites inside the window with their hidden flag. `mansion_step` drops a taken mark only
for a ball on screen and not hidden, and marks a ball on screen and hidden as taken.
Guard test: `test_mansion_b1f_keeps_the_mark_of_a_taken_ball_off_screen_and_marks_one_seen_hidden`.

## Verification

Replay of the stalled canonical save: (19, 25) marked taken at once, the ball (1, 22) picked up, the south switch pressed,
then on toward the north-west balls. On the host: the cleared run moves past (18, 20).
