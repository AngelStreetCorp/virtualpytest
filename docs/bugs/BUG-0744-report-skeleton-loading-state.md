# BUG-0744 — The report pages greeted you with a red `N/A`, and a spinner in an empty page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0744                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic — but it is the first thing a user sees on the page, and it reads as a failure) |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Open `/test-results/reports` on a cold load. Before the data lands, the two stat tiles read:

```
Success rate
N/A%          <- in red
Avg duration
N/A           <- in red
```

and the table under them holds a spinner so small it is barely a mark on the page, with a
few hundred pixels of empty white beneath it.

`/test-results/cicd-reports` had the opposite half of the same problem: no stat tiles at all
during the first ~1.5 s, just a lone circular spinner floating in the middle of a blank
page — and then all seven KPI cards, the header and fifteen table rows arriving at once, so
the page visibly *popped* into place.

Measured on the live site (1600×1000, headless Chromium, 2026-10-21), sampling
`document.body.innerText` every 25 ms from commit:

| t | `/test-results/reports` | `/test-results/cicd-reports` |
|---|---|---|
| ~0.4 s | chrome up, content empty | chrome up, filters up, no KPI row |
| ~0.7 s | **`N/A%` / `N/A` in red** + tiny spinner | lone spinner, page otherwise blank |
| ~1.0 s | unchanged | unchanged |
| ~2.2–3.1 s | real values (`82.0%`, `17.1s`) + rows | 7 KPI cards + 15 rows, all at once |

## Root cause

Two separate mistakes, both in the same direction — *an unknown value was drawn as if it were
a known one*.

**The red `N/A`.** `TestReports.tsx` computed its tiles as:

```tsx
const successRate = totalReports > 0 ? ((passedReports / totalReports) * 100).toFixed(1) : 'N/A';
// …
color: Number(successRate) >= 80 ? P.success : Number(successRate) >= 50 ? P.warning : P.error,
```

`totalReports` is `0` during the first load, so `successRate` was the string `'N/A'`.
`Number('N/A')` is `NaN`, and every comparison against `NaN` is `false` — so the rate chain
fell through all three branches and landed on its **last** one, `P.error`. "Not loaded yet"
was rendered in the exact colour reserved for "this failed", for the whole time the request
was in flight. The same fell-through branch also coloured a genuinely empty result set red.

**The spinner.** Both pages gated their body on `loading` and rendered a centred
`<CircularProgress>` in whatever space was left. That space was nothing: CI/CD rendered
*only* the spinner, so there was no KPI row, no header, no column widths to reserve. It
violates UI_STYLE §10 S6 — "loading states are the size of the content they replace, and
they gate on the `loading` boolean, never on 'data is empty'" — and contract #29 on layout
stability.

## Fix

**One shared skeleton, used by both pages** —
`frontend/src/components/common/ReportSkeleton.tsx`:

- `ValueSkeleton` — one grey bar for a stat tile's value. The tile keeps its own label,
  padding and border, so the *real* markup stays the single source of a tile's geometry and
  swapping a bar for a number cannot move anything.
- `TableRowsSkeleton` — placeholder `<TableRow>`s for a `<TableBody>`, one entry per visible
  column, `null` marking a cell that holds an icon rather than text. Widths vary per row and
  column so the block reads as pending content, not as a striped table painted on the page.
  The real header row above it is static text and stays mounted, so columns never shift.

`ReportSkeleton.tsx` is imported by **both** `/test-results/reports` and
`/test-results/cicd-reports`, so the two pages pulse identically instead of drifting apart
behind two hand-rolled loaders — which is the request that started this.

**`TestReports.tsx`**
- The tiles' stats now compute to `number | null` / `string | null`. `null` means "nothing to
  compute from" and renders a muted `—`, never a red rate. The `NaN` fall-through is gone:
  the colour chain now tests `successRate === null` first.
- `loading` swaps the tile's value for a `<ValueSkeleton>`; the labels (`Success rate`,
  `Avg duration`) stay readable throughout, so the user knows what is coming.
- Both tables (Tests and Campaigns) render `<TableRowsSkeleton>` in the body. The spare
  `<LoadingState>` spinner component is deleted.
- Each table's skeleton widths are built from that table's *own* visibility predicates, so
  the grey rows line up under the header whatever columns the user has hidden.

**`CICDReportsPage.tsx`**
- `KpiCard` gained a `loading` prop: it keeps the label and the tile and stubs the value and
  the sub line.
- The lone spinner is replaced by the page's own shape — the KPI row at its real tile count
  (`KPI_TILE_COUNT = 2 + CATEGORIES.length`), then the runs table with its **real** header
  and column widths and twelve skeleton rows. `catOrder` was hoisted out of the `kpi`
  `useMemo` to module scope as `CATEGORIES` so the skeleton and the live row count from one
  source.

## A second bug the first fix introduced

The first cut of `TableRowsSkeleton` sized its rows with `sx={{ py: (rowHeight - 16) / 4 }}`.
Deployed and measured on `/test-results/cicd-reports`, every placeholder row came out **125 px
tall instead of 42** — the skeleton was three times the height of the table it stood in for,
and the page was worse than before.

Cause: **MUI's `sx` runs bare numbers in padding through the theme's `spacing`** (8 by
default). `py: 6.5` did not mean 6.5 px, it meant `6.5 × 8 = 52 px` of padding above and below
a 16 px bar, which is the 125 px the browser reported:

```js
// measured in the deployed page, not reasoned about
rowHeights: [125, 125, 125, …]        // wanted 42
firstCellPadding: "52px 16px"         // wanted "12px 16px"
```

Fixed by an exported `rowPaddingY(rowHeight)` that returns an explicit `Npx` **string** — the
unit suffix skips the spacing transform — and by never inlining that arithmetic into `sx`
again. `Math.floor`, not `round`, so the row lands exactly on `rowHeight` rather than 1 px
over it.

The CI/CD KPI tiles had the same class of problem in a different form: the placeholder drew a
single bar where the live `KpiCard` draws three lines (`caption` / `h5` / `caption`), so the
row would shrink by two lines when the numbers arrived. `StatTileSkeleton` now reserves all
three, inside the tile's own `p: 2 / flex: 1 / minWidth: 100` box.

Both are pinned by tests that do not depend on the browser: `rowPaddingY` is a pure function
so the string form is asserted directly (a bare number fails it), and the KPI test counts
exactly 7 tiles of exactly 3 bars.

## Verification

`tests/frontend/ReportSkeleton.test.tsx` (new, 7 tests) holds both pages' first load open
with a never-settling fetch and asserts what is on screen.

The four page-level tests were checked as real regression tests — run against the pre-fix
sources with `git stash push -- <the two page files>`, **4 failed / 4 passed** across the two
versions:

```
× Test Reports > skeletons the stat values instead of showing a red N/A while the first load is in flight
× Test Reports > skeletons the table body rather than showing a centred spinner
× Test Reports > shows a muted dash, not a red N/A, when the load lands with no results
× CI/CD Reports > draws the KPI row and a skeleton table instead of a lone spinner
```

Geometry, measured in the browser on the deployed build after the fix:

| | before the fixes | after (live) |
|---|---|---|
| skeleton row height | 125 px | **42 px** — live row is 42 px |
| first cell padding | `52px 16px` | **`12px 16px`** — live cell is `6px 16px` |
| KPI tile bars | 1 | **3** — the live card draws caption / h5 / caption |
| KPI tile height | 112 px | **89 px** — live tile is 88 px |

Also green: `tsc --noEmit` (0 errors), `eslint` on both changed files, `npm run build`, and
the four report suites — `ReportSkeleton`, `TestReports`, `TestReportsRunManagement`,
`CICDReports` — 16 passed / 16.

Shipped in three commits on `main`: the skeleton itself, the `sx` spacing correction, then the
row-height and tile-line-box pins. Live build at verification: `main-2026.10.21-89478`.

## Notes

- The cell-level `'N/A'` fallbacks elsewhere on the page (`execution_time_ms` null,
  `userinterface_name` empty) were **left alone on purpose**. Those mean "this run recorded
  no duration", which is a real absence in real data, not a loading state — and they render
  in the default muted text colour, not the error colour. Only the header tiles were a
  first-load artefact.