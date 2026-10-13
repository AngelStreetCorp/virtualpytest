# BUG-0462 — Device Control: unselected model chip in the Group Models strip is dim in dark mode

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0462                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | _pending merge_                                              |

## Symptom

In `Group control` on `https://virtualpytest.angelstreet.io/device-control`,
the unselected model chip (`stb` in the operator's original screenshot)
reads as dim in dark mode — the label is the gold accent over a 13% gold
tint over the dark bar surface, which lands at ~4.5:1 contrast. It just
passes WCAG AA for normal text, but visually it looks faded and operators
have to lean in to read it. Light mode was unaffected.

The selected-state half of the same problem was BUG-0461 (selected chip
text invisible against the gold fill). This is the unselected half:
same component, same colour-collision root cause, lower severity because
the text survives — just dim.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control`, desktop,
   signed in.
2. Click `Group control` to enter group mode.
3. Look at the `Models` strip in the sticky `GroupSelectBar` (or in the
   group modal header). The chips that are **not** selected — i.e. the
   models with zero devices currently in the group — show a faint gold
   label on a faint gold tint. The text is readable but dim; in the
   operator's words "should be" clearly readable.

`frontend/src/components/rec/group/GroupModelBadgeRow.tsx:131-141` —
the unselected branch paints the label with `P.accentText`
(`#d4a574` in dark mode) on top of `bgcolor: ${P.accent}22`
(`rgba(212,165,116, 0.13)`) over the bar's `P.surface` (`#242424` in
dark mode). The effective background blends to roughly `#4b4036`;
`#d4a574` over `#4b4036` is 4.48:1 — just below WCAG AA's 4.5:1
threshold for normal text.

## Root cause

`GroupModelBadgeRow`'s label colour was a single expression with two
buckets: selected (`'#1a1a1a'`) or unselected (`P.accentText`). The
unselected branch was the original design's "outlined chip" — text in
the accent gold on a thin gold tint. That reads fine on a pure white
surface, but on the dark bar surface the gold-on-gold combination loses
~1.5 stops of contrast and ends up right at the legibility edge.

Every other gold-on-dark text in the app uses `P.textPrimary` (white-ish)
or a brighter gold (`P.gold = #FFD700`) when it has to live over a
dark-tinted background — see `RunTests.tsx` filter chips, the device
page header, the build-campaigns status pills.

## Fix

`frontend/src/components/rec/group/GroupModelBadgeRow.tsx` — swap the
unselected branch's `color: P.accentText` for `color: P.textPrimary`.

- Dark mode: `#f0f0f0` over the 13% gold tint → **9.5:1** contrast.
- Light mode: `#141414` over the 13% gold tint (the bar surface is
  `#ffffff` in light) → **7.1:1** contrast.

The chip keeps its gold tint (`${P.accent}22`) so it still reads as a
gold-accented filter chip, not a plain label. The 1px accent border on
top carries the model identity; the text just becomes the page's
normal readable tone. Hover (`${P.accent}40`) and the selected branch
(`#1a1a1a` on full gold) are unchanged — all three states now pass
WCAG AA comfortably.

## Verification

- `tsc --noEmit` clean on the worktree.
- Spot-check at `https://127.0.0.1:5074/device-control` (vite dev): in
  dark mode the unselected chip's label reads as crisp page-text on the
  gold-tinted chip; in light mode the same chip reads as crisp
  near-black on the same tint.

## Why both fixes live in the same file

The selected and unselected branches share one `sx` block in
`GroupModelBadgeRow.tsx`. BUG-0461 only touched the selected branch
because that one was unreadable; BUG-0462 touches the unselected branch
because that one is dim. They don't overlap — a single commit could
have done both, but two commits keep the bug tracker honest about
*what each change fixed and why* (the selected-branch root cause was
`accentText === accent`; the unselected-branch root cause is a softer
gold-on-gold-on-dark contrast floor).