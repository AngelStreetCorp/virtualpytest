# BUG-0923 — The Pokémon stall fixer worked from a checkout that was a day old

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0923                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                       |
| Area      | games / pokemon stall pipeline (ops agent)                   |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/task164-stall-fixer-tree`                    |

---

## Symptom

The stall watcher started the fixer for the Pokémon's `hall_of_fame` stall on 2026-10-26 01:11
(`pokestall-20261026-020740`). The fixer replayed the canonical save locally and found this:

```
Excellent — the local replay hit a RecursionError: walk → unblock → talk_at → walk → unblock…
```

That recursion **had been fixed 16 hours earlier** and is on main since `c25b5cbbef6d` (BUG-0919).
The stall the fixer was sent to fix was a different thing: the live run had ended with
`STALLED: the same map position for 300 ticks at hall_of_fame` — a stall, not a crash.

So the fixer spent its half hour on a bug that no longer existed, and the save stayed locked.

## Root cause

**The fixing session started in the shared checkout.**

`scripts/agent/pokemon_stall_watch.sh` handed the session a working directory:

```bash
REPO="${HOME}/virtualpytest"     # where the fixing session works (it makes its own worktree)
```

`~/virtualpytest` is the working copy of **every Claude Code session on codebox**: its branch is
switched under them and its HEAD is whatever the last session left behind. On 2026-10-26 it sat at
`4cb24d35e` — **2026-10-25 02:37**, a day behind main. The fixer's brief tells it to read the runner
and `git log --oneline -15 -- shared/src/lib/game/pokemon` to see whether someone already shipped a
fix; in that tree there was no such log, because the fix was not in that tree.

This is the same class of fault as BUG-0920 (*the lanes ran the code they were deployed with*), one
step further down: that fix put the **watcher's own clone** back on main before every tick, but the
tree the *fixer* works in was never touched.

## Fix

- `scripts/agent/pokemon_stall_watch.sh` — the fixer gets a tree of its own,
  `~/.local/share/vpt-stall-fix`, put on `origin/main` right before the session starts, and the
  session starts there (`cbsession -d "${FIX_REPO}"`). A tree that is **dirty** (the previous fixer
  is still at work in it) is left alone, because a reset would throw that work away; a failed fetch
  never stops the fixer, it keeps the code it has.
- The clone's **origin URL** is set right after the clone: a clone of a local path takes that path as
  its origin, so the sync would fetch the stale shared checkout instead of the real remote.
- `scripts/pokemon_stall_review.py` — the brief names the tree (`--repo`) and tells the agent to read
  the code there and **not** from `~/virtualpytest`.

## Verification

- `pytest -q tests/scripts/test_stall_watch_script.py` → **6 passed** (new file): the fixer is not
  started in the shared checkout, it gets a tree of its own, that tree is synced before the session
  starts, the brief names it, and the brief template holds no placeholder the formatter would choke
  on.
- The clone, made exactly the way the watcher makes it, lands on `f666d080d` (`origin/main`) and
  carries the runner fix of BUG-0919 — the code the fixer of yesterday would not have seen.
