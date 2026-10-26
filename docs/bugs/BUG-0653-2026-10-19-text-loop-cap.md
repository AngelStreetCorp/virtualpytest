# BUG-0653 — Pokémon runner cycles an NPC's dialogue forever and never moves

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0653 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

When an NPC's dialogue keeps showing text boxes, the runner presses A (or B for a "surnom" prompt) on every tick and
never leaves the text branch. Nothing counted those ticks, so a dialogue that cycled forever kept the runner still.

## Evidence

Live run, 00:45 UTC, map 3 at (27, 12): 300 ticks in a row with a text box open, cycling through an NPC's lines. Zero
events were logged and the runner never moved. The memo's `guard_talks` for 3:28,12 was 4.

## Root cause

`tick()` in `shared/src/lib/game/pokemon/runner.py` returns `"text"` after each text-box press and keeps no count.
The busy (cutscene) branch was capped by BUG-0648 (`busy_ticks`), but the text branch above it was not.

## Fix

- `Runner.text_ticks` (class default and `__init__`) counts consecutive ticks with a text box open.
- On the 60th consecutive text tick the runner emits `text_stuck` (ticks, position, map), presses B twice with a 250 ms
  wait after each, resets the count and returns `"text stuck"`. Every other text tick presses as before.
- Any tick that is not a text tick resets the count, just before the busy branch.

## Test

`test_a_text_box_that_never_closes_gets_two_b_presses_on_the_sixtieth_text_tick` in `tests/shared/test_pokemon.py`: a
text box is open for 61 ticks. The 60th tick must press B twice and emit one `text_stuck`, the count must reset, and
the next tick with the box closed must reset it to 0. The test fails on the code before this fix.
