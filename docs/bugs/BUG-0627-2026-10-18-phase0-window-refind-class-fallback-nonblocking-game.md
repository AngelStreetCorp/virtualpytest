# BUG-0627: phase-0 window re-find, League class fallback, non-blocking game wait, one taskkill

**Date:** 2026-10-18
**Discovered on:** live V10-V16 runs on `vpt-windows`.
**Severity:** medium — the chain stopped at `click_lol_icon` or `wait_for_league`.

## What was happening

- The Riot Client re-creates its top-level window after the splash (new HWND, same title). The click step then used the dead
  HWND, fell back to a stale geometry and was refused as `STALE_GEOMETRY` / "not the captured window".
- `_wait_for_league_window` passed `exact=False` to `wait_for_window`, which has no such argument (`TypeError`). The League
  Client title also changes per page.
- `wait_for_league_game` failed the whole chain after 240 s when nobody accepts a queue pop.
- `_kill_existing` ran three separate `taskkill` calls.

## What ships

- `_detect_and_click` re-finds the window by title when its HWND is gone and uses it as the new anchor.
- New `_poll_league_window`: title substring first, then window class `RCLIENT`.
- `wait_for_league_game` is non-blocking: `ok=True` with a caveat, default timeout 240 s → 15 s.
- One `taskkill /IM … /IM … /IM … /F /T` call for Riot, League Client and the game.

## Ops note

On the box, `C:\virtualpytest\run_phase0.py` imported the library from a stale `C:\virtualpytest\vpt-shared` copy (wave 8 and
older), so deploys had no effect. It now imports from the deployed tree `C:\virtualpytest\virtualpytest`.
