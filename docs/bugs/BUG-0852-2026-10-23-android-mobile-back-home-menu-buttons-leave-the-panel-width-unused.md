# BUG-0852 — Android Mobile Back / Home / Menu buttons stay small: the panel width is not used

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0852                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In the Android Mobile remote panel (Take Control on a phone), the **Back**, **Home** and **Menu**
buttons next to the D-pad stayed narrow even after BUG-0845 made them square: the row was still
capped well inside the panel, so the three buttons came out around 30 px wide with a visible
empty strip at the right edge of the panel. The panel itself was wide enough to give them more
room.

## Root cause

`frontend/src/components/controller/remote/AndroidMobileRemote.tsx` wrapped the whole control
column in a `Box` with `maxWidth: '238px'`, while the panel's own width comes from
`layoutConfig.containerWidth` (300 px, minus the container padding). The Back/Home/Menu row
shares that column with the D-pad (118 px wide), so it could never use more than ~112 px — three
buttons of ~34 px plus gaps — no matter how wide the panel actually was.

The row's own gap was also still `0.25` (2 px), which read as the buttons touching each other.

## Fix

- The control column now uses the full panel width (`maxWidth: '100%'`) instead of the hard
  238 px cap, so the Back/Home/Menu row gets the space the panel really has.
- The row gap goes from `0.25` to `0.5` so the three square buttons read as separate buttons.

The square behaviour itself (grow on the tooltip wrapper, `aspectRatio: 1 / 1` on the button) is
BUG-0845 and is kept as is.

## Verification

Open Device Control → Take Control on an Android phone and look at the Device Controls row:
Back, Home and Menu are square buttons of equal size, side by side, filling the space beside the
D-pad, with no empty strip at the right of the row. Each still shows its tooltip and still sends
`BACK` / `HOME` / `MENU`.
