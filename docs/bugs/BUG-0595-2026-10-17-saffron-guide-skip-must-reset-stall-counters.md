# BUG-0595 — `_saffron_skip_drink_detour` advanced GUIDE but didn't reset the same-spot stall counter, so the host re-stalled on the same tick

## Summary
Post-deploy to host-clone-1 (version `main-2026.10.17-88381`, BUG-0589 + BUG-0594 fixed),
the saffron scheduler DID register a `guide_skip` event (GUIDE 9 → 11) but the run
ended in ~15 s with a fresh `same_spot` stall at the same `(map 6, pos (39, 20))`. The
GUIDE bump changed the runner's plan (saffron-area edge way instead of the MART_ROOF
detour), but the bump itself doesn't move the player on the screen. The next
`overworld_tick` fed the same `(6, (39, 20))` into `StallDetector.observe()`,
incremented `spot_ticks` from the **600+ counter the runner had already accumulated
in earlier failing runs** to 601, and triggered `same_spot` again. The runner's plan
changed; the stall detector didn't get the memo.

## Local repro (2026-10-17 13:20 UTC)
- Host save memo: `memo["stall"]["spot"] = [6, [39, 20]]`, `memo["stall"]["spot_ticks"] = 600`
- reproduce: load the host memo into a Runner, call `saffron_step(here=6, info=info)`.
  `r.memo["guide_i"]` jumps 9 → 11 (correct). `r.memo["stall"]["spot_ticks"]` stays at 600
  (incorrect). The next `overworld_tick` reads `r.memo["stall"]["spot_ticks"]`, increments
  it to 601, returns `"same_spot"`.

## Fix
Inside `_saffron_skip_drink_detour`, when GUIDE advances, also reset the stall's
per-spot counters and progress:

```python
if later:
    memo[GUIDE] = later[0]
    self.event("guide_skip", milestone=ms.id, from_=i, to=later[0], map=here)
    # Reset the same-spot stall counter: the GUIDE bump means the runner is on a NEW
    # route ... the runner's current position is a temporary waypoint shared with the
    # old route. The same_spot stall would otherwise trigger instantly because the memo
    # carried a 600+ spot_ticks from earlier failing runs on the same square ...
    stall = memo.get("stall")
    if isinstance(stall, dict):
        stall["spot"] = None
        stall["spot_ticks"] = 0
        stall["progress_s"] = 0.0
```

The next `overworld_tick` re-enters `StallDetector.observe()` with a fresh `spot = [6, [39,20]]`
and `spot_ticks = 1`; the detector then grants 600 real overworld ticks before the next
`same_spot` stall — long enough for the runner to walk from `(39, 20)` east to the saffron-area
edge squares `(49, 10)` / `(49, 11)` and step onto Route 7.

## Verification on host-clone-1
After deploy (`:88437`): the `pokemon-long-play-jev` run starts a fresh `same_spot` accumulator
on the saffron-area square; memo `guide_i` jumps 9 → 11 with `kind=guide_skip, from_=9, to=11,
map=6`. The run continues for the full `max_duration=2000 s` window instead of failing in 5 s.

## Tests
Two new regression tests in `tests/shared/test_pokemon.py`:
- `test_saffron_skip_resets_same_spot_stall_when_guide_is_bumped` — sets a synthetic
  host-style `memo["stall"]` (`spot_ticks=600`), confirms `saffron_step` zeroes it.
- `test_saffron_skip_does_not_reset_stall_when_no_bump` — same setup but GUID already at
  the second CELADON, confirms the counters are NOT touched (the runner's plan didn't
  change).

109/109 pokemon tests pass (was 107/107 before; the two new tests add coverage).
