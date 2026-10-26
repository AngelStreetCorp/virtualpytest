# BUG-0535 — The overlay detector calls a promo slate a notification or a popup

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0535                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                          |
| Area      | shared / screen_state_cv                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

During the TASK-104 live check, Localize on vpt-pi1 stb3 (`stb_tv`, the set-top box screensaver showing a
film promo slate) answered `kind=overlay`, label *Notification*. The monitor's Tier-2
`overlay` field said `notification` on the same frames. After the first fix, stb4's screensaver
(another slate: a bright picture over the full height from the right edge, dark on the left) read
as a *Popup*.

## Root cause

`screen_state_cv._classify_plate` named any raised plate that touches the top-right corner a
notification, whatever its size. The bright half of the slate formed one plate of 0.80 × 0.88 of the
frame starting at the top edge and reaching the right edge, so it qualified. The modal rule had the
same gap: a plate centred enough, over a darker surround, was a popup even when it touched the frame
edges.

## Fix

A notification must also be a band: at most `OVERLAY_NOTIFICATION_MAX_W` = 0.45 of the width and
`OVERLAY_NOTIFICATION_MAX_H` = 0.30 of the height (`Thresholds` fields, overridable). The slate now
reads `unknown` and Localize falls through to screen memory / unknown. A popup must float inside
the frame: a plate touching any edge (`OVERLAY_POPUP_EDGE_MARGIN` = 1 %) is page, not a modal. On the
captured stb_tv frames: both slates now read `tooltip` (not a place, Localize falls through), the real
MENU popup over live video still reads `popup`.

## Verification

`tests/shared/test_screen_state_cv.py::test_a_page_reaching_the_top_right_corner_is_not_a_notification`
and `::test_a_page_spanning_the_frame_height_is_not_a_popup`;
the stb3 frame re-run through `overlay_plate` reads `unknown`; the real notification fixture still reads
`notification`.
