# BUG-0489 — Phone remote Scr↓ did not scroll a page down

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0489                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend remote / backend_host android_mobile                |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Product video 25b preflight (group control, S21x on vpt-pi1 + S7 on vpt-mf1): with
virtualpytest.com open in Chrome, Scr↓ pressed twice left the S21x page unchanged, while both
tiles said "Sent". The same run also reported that on the S7 "Enter arrived before the text".

## Root cause

1. **Scroll direction.** The Android Mobile remote's Scr↓ sent `SWIPE_DOWN`, and every backend
   (`android_mobile`, `appium_remote`, `phone_agent`) reads `swipe_*` as the *finger* direction:
   `SWIPE_DOWN` dragged (500,500)→(500,1500). A finger moving down drags the page toward its top,
   so on a page already at its top nothing moved. Scr↑/←/→ were inverted the same way.
2. **Fixed pixels.** The uppercase `SWIPE_*` commands used the method defaults: `SWIPE_UP` was
   (500,800)→(500,500), a 300 px nudge on a 2340 px S21x, off-centre on a 1080 px-wide screen.

The S7 "text after Enter" was **not** an ordering bug. The S7 host log shows `input_text`
finishing (`adb shell input text` returns only once the key events are injected, ~3.3 s for 17
characters on Android 8) 1.5 s before `press_key ENTER`; replaying the same sequence through
the host API loads the page every time. What the video saw is the S7 stream lagging: the S7 has
no HDMI capture, its tile is an `adb screencap` loop fed to ffmpeg, and its capture showed a
screen change 5.8 s after it happened (measured on vpt-mf1), plus the player's buffer. In
`pf-beat8-2.png` the S7 tile still shows 20:48 while Enter ran at 20:48:59.9.

## Fix

- `AndroidMobileRemote.tsx`: Scr↓ sends `SWIPE_UP`, Scr↑ `SWIPE_DOWN`, Scr← `SWIPE_RIGHT`,
  Scr→ `SWIPE_LEFT` — the finger direction that scrolls the content the way the arrow points.
  `swipe_*` command meaning is unchanged for navigation trees, MCP and AI tests.
- `android_mobile.py`: `SWIPE_*` go through `screen_swipe()`, sized from the live screen
  (`get_orientation`): vertical 70%→30% of the height at mid-width, horizontal 80%→20% of the
  width at mid-height, 300 ms.

## Verification

On the real phones (S21x 1080×2340, S7 1080×1920 logical), Chrome on about:blank, Click by
Text `about:blank` → `input_text virtualpytest.com` → `ENTER` loaded the site on both; each of
two `SWIPE_UP` via `screen_swipe` ((540,1638)→(540,702) on the S21x, (540,1344)→(540,576) on
the S7) scrolled the page visibly further down. Before the fix, two `SWIPE_DOWN` left the S21x
page identical.

Not fixed here: the S7 stream lag (screencap → ffmpeg pipeline on vpt-mf1).
