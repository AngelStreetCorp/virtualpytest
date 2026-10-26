# BUG-0932 — The clear of a stall reached the wrong lane: the second save waited 5 h 30

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0932                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                       |
| Area      | games / pokemon dispatcher (ops agent)                       |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/task164-clear-the-right-save`                |

---

## Symptom

The **second** Pokémon's save did not play from 2026-10-26 01:14 to 06:50 — five and a half hours —
although the fix for its stall was on main and deployed on its host.

The lock of the save was right (`stall_second.lock.json`), the watcher saw it, a fixer worked on it
(02:27, in the tree of BUG-0923), and the fixer's brief told it exactly what to do:

```
6. Clear the lock: `python3 scripts/agent/pokemon_dispatch.py clear-stall` (the next dispatcher tick,
   within a minute, starts a run with `--clear_stall yes` on a free host).
```

That command **only ever clears the first lane's save**. `pokemon_dispatch.py` reads its save from
`POKEMON_SAVE` and its state from `POKEMON_STATE_DIR`, and the plain command uses the defaults — the
first lane's. The second lane runs under its own unit, with
`POKEMON_SAVE=second` and `POKEMON_STATE_DIR=~/.cache/pokemon-dispatch-2`.

So the fixer cleared the wrong lane: the first lane's flag (which the first lane had already used at
02:22) and never the second lane's. The second lane's dispatcher kept logging, every minute:

```
save locked by a stall; waiting for the fix (then: pokemon_dispatch.py clear-stall)
```

and the watcher, seeing the lock still there, re-armed a fixer every six hours.

## Fix

- `scripts/agent/pokemon_dispatch.py` — `clear-stall` takes `--save <name>`. A clear for **another**
  save is written into the canonical store (`clear_<save>.request`), the one place both lanes share;
  the lane that plays that save takes the request on its next tick and clears its own lock. The plain
  command keeps its meaning (this lane's own save).
- `scripts/pokemon_stall_review.py` — the brief's clear command names the save the stall is about
  (`--save <save>`), so the fixer clears the lock it was sent for.
- `scripts/agent/pokemon_stall_watch.sh` — the watcher reads the save from the lock file it is fixing
  (`stall_second.lock.json` → `second`) and passes it on.

## Verification

- `pytest -q tests/scripts/test_pokemon_dispatch.py` → **16 passed**, two of them new: a clear asked
  for another save reaches that lane (and only that lane), and a request in the store clears the lock
  on the next tick.
- `pytest -q tests/scripts/test_stall_watch_script.py` → **7 passed**: the watcher names the save and
  the brief carries the clear command that names it.
- Live: both lanes were cleared the repo's own way on 2026-10-26 06:50 and started again at 06:51 —
  the main save on `host-clone-1`, the second save on `host-clone-2`, one lease each.
