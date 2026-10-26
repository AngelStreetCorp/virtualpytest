# BUG-0711 — Pokémon runner stands at the top of Silph Co.'s stairs: Giovanni is reached by the Card Key and the teleporters

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0711                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-silph-11f`                            |

---

## Symptom

Run `20261019-221517` (host-clone-1) climbed Silph Co.'s stairs 1F -> 11F (`walk_target` on 181, 207..213, 233, 234),
then logged nothing for 5 min and stalled `no_progress` on `silph_co` on 11F (235) at (7, 2).

## Root cause

1. `milestones.py` `silph_co` (BUG-0710) guides up the stairs to 11F and ends with "talk to the nearest person". 11F's
   stairs end in a part with no way to Giovanni: his room is behind a Card Key gate (tile 0x5E, (6, 13)) that opens from
   the part the 7F teleporter lands in. 7F's teleporter is in the part 3F's teleporter reaches, behind a gate on 3F. The
   Card Key is an item ball on 5F (21, 16). `runner.py` `talk_to_nearest` walked toward an unreachable sprite each tick.
2. With the key route added, a replay of the canonical save hit four more walls on the way:
   - the bag was full (20 kinds) with no Nugget left: the Card Key's ball said "no room" (`hm.TOSSABLE` was Nugget only);
   - `hm.goto` stopped after 14 cursor moves, short of the 19th bag entry, so the toss chose the wrong item;
   - `world.parts` flooded over warp squares: 5F's teleporter pad (9, 15) joined a strip shut by a beaten Rocket to the
     corridor north, so the route kept the warp (11, 5) the walk could never reach (back and forth at (10, 16));
     `blocker_on_the_way` planned over the pad as well and named no blocker;
   - 11F's warp entry (5, 5) is dead (a "last map" entry on plain floor) but was treated as a wall, the only way into
     the president's row; and his Master Ball wanted a free slot too.
3. After the Master Ball, `marsh_badge` looped Silph 1F <-> Saffron: the memo still walled the Rockets' squares in
   Saffron (the gym's (34, 4)), and `SILPH_ELEVATOR` in its area drew the explorer back inside.

## Fix

- `Runner.silph_step`: no Card Key -> to 5F and take its balls; then route to 11F's teleporter part; if none, go to 3F
  and open Card Key gates (`card_key_door`: tiles 0x18 / 0x24, 0x5E on 11F, as the game's `PrintCardKeyText`); on 11F open
  the gate, then talk to the president by his picture (`make_room` first).
- `world.parts` treats warp squares as no way through (except the player's own and `INERT_WARPS`, 11F (5, 5));
  `avoid_warps` skips `INERT_WARPS`; `blocker_on_the_way` avoids warps like the walk.
- `hm.TOSSABLE` = Nugget, Full Restore, Rare Candy; a stack is tossed whole; `hm.goto` moves up to 26 times.
- `silph_co` done: Saffron's memo walls are dropped; `marsh_badge` area without `SILPH_ELEVATOR`.

## Verified

Local replay of the canonical save (`pokemon_play_local.py`): 9F teleporter -> 5F, Full Restore tossed, Card Key taken;
back by the pad, 9F, 10F, 4F, 3F, gate (17, 8) opened, teleporter to 7F, rival, to 11F (3, 2), gate (6, 13) opened,
Giovanni beaten, Rare Candies tossed, Master Ball: `silph_co` done; then down to Saffron, the gym door (34, 3), inside
Sabrina's gym (178). Guard tests: `test_silph_co_teleporter_pad_is_no_way_through_and_the_card_key_comes_first`,
`test_silph_step_fetches_the_card_key_on_5f_first`.
