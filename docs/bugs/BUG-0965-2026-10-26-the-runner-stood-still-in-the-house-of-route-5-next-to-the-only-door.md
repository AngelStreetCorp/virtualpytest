# BUG-0965 — The runner stood still in the house of Route 5, next to the only door out

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0965                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-vermilion-wayon`                         |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled again on 2026-10-26, after BUG-0963 had been
deployed: the run `20261026-223502` (host-clone-2, the `second` lane) wrote
`stall_second_20261026-223502.json` with the reason `same_spot` — "the same map position for 300
ticks" — on **map 70** (the house on Route 5) at square **(2, 0)**, milestone `vermilion`, 12
milestones done (`bill`), **no deferral** (`deferred: []`).

The good news first: the run crossed **nine maps** (Cerulean 3 → the trashed house 62 → Route 24 35
→ Route 5 16 → the path under Route 5 71 → the underground path 119 → the path under Route 6 74 →
Route 6 17 → the house 70) — the ping-pong of BUG-0963 was gone. But the run ended sealed in the
house, and the local replay of the pulled save is blunt about it: **607 ticks, every one of them
"no route"**.

```
{"ticks": 607, "counts": {"no route": 607}, "milestone": "vermilion", "map": 70, "pos": [2, 0]}
```

## Root cause

A door (a warp square) is **not part of the walkable fill** — stepping on it warps the player, so
`world.parts()` keeps the door squares out of the flood fill and the part of the player and the part
of a door can differ.

The house of Route 5 (map 70, 8 × 6) has four doors: `(3, 0)`, `(4, 0)`, `(3, 5)` and `(4, 5)`.
Measured on the live save, all four are in **part 2** (the room) while the player stands on
**(2, 0)**, the one square next to the door `(3, 0)` — **part 0**. The world graph therefore knows no
way out of the player's part (`World.route(70, 16, start_part=0)` is `None`), `go_to_map` answered
"no route" on every tick, and the runner stood still on `(2, 0)` until the stall detector wrote the
run down:

```
walk_target map 70 pos [4, 0] target [3, 0] branch route   ← the door next to the player
lost       map 70 next 5                                   ← no route to Vermilion
lost       map 70 next 16                                  ← no route to Route 5
stalled    reason same_spot milestone vermilion map 70 pos [2, 0]
```

## Fix

`shared/src/lib/game/pokemon/runner.py`

- New `Runner.door_beside(here, info, walk)`: the door of this map next to the player (one square
  away), when the game has not refused it before (`bad_warps`).
- `go_to_map` uses it when there is no route at all: the runner steps on the door next to it, the
  warp fires and the player is out of the part the graph knows no way out of.

## Verification

- Guard test `test_the_runner_walks_out_through_the_door_next_to_it_when_the_graph_knows_no_way_out`
  (`tests/shared/test_pokemon.py`): it builds the world graph measured on the live save and fails
  without the fix (`AttributeError`).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **221 passed**.
- **Verified on the emulator**: the local replay of the pulled save (the runner sealed in the house)
  walks out of the door and plays on.
