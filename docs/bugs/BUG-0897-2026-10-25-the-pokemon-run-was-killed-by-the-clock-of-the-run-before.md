# BUG-0897 — The Pokémon run was killed by the no-progress clock of the run before it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0897                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games                                                       |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The `latest` lane stopped on **Victory Road 1F** (map 108) and locked the save. The run
`20261025-000846` ended with `no_progress`: "no milestone, no new map and no new square for 5 min
of game time", at map 108, pos (9, 14), milestone `hall_of_fame`.

The run is the odd one out: it **played 29 seconds** (it started at 00:08:46 and the detector
wrote the report at 00:09:15) and its whole log is three events —

```
{"kind": "strategy",   "trigger": "resumed after a stop", "source": "fallback", …}
{"kind": "boulder_push", "map": 108, "boulder": [9, 14], "to": [[8, 14]],
 "direction": "LEFT", "steps": 1, "moved": true, "aside": true}
{"kind": "stalled",    "reason": "no_progress", "milestone": "hall_of_fame", "map": 108, "pos": [9, 14]}
```

— and the counters of the report say why it was so short:

```
"stall_counters": {"progress_s": 300.19465494155884, "maps": [108, 34], "milestones": 33,
                   "spot": [108, [9, 14]], "spot_ticks": 1, "ms": "hall_of_fame"}
```

`progress_s` is **300.19 s**, already over the threshold of 300 s — and it is the clock of the run
**before** this one, not of this one.

## Root cause

**A run must not be judged on a measurement it did not spend.**

- The no-progress clock lives in the memo and **carries over from one run to the next**
  (`shared/src/lib/game/pokemon/stall.py:51`), so that a milestone that never progresses is caught
  even when every run is short. The clock of a run that ended in a stall is forgotten when the
  lock is cleared (`stall.py:217 forget_on_unlock`).
- The run before this one (started 2026-10-24 21:34 UTC) played its full budget and **died before
  it wrote its stall report and its lock**: the dispatcher pulled **2 files** (the state and the
  memory), found **no lock** and started the next run **without** `--clear_stall yes`, so nothing
  cleared the clock it had left behind.
- The report and the lock of a stalled run were written **after** the long upload of the game
  report (a video of tens of MB, `test_scripts/game/game_pokemon.py:455`), while the **memory** —
  the file that carries the overdue clock — was written long before it
  (`game_pokemon.py:443`). A run that dies in between leaves the save **unlocked with an overdue
  clock in it**.

The next run then inherited the clock, and the detector fired on its **very first tick**: the
first `observe()` of a run adds no time (the detector has no previous tick, `stall.py:60`), so the
inherited value was read as it was and `stall.py:100`
(`if st["progress_s"] >= self.no_progress_s`) fired at once. The detail of the report — *"for 5 min
of game time"* — describes the run before, not this one.

The floor itself was **not** stuck: the rock the chain pushes was moved out of the doorway
(`boulder_push … boulder [9, 14] → [[8, 14]] direction LEFT moved True aside True`) exactly as it
should be — the move that lets the player out of the pocket and off the floor.

## Fix

- `shared/src/lib/game/pokemon/stall.py` — a measurement that is **already overdue when a run
  starts** is not that run's: the run starts its own clock. The no-progress clock and the counter
  of the square the player stands on are reset when the run inherits them overdue. A clock **under**
  the threshold still carries over — the time of a stuck milestone spans its runs.
- `test_scripts/game/game_pokemon.py` — the stall report **and the lock** are written **before** the
  memory and before the upload of the game report. A run that dies in between still leaves the lock
  behind, so the dispatcher waits for the fix instead of starting a doomed run that dies in seconds
  and locks the lane again.

## Verification

- `python3 -m pytest -q tests/shared/test_pokemon.py` → **208 passed** (2 new guard tests: a run is
  not killed by a no-progress clock it inherited, and the stall report and the lock are written
  before the game report is uploaded).
- A local replay of the canonical save of this stall (`test_scripts/game/local/pokemon_play_local.py`,
  240 s, the code of `main`) plays the floor and **recovers** on its own: the runner leaves the
  floor and enters it again (`waypoint_unreachable 108 wanted 194 back 34` → the exit mat at
  (8, 17) → map 34 → back to 108), which puts the boulders back where they were, and the chain of
  the pressure switch then runs to the end — (5,15)→(5,16)→(9,16)→(9,14)→**(16,14)**→(16,12)→
  (17,12)→**(17,13)**, the switch, every push `reached`. **249 ticks, `stalled: null`.**
- The `deferred` list of the report is empty: no milestone was deferred and the story was not ended
  on a flag, so this is not a `deferred_end` stall.
- On the live hosts: the fix is deployed with `main-2026.10.24-89966` (host-clone-1 and
  host-clone-2, the two hosts `POKEMON_HOSTS` names) and the lock of the save is cleared; the next
  dispatcher tick starts a run with `--clear_stall yes` on the first free host.
- **On the live host** (the run of 2026-10-24 22:43 UTC on host-clone-1, deployed
  `main-2026.10.24-89966`): the run **inherited the very same overdue clock** — the memory it
  started from carried `progress_s = 300.19465494155884`, the value the run of the report died on —
  and it did **not** die on its first tick: it played for **22 minutes** (1349 s) and left the save
  **unlocked** (no lock, no stall report). Without the fix that run would have been killed 16 s into
  it, exactly like the run of the report. The next run started at 23:06 UTC and the lane keeps
  playing; **its recorded steps show the runner playing the game**: `Started at hall_of_fame (save
  latest)` → `defeat: money_before=493, money_after=246` → `strategy: trigger=defeat at
  hall_of_fame, source=fallback, plan="Lost at hall_of_fame to a string of weak trainers: heal more
  often, no training."` → `healed: hp=467` — 22 minutes of fight, loss, re-plan and heal instead of
  a stall on the first tick.
- **Still open (not this bug).** The process of that run died before it wrote its files (the state,
  the memory and the segment), so its play was lost: a run that dies **during** the play still loses
  everything, because the state and the memory are only written at the end of the run. That is the
  pre-existing weakness of the executor (the handover's "the executor hang"), and it is what left the
  overdue clock behind in the first place — the fix makes the lane survive it, it does not save the
  play of a run that dies mid-way.
