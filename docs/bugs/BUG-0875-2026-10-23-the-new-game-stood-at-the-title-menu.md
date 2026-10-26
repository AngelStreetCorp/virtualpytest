# BUG-0875 — The new game stood at the title menu: the runner pressed keys into a frozen emulator and the lock stopped the lane

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0875                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The second long-play lane (the parallel save `second`, TASK-164) never played a single step. Every run
died the same way: `no_progress` at the milestone `starter`, map 0, position (0, 0), no Pokémon and no
money — the picture of a brand-new game that has not even been started.

Run `20261023-144004` (host-clone-1):

```json
{"kind": "pokemon_stall", "created": "2026-10-23T14:47:39+0200", "run_id": "20261023-144004",
 "save": "second", "reason": "no_progress",
 "detail": "no milestone, no new map and no new square for 5 min of game time",
 "milestone": "starter", "map": 0, "pos": [0, 0], "done": [], "deferred": [],
 "stall_counters": {"progress_s": 309.4, "maps": [0], "milestones": 0, "spot": null,
                    "spot_ticks": 0, "ms": "starter", "battle_s": 0.0, "cells": 1}}
```

The run itself:

```
"play_duration_s": 450.2, "ticks": 11, "ticks_by_kind": { "intro": 11 },
"money": 0, "party": [], "badges": 0, "saved": false
```

**11 ticks in 450 seconds**, and one single event: the `stalled` one. The four runs before it
(12:41, 13:43, 14:09, 14:24) are identical, and the dispatcher could not pull a save out of any of them
(`pull lacks state_second.json`), so the lane started a **new game** every time and never got past the
title screen.

## Root cause

**The game was alive but frozen, and the runner could not tell.**

The host's journal of the run:

```
14:40:16.590  JS done js:b4bda3d9 () => vptGB.hold('a', 90) in 2ms      <- the runner presses
14:40:21.012  JS done js:84317993 () => vptGB.hold('start', 90) in 11ms  <- the 6th press: the menu opens
14:40:21.660  JS done js:a32db882 () => vptGB.wram() in 48ms            <- the last answer of the page
14:40:26.661  Page screenshot timed out after 5s
14:40:51      Error: JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
```

The host's screen capture of that run shows the French title menu with the cursor on **"▶ NOUVEAU
JEU"** — the START press opened the menu, and the A press that should have picked the new game never
reached it. The captures are byte-identical over ten seconds, so the emulated CPU was not ticking
either: the game's memory never moved.

Two runner defects turned that into a **locked** save:

1. **The dead-page guard of BUG-0872 does not cover a new game.**
   `shared/src/lib/game/pokemon/runner.py`:

   ```python
   if "starter" in self.memo.get("done", []) and not self.read(ADDR["party_count"])[0]:
       self.blank_reads += 1
       if self.blank_reads >= BLANK_READ_LIMIT:
           self.event("emulator_gone", reads=self.blank_reads)
           return "emulator gone"
   ```

   A new game has no starter, so the guard never fires: the runner presses A and START into the frozen
   game, tick after tick, until the budget ends.

2. **The stall detector counts the intro as "no progress".**
   `shared/src/lib/game/pokemon/stall.py` (`StallDetector.observe`) only skips the time of a *guarded*
   activity (`Runner.self_guarded`: training and the Surf hunt). The intro of a new game — the title
   screen, Oak's speech, the names — is not guarded, so the no-progress clock ran while the runner was
   still naming the player. Five minutes later the detector wrote the report **and the lock**, and the
   dispatcher starts no run while a save is locked.

   The report's counters are the fingerprint of a run that never played: `spot: null`, `spot_ticks: 0`
   (every tick was exempt: "intro"), `maps: [0]`, `cells: 1`, `milestones: 0`.

Why the emulator stopped is the platform's business (the page's renderer stopped answering after the
sixth press; the same symptom ended the run of 13:28 — BUG-0872 — and the "latest" lane's run of 14:55
logged 58 JavaScript timeouts as well). The runner has to survive it.

## Fix

`shared/src/lib/game/pokemon/runner.py`

* `Runner.game_is_frozen()` — the game's work RAM is compared with the previous tick's snapshot
  (`SnapshotIO.snapshot()`, the 8 KB the runner already fetches every tick, so the probe is free). The
  game writes its OAM shadow every frame — measured: the work RAM changes in **every** 100 ms window,
  484 addresses — so a snapshot that does not change at all for `FROZEN_TICKS` (4) ticks is a game
  whose keys go nowhere.
* `Runner.reboot_emulator()` — the emulator is restarted in the page (`vptGB.boot()`: the ROM is
  loaded again and the save with it), so the run goes on from the save instead of standing still.
  When the page does not answer at all, the run ends with `emulator gone` — **before** the detector sees
  it, so there is no stall and **no lock** (the rule of BUG-0872, now true for a new game too).
* `Runner.self_guarded()` — the intro of a new game is a guarded activity: its time is not "no
  progress" any more.

`test_scripts/game/game_pokemon.py`, `test_scripts/game/local/pokemon_play_local.py`

* the IO's `reboot()`: the page is asked to boot the ROM again.

## Verification

Guard tests in `tests/shared/test_pokemon.py` (the whole file passes: 173 tests):

* `test_a_game_that_never_moves_is_restarted_and_never_locks_the_save` — a game whose memory never
  changes is restarted after `FROZEN_TICKS` ticks; a page that cannot be restarted ends the run with
  `emulator gone` (no stall, no lock); a running game is never taken for a frozen one.
* `test_the_intro_of_a_new_game_is_not_counted_as_no_progress` — the intro is guarded, and the stall
  detector sees no progress in it.

A local replay of a fresh game with the same code plays the intro through (233 ticks: 157 of them in
the intro, then Oak's speech and the bedroom), and the game's work RAM changes in every 100 ms window.

Diagnosis: `~/vpt-private/pokemon/stalls/stall_second_20261023-144004.diagnosis.md`.

**No defer flag was involved**: `deferred` is empty and no `*_deferred` flag was set. The game needs the
starter Pokémon and the whole story; nothing was skipped to get here.
