# BUG-0471 — Analytics KPI tiles are an even grid but their content hugs the left edge

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0471                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic — the grid is correct, the text just sits left) |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | `TBD`                                                        |

---

## Symptom

Follow-up to BUG-0466. After the five headline tiles on
`/monitoring/analytics` were put on equal columns, the row was evenly
spaced but still did not read as aligned: every label, number and caption
sat hard against the left edge of its own column, with a visible void to
its right. The wider the tile, the bigger the void — `12 / 13` in a 122px
column left ~9px of dead space on the right while `6` in the same width
column left ~52px.

```
  ROBOTS      DEVICES   OPEN INCIDENTS   ACTIVE ALERTS   PASS RATE
  12 / 13     45 / 54   164              6               79.7%
  ^left       ^left      ^left            ^left           ^left
  |<--122-->| |<--122-->| |<--122------->| |<----122----->|
```

## Root cause

BUG-0466 gave each tile `flex: 1 1 0`, so all five are exactly the same
width. It did not change the alignment *inside* that width: `StatTile`
still rendered its three `Typography` lines with the browser default
`text-align: start`, so every line began at the tile's left content edge.

That default was correct while each tile was only as wide as its own text —
there was no slack to distribute, so left-aligning was indistinguishable
from centring. It stopped being correct the moment the tiles became equal
columns: the leftover space now lands *inside* every tile instead of
between them. Left-aligning an over-wide box is what leaves the void.

Two widths that are equal but hold different amounts of text is exactly
what makes the row look ragged again — the numbers no longer share a
common left edge or a common centre line, so the eye reads misalignment
even though the grid is mathematically even.

## Fix

`frontend/src/components/analytics/StatTile.tsx` — a `grow` tile also
centres its own content:

```diff
-  <Box sx={grow ? { flex: '1 1 0', minWidth } : { minWidth }}>
+  <Box sx={grow ? { flex: '1 1 0', minWidth, textAlign: 'center' } : { minWidth }}>
```

`textAlign` on the tile covers all three lines at once — the `noWrap`
uppercase label, the large value and the caption — so they stack on one
axis instead of needing three separate alignments.

The change stays inside the `grow` branch on purpose. `grow` is opt-in and
only the Overview headline row passes it; the other `StatTile` call sites
(`RunSummary`, `ShareRun`, `CustomReportBuilder`, `RunGroupDetail`, the
Alerts "Review state" row) size to their content and are deliberately left
left-aligned, so nothing else on the app moves.

## Verification

Measured in a real browser against the real `StatTile` and theme — the
offset of each line's centre from its tile's centre, in CSS px:

| tile | label | value | sub |
|------|-------|-------|-----|
| Robots | 0 | 0 | 0 |
| Devices | 0 | 0 | 0 |
| Open incidents | 0 | 0 | 0 |
| Active alerts | 0 | 0 | 0 |
| Pass rate | 0 | 0 | 0 |

And the grid itself is unchanged by the centring — still 122px per tile
with a uniform 32px gap, values still `font-size: 30px` on one baseline.

Also checked:

- Dark **and** light mode — identical centring in both.
- Narrow viewport (460px) — tiles wrap into 2 then 1 column and each stays
  centred in its own column; nothing clipped or squashed.
- No other `StatTile` call site passes `grow`, so no other page changes.
- `npm run lint` (eslint + `scripts/ui-check.mjs`) and `tsc --noEmit` pass.

To confirm on the deployed build: open `/monitoring/analytics`; each of the
five tiles must have its label, number and caption centred on the same
vertical axis.