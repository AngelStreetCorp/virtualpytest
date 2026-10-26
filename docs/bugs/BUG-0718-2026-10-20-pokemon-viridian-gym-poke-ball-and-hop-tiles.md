# BUG-0718 — Pokémon runner takes the Viridian gym's Poké Ball for the gym leader and cannot walk over its hop tiles

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0718                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | `dfaf9dbd3`                                                  |

---

## Symptom

Host run `20261020-123129` (host-clone-2) stalled `no_progress` on the milestone `earth_badge` in the Viridian
City gym (map 45), at (16, 12): 5 min of game time with no milestone, no new map and no new square. The run's log
holds nothing but the strategist's plan and the stall itself — 791 ticks, **563 of them `cutscene` and 228 `walk`**,
no battle, no `walk_target`, no `gym_leader`:

```
{"kind": "strategy", "trigger": "resumed after a stop", …}
{"kind": "stalled", "reason": "no_progress", "milestone": "earth_badge", "map": 45, "pos": [16, 12]}
```

The save had 7 badges and `silph_co` done: only Giovanni was missing. The stall report is
`~/vpt-private/pokemon/stalls/stall_latest_20261020-123129.json`, the analysis
`~/vpt-private/pokemon/stalls/stall_latest_20261020-123129.diagnosis.md`.

The two runs before it stalled the same way, in the same gym: `20261020-121723` at (16, 10) and
`20261020-112634` at (18, 8) (the latter with 23 `cutscene_stuck` events).

## Cause

Three things went wrong, all in the Viridian gym (map 45).

**1. The gym's Poké Ball was taken for the gym leader.** `goal_action` asks `Runner.gym_leader`
(`shared/src/lib/game/pokemon/runner.py:2137`, the BUG-0716 rule) for the leader and then `talk_at`s him. The rule
only asks "a person whose picture no other person in the room's list shares", and the Poké Ball lying at the top
of the gym's north corridor (picture 61, at (16, 9)) passes it: its picture is unique and it is on screen. The
ball is not a person — pressing A while facing it (checked on the emulator) makes the game answer
**"Votre inventaire est plein !"**.

**2. The grid knows nothing about the gym's one-way hop tiles.** The square in between, **(16, 10), is a hop
tile** (the chevron squares of the gym tileset, tile `0x4C`): stepping on it from the south throws the player two
squares back down and locks the controls (`wJoyIgnore = 0xFF`) while the hop plays. `overworld.full_grid`
(`shared/src/lib/game/pokemon/overworld.py:145`) only reads the ROM's `LedgeTiles` table for the **outdoor**
tileset (8 entries, all for the outdoor standing tiles `0x2C`/`0x39`), so the A* routed the player straight into
the tile that throws him back. The same tiles are at (18, 2), (18, 10), (19, 1), (4, 6), (13, 16) and (13, 17).

**3. The hop looked like a cutscene.** The runner's busy branch (`runner.py:430-436`, BUG-0648) waits and presses
A every 5 s, which does not end a hop, and the position changes under the runner's feet, so the A* planned the
same path again. A local replay of the pulled save shows the loop exactly:

```
  0.5s tick#1  walk      pos=(16, 11) joy_ignore=0x00
  0.9s tick#2  walk      pos=(16, 10) joy_ignore=0xFF   <- the runner steps onto the hop tile
  1.2s tick#3  cutscene  pos=(16, 10) joy_ignore=0xFF
  1.6s tick#4  cutscene  pos=(16, 11) joy_ignore=0xFF   <- the game throws the player back down
  2.6s tick#7  cutscene  pos=(16, 12) joy_ignore=0x00   <- and again
  3.1s tick#8  walk      pos=(16, 11)                    <- the runner walks up again
```

The player oscillated (16, 12) → (16, 11) → (16, 10) → (16, 12) every 1.7 s for 5 minutes.

The leader himself was never reached: the person standing in the player's room, the sprite at (16, 15) with
picture 36, is the Pokémon Kid of the gym ("Salut ! Champion en herbe ! … M-moi, je ne sais pas qui est le
CHAMPION de JADIELLE !"), and the leader is the trainer of the gym's north-west room, picture 23 at (2, 1).

## Fix

* `gym_leader` and its fallback rule only consider **people** (`Runner.is_person`): a Poké Ball on the floor is
  never a candidate.
* A person who answers with a plain dialogue instead of a battle is **not the leader**: the runner remembers him
  (`memo["not_leaders"]`) and the next candidate gets a go. The trainer's battle line ("GIOVANNI veut se battre!")
  is what tells a trainer from a passer-by — the same word `gym.py` already reads on the trash cans.
* The runner **learns the hop tiles**: when the game pushes the player back the way he came, the square is
  remembered (`memo["hops"]`) and the grid closes it, so the A* walks around it instead of into it.

## Guard tests

* `tests/shared/test_pokemon.py::test_viridian_gym_leader_is_not_the_poke_ball_and_the_kid_is_skipped`
* `tests/shared/test_pokemon.py::test_a_gym_hop_tile_that_threw_the_player_back_is_never_walked_on_again`

## Verified

Local replay of the pulled save (the same save the host stalled on): the runner no longer oscillates at
(16, 10), it talks to the Pokémon Kid, marks him and goes for the trainer of the north-west room.
