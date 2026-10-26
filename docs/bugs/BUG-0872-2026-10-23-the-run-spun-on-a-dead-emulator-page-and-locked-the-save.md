# BUG-0872 — The run spun on a dead emulator page and the lock stopped the whole long play

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0872                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped. The run of 2026-10-23 13:28 (host-clone-1) reported a stall and the
dispatcher started no run at all afterwards — the save was locked and every minute of play was lost:

```
no_progress: no milestone, no new map and no new square for 5 min of game time
at hall_of_fame (map 0, pos (0, 0))
```

Map 0, position (0, 0) is not where the game was: the run's own log says it was on **Route 23 (map 34)**
at (11, 105), surfing POISSIRENE over the water. The run's whole log was four events:

```
{"kind": "strategy",   "trigger": "resumed after a stop"}
{"kind": "walk_target", "map": 34, "pos": [11, 105], "target": [4, 31], "branch": "route"}
{"kind": "surf",        "map": 34, "at": [10, 103], "pokemon": "POISSIRENE"}
{"kind": "stalled",     "reason": "no_progress", "map": 0, "pos": [0, 0]}
```

Nothing at all between the surf (13:29:37) and the stall (13:40:12): **no key was pressed** in those ten
minutes, and not one event was written.

## Root cause

**The emulator page died and the runner could not tell.**

The host's journal of that run:

```
13:29:41  [PLAYWRIGHT 13:29:41.194]: JS done js:a32db882 () => vptGB.wram() in 30ms   <- the page answers
13:29:41  [PLAYWRIGHT 13:29:41.707]: JS done js:c1e9562a () => vptGB.hold('up', 180) in 2ms
13:30:25  [PLAYWRIGHT 13:30:25.831]: Page screenshot timed out after 20s                <- the page is gone
13:30:40  [device_utils] No run page screenshot (the run has no live page to photograph)
```

`test_scripts/game/game_pokemon.py` — `VptGameIO.wram()`:

```python
def wram(self):
    return self.js("() => vptGB.wram()") or [0] * 0x2000
```

When the page is dead the executor's JavaScript call answers with nothing, and the runner is handed
**8 KB of zeros** — indistinguishable from a game whose memory happens to be empty.

`shared/src/lib/game/pokemon/runner.py` — `Runner.tick()`:

```python
if "starter" in self.memo.get("done", []) and not self.read(ADDR["party_count"])[0]:
    # a blank memory read (seen on a host: no Pokémon, money 0): it would look like a defeat
    self.io.wait(300)
    return "bad read"
```

The branch was written for a **one-off** blank read. It has no limit and writes no event, so the runner
waited 300 ms and read again, for ever. Each of those ticks cost the 15 s of the dead page's JavaScript
timeout: the run burned 9 min 35 s doing nothing.

`shared/src/lib/game/pokemon/stall.py` then did what it was built for — no milestone, no new map, no new
square for five minutes — and wrote the stall report **and the lock**. The dispatcher starts no run while
the save is locked, so the long play was over until a person (or an agent) fixed the cause and cleared it.

The save itself was not lost: the page was dead, so `vptGB.upload()` failed, `saved` was false and
`state_latest.json` was never replaced. The canonical save still decodes to map 34, position (11, 105),
a party of 5 and 8 badges — the game exactly where the run started.

## Fix

`shared/src/lib/game/pokemon/runner.py`

- A blank read is counted. After **3 consecutive** blank reads the game is gone: the runner writes an
  `emulator_gone` event and the tick says so.
- `run()` ends the run on that tick, **before** the stall detector sees it: a map and a position the game
  is not on are never counted, so there is no stall and no lock.

`test_scripts/game/game_pokemon.py`

- A run that ended because the page died is not a stalled run: no report, no lock (the dispatcher keeps
  playing the save) and it is not counted as a run without progress.
- The state of a game that is gone is never written over the save: if the party that was there is not
  there any more, the upload is refused. A ROM that restarted by itself would otherwise have replaced the
  8-badge save with a title screen.

`shared/src/lib/game/pokemon/stall.py` was not changed: BUG-0868 already teaches the detector that a
slow tick is a slow tick. What was missing was the runner saying "there is no game left".

## Verification

`python3 -m pytest -q tests/shared/test_pokemon.py` — 168 passed, including
`test_a_dead_emulator_page_ends_the_run_instead_of_spinning_on_blank_reads` (three blank reads end the
run, the detector never sees the end of the run, and a game that answers again starts the count again).

The replay of the stalled save: `~/vpt-private/pokemon/stalls/stall_latest_20261023-132854.diagnosis.md`.
