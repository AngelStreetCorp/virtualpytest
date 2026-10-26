# BUG-0697 — Pokémon runner walks into the locked Cinnabar gym door for 5 min

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0697                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/runner.py`       |

---

## Symptom

Run `20261019-180126` (host-clone-1) stalled `no_progress` on milestone `volcano_badge` at Cinnabar Island (8) (18, 4),
right below Blaine's gym door (18, 3). Replayed locally: 184 `text` ticks and 80 `walk` ticks in 2 min, the screen reads
"La porte est fermée..." (the door is locked) each time.

## Root cause

In Generation I the Cinnabar gym door opens only with the Secret Key, an item ball in the Pokémon Mansion's basement. The
milestone list (`shared/src/lib/game/pokemon/milestones.py`, `volcano_badge`) went straight from `seafoam` (reach Cinnabar)
to the gym, with no step for the key, so the runner walked into the locked door until the save was locked.

The Mansion needs more than the guide: the basement stairs are in a part of 1F the entrance does not reach. The way is
2F's north-west stairs (6, 1) to 3F, the 3F switch (statue above (10, 6)) to open the gates to the holes, the hole
(16, 14) down into 1F's stairs part, then B1F, whose two switches ((18, 26) south, (20, 4) north) flip all gates of all
floors. The holes are not warps, so the world graph does not know them, and its parts do not follow the gates.

## Fix

- `milestones.py`: new milestone `secret_key` between `seafoam` and `volcano_badge` (guide Cinnabar, 1F, 2F, 3F, 1F, B1F,
  area the four Mansion floors, done on the Secret Key in the bag or 7 badges; deferred with `surf_deferred` like its
  neighbours).
- `runner.py` `mansion_step`: on 2F walk to the north-west stairs; on 3F press the switch if the hole is gated, then take
  the hole (a landing on 2F tries the next hole); on B1F take the balls in reach and, when the rest are gated, press the
  switch in reach nearest them. `mansion_way_out` (key in the bag): walk straight to a door or the B1F stairs; if the
  1F hole part is shut off from the doors, go down and flip the gates once more on B1F.

Guard tests: `test_volcano_badge_waits_for_the_secret_key_from_the_mansion_basement`,
`test_mansion_3f_presses_the_switch_when_the_holes_are_gated_then_takes_the_hole` in `tests/shared/test_pokemon.py`.

Replay of the stalled save (local emulator): 1F, 2F, 3F (switch), hole to 1F, B1F (switch twice), key in the bag,
`volcano_badge` again, out through B1F and 1F (one more flip), into the gym (166), `gym_leader` seen at (14, 5).
Next expected: Blaine's gym quiz gates.
