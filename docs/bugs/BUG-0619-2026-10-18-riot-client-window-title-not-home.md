# BUG-0619: phase-0 wait_for_riot looked for window title='Home', but the actual Riot Client title is 'Riot Client'

**Date:** 2026-10-18
**Originally filed as BUG-0611 in the wave 7 commit message**;
renumbered to 0619 because a parallel agent claimed 0611 for
`auto_tag_with_project` deprecation. See "Renumber note" below.
**Discovered on:** V6 run on `vpt-windows`. The chain found 18
visible windows in session 1 (correct — the python is now in the
operator's session via the BUG-0610 logging + interactive
scheduled task), but `wait_for_window(title="Home")` returned
`None` after 60 s. The progress thread's
`[phase0] wait_for_riot +5s: ... match: hwnd=0x... title='Riot
Client' cls='Chrome_WidgetWin_1'` log line was the diagnostic.
**Severity:** high — chain-blocking. The wait step would have
succeeded if the title had been right.

## What was happening

`Win32WindowTracker.find_riot_client()` and
`Phase0Runner._wait_for_riot_window()` were both looking for
`title="Home"`. The original guess came from a misreading of
the Riot Client's left-sidebar page label ("Home" is the page
name on the sidebar) as the window's title bar text.

The actual Riot Client's main UI window title is
**`"Riot Client"`**, with class `"Chrome_WidgetWin_1"`
(Electron renderer). Verified by Win32 `EnumWindows` on the
live box:

```
WIN hwnd=0x8e0218 title='Riot Client' cls='Chrome_WidgetWin_1' pid=22004
```

The "Home" page name is a sidebar navigation tab inside the
window, not the Win32 title.

## What ships

- **`shared/src/lib/game/leagueoflegends/window_tracker.py`**:
  `find_riot_client()` now `query_by_title("Riot Client")` and
  the docstring notes the actual Electron class.
- **`shared/src/lib/game/leagueoflegends/phase0_runner.py`**:
  `_wait_for_riot_window()` passes `title="Riot Client"` to
  `wait_for_window(...)`.
- **Tests updated**:
  - `tests/shared/test_leagueoflegends_window_tracker.py`:
    `test_tracker_unavailable_*` calls now use "Riot Client"
    where they used "Home".
  - `tests/shared/test_leagueoflegends_phase0_runner.py`:
    `FakeTracker.find_riot_client()` and the `_tracked(...)`
    fixtures in the happy-path test now use "Riot Client".
- **No change to the find_league_client API** — the League
  Client's title is "League of Legends" (correctly substring
  matched with `exact=False`).
- **No semantic change to the drift translator** — the
  translator cares about `(x, y, w, h)`, not the title.

## Why this matters

- This bug was the gate between "the python sees the desktop"
  (V5) and "the python finds the Riot Client window"
  (V6). Without this fix, no amount of progress logging or
  multi-scale matching can get past `wait_for_riot`.
- The original "Home" guess is the kind of bug unit tests
  can't catch: the test fixtures were constructed by the
  same agent who guessed "Home", so the round-trip matched
  perfectly. The fix only surfaced when the chain ran on
  the real desktop.
- **Lesson**: when guessing window titles from screenshots,
  read the **title bar** (the OS-level window decoration),
  not any in-window text. The Riot Client's title is set by
  the Electron `BrowserWindow({title: "Riot Client"})`
  call, which is the source of truth.

## Renumber note

- This bug was originally claimed as **BUG-0611** in the
  wave 7 commit message (`109bb8a2c`). At the time the
  commit was prepared, `git ls-tree -r origin/main
  docs/bugs/ | grep BUG- | sort -u | tail -1` returned 0608
  (0609/0610 were claimed but not yet on origin/main in the
  agent's window). Between the commit and the push, a
  parallel agent committed
  `docs/bugs/BUG-0611-2026-10-18-deprecate-auto-tag-with-project.md`
  on origin/main. The fix is re-filed here as BUG-0619.
  The original commit message retains the 0611 reference.
