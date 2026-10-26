# BUG-0868 — The stall detector could not see a dead browser page, so the run never reported its stall

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0868                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's runs stop moving and stay stopped. The lane looks healthy — the process is alive, the lease is held
and renewed, the model is called — but the game does not move for the rest of the budget:

```
10:36:55  last screenshot
10:51     still the same frame, the run still "running"
```

The frame is the **Pokédex menu** (`POKéDEX / POKéMON / OBJET / SAUVER / OPTION / RETOUR`). The host's journal
says why the game cannot be read any more:

```
[PLAYWRIGHT] JS start () => vptGB.wram()
[PLAYWRIGHT] JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
[PLAYWRIGHT] Page screenshot timed out after 20s
```

Every read of the game's memory waits out its 15 s timeout and answers with nothing.

## Root cause

The stall detector counts the game time of a tick, but it **capped** that time at 5 seconds:

```python
dt = min(5.0, now - self._last) if self._last else 0.0
```

A tick is normally a fraction of a second, so the cap never mattered. When the page stops answering, a tick is
four reads of 15 s each — a minute of wall clock — and the cap counted it as 5 s of game time. The no-progress
clock therefore ran **12 times slower than the wall clock**: five minutes of game time needed 60 ticks, that is
an hour of real time. The run's budget is 33 minutes, so the stall was never reached: the run outlived its
budget, no stall report was written, no lock was set, and the watcher never called a fixer.

## Fix

`shared/src/lib/game/pokemon/stall.py`

- `TICK_DT_CAP_S = 60.0` — a slow tick counts the time it really took (a dead page: a minute per tick).
- `STOP_GAP_S = 300.0` — a gap longer than five minutes is a stop between two runs, not a slow tick: it counts
  nothing (the old behaviour of "a stop between two runs adds nothing" is kept).

With that, a dead page is seen as a stall after ~5 minutes of wall clock: the run ends cleanly, writes the stall
report and the lock, and the watcher starts the fixer that repairs the save — the way every other stall is
handled.

## Verification

`python3 -m pytest -q tests/shared/test_pokemon.py` — 167 passed, including
`test_stall_detector_sees_a_dead_browser_page_where_every_read_waits_out_its_timeout` (12 ticks of a minute: the
stall is seen), and the existing "a stop between two runs adds nothing" test.
