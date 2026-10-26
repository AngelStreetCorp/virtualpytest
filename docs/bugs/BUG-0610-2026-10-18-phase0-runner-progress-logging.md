# BUG-0610: phase-0 runner has no live progress logging — the chain looked stuck for 12 h with no signal

**Date:** 2026-10-18
**Discovered on:** first live run of `Phase0Runner.run()` on `vpt-windows`.
The chain hung for 715 minutes (12 hours, 2242 CPU min) without writing
a `phase0-result.json`, leaving the operator blind to whether the
chain was making progress, stuck in a wait loop, or had crashed.
**Severity:** medium — the run was a no-op smoke test on a developer
machine, not a customer-impacting failure, but the silence made the
incident look like a hard crash when it was actually a stuck
`wait_for_window` poll.

## What was happening

`Phase0Runner._wait_for_riot_window()` calls
`Win32WindowTracker.wait_for_window(title="Home", timeout_s=60)` in a
loop with a 0.5 s poll. The poll logic is correct (deadline-based,
returns None on timeout) and the unit tests cover it. The actual
failure was upstream: the scheduled task was launched in **session 0**
(SYSTEM principal) on `vpt-windows`, so the python was enumerating
session-0 windows. The Riot Client UI was in session 1 (the user's
logged-in console). `EnumWindows` returns the session-0 desktop,
which has no visible windows. Result: 60 s of silent polling, then
`None` returned, the step reported `wait_for_riot ok=False`, and the
chain exited cleanly. The 12-hour uptime was the **system Python**
binary staying alive because the parent PowerShell never reaped it
after the python script terminated inside the `wait` call's parent
thread — unrelated to the deadline logic.

The follow-on investigation (V5 task, session-1 principal) confirmed
the diagnosis by reading the live `phase0-run.log` (which **did not
exist** before this fix): no progress lines, no `wait_for_riot`
output, no start/timeout markers.

## What ships

- **`Phase0Runner._wait_for_riot_window()` + `_wait_for_league_window()`**
  start two new background threads per wait step:
  - A **progress thread** (`_wait_progress_loop`) that logs every 5 s
    with the visible-window count, the count of `riot_like` /
    `lol_like` matches (filtered by title and class_name), and a
    `tasklist /FI` summary of `RiotClientServices.exe`,
    `LeagueClientUx.exe`, `League of Legends.exe` process states.
    This is the line that would have shown `visible=0` and
    `RiotClientServices: 1 alive` immediately, before the 60 s
    timeout, making the session-0 isolation obvious from the log.
  - An **explicit start / timeout / found line** bracketing the
    wait (`[phase0] wait_for_riot: starting (timeout=60s)` →
    `[phase0] wait_for_riot: found HWND=0x... pos=(...)` or
    `[phase0] wait_for_riot: TIMEOUT after 60s`). Same shape on
    `wait_for_league`.

- **`Phase0Runner.run()`** now also prints explicit
  `[phase0] kill_existing: starting / done` and
  `[phase0] launch_riot: <path>` lines so the operator can see
  which step the chain is on, even if the chain never reaches the
  JSON-writing code at the end.

- The new lines are emitted via `print(..., flush=True)` so they
  reach the parent PowerShell's stdout immediately (no buffering).
  They are also captured by the entry script's `_TeeWriter` (see
  `run_phase0.py` v2) which mirrors every print to
  `C:\virtualpytest\phase0-run.log` for postmortem.

- A new helper method `_wait_progress_loop(step_name, start,
  stop_after_s)` lives at the bottom of `phase0_runner.py`. It
  joins on the `tracker.enumerate()` calls + a `tasklist` shell-out
  every 5 s, with a `subprocess.run(..., timeout=3)` guard on the
  tasklist so a wedged `tasklist` cannot block the progress thread.

- **No new tests** — the helper is read-only logging; the existing
  `test_phase0_runner.py` covers the underlying wait / detect /
  click logic. The progress thread exits cleanly on its own deadline
  and the main thread is not blocked by it (it's a daemon).

- The progress lines are operator-friendly: short enough to scan
  quickly (`[phase0] wait_for_riot +5s: visible=18 riot_like=1
  lol_like=0 procs={...}`), one per 5 s, never raised to error
  level — a stuck chain looks like 12 identical lines in the log,
  not a single 12-hour blank.

- Companion fix shipped in the same wave: `run_phase0.py` v2 opens
  a `phase0-run.log` and a try/except/finally wrapper around
  `main()` so even a crash mid-step writes `phase0-result.json` (the
  v1 wrapper had no tee + no try/except, so a `wait_for_window` that
  returned `None` propagated and the script died before JSON).

## Why this matters

- The first end-to-end run of the chain on `vpt-windows` hung for
  12 hours in a known-broken state (session-0 vs session-1) without
  producing a single log line. The 12-hour CPU-time anomaly
  (`PID 28744` showing 2242 CPU min in `Get-Process`) would have
  been diagnosed in 5 minutes if the log had shown
  `visible=0 riot_like=0` once per 5 s.
- The 12-hour hang cost two investigation cycles (V4 task, V5
  task) and required a v2 of `run_phase0.py` with the
  try/except/finally wrapper. With BUG-0610's logging in place, the
  V4 result would have been: log says `visible=0` after 5 s →
  suspect session-0 isolation → switch the scheduled task to
  `LogonType Interactive` + `UserId "joach"` → V5 succeeds in
  30 s instead of 90 min.
