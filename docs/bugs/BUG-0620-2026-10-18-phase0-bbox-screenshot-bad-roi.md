# BUG-0620: phase-0 _detect_and_click passed the window rect as screenshot bbox — but the window's query-based rect was the wrong ROI on multi-monitor vpt-windows

**Date:** 2026-10-18
**Originally filed as BUG-0612 in the wave 8 commit message**;
renumbered to 0620 because a parallel agent claimed 0612 for the
AI budgets `team_id` null fix. See "Renumber note" below.
**Discovered on:** V7 run on `vpt-windows`. The detector failed
to find the LoL icon in 5 attempts even though the icon was
plainly visible in the operator's VNC view. The screenshots
returned by `screenshot_fn(target_path, bbox=...)` were 600×600
PNG crops that showed the **middle of the Riot window** (the
"What's New" carousel) but **not the left sidebar** with the
LoL icon.
**Severity:** medium — chain-blocking. The bbox was cropping
the wrong region.

## What was happening

The wave-8 attempt to scope the screenshot to the Riot window
(so the detector's normalized point is window-relative) was:

```python
geom = window.geometry
self._screenshot_fn(
    screenshot_path,
    bbox=(geom.x, geom.y, geom.x + geom.w, geom.y + geom.h),
)
```

The issue: the `window.geometry` returned by the tracker's
`wait_for_window` was based on a Win32 query that landed in a
**different session** than the screenshot. The python was in
session 1 (interactive scheduled task, BUG-0610 logging) and
its `EnumWindows` saw one Riot window at `(660, 276)` with
`w=620, h=600`. But the screenshot was captured by
`ImageGrab.grab(bbox=(660, 276, 1260, 876), all_screens=True)`
which actually grabbed the **wrong region** — the bbox
corresponded to a region of the desktop that did NOT contain
the Riot Client's left sidebar.

Root cause: the OS's primary monitor reported as 1024×768
(via `GetSystemMetrics(SM_CXSCREEN)`), but the actual GDI
capture returned 1920×1200 (via `ImageGrab.grab(all_screens=True)`).
The 1920×1200 GDI bitmap is the **secondary** monitor's
coordinate space, where (0, 0) is the top-left of the SECONDARY
monitor, not the primary. The `wait_for_window` query returned
the Riot window's position in the primary monitor's virtual
coordinates; the screenshot was taken in the secondary
monitor's pixel coordinates. The two were offset by ~1920 px
on x and ~200 px on y, so the bbox captured the wrong region.

## What ships

- **Wave 9 reverted the bbox attempt**. `_detect_and_click` now
  calls `self._screenshot_fn(screenshot_path)` without a bbox —
  the full-desktop capture that wave 5 / wave 8 / wave 9 all
  use. The detector's normalized point is now passed to
  `translate_decision_to_screen` with the new
  `screenshot_extent` keyword (BUG-0615) so the click pixel
  is computed correctly.

- The orchestrator still reads `window.geometry` for the drift
  check (it gates the click if the window moved between
  wait and click). The drift translator uses
  `current.x + normalized.x * current.w` as the click
  destination ONLY when no `screenshot_extent` is provided.
  With `screenshot_extent` provided (the phase-0 case), the
  formula becomes
  `screenshot_extent.x + normalized.x * screenshot_extent.w`
  = `0 + 0.135 * 1920` = `260` for the LoL icon center.

- The bbox attempt is preserved in the `_detect_and_click`
  history (the wave-8 commit on the feature branch) so the
  investigation is greppable, but the production code does
  not pass a bbox.

- **No new tests** — the change is one line (`screenshot_fn(
  screenshot_path)` instead of `screenshot_fn(screenshot_path,
  bbox=...)`), and the existing 172 tests cover the underlying
  screenshot-to-pixel path.

## Why this matters

- The bbox approach is sound in theory — capture a smaller
  region, the detector has less surface area to match, the
  match is faster and more accurate. It only works if the
  capture coord system and the tracker coord system are
  the same. On `vpt-windows` they are not (multi-monitor
  + DPI scaling + VNC virtual display), and the bbox
  approach silently captures the wrong region.
- The fix is the simplest possible: don't try to be smart,
  capture the full desktop, use the screenshot_extent keyword
  on the translator to denormalize correctly. The cost is
  one full-desktop ImageGrab call (5-20 ms on Windows GDI)
  and a slightly larger match surface for the detector
  (still < 50 ms with multi-scale).

## Renumber note

- This bug was originally claimed as **BUG-0612** in the
  wave 8 commit message (`bebbff02d`). A parallel agent
  committed `docs/bugs/BUG-0612-2026-10-18-ai-budgets-team-id-not-null.md`
  on origin/main between the wave 8 commit and the wave 9
  push. Re-filed as BUG-0620. The wave 8 commit message
  retains the 0612 reference.
- The actual wave 8 commit was correct in its DESCRIPTION
  of the fix; the ID collision is the only thing that
  changed.
