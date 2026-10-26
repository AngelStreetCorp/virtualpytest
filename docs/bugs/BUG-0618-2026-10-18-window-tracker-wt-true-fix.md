# BUG-0618: Win32WindowTracker WNDENUMPROC callback returned wt.TRUE / wt.FALSE, but those attributes do not exist in ctypes.wintypes

**Date:** 2026-10-18
**Originally filed as BUG-0609 in the wave 6 commit message**;
renumbered to 0618 because a parallel agent claimed 0609 for the
projects-slice follow-ups. See "Renumber note" below.
**Discovered on:** first end-to-end run of the wave-5
`Phase0Runner` on `vpt-windows`. The chain launched
`RiotClientServices.exe` successfully (PID 27568) but the
`Win32WindowTracker.wait_for_window` poll returned `None`
forever — the `EnumWindows` callback was raising
`AttributeError: module 'ctypes.wintypes' has no attribute
'TRUE'` on the first `IsWindowVisible` check.
**Severity:** high — chain-blocking. The tracker is the read-only
planner for every click; a tracker that crashes silently is a
no-op for the whole orchestrator.

## What was happening

In `Win32WindowTracker.enumerate()`, the WNDENUMPROC callback
returned `wt.TRUE` / `wt.FALSE` to signal "continue enumerating"
or "stop":

```python
@_WNDENUMPROC
def _cb(hwnd, lparam):
    if not _BOOL(_user32.IsWindowVisible(hwnd)):
        return wt.TRUE   # AttributeError on Windows
    rect = wt.RECT()
    if not _BOOL(_user32.GetWindowRect(hwnd, ctypes.byref(rect))):
        return wt.TRUE
    ...
    return wt.TRUE
```

`ctypes.wintypes` (alias `wt`) does **not** define `TRUE` or
`FALSE`. The correct constants are bare `True` / `False` (Python
booleans, which ctypes converts to/from `LONG` for stdcall
APIs), or `ctypes.c_long(1)` / `ctypes.c_long(0)`. The
`wt.TRUE` reference raised `AttributeError` on the first
invisible window, the callback propagated the exception, and
`EnumWindows` returned an empty result. The tracker saw 0
windows and reported "no Riot Client found" 60 s later.

The fix was applied to the vpt-windows copy of
`window_tracker.py` during the operator's live debug session on
2026-10-18 09:30, but was **not committed** to the worktree
until wave 6. The reason: the wave-5 commit
(`6de5fdae4 feat(league): TASK-121 wave 5 - phase-0 launcher
chain`) shipped with the broken `wt.TRUE` references — the
unit tests on macOS passed because the tracker raises
`TrackerUnavailableError` immediately on non-Windows hosts,
so the WNDENUMPROC callback was never reached.

## What ships

- **`shared/src/lib/game/leagueoflegends/window_tracker.py`** —
  three `wt.TRUE` references replaced with bare `True`. The
  callback's restype is `wt.BOOL`; Python's `True` is a `bool`
  which ctypes marshals to a 4-byte integer for stdcall APIs.
  The ctypes layer handles the conversion; no explicit cast
  needed.

- **No new tests** — the WNDENUMPROC callback path is
  Windows-only and would need a mocked `user32.dll` to test on
  macOS. The existing `TrackerUnavailableError` tests still
  cover the cross-platform guard, and the V8 run on
  `vpt-windows` (where `EnumWindows` returned the Riot
  Client window with title "Riot Client" and class
  "Chrome_WidgetWin_1") is the live integration test.

- **Followup**: ship a Windows-only integration test that
  imports `Win32WindowTracker` and asserts
  `tracker.enumerate()` returns a non-empty list of
  `TrackedWindow` when run on a host with at least one
  visible window. The test would have caught this bug in
  wave 5. The catch is it can only run on Windows, so it
  needs to live in a `pytest -m windows` marker or a
  separate Windows-only test file. TODO in `TASK-121 §6`.

## Why this matters

- Every `click_*` step of the phase-0 orchestrator calls
  `tracker.query_by_hwnd` immediately before the click
  (BUG-0617 makes the failure mode non-fatal, but the
  drift check still relies on a live tracker). A broken
  `enumerate()` makes the tracker useless.
- The wave-5 unit tests were not a sufficient integration
  gate because they short-circuited on macOS via
  `_require_windows()`. A future test suite needs at least
  one Windows-only integration smoke test per
  Win32-backed module (`window_tracker`, `click_executor`).
  See `TODO-handover.md` §3.

## Renumber note

- This bug was originally claimed as **BUG-0609** in the
  wave 6 commit message (`728ede78a`). At the time the
  commit was prepared, `git ls-tree -r origin/main
  docs/bugs/ | grep BUG- | sort -u | tail -1` returned
  0608, so 0609 looked free. Between the commit and the
  push, a parallel agent committed
  `docs/bugs/BUG-0609-2026-10-18-projects-slice-followups.md`
  (a different bug) on origin/main. Per the BUG-id
  renumbering rule, the fix is re-filed here as BUG-0618.
  The original commit message retains the 0609 reference
  (history is read-only); this doc supersedes it.
