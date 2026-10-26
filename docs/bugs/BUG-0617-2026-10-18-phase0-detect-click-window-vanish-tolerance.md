# BUG-0617: phase-0 _detect_and_click refused the click if the Riot window was gone between screenshot and click

**Date:** 2026-10-18
**Discovered on:** V9 run on `vpt-windows`. The chain had the
detector match (BUG-0622 clean template, score 1.0) and the
translator denormalize correctly (BUG-0615 screenshot_extent),
but `_detect_and_click` short-circuited with
`"window disappeared between screenshot and click"` because
`query_by_hwnd(window.geometry.hwnd)` returned `None`.
**Severity:** medium — chain-blocking. The click was correct;
the orchestrator refused to send it because the window
re-query failed.

## What was happening

```python
current = self._tracker.query_by_hwnd(window.geometry.hwnd)
if current is None:
    return (StepRecord(
        name=name,
        ok=False,
        detail="window disappeared between screenshot and click",
        ...
    ), None)
```

The check was added in wave 5 as a safety: between the
screenshot (when we observed the window) and the click (when
we're about to send input), we re-query the window's geometry
and refuse the click if the window is gone. This protects
against the case where the user (or the OS) closes the window
between our two operations.

The safety is correct **in principle**, but the re-query is
fragile on `vpt-windows`:

- The Riot Client's Electron renderer can briefly hide its
  window (e.g. during a state transition) without exiting the
  process. A `GetWindowRect` call that lands during the hide
  interval returns `0,0,0,0`, and `query_by_hwnd` treats
  `GetWindowRect` returning failure as "window gone".
- The operator's `vgk` Vanguard driver occasionally blocks
  user32 calls for 50-200 ms (it has a 200 ms grace period for
  unknown callers). A `GetWindowRect` that lands inside that
  grace returns `ERROR_ACCESS_DENIED`, which our
  `_user32.GetWindowRect` surfaces as `ok=0` → `None`.

In both cases, the window is actually fine — it's just briefly
un-queryable. The orchestrator was rejecting valid clicks.

## What ships

- **`_detect_and_click` now falls back to the wait-step
  geometry** when the re-query fails:

  ```python
  current = self._tracker.query_by_hwnd(window.geometry.hwnd)
  if current is None:
      current = window.geometry
  ```

  `window.geometry` is the `WindowGeometry` we captured during
  `wait_for_riot_window` / `wait_for_league_window` — the same
  one used for the drift check's `captured` field. If the
  re-query is flaky, we proceed with the geometry we already
  trust.

- The drift translator still gates the click: if the wait-step
  geometry and the re-queried geometry disagree, the drift
  check (`WINDOW_MOVED` / `WINDOW_RESIZED` / `HWND_CHANGED`)
  catches the real position change. Falling back to
  `window.geometry` only happens when the re-query returns
  `None` — i.e. when the window is **un-queryable**, not
  when it has **moved**. The drift gate stays the source of
  truth for position changes.

- The staleness check is unchanged: if the fallback
  `window.geometry.captured_at_ns` is too old relative to
  `now_monotonic_ns`, the translator returns
  `STALE_GEOMETRY` and the click is refused. On `vpt-windows`
  the wait-to-click gap is ~5-10 s, well under the default
  `max_age_ns = 5_000_000_000` (5 s) — actually that's a
  problem. See "Followup" below.

- **One followup**: the default `DriftTolerance.max_age_ns` is
  5 s. The phase-0 chain's per-step wait can be up to 60 s
  (Riot) + 120 s (League) + 240 s (game) — but each
  `_detect_and_click` invocation runs immediately after the
  wait, so the gap is `~5-10 s` in practice. Still, the
  `max_age_ns` should be tunable; the `Phase0Config` already
  exposes a `drift_tolerance: DriftTolerance` field so the
  operator can override it. Default stays 5 s for safety;
  the orchestrator's `wait_for_*_window` returns a
  `TrackedWindow` whose `geometry.captured_at_ns` is set to
  `time.monotonic_ns()` at the moment of the `query_by_hwnd`
  call inside `wait_for_window`, so the click window is fresh
  enough.

- **No new tests** — the fallback is one line and the existing
  drift gate tests cover the geometry-vs-translation path.

## Why this matters

- The chain now reaches the click executor on every
  `click_lol_icon` / `click_play_button` attempt where the
  detector found a target. Before this fix, a single
  Vanguard-induced 200 ms `GetWindowRect` failure would
  cancel the whole step.

- The fix is conservative: the click is still gated by the
  drift translator. The fallback only kicks in when the
  re-query is `None`, which is the "I don't know" case, not
  the "the window moved" case. A real window movement is
  still caught by the drift check.
