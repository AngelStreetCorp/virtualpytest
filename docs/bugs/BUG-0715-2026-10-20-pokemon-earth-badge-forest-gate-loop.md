# BUG-0715 — Pokémon runner walks in and out of Viridian Forest's north gate on the way to Giovanni

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0715                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `fix/pokemon-earth-route2`                     |

---

## Symptom

Run `20261020-094747` (host-clone-1), after Sabrina, came out of Diglett's Cave on Route 2's north half and then went in
and out of Viridian Forest's north gate (map 0x2F) through Route 2 (3, 11) for 5 min: stalled `no_progress` on
`earth_badge`.

## Root cause

On Route 2's north half the known way to Viridian is through the forest (Route 2's own gate was never visited). The gate
is neither the guide map nor in the milestone's `area`, and `Runner.story` sends the runner from such an "off the route"
map back to the guide map, Route 2. From Route 2 the route led into the gate again.

## Fix

- `earth_badge` area adds the forest's north gate, the forest and its south gate (as `seafoam` already does for the same
  stretch walked north to south), so inside them the runner goes on toward Viridian.
- Guard test: `test_earth_badge_walks_south_through_viridian_forest_from_digletts_house`.
