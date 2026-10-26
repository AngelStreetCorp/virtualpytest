# BUG-0566 — Monitoring overlay hid the Localize screen chip

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0566                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In Take Control, turning Monitoring on hid the top-right Localize chip (`home_recodings · 98 %`).
The consecutive-error ERROR/WARNING badge sat in the same corner, so the recognised screen
disappeared while Monitoring was open.

## Root cause

`RecStreamContainer` only mounted `LocalizeVideoBadge` when `!monitoringMode`, on the assumption
that the overlay's top-left "Screen:" line was enough. The overlay also drew ERROR/WARNING at
`top: 16`, which covered the chip if it had stayed mounted. The monitoring layer is z-index 1300;
the chip was 1250, so it would lose even if both were shown.

## Fix

Always render the Localize chip in the stream modal. Raise its z-index above the monitoring layer.
Move ERROR/WARNING to `top: 44` so they sit under the chip.

## Verification

Open Take Control on a tv_app device with a recognised screen. Toggle Monitoring on: the chip
(`<screen> · N %`) stays top-right and ERROR/WARNING, if present, appear just below it.
Toggle Monitoring off: the chip is unchanged.
