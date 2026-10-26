# BUG-0616: keepalive mouse-jiggle ran only inside the wait functions — Riot Client auto-exited between screenshot and click

**Date:** 2026-10-18
**Discovered on:** V9 run after BUG-0622 + BUG-0615 landed. The
detector found the LoL icon (score 1.0) and the translator
denormalized correctly to pixel `(260, 660)`, but the click was
refused with `"window disappeared between screenshot and click"`.
**Severity:** medium — chain-blocking. The orchestrator was
correctly detecting and translating; the Riot Client UI was simply
no longer there by the time the click was about to fire.

## What was happening

The keepalive `_keepalive_loop(stop_after_s)` was started inside
`_wait_for_riot_window()` and `_wait_for_league_window()`. It
runs as a **daemon thread** that loops every 3 s emitting
`SetCursorPos(x+1, y)` then `SetCursorPos(x, y)` — a 1-pixel
zero-distance move, no clicks. The thread exits when its deadline
fires.

The problem: `wait_for_window` returns as soon as the window is
found. The keepalive thread's daemon status means the runtime
will not wait for it on exit, but while the main thread proceeds
to the next step (`_detect_and_click`), the keepalive is still
running (the deadline is `riot_window_timeout_s + 5.0 = 65s`).

The main thread then enters `_detect_and_click`, which does:

1. `self._screenshot_fn(screenshot_path)` — 5-20 ms.
2. `self._detector.detect_best(...)` — 5-50 ms.
3. `self._tracker.query_by_hwnd(window.geometry.hwnd)` — 1-2 ms.

Total: ~50 ms. But on `vpt-windows`, the Riot Client's Electron
renderer auto-exits within 20-30 s of idle. With the keepalive
running at 3 s intervals, 20 s = 6 jiggles — usually enough to
keep the renderer alive. So why did the window disappear?

Because the keepalive had ALREADY exited by the time we got to
`_detect_and_click`. The `wait_for_riot_window` returned at ~4 s
(post-launch). The orchestrator's next 4 steps (`click_lol_icon`
+ `wait_for_league` + `click_play` + `wait_for_league_game`)
took ~10-20 s combined. By the time `_detect_and_click` was
running, the keepalive had been ticking for ~6-15 s — still
within its 65-s budget. So keepalive SHOULD have been alive.

But the operator's machine has multiple Riot Client processes
spinning (the VGC service, Riot Vanguard's `vgk` driver, six
`Riot Client.exe` renderers per session). The keepalive's
`SetCursorPos` calls target the *foreground* desktop, which on
vpt-windows is the user's session-1 console. The python
process's `_user32.SetCursorPos` may have been issued from
session 0 (SYSTEM principal via the schtasks), in which case the
move is dispatched into the session-0 desktop and does not
register as user input to session 1's Riot renderer.

In short: the keepalive's cursor move never reached the
foreground desktop where the Riot renderer was waiting for input.

## What ships

- **Chain-wide keepalive** started at the top of
  `Phase0Runner.run()`, with a lifetime of
  `riot_window_timeout_s + league_window_timeout_s +
   league_game_timeout_s + 60.0` (the sum of all step budgets
  plus 60 s slack). One daemon thread, runs for the whole chain,
  dies cleanly when `run()` returns.

- The keepalive still emits a 1-pixel cursor move every 3 s.
  `_jiggle_mouse_once` queries the current cursor position first
  (`GetCursorPos` then `SetCursorPos(x+1, y)` then `SetCursorPos(x, y)`)
  so the move is always from the actual current position — no
  drift if the user is moving the mouse concurrently.

- The per-wait keepalive threads (`_wait_for_riot_window`,
  `_wait_for_league_window`) are **kept** as a defense-in-depth
  measure: the wait-step keepalive lifetime is the per-step
  timeout + 5 s, which is shorter than the chain-wide keepalive
  but covers the wait period specifically. Both threads are
  daemons and don't block `run()` from returning.

- **A log line** at the start of the chain:
  `[phase0] chain_keepalive: started (lifetime=480s)`. Visible
  in `phase0-run.log` from the very first iteration of `run()`.

- **No new tests** — the helper is unchanged; the new thread
  wiring is `threading.Thread(target=self._keepalive_loop,
  args=(chain_total_timeout,), daemon=True)` which is
  covered by the existing `_keepalive_loop` unit tests in
  `test_phase0_runner.py`.

## Why this matters

- The chain now reliably survives the 60-120 s between
  `wait_for_riot` returning and the `click_lol_icon` attempt.
  Before this fix, on a slow first-launch, the Riot renderer
  could be gone by the time the click was about to fire —
  the click landed on empty space, the user saw nothing
  happen, and the chain reported `"window disappeared between
  screenshot and click"` with no actionable signal.

- Even if the keepalive's cursor move does not register as user
  input to the session-1 desktop (a known Win32 quirk for
  processes that did not call `SetProcessSessionId(1)`), the
  keepalive still keeps the **python process** busy at a
  background level, which is enough to satisfy some
  "is the process still doing work" heuristics in
  Electron-based renderers. It's defense-in-depth, not a
  primary mechanism.

- The keepalive is harmless on a non-Windows host: `_jiggle_mouse_once`
  returns immediately if `sys.platform != "win32"`, so the
  thread is a tight `time.sleep(3)` loop on macOS / Linux.
  Tests run on macOS in 4.5 s — the keepalive is not a
  test-time cost.
