# BUG-0596 — `saffron_step` walked to the saffron-edge only when the runner's own partition didn't include one, so Celadon (39, 20) sat unmoving for the full 2000-s budget

## Summary
Post-deploy to host-clone-1 (version `main-2026.10.17-88443`, BUG-0589 + BUG-0594 + BUG-0595
fixed), the saffron scheduler logged **23 `guide_skip` events** (every ~82 s, all `from_=9
to=11 map=6`) and zero other actions for the full 1900 s budget. The runner didn't stall,
didn't heal, didn't battle — it just sat at `(map=6, pos=(39, 20))` ticking over.

`overworld_tick` called `saffron_step` on every observe, but `saffron_step` returned `None`
because the runner's `part` (partition 0 of Celadon) already included the saffron-edge square
on the east side at `(49, 20)`. The first hop of the saffron-guide's next-map route (CELADON
→ Route 7) is then expected to be the east edge — but `go_to_map` keeps picking the
celadon-mart warp at `(39, 19)` as the first hop (same south-gate warp stall shape as
BUG-0589, just on a different partition). The runner walks UP into the warp, lands in
Celadon Mart 5F, comes back, walks UP again, lands in Celadon Mart 5F, comes back — all
without logging an event because the warp_unusable detector is keyed on stuck ≥ 6.

## Why `part` already included the saffron-edge

The runner at `(39, 20)` is in Celadon's partition 0. Partition 0 owns every warp and every
edge of Celadon (the map is one connected region with no tile-pair walls). So `part`
includes `(49, 20)` and the `if not any(sq in part for sq in saffron_edges): walk(...)`
guard never fires.

## Local repro (2026-10-17 15:23 UTC)
- Host save memo: `guide_i=12`, milestone=`saffron`, done list ends at `strength`,
  `drink_bought=true`.
- Probe (`/tmp/probe_runner7.py` with the host memo + a fake IO): run `Runner.tick()` 60
  times at `(map=6, pos=(39, 20))` with a drink in the bag.
- Before the fix: every tick returns `"no route"`. GUIDE stays at 11. No `walk` action.
- After the fix (below): every tick returns `"walk"` until the runner reaches `(49, 20)`,
  then `None`. The runner is on the saffron-edge and `go_to_map` can cross east to
  Route 7 on the next observe.

## Fix
In `saffron_step`, after the existing partition check, also force a walk to the closest
saffron-edge square when the runner is on Celadon with a drink in the bag. The runner's
plan is "walk to Route 7 to reach Saffron City" — start that walk from the edge, not from
a square where `go_to_map` would prefer a celadon-mart warp.

```python
if saffron_edges:
    target = min(saffron_edges, key=lambda s: abs(s[0] - self.pos()[0]) + abs(s[1] - self.pos()[1]))
    if self.pos() != target:
        return self.walk(target)
if had_drink_before:
    self._saffron_skip_drink_detour(here)
return None
```

The check `if self.pos() != target` avoids an infinite loop once the runner is on the edge
(saffron_step returns None, `overworld_tick` falls through to `go_to_map` and crosses east).

## Tests
- `test_saffron_step_walks_to_saffron_edge_when_player_already_in_part_with_saffron_edge` —
  new test; BUG-0596 regression: walk toward `(29, 10)` even when the runner's partition
  already includes `(29, 10)`.
- `test_saffron_step_skips_drink_detour_when_guide_is_on_first_celadon` — updated to assert
  the new walk + bump together.
- `test_saffron_step_idempotent_when_guide_already_advanced` — updated to assert the walk
  fires on every CELADON observe.
- `test_saffron_step_returns_none_when_runner_already_in_part_with_saffron_edge` —
  removed (the assertion it made is the bug).
- All 109 pokemon tests pass (`tests/shared/test_pokemon.py`).

## Deploy
1. Local: commit on a `pokemon-bug-0596-saffron-walk` branch off `main`, push.
2. Merge to `main`, then `update_core.sh` on host-clone-1 (free lease).
3. Resume `pokemon-long-play-jev` after the deploy.
4. Expected next host run: a `walk` + `entry` log every tick, the runner crossing to
   Route 7 within 30 s, then the saffron-edge gate talk (BUG-0589 still applies — the
   guard takes the drink), then the saffron predicate fires (`map == SAFFRON`) and
   `saffron` lands on `done`.