# BUG-0949 — The stall watcher left the save locked when its fixer ended

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0949                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | scripts (pokémon stall watcher)                              |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/task164-watcher-clears-the-lock`             |

---

## Symptom

An unattended Pokémon lane (TASK-33, TASK-164) can only play again when the lock of a stalled save is
cleared. The chain that clears it:

```
run stalls -> the dispatcher writes stall_<save>.lock.json in the canonical store
           -> the stall watcher starts one fixer agent (scripts/agent/pokemon_stall_watch.sh)
           -> the fixer diagnoses, fixes, deploys and CLEARS THE LOCK   <- the last link
           -> the lane plays on
```

The last link was the fixer agent's own work (step 6 of its brief). On 2026-10-26 two fixers ended
without doing it, and nothing noticed:

| Fixer | Stall | The lock was released | The lane was dark |
|---|---|---|---|
| `pokestall-20261026-084552` | `stall_second_20261026-084552.json` (second save) | 12:12 | **4 h 30** |
| `pokestall-20261026-121745` | `stall_latest_20261026-121745.json` (first save) | 12:11 | **54 min** |

Both fixers did their real work (the second save's diagnosis and fix are on main); neither cleared the
lock. The lane was dark until the lock was cleared by hand, and the save of the first lane did not
play a single minute in between.

Nothing reported it either. The watcher's own rule is *"a report that was handled is armed again only
after 6 h"*, so the same stall was not even looked at again, and the dispatcher's log only said
`save locked by a stall; waiting for the fix (then: pokemon_dispatch.py clear-stall)` once a minute.

## Root cause

**The watcher had two duties and did one of them.** It starts a fixer for a stall, and it lets the lane
play again. Only the first was implemented: when the fixer session was over, the watcher killed it
(`tmux kill-session`) and moved on to the next stall. Releasing the lock was left to the agent, which
is the one part of the chain that can end without having done its last step — the session can die, it
can be closed after the 75 min mark, or it can decide that the fix is enough.

The lock is the **only** thing that keeps a lane from playing, so an agent that forgot it did not slow
the lane down: it stopped it, for ever, with no alarm.

The other half of the root cause is the shape of the chain itself: the clear was a *step of the
fixer's brief* rather than a *duty of the watcher*. A brief is a suggestion to an agent; a duty of the
watcher is code that runs every minute whether or not an agent remembers.

## Fix

`scripts/agent/pokemon_stall_watch.sh`

- **The watcher clears the lock itself when its fixer is over.** The clear goes through the
  dispatcher's own command (`pokemon_dispatch.py clear-stall --save <save>`), so it lands with the
  lane that plays that save (BUG-0932) and that lane starts at once instead of waiting for its slot.
- **Only the lock that still names that very report is cleared.** A newer stall holds the lock then,
  and that one is not ours to clear: the watcher arms a fixer for it on its own.
- **A lock whose fixer is still working is never cleared.** The live fixer's report is read from the
  handled list and the clear is skipped while it is at work.
- **A failed clear keeps the fixer session**, so the next tick of the watcher tries again; the session
  is closed only once its save is unlocked.
- The fixer's own clear still works and is still asked for — it is simply no longer load-bearing.

## Verification

- `tests/scripts/test_stall_watch_clear.py` runs the watcher script **for real**, in a sandbox: a fake
  canonical store, a fake tmux, a fake ssh and a fake dispatcher that records the clear.
  - a finished fixer clears the lock of **its own** save (`clear-stall --save second`),
  - the first lane's save is named `latest` and not the default of the command,
  - a save that is not locked any more is not cleared,
  - a **newer** stall holding the lock is not cleared,
  - a fixer that is still working keeps its lock,
  - a failed clear keeps the session for the next minute.
  - **9 passed** — the four tests that describe the new behaviour fail without the fix
    (`the save stayed locked after its fixer ended`), the five guards pass with and without it.
- `python3 -m pytest -q tests/scripts/test_stall_watch_script.py tests/scripts/test_pokemon_dispatch.py
  tests/scripts/test_stall_watch_clear.py` → **32 passed**.

## Still open (not this bug)

* The save itself: the first lane stands on the last floor before the Hall of Fame (map 108, square
  (1, 1)) and re-stalls there. That is the runner's own bug — BUG-0947 and BUG-0948 fixed the door
  the player stands on and the rock that sealed him in; Victory Road 2F's plan is still open.
* A run that dies mid-way is still lost (the state and the memory are written at the end of a run).
