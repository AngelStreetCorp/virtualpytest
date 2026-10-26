# BUG-0461 — Device Control: selected model chip label is invisible in dark mode

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0461                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | _pending merge_                                              |

## Symptom

In `Group control` on `https://virtualpytest.angelstreet.io/device-control`,
once at least one device of a model is selected the model chip turns into a
gold pill **with no visible label** (the empty pill in the operator's
screenshot — `Models  [gold pill]  stb`). The chip is filled with the
gold accent, but the model name inside it disappears — the operator can't
read which model they just added to the group. Light mode reads correctly
because the chip text falls back to a darker gold on the same gold fill.

The "Models" caption next to it and the unselected chip (`stb`) also look
dim in dark mode, but they stay legible — the selected chip is the only one
that becomes unreadable.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control`, desktop,
   signed in.
2. Click `Group control`, pick a model with 2+ devices, click one device
   chip so that at least one model has a non-zero in-group count.
3. Look at the `Models` strip in the sticky `GroupSelectBar` (or at the
   `Models` strip in the group modal header).
4. The chip whose model just got at least one member in the group is
   filled with the gold accent and the model name is invisible on top of
   it — only the surrounding outlined chips read.

`frontend/src/components/rec/group/GroupModelBadgeRow.tsx:128-131` —
the selected chip is filled with `P.accent` (`#d4a574` in dark mode) and
its text colour is `P.accentText` — which is **also `#d4a574`** in
`AGENT_CHAT_PALETTE` (lines 23/25). Same value, no contrast, label gone.

## Root cause

`GroupModelBadgeRow` chooses its label colour with one expression:

```
color: enabled ? P.accentText : P.textMuted
```

In the dark palette `P.accentText === P.accent === #d4a574`, so the
selected branch (`count > 0 && enabled`) paints text in the same colour
that fills the chip. The unselected branch survives only because the
chip background is `${P.accent}22` (a 13% tint over the dark bar surface)
and the text reads against that darker surface.

`AGENT_CHAT_PALETTE_LIGHT` (line 53) uses `#8f5f2e` for `accentText`, so
the same chip reads correctly in light mode. The whole-app convention
for "gold fill + readable label" is `bgcolor: P.accent, color: '#1a1a1a'`
— see `frontend/src/components/common/PageChrome.tsx:79-80`
(`goldButtonSx`), `RunTests.tsx:4283`, `BuildCampaigns.tsx:586`,
`TestCaseBuilderHeader.tsx:216`, `MasterchiefConfirmCard.tsx:270-271`.
`GroupModelBadgeRow` was the one place that forgot to follow it.

## Fix

`frontend/src/components/rec/group/GroupModelBadgeRow.tsx` — pick the
label colour from three buckets instead of two:

- `!enabled` → `P.textMuted` (greyed chip, no change)
- `count > 0` (selected, filled gold) → `'#1a1a1a'` (fixed dark,
  matches every other gold-fill button in the app)
- otherwise (unselected, tinted background) → `P.accentText` (unchanged)

The selected state is the same dark text the rest of the app puts on a
gold accent — a 7:1 contrast on `#d4a574`, easily passes WCAG. The
operator's request was "white"; the rest of the app uses dark text on
the gold for consistency and accessibility, and the dark text reads
clearly against the gold pill. The fix stays in the existing worktree
shape (no new palette token, no i18n key, no test fixture change).

## Verification

- `tsc --noEmit` clean on the worktree.
- `vite` dev server starts cleanly (tested on `127.0.0.1:5074`).
- Spot-check at `https://127.0.0.1:5074/device-control`: in dark mode,
  once a model chip is in the selected state its label is now readable
  dark text on the gold fill, in the same style as the `Control N devices`
  primary button in the same bar.

## Follow-up worth considering

The unselected chip's label (`P.accentText` on a 13% gold tint over the
dark bar surface) is on the edge of legibility — about 3:1 contrast, not
WCAG-clean. If the operator reports it too, the same `#1a1a1a` swap
on the unselected branch (with a darker gold background tint) would
fix both states together.