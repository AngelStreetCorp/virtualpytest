# BUG-0938 — The Pokémon runner aimed at a door the game draws as a wall, and walked into it for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0938                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/pokemon-forest-door`                         |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26 at 07:56 on `host-clone-2`: the
run `20261026-075140` wrote `stall_second_20261026-075140.json` with the reason `no_progress` — no
milestone, no new map and no new square for 5 minutes of game time — on **map 50** (the gate house
at the south of Route 2, the way into the Viridian Forest) at square **(4, 1)**, with the milestone
`pewter`. The run wrote two events and then stood still:

```
{"kind":"strategy","source":"llm","plan":"Travel through Cross Route 2 and Viridian Forest to Pewter City …"}
{"kind":"stalled","reason":"no_progress","milestone":"pewter","map":50,"pos":[4,1]}
```

The counters say the player walked **two squares** (`cells: 2`, `maps: [50]`) and then ping-ponged
between them. The memo of the save says what it aimed at: `last_walk_target = [50, 4, 0, null]`.

The same save had already stalled the same way five hours earlier (run `20261026-020749`, map 50,
pos (4, 2)) — the same room, the same target.

## Root cause

**The room's north door is at (5, 0); the map's warp table also lists (4, 0), which the tiles draw
as a wall — and the runner aimed at the wall.**

Read out of the canonical save (work RAM + the owner's ROM), the gate house of Route 2:

```
map 50: 10 x 8 squares, warps (4,0)→51 warp 3, (5,0)→51 warp 4, (4,7)→13 warp 5, (5,7)→13 warp 5
```

| Square | Tile | Walkable | Warp |
|--------|------|----------|------|
| (4, 0) | `0x4A` — the wall of this tileset | **no** | yes, to the forest's warp 3 |
| (5, 0) | `0x3B` — the floor of the door | **yes** | yes, to the forest's warp 4 |

The passable list of the tileset the room uses (the ROM's collision table) is
`01 12 14 1A 1C 37 38 3B 3C 5E`: `0x4A` is not in it, `0x3B` is. The map's warp table lists a door
the tiles never open.

- `shared/src/lib/game/pokemon/runner.py` — the warp choice of `go_to_map`: the route's first hop
  is the warp (4, 0) (the world graph learned it from the map header), and the "twins" filter keeps
  the candidates that lead to the **same destination warp index** — (4, 0) leads to the forest's
  warp 3 and (5, 0) to its warp 4, so the live door was filtered out and the wall was kept.
- `runner.py` (`walk`) — a refused step is covered by the fallback that tries the other keys (the
  gym's hop tiles, BUG-0740), so `stuck` never grows, the "warp unusable" escalation never fires,
  and the warp is never marked bad: the runner aims at the wall for ever. The fallback turns the
  refused step into a step back down, so the player ping-ponged between (4, 1) and (4, 2) until
  the detector's 300 s ran out.

The room's two sprites (the old man at (2, 6), a hiker at (8, 4)) are not on the corridor: the
blocker is the wall itself.

## Fix

`shared/src/lib/game/pokemon/runner.py`: the warp squares the game shows as walls are skipped when
the candidates of the hop are chosen (`open_warps`) — the runner aims at the door at (5, 0) and
walks into the forest. When every candidate is a wall, the old choice is kept: the screen may be
stale, and a warp the game does not show is not known to be a wall.

## Verification

- Guard test `test_a_warp_the_game_draws_as_a_wall_is_not_the_one_the_runner_aims_at` in
  `tests/shared/test_pokemon.py`: it fails without the fix (the runner aims at (4, 0)) and passes
  with it (it aims at (5, 0)).
- The same check on the **stalled save itself** — the canonical `state_second.json`, the owner's
  ROM, the save's own world graph and the visible grid the game draws, player at (4, 1) — with the
  runner's own `go_to_map`:
  `the code main ran before the fix -> aims at (4, 0) (the wall)`,
  `the code main runs now -> aims at (5, 0) (the door)`.
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **213 passed**.
- Deployed on host-clone-1 and host-clone-2 (build `main-2026.10.26-90100`; the `runner.py` of both
  hosts is byte-identical to main's), the lock of the `second` save cleared
  (`pokemon_dispatch.py clear-stall --save second`) and the run that started on host-clone-1 plays
  on instead of standing in the room.
- The diagnosis of the stall, with the map data read out of the save:
  `~/vpt-private/pokemon/stalls/stall_second_20261026-075140.diagnosis.md`.
