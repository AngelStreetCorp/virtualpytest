# BUG-0567 — Black screen tile showed Live instead of Black Screen

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0567                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | monitoring                                                   |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A device tile showed the Localize badge `live` on a fully black picture. The matcher was not
naming the screen. The operator expected `Black Screen · 100 %` (signal + how black the frame is).

## Root cause

While a blackscreen incident is ongoing, freeze detection is skipped (correct: freeze must not
outrank blackscreen). Motion is measured only inside freeze, so the last motion dict stayed
`kind=full` from the previous live channel. The 1 Hz Localize loop treats full-frame motion as
live TV and skips `identify_screen` / `classify_special_state`, so the badge never left `live`.

## Fix

On blackscreen / no_signal, replace the stale motion dict with a static signal state. The
Localize gate yields to that state and returns a `signal` verdict (`Black Screen` / `No Signal`).
The tile shows `Black Screen · 100 %` for a confident signal.

## Verification

Unit tests: stale `kind=full` + `state=blackscreen` is signal, not live; fuse clears cached live
motion when freeze (and therefore motion) is missing. After deploy, restart `vpt-monitor-img` on
the host and confirm a 100% black capture shows `Black Screen · 100 %` instead of `live`.
