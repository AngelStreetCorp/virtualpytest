# BUG-0443 — Edit / Group control / Exit group plain text + flash the count

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0443                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `2214de994` (merge: `c7139a030`)                             |

## Symptom

Three small UX issues on the deployed `/device-control` page header
(seen on BUG-0438 + BUG-0440 + the label-rename chain):

1. **`Exit group` had a gold border**, while `Group control` (the same
   button in the off state) and `Edit` (its neighbour) were plain
   gold text. The border flashed in/out as the user toggled group
   mode, and a hover/click ripple on top of the outlined variant
   read as accidental motion on what is, in practice, a label that
   flips. The three buttons should look the same in both states.
2. **`Group control` ⇄ `Exit group` changed width** as the label
   flipped (13 chars vs 10 chars). The page row to the right
   (filters, View) shifted by a few px on every toggle.
3. **The `0 of 19 selected · select all - unselect all` line below
   the tag input** in Edit mode was static. Selecting a device
   changed the number with no visual cue, so the user had to look
   at the chips or the count itself to confirm the click landed.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Click `Group control`, pick 2+ devices, click `Control N devices`,
   then `Release all` — the modal closes and the header shows
   **`Exit group` with a gold outline** that wasn't there before
   the click. Hover/click the button — the outline ripples.
3. Click `Exit group` to leave group mode — the outline disappears.
   Click again — it reappears. The button's width also moves a few
   pixels each time the label flips.
4. Click `Edit` to enter Edit mode. Below the tag input, the line
   `0 of 19 selected · select all - unselect all` appears. Click a
   device checkbox — the count becomes `1 of 19 selected` with no
   visual cue; the user has to read the digits.

## Root cause

`frontend/src/pages/Rec.tsx`:

- The `Group control` Button used
  `variant={groupSelection.isGroupMode ? 'outlined' : 'text'}` and
  `borderColor: P.accent`. The variant swap and the border colour
  were the flash + ripple.
- The Button had `whiteSpace: 'nowrap'` but no `minWidth`, so the
  longer `Group control` label gave the button a different width
  than `Exit group`. The Edit button had `minWidth: 64` (already
  fixed) but no `whiteSpace: 'nowrap'`.
- The `X of Y selected` Typography was static — no animation, no
  keyframe, no state change on count update. The count was a
  number with no "I just changed" signal.

## Fix

`frontend/src/pages/Rec.tsx`:

- The `Group control` Button is now `variant="text"` in both
  states. The `borderColor` line is gone. A new `minWidth: 116`
  (chosen to fit `Group control` at the same MUI size) holds the
  width steady as the label flips; `whiteSpace: 'nowrap'` was
  already there. The new button is visually identical to `Edit`
  in every state — both plain gold text, same height (40 px),
  same `alignSelf`, same `flexShrink: 0`.
- The `Edit` Button gains `minWidth: 80` and
  `whiteSpace: 'nowrap'`. Its old `minWidth: 64` was enough for
  `Edit` and `Cancel` but the wider value matches the
  `Group control` button's spec (40 px row, label never reflows).

- A new `selectedCountFlash` state + `prevSelectedFilteredCountRef`
  + `useEffect` detect when `selectedFilteredCount` actually
  changes (a user toggle, not a re-render) and bump a counter. A
  `countFlash` MUI `keyframes` runs a 0.7 s ease-out pulse on the
  `Typography`'s background, from `P.accent + 40` (alpha 0x40,
  ~25%) to transparent. The counter is the Typography's React
  `key`, so the component remounts and the animation replays on
  every change. The chip/select-all row keeps its existing 28 px
  `minHeight`, so nothing around the count shifts.

`docs/agent/platform/UI_STYLE.md` — §5 "Mode-toggle buttons in a
header" row no longer allows "grow a border" as a visual change.
Variant is always `text`; `minWidth` is always big enough to hold
the longer of the two labels. §9.6 ship-checklist item 6 updated
to match, and the cross-refs now point at BUG-0437 / BUG-0438 /
BUG-0443 instead of just the first two.

## Verify

- `tsc --noEmit` clean, `node scripts/i18n-check.mjs --quiet`
  clean (313 keys, 0 errors), `vite build` clean
  (`✓ built in 32.35s`).
- Open `/device-control`. `Group control` and `Edit` are both
  plain gold text at the same height. The two are different
  widths (label-fitted), but their slots are fixed.
- Click `Group control`. The button stays in place, the label
  flips to `Exit group`, no border appears, the row to the
  right (filters, View) does not move. Click `Exit group` —
  same in reverse. The width does not change.
- Click `Edit`. The tag input row appears with the
  `0 of 19 selected · select all - unselect all` line below.
  Click a device checkbox — the line briefly pulses gold
  (0.7 s, fades to transparent). Click again to deselect — the
  pulse plays again. The chips/select-all row does not reflow.

## Why this is now a UX rule

The "Mode-toggle buttons in a header" entry in `UI_STYLE.md` §5
already existed (added with BUG-0438). It allowed two visual
changes — label flip and a "grow a border" — under the
"never reflows" rule. BUG-0443 closes the second loophole: a
`text ⇄ outlined` swap flashes a border in/out on every toggle
and reads as accidental motion, not as "this mode is on". The
label is enough; the variant stays. `UI_STYLE.md` now spells
this out, and the ship-checklist item 6 (BUG-0438) is updated to
match. The `0 of 19 selected` flash is documented in the bug;
it's a one-line animation triggered by a `useRef`-backed diff,
not a system-wide rule.
