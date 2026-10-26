# BUG-0712 — Pokémon runner stands in Sabrina's gym: her room is reached only by teleporter pads

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0712                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-sabrina-pads`                         |

---

## Symptom

Run `20261019-233721` (host-clone-2) got the Master Ball (`silph_co` done), walked into Saffron's gym (178), logged
`gym_leader` and then nothing for 5 min: stalled `no_progress` on `marsh_badge` at (8, 13), the entrance room.

## Root cause

Saffron's gym is nine rooms with walls between them; the only ways between rooms are 28 teleporter pads that lead to
other pads of the same map. Sabrina (9, 8) is in the middle room, reached only from the top-left room's pad (1, 5).
`runner.py` `goal_action` (`*_badge` branch) called `talk_at(leader)`, i.e. `walk` with A* over the floor; the walk treats
every pad as a wall (`avoid_warps`) and same-map warps are no link of the world graph, so no path existed and nothing in
the runner knew to step on a pad.

## Fix

- `world.pad_route(walk, info, pos, goal)`: a breadth-first search over the map's parts (`world.parts`), each same-map pad
  taking its part to its twin's part; returns the first pad to step on (None when the goal is in reach or unreachable).
- `goal_action`: in Saffron's gym, while `pad_route` names a pad, walk onto it; in Sabrina's room it talks to her as before.
- Guard test: `test_sabrina_gym_room_is_reached_by_a_chain_of_teleporter_pads`.

## Verified

Replay of the canonical save (stall backup `20261019-235618`), 240 s: pads (11, 15) -> (19, 17) ... -> (1, 5) -> (11, 11),
Sabrina beaten, `marsh_badge` done (7 badges), out of the gym and on Route 6 toward `earth_badge`.
