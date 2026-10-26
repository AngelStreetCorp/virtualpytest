# BUG-0643 — Pokémon runner stalled toward Seafoam with no Surf or Strength user in the party

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0643                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Host run `20261018-223003` (`seafoam`, right after [BUG-0640](BUG-0640-2026-10-18-pokemon-route5-pocket-gate-door.md)
cleared the Saffron stall) explored Saffron's Fighting Dojo (map 177), won its trainer fights, then:

```
{'kind': 'lost', 'map': 177, 'next': 162}
{'kind': 'stalled', 'reason': 'same_spot', 'milestone': 'seafoam', 'map': 177, 'pos': [4, 2]}
```

## Root cause

The save's memo has `surf_deferred` and `strength_deferred`: the party (a Venusaur-line leader and a Golbat) can learn
neither HM. Seafoam Islands are reached only by Surf and drained only with Strength, so the world graph has no route to
any `seafoam` map (162 = Seafoam B4F) and `go_to_map` ends `lost` on whatever map the runner stands on. `volcano_badge`
(Cinnabar Island) has the same wall: it is reached by Surf. `milestones.py` deferred `surf` and `strength` but not the
milestones that need them.

## Fix

`shared/src/lib/game/pokemon/milestones.py`: `seafoam` is done when `surf_deferred` or `strength_deferred` is set,
`volcano_badge` when `surf_deferred` is set, like `strength_deferred` on the `strength` milestone. The story moves on to
`earth_badge`. This is a defer, not a solution: the run still needs a Surf learner (Silph Co.'s Lapras gift is now in
reach) to play Seafoam and Cinnabar.

### Second cause on the same square: the prize Pokémon's dex page

Replaying the host save with the defer, `seafoam` completed and `earth_badge` started, but the player still stood at
(4, 2): every walk to the dojo door ended `warp_stuck`. A probe of the screen showed Hitmonlee's Pokédex page (the
dojo's prize ball, picked up at (4, 1)). It draws no text box, so `text_box_open` is false and the runner pressed walking
keys, which the page ignores. `memory.dex_page_open()` tells the page by its frame (tile 0x63 top left, divider
0x68…0x6A on row 9), and `Runner.tick` presses A on it before the text-box check.

## Verification

- `tests/shared/test_pokemon.py::test_seafoam_and_cinnabar_are_deferred_without_a_surf_or_strength_user`.
- `tests/shared/test_pokemon.py::test_dex_page_of_a_prize_pokemon_is_closed_with_a`.
- `python3 -m pytest -q tests/shared/test_pokemon.py`: 121 passed.
