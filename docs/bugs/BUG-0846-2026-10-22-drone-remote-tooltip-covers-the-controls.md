# BUG-0846 — The drone remote panel's tooltip covers the controls you are steering with

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0846                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the flight controls are covered by their own label for the whole flight |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Reported on the drone remote panel (the `TelloRemote` panel on the drone tile and on the device
page).

- **Page / route:** /device-control (drone tile, remote panel) and the device page.
- **Viewport / theme:** desktop, dark.

Steps to reproduce:

1. Pair a Tello and take off, so the flight controls are live.
2. Press and hold the round move pad — or hold **Rotate left**, **Rotate right**, **Up** or **Down**.
3. Keep flying. The pointer stays on the control for the whole flight, because it is press-and-hold.

**Expected:** the controls never cover themselves. You can read the pad and the buttons while you
fly.

**Actual:** about a second in, a tooltip appears and stays for as long as you hold:
**"Move: forward, back, left, right"** over the top of the pad, or **"Rotate left"** / **"Up"** /
etc. over the neighbouring buttons. The panel is unreadable at exactly the moment it is being used,
and it hides the stick you are steering with — the one indicator that tells you what the drone is
doing right now.

Evidence: owner report with a screenshot of the panel with the pad held and the tooltip sitting over
the top of the controls, 2026-10-22.

## Root cause

Every flight control in the panel was wrapped in a MUI `<Tooltip>`. A tooltip is a **hover**
affordance, but all five of those controls are **press-and-hold**: the operator's pointer rests on
them for the entire flight, because releasing is what stops the drone. MUI opens a tooltip on
pointer-enter and holds it until leave, so the tooltip's lifetime is exactly the duration of the
flight — the label is guaranteed to be parked over the controls at the precise moment they are
needed.

The move pad made it worse by asking for it: its tooltip used `placement="top"`, so it landed
squarely on the **Up** button and the top edge of the pad, in the middle of the control cluster
rather than outside it.

Nothing about the controls *needed* a tooltip. The pad already draws its four direction arrows
inside the ring, and the stick itself shows the vector. The round buttons are single, unambiguous
icons.

## Fix

The tooltip is removed from the five controls that are held, and kept on the controls that are
clicked.

- **MovePad** — the `<Tooltip title="Move: forward, back, left, right" placement="top">` wrapper is
  gone. The `<Box>` that carries `role="slider"` becomes the root element, carrying up its `ref`,
  pointer handlers and `sx` unchanged; how the pad tracks the pointer and reports the vector is
  untouched. The string no longer exists in the codebase.
- **HoldButton** (Up, Down, Rotate left, Rotate right) — the `<Tooltip>` and the `<span>` it needed
  as a target are gone and the `IconButton` is the root. `flexShrink: 0` is added on purpose: the
  `<span>` used to be the flex item whose `min-width: auto` is what stopped these 52 px round
  buttons from being squashed in the row that also holds the pad, and without the span that
  guarantee is not automatic.
- **Accessibility is kept, not dropped.** All five controls keep their `aria-label` (`Move pad`,
  `Up`, `Down`, `Rotate left`, `Rotate right`), so a screen reader still names each one. What was
  removed is only the visual hover label.
- **The click-only tooltips stay**: battery, link state, flight history, emergency stop and the four
  flips. The pointer does not rest on those, so they cannot sit over the controls for the length of
  a flight, and their labels are worth having.

## Verification

`tests/frontend/DroneTileSingleVoice.test.tsx` — 23 tests, 2 of them new. Both new tests **fail**
against the previous component and pass against this one (checked by reverting the component to
`origin/main` and re-running: 2 failed, then 23 passed).

```
cd tests/frontend && ./node_modules/.bin/vitest run DroneTileSingleVoice
```

Covered:

- The move pad: hover, then press and keep the pointer down for 2 s — no `[role="tooltip"]` exists
  in the document and the text "Move: forward, back, left, right" is not rendered.
- Each of the four round hold buttons in turn (**Rotate left**, **Rotate right**, **Up**, **Down**):
  hover, hold for 1.2 s, assert no tooltip element and that the button's own label is not drawn as
  text.

`tsc --noEmit` over `frontend/tsconfig.json` is clean.