# BUG-0699 — Pokémon runner cannot pick up the Secret Key with a full bag

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0699                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/runner.py`       |

---

## Symptom

Found in the local replay of stall `20261019-190740`, after the BUG-0698 fix: on the Pokémon Mansion's B1F the runner stood at
(5, 12), above the Secret Key's ball (5, 13), for 264 `at goal` ticks, then (with the ball retried) 91 `talk` ticks.

## Root cause

The bag held 20 kinds of items, the Generation I limit, so the ball answered "no room" and stayed on the floor.
`Runner.take_ball` marks a ball taken once `talk_at` pressed A, whatever the game answered, so `mansion_step` had no ball
left to go for.

## Fix

`runner.mansion_step` on B1F: with a full bag a Nugget is tossed first (`hm.toss_item`, the same as before the Celadon vending
machine), and a ball marked taken but still on the floor is retried. Replay: Nugget tossed, `secret_key` done, out through 1F.
Guard test: `test_mansion_b1f_makes_room_in_a_full_bag_before_the_secret_key_ball`.
