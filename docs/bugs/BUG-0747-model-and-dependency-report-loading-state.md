# BUG-0747 — Two more report pages had the same red `N/A`, and a spinner instead of their table

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0747                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic, and the same defect class as BUG-0744)        |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Two more pages in the same **Test → Report** dropdown carried the exact defect BUG-0744 fixed on
`/test-results/reports` and `/test-results/cicd-reports`:

- **`/test-results/model-reports`** painted its **Success rate** tile with `N/A%` in the error
  colour whenever there were no executions — on the first load, and on any genuinely empty
  result set.
- **`/test-results/model-reports`** and **`/test-results/dependency-report`** replaced their
  whole table body with a single centred spinner: one row spanning every column, so the page
  showed a mark in a large empty area and then popped the real table into place.
  `DependencyReport` did this in **four** tables (script↔node, script↔edge, node↔script,
  edge↔script).

## Root cause

**The red `N/A` is the same fall-through as BUG-0744**, copied. `ModelReports.tsx`:

```tsx
const successRate = totalVolume > 0 ? ((totalSuccessful / totalVolume) * 100).toFixed(1) : 'N/A';
// …
{ label: 'Success rate', value: `${successRate}%`, color: rateColor(Number(successRate), P) },
```

`totalVolume` is 0 before the first load lands, so `successRate` is the string `'N/A'`,
`Number('N/A')` is `NaN`, and `rateColor` — `(pct >= 80 ? success : pct >= 50 ? warning :
error)` — fails every comparison against `NaN` and returns `P.error`. Two layers were at
fault: the `'N/A'` sentinel, and the shared `rateColor` chain having no "no data" branch to
land on.

**The spinner is the same anti-pattern**: `loading ? <TableRow><TableCell colSpan={N}><
CircularProgress /></TableCell></TableRow> : …`, which reserves nothing — the page has no
column widths, no row count and no stat tiles while the data is in flight.

## Fix

- **`ModelReports.tsx`** — `successRate` is now `number | null` and `avgDuration` `string | null`;
  `null` means "nothing to compute from" and renders a muted `—`, never a red rate. The colour
  chain tests `successRate === null` first, so it can no longer fall through. Every number in
  the tile row is unknown while loading, so each value slot takes a `ValueSkeleton` and the
  labels stay readable — the page no longer greets the user with a row of `0`s.
- **Both pages** — the spinner rows are replaced by `TableRowsSkeleton`, one entry per visible
  column, from the same shared module `TestReports` and `CICDReportsPage` already use.
  `DependencyReport`'s four tables get widths matching their own column counts (4 and 5).
- **Unknown counts are no longer drawn as `0`.** On `DependencyReport` the four tiles read
  `Scripts → nodes / Scripts → edges / Nodes covered / Edges covered`, and every one of them
  showed a plain `0` while the load was in flight — the same defect as the red `N/A`, one class
  milder: "this interface has no dependencies" instead of "we have not looked yet". Each value
  slot now takes a `ValueSkeleton` while loading and the label stays readable.
- The now-unused `LoadingState` helper and `CircularProgress` import are gone from both files.

## Verification

`tests/frontend/ReportSkeleton.test.tsx` grew to **9 tests**. The two new ModelReports tests
hold the interface list, the metrics fetch and the execution results open, select a real user
interface so the tile row is actually reached, and assert both that no `N/A%` is rendered and
that nothing reading N/A (or a stand-in dash) carries the error colour.

Checked as real regression tests — `git stash push -- frontend/src/pages/ModelReports.tsx`,
**2 failed / 9 passed** across the two versions:

```
× ModelReports never renders an N/A% success rate while the executions are pending
× ModelReports shows a muted dash, not a red rate, when the load lands empty
```

Traps found while writing them, all three of which cost real time:

1. The interface listbox opens with a *placeholder* option ("Select a user interface to
   analyze…"), so selecting `options[0]` picks the empty value and the tile row is never
   reached — the tests select by **name**, not by index.
2. On this page `loading` tracks the *interface list*, not the executions, so the tests assert
   what a user can see rather than which internal flag is set.
3. A hook mock returning a **fresh arrow per render** is not harmless. `ModelReports`' interface
   load puts `getAllUserInterfaces` in its effect deps, so a per-call arrow made the dep look
   changed on every render and the list never settled — the Select stayed disabled and its
   options never opened. Hoisting the reference outside the factory fixes it, the same trap
   `DependencyReport.test.tsx` documents.

A unit test for the `DependencyReport` **tile** change was written and then removed: that page
gates its tile row behind an interface selection whose Select is disabled by a
`loadingInterfaces` flag with the same per-render-dep instability, and mocking it into a
loading state took longer than the change it was meant to cover. The table fix and the tile fix
are instead verified in the browser on the deployed build (below), which is where the geometry
is decided anyway.

Also green: `tsc --noEmit` (0 errors), `eslint` on all three changed files, and the six report
suites — `ReportSkeleton`, `ModelReports`, `DependencyReport`, `TestReports`,
`TestReportsRunManagement`, `CICDReports` — **20 passed / 20**.

Verified on the deployed build by driving the interface Select (it opens on `mousedown`, not
`click`) and sampling the load that follows:

| page | spinner | skeleton bars | rows | red/amber N/A |
|---|---|---|---|---|
| `/test-results/model-reports` | **0** | 87 | 8 placeholder | **0** |
| `/test-results/dependency-report` | **0** | 24 | 6 placeholder | **0** |

Real data landed at ~600 ms and ~400 ms respectively, so the skeleton window is short but the
page no longer shows a red `N/A` or a bare spinner in it.

## Notes

- **`rateColor` itself was left alone.** It has no "no data" input, and every other call site
  already guards (`kpiTiles.tsx` passes `undefined` when `total === 0`; `RunTests` passes
  `null`; `ModelReports`' own metrics rows use `|| 0`). Adding a null branch to a shared helper
  for the sake of two call sites is a wider change than the defect warrants; the guard belongs
  where the sentinel is produced.
- **`/test-results/dependency-report` and `/test-results/model-reports` both require a user
  interface to be selected** before they show any data, so a first-load probe has to drive the
  MUI Select (which opens on `mousedown`, not `click`) to reach the loading state at all.
- Pages with the same spinner-instead-of-skeleton shape, **not** changed here and worth a
  follow-up: `MonitoringIncidents.tsx` (2 tables), and the settings/config tables in
  `Models.tsx`, `UserInterface.tsx`, `UserInterfaceReferences.tsx`.