# BUG-0466 — Analytics headline KPI tiles are not aligned and space out raggedly

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                       |
|-----------|-------------------------------------------------------------|
| ID        | BUG-0466                                                    |
| Reported  | 2026-10-11                                                  |
| Status    | Fixed (pending deploy)                                      |
| Severity  | Low (cosmetic — no wrong number, no broken interaction)     |
| Area      | frontend                                                    |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                       |

---

## Symptom

The five headline tiles on `/monitoring/analytics` (Robots · Devices · Open
incidents · Active alerts · Pass rate) do not sit on an even grid. The
whitespace between them visibly jumps around, with a wide hole after
`45 / 54`:

```
ROBOTS         DEVICES         OPEN INCIDENTS   ACTIVE ALERTS   PASS RATE
12 / 13        45 / 54         164              6               79.7%
^^^^^^^^^^^^^  ^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^  ^^^^^^^^^^^^^
   35px          <67px>          37px            46px
```

Measured off a 2x retina capture of the live page, the visible gaps between
tiles were **35 / 67 / 37 / 46 px** — four different values where one is
expected.

A second, related impression: `164` and `6` look smaller than `12 / 13`,
`45 / 54` and `79.7%`. That one is an optical illusion and was **not** the
bug — see below.

## Root cause

Two independent things were going on, and only one of them was real.

**Not a bug — the digit sizes.** Every value in the row already rendered at
the same `font-size: 30px`, the same `line-height: 36px`, and the same `y`
position. The perceived size difference is the slash in `12 / 13`: a `/`
ascends above the cap height and descends below the baseline, so it makes
that tile's row look taller than a row of plain digits. Nothing was wrong
with the typography, and no font or size change was needed.

**The real bug — hand-picked `minWidth` floors.** `StatTile` sizes itself to
the widest of its three lines, and the Overview row passed a different
`minWidth` per tile in `frontend/src/components/analytics/panels.tsx`:

| tile | content | `minWidth` | box | trailing whitespace |
|------|---------|-----------|-----|---------------------|
| Robots | 113px | 110 | 113 | 0 |
| Devices | 114px | **150** | 150 | **36** |
| Open incidents | 114px | 120 | 120 | 6 |
| Active alerts | 106px | 120 | 120 | 14 |
| Pass rate | 105px | 110 | 110 | 5 |

The `CardContent` is `display: flex` with `gap: 4` (32px) and **no**
`flex-grow` on the children, so each tile is simply as wide as its own
content — and when `minWidth` exceeded that content, the surplus stayed
*inside* the tile as trailing whitespace. That whitespace, plus the fixed
32px gap, is the visible gap. `Devices` reserved 150px for a 114px number
and opened a 36px hole after itself, which is the `67px` gap above.

The floors had also drifted out of proportion with the content: the numbers
they reserve (110–150px) had nothing to do with the labels they sit under
(`OPEN INCIDENTS` is the widest at 115px, `ACTIVE ALERTS` 107px).

## Fix

`frontend/src/components/analytics/StatTile.tsx` — add an opt-in `grow`
prop that gives a tile an equal share of the row:

```diff
-  <Box sx={{ minWidth }}>
+  <Box sx={grow ? { flex: '1 1 0', minWidth } : { minWidth }}>
```

`flex: 1 1 0` (basis `0`, not `auto`) so the equal share is independent of
content — one wide value cannot shove its neighbours off the grid.
`minWidth` is kept as the floor that lets a tile wrap rather than squash on a
narrow viewport. The prop defaults to `false`, so every other `StatTile`
call site is untouched.

`frontend/src/components/analytics/panels.tsx` — replace the five per-tile
widths with one shared floor, and switch the row to `grow`:

```diff
+const KPI_TILE_MIN_WIDTH = 120;
...
-  minWidth={110}                              +  minWidth={KPI_TILE_MIN_WIDTH} grow
-  minWidth={150}                              +  minWidth={KPI_TILE_MIN_WIDTH} grow
-  minWidth={120}                              +  minWidth={KPI_TILE_MIN_WIDTH} grow
-  minWidth={110}                              +  minWidth={KPI_TILE_MIN_WIDTH} grow
```

One gotcha worth recording, because the first attempt at this fix silently
did nothing: **the old floors summed to 610px, and with the 4 × 32px gaps
that consumed the entire 738px container.** With `flex-grow: 1` and zero
free space left over, every tile stayed pinned to its own floor and the
widths came back exactly 110/150/120/120/110. Equal columns only appear
once the floors leave slack to distribute — hence one shared 120px floor
rather than five different ones. 120px is sized to the widest real label
(`OPEN INCIDENTS`, 115px) so nothing clips or wraps.

## Verification

Measured in a real browser against the real `StatTile` and the real theme,
before and after:

- **Before** — tile widths `110 / 150 / 120 / 120 / 110`, visible gaps
  `35 / 67 / 37 / 46 px`.
- **After** — tile widths `122 / 122 / 122 / 122 / 122`, visible gaps
  `32 / 32 / 32 / 32 px`, values still all at `font-size: 30px` on a
  shared baseline (`y` identical across all five).

Also checked:

- Dark **and** light mode — the row aligns identically in both.
- Narrow viewport (460px) — tiles wrap to two columns and then one, still
  equal width, nothing clipped or squashed. `minWidth` is what makes the
  wrap happen instead of the numbers compressing.
- `npm run lint` (eslint + `scripts/ui-check.mjs`) and `tsc --noEmit` both
  pass.

To confirm on the deployed build: open `/monitoring/analytics`, and the gaps
between the five headline tiles must all read the same width.