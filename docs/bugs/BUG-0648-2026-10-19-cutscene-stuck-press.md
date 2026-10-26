# BUG-0648 — Pokémon runner waits forever in a cutscene with no text box

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0648 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | game / pokemon |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

The Pokémon runner stopped making progress when a dialogue or cutscene stayed on screen without a detectable text
box. The game's input-ignore flag was set, so the runner only waited and never pressed a button, and it waited
indefinitely.

## Evidence

In the live run of 2026-10-19 at 23:00 UTC the runner stalled on map 3 for about 5 minutes. The run's event log had
no walk events during that time and no key was pressed, so the runner was in the cutscene branch of `tick()` the whole
time.

## Root cause

`Runner.tick()` in `shared/src/lib/game/pokemon/runner.py` has a busy branch:

```python
if busy(self.read):          # text box open, or wJoyIgnore set by a cutscene
    self.io.wait(250)
    return "cutscene"
```

`busy()` (`memory.py`) is true whenever the input-ignore flag is set. The text-box branch above it presses A only when a
text box is detected. When a cutscene sets the flag but draws no text box, nothing in the busy branch ever presses a
button, so the runner loops on `wait(250)` for as long as the flag stays set.

## Fix

- `Runner.busy_ticks` counts consecutive busy ticks (class default and `__init__`).
- In the busy branch the counter increments. On every 20th busy tick (about 5 s) the runner emits one
  `cutscene_stuck` event with `ticks` and presses A once (`self.io.press("A", 90)`). The wait and the return value
  `"cutscene"` are unchanged.
- The non-busy path resets `busy_ticks` to 0 right after the busy branch.

Ticks that return earlier in `tick()` (intro, battle, dex page, text box) do not reach this code and do not reset the
counter. No other behaviour changes.

Files: `shared/src/lib/game/pokemon/runner.py`.

## Test

- `tests/shared/test_pokemon.py::test_a_cutscene_with_no_text_box_gets_an_a_press_on_the_twentieth_busy_tick` drives
  25 busy ticks with no text box, then one free tick. It expects exactly one `A` press, one `cutscene_stuck` event with
  `ticks == 20`, `busy_ticks == 25` while busy, and `busy_ticks == 0` after the flag clears.
  Before the fix it fails (no A press); after the fix it passes.
- `python3 -m pytest tests/shared/test_pokemon.py -q` run once at the end.
