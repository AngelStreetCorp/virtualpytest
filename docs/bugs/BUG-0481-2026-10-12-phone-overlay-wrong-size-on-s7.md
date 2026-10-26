# BUG-0481 — Phone tap overlay misaligned on phones that are not 1080x2340 (S7)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0481                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend · remote · Android mobile overlay                   |
| Fixed in  | build 90145 |
| Commit    | f9d9ff9b5                                                    |

---

## Symptom

In Take Control, the element overlay drawn over the phone stream fit a Galaxy S21 but not a
Galaxy S7: on the S7 the overlay frame was narrower than the screen image, so the boxes sat
off the icons they belong to.

## Root cause

`AndroidMobileRemote` passed a hardcoded `deviceWidth=1080` / `deviceHeight=2340` to
`AndroidMobileOverlay`. The overlay scales dump coordinates and computes the stream content rect
from that aspect ratio, so it was only correct for phones with that screen shape. The S7 is
1440x2560 (9:16).

## Fix

`useAndroidMobile.checkOrientation()` already calls `/server/remote/getOrientation`, which returns
the live `width`/`height` from `dumpsys`. The hook now keeps that size (normalised to portrait)
and the remote passes it to the overlay, swapped for landscape. Until the first read answers it
falls back to the layout default.
