# BUG-0920 — The lanes ran the code they were deployed with, not the code of main

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0920                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | infra / game lanes                                           |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

**The fixes were on main and the lanes did not have them.** Two of them, in two different ways, and
neither announced itself:

- The **stall watcher** kept the code that reads only the **latest** lock of the canonical store
  while main had long read **every** lock. The second Pokémon save therefore stayed locked from
  **2026-10-23 17:35** to 2026-10-25 — two days — and nobody was ever asked to fix it: the watcher
  looked at a file that did not exist and went quietly back to sleep.
- The **game dispatcher** ran a tree that was dozens of commits behind main. The CoC job that main
  had already repaired was still the old one, and the lane's own log said so every minute:
  `tick: coc-flash: past 2026-10-25`.

Nothing failed. The lanes were *healthy* and *out of date*, which is the worst kind of failure: the
owner saw a lane that was running and a lane that was not playing.

## Root cause

**The lanes ran from clones that were never synced, and the sync that was there could not work.**

| Lane                     | Ran from                        | How it was meant to stay current                | What actually happened                                                       |
|--------------------------|---------------------------------|--------------------------------------------------|---------------------------------------------------------------------------|
| game dispatcher          | `~/.local/share/game-dispatch/repo` | nothing (the unit has no sync step)          | the clone sat on an old commit                                            |
| Pokémon dispatcher       | the shared checkout `~/virtualpytest` | somebody pulls it (nobody does, by hand) | it stays wherever the last session left it                              |
| stall watcher            | `~/.local/share/vpt-stall-watch` | `git pull --ff-only` inside the script       | the clone sat on a **merge commit**: the pull could not fast-forward, `\|\| true` swallowed the failure, and the clone stayed where it was |
| CoC Flash lane           | the shared checkout `~/virtualpytest` | the same | the same                                                          |

Two different mistakes, one consequence. A clone that is never synced runs the code it was
deployed with, for ever. A pull that cannot fast-forward is a **silent** no-op — the `|| true` that
keeps the lane alive when the network is down also hides a pull that never happened.

The shared checkout was the worse of the two: it is the working copy of **every Claude Code session
on this host**, and its branch is switched under them (the repository's own rules say so). A lane
that runs from it runs whatever branch the last session left behind.

## Fix

- `scripts/agent/sync_lane_clone.sh` — brings a lane clone back to `origin/main`. A fetch that fails
  (no network, no key) does **not** stop the lane: it keeps the code it has and says so.
- Every lane unit now syncs its clone before each tick and runs the lane code **from that clone**
  (the units themselves are with the owner, Q235: they are the half of the change the merge policy
  holds back, and they are already installed on codebox).
- The stall watcher's own `git pull` is gone: the unit's sync does the job, and it does not fail
  silently.

After the merge the lanes pick the code of main up **by themselves**, within a minute.

## Verification

- `scripts/agent/install_codebox_lanes.sh` on codebox: the five units are active, and the clone of
  the game dispatcher moved from `b206ee3a1` (the old commit) to the tip of main.
- The stall watcher's journal shows the sync line before every run of the watcher.
