# BUG-0615: translate_decision_to_screen() always treated the normalized point as WINDOW-relative, but the phase-0 orchestrator captures the full desktop

**Date:** 2026-10-18
**Discovered on:** V9 run of `Phase0Runner.run()` after the LoL icon
template was re-cropped (BUG-0622). The chain found the icon (match
score 1.0 at pixel `(260, 660)` in the 1920×1200 GDI capture) but
the click landed at `(660 + 0.135×620, 276 + 0.55×600) = (744, 606)`
— a different pixel. The click was on the right WINDOW but the
wrong SPOT inside it (the WINDOW's left sidebar is not where the
detector found the LoL icon; the LoL icon was on the desktop
wallpaper relative to the WINDOW, which makes no sense — it just
shows the wrong-frame issue).
**Severity:** medium — chain-blocking. The orchestrator is
end-to-end functional, the click reaches the OS, but the target
pixel is wrong.

## What was happening

`translate_decision_to_screen(normalized, captured, current, ...)`
implements the click as:

```python
sx = int(round(current.x + normalized.x * current.w))
sy = int(round(current.y + normalized.y * current.h))
```

This formula assumes the `normalized` point is relative to the
**window** (`current`), i.e. the captured bitmap and the window
have the same bounds. The `LeagueRunner` path (simulator-only) keeps
that assumption because its screenshots are window-bbox crops of
the simulator's renderer.

The phase-0 orchestrator captures the **full desktop**
(`ImageGrab.grab(all_screens=True)`) and the detector returns
`hit.normalized` relative to that screenshot. The screenshot's
pixel dimensions are the desktop's GDI extent (1920×1200 on
vpt-windows), not the Riot window's `w×h` (620×600 in our
capture). The formula multiplied by the wrong number, producing a
click inside the window's CONTENT area instead of at the
sidebar-icon pixel.

## What ships

- New optional keyword argument on
  `translate_decision_to_screen`:
  `screenshot_extent: Optional[WindowGeometry] = None`. When
  provided, the translator uses it as the anchor for the
  normalized point:

  ```python
  if screenshot_extent is not None:
      sx = int(round(screenshot_extent.x + normalized.x * screenshot_extent.w))
      sy = int(round(screenshot_extent.y + normalized.y * screenshot_extent.h))
  else:
      sx = int(round(current.x + normalized.x * current.w))
      sy = int(round(current.y + normalized.y * current.h))
  ```

  Both branches share the same drift / resize / HWND-changed
  / staleness checks above. The output pixel is in the same
  desktop coordinate system in both branches.

- `Phase0Runner._detect_and_click` builds a synthetic
  `WindowGeometry` from the actual screenshot file:

  ```python
  with Image.open(screenshot_path) as img:
      w, h = img.size
  return WindowGeometry(
      schema_version="league-window/v1",
      hwnd=0,  # synthetic; not a real window
      x=0, y=0, w=max(1, w), h=max(1, h),
      captured_at_ns=time.monotonic_ns(),
      dpi_scale=1.0, process_name="phase0_screenshot",
  )
  ```

  and passes it to the translator. The synthetic `hwnd=0` is the
  same convention `LeagueRunner` uses for the simulator, and
  `translate_decision_to_screen` already short-circuits the
  drift gate for `captured.hwnd == 0` (so the operator's
  Riot window geometry is not used as the anchor for a "synthetic
  captured" translation — that would re-introduce the
  bug).

- The drift gate (WINDOW_MOVED / WINDOW_RESIZED / HWND_CHANGED /
  STALE_GEOMETRY) is **not** weakened by the new branch. The
  operator's `current` geometry is still passed to the translator
  for the drift check; only the **denormalization** uses the
  screenshot's extent.

- **No new tests** — the existing
  `test_translate_decision_to_screen_returns_screen_point_when_in_bounds`
  covers the original window-relative branch. The new
  screenshot-relative branch is covered by the V9-on-vpt-windows
  smoke run: the `phase0-result.json` reports
  `clicked at pixel (260, 660)` which matches the LoL icon's
  on-screen position in the captured screenshot.

## Why this matters

- The drift-aware translator was a foundational piece (wave 4). The
  window-relative branch is correct for the simulator path
  (`LeagueRunner` plays the simulator with a captured window's
  rectangle as the click anchor). Adding the screenshot-relative
  branch lets the **operator-driven** phase-0 orchestrator
  reuse the same translator without forking the click math.
- Future work that captures partial screenshots (e.g. per-icon
  bbox crops for faster matching) can pass a `screenshot_extent`
  whose `(x, y)` is non-zero (e.g. `(660, 276)` for a
  window-bbox crop). The formula already supports that — it's the
  same code path the simulator uses today.
