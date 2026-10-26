# BUG-0269 — AI Generate's validation wrote an app restart as the way back, or none at all, on Android

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0269                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the created edges went back home by restarting the app (~9 s), or had no way back |
| Area      | `backend_host/src/services/ai_exploration/phases/validation_runner.py` (`smart_backward`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

On an Android phone with Google TV (entry edge: `close_app`, `launch_app`, `click_element("Home")`),
AI Generate created Search, Shop, Library and Watchlist and validated them. Afterwards:

- `shop → home`, `library → home` and `watchlist → home` were *close the app, launch it, tap Home*,
  although tapping the Home tab alone had brought each tab back;
- `search → home` was empty, reported `failed_recovered`.

## Root cause

`smart_backward` tries the entry edge's actions first. It replays only their taps, but it stored
**all** of the entry edge's actions as the reverse, so `close_app` and `launch_app` came along.

On the Search screen the app shows no Home tab, so the tap on "Home" could only match Android's
navigation-bar Home button. That left the app for the launcher, every later step (BACK, BACK
again) failed, and the run recovered by restarting the app, leaving the reverse empty.

## Fix

- Step 1 stores only the taps it replayed.
- Step 1 runs only when every label it would tap is an element of the app's own window on the
  current screen (Android dumps know each element's window). Otherwise it goes straight to BACK.

## Verification

- `py_compile` passes; the window check returns true for "Home" on Google TV's tab screen and
  false when only Android's navigation bar has it (the phone's own dump).
- Deployed and run on the phone 2026-10-04: Shop, Library and Watchlist go back with
  `click_element("Home")`; Search with BACK (×2 once BUG-0279 was in).
