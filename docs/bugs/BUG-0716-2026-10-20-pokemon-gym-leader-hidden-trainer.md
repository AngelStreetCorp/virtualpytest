# BUG-0716 — Pokémon runner chases a hidden gym trainer instead of the leader

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0716                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Host run `20261020-112433` (host-clone-2) stalled `no_progress` on the milestone `marsh_badge` in Saffron's gym
(map 178), at (9, 13) and then (8, 13): 5 min of game time with no milestone, no new map and no new square. The
run's log shows the leader found and then 303 s of silence — no `walk_target`, no `walk_stuck`, no battle:

```
{"kind": "gym_leader", "milestone": "marsh_badge", "picture": 33, "at": [18, 8]}
{"kind": "stalled", "reason": "no_progress", "milestone": "marsh_badge", "map": 178, "pos": [8, 13]}
```

The save had 7 badges and `silph_co` done: only Sabrina was missing. The stall report is
`~/vpt-private/pokemon/stalls/stall_latest_20261020-112433.json`, the analysis
`~/vpt-private/pokemon/stalls/stall_latest_20261020-112433.diagnosis.md`.

## Cause

`goal_action` (`shared/src/lib/game/pokemon/runner.py:2107`) picks the gym leader as *the topmost person whose
picture is alone in the room's list*:

```python
people = overworld.sprite_list(self.read)
alone = [p for p in people if [q[0] for q in people].count(p[0]) == 1] or people
leader = min(alone, key=lambda p: p[1][1])
```

`overworld.sprite_list` (`shared/src/lib/game/pokemon/overworld.py:66`) also returns the **hidden** people of the
other rooms (image `0xFF`, off screen) with their map positions. In Saffron's gym the eight psychic trainers share
only two pictures (4 and 25), so the trainer with picture 13 — at (9, 8), in the middle room — is alone in the list
and his y (8) is smaller than Sabrina's (15). The runner took that trainer for the leader, although Sabrina
(picture 36) was standing two squares away in the player's own room.

`talk_at` → `walk` → `astar` finds no path to a person in another room (the rooms are joined only by teleporter
pads), so `overworld.toward` (`shared/src/lib/game/pokemon/overworld.py:293`) walked to the reachable square
closest to that unreachable sprite — and back again, for ever.

## Fix

`Runner.gym_leader` (`shared/src/lib/game/pokemon/runner.py:2134`): the leader is the person standing in the
player's room — on screen and not hidden — whose picture no other person shares. The hidden trainers are left out,
and a beaten trainer (a wall) is left out too. When nobody is on screen (the leader is in another room, the case of
BUG-0712) the old rule and the pad chain stay untouched.

Guard test: `tests/shared/test_pokemon.py::test_saffron_gym_leader_is_the_person_in_the_players_room_not_a_hidden_trainer`.

## Verification

- Replay of the canonical save (`~/vpt-private/pokemon/stall112433/`): `gym_leader -> (36, (10, 15))` — the runner
  walks next to Sabrina and talks to her instead of walking onto the teleporter pad and standing there.
- `python3 -m pytest -q tests/shared/test_pokemon.py` → 155 passed.
