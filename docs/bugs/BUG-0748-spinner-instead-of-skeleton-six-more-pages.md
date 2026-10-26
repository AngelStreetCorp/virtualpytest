# BUG-0748 — Six more pages replaced their content with a bare spinner while loading

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0748                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic — no wrong numbers here, just an empty page that fills in) |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The follow-up sweep for BUG-0744 / BUG-0747 found the same **loading** half of that defect on six
more pages (no red `N/A` anywhere — that was already fixed on the Report pages). Each one replaced
the content it was about to show with a centred spinner:

| page | what was replaced |
|---|---|
| **`/configuration/interface`** (`UserInterface.tsx`) | the whole user-interface table, header included |
| **`/configuration/models`** (`Models.tsx`) | the whole models table, header included |
| **Interface → References** (`UserInterfaceReferences.tsx`) | the whole references table |
| **Alerts / Monitoring Incidents** (`MonitoringIncidents.tsx`) | both tables — Active and Closed — with one spinner row each spanning every column |
| **Coverage** (`Coverage.tsx`) | the whole category list, and each expanded category's requirements table |
| **Localize Coverage** (`LocalizeCoverage.tsx`) | the whole app list — a card list on a phone, a six-column table on a desktop |

The user-visible shape was the same everywhere: a spinner floating in a large empty area, then
the real content popping into place.

## Root cause

One pattern, written out six times:

```tsx
{loading ? <LoadingState /> : rows.length === 0 ? <EmptyState /> : <TableContainer>…header…rows…</TableContainer>}
```

Where the table lived *inside* the `else`, the loading branch threw the **header** away too, so
the page reserved no column widths, no row count and no tile heights. On `MonitoringIncidents` it
was worse than "no shape": a single `<TableRow><TableCell colSpan={7}><CircularProgress/></…>`
spanned the entire table — the one thing a table skeleton must never do, because it is exactly the
"big empty area" the skeleton exists to remove.

Two pages were worse still than an empty area, because they drew **wrong numbers**: `Coverage`'s
category list and `LocalizeCoverage`'s app list are gated on `!isLoading`, so they showed nothing —
but the pages above them (`StatTiles`) rendered their own counts as `0` in the meantime.

## Fix

Every one of them now draws the layout it is about to fill, using the shared
`components/common/ReportSkeleton.tsx` from BUG-0744.

**The header stays mounted.** On `Models`, `UserInterface` and `UserInterfaceReferences` the
table shell and `<TableHead>` are hoisted into one shared piece used by both branches
(`modelsShell`, `interfaceShell`, `referencesShell`), so the live rows and the placeholder rows
have one geometry and the columns cannot shift between them. On `MonitoringIncidents` and
`LocalizeCoverage` the header was already outside the loading branch, so only the body changed.

Two shapes needed more than a table skeleton:

- **`Coverage`'s category list** is a CSS grid, not a table —
  `gridTemplateColumns: '20px 150px minmax(80px, 1fr) 44px 64px 72px 80px 72px'`. The placeholder
  draws seven rows on **the same grid**, with a bar in each cell and a 6 px rounded bar standing
  in for the `LinearProgress`. Its expanded category's requirements table moved into a
  `RequirementTable` component that owns the shell and header, exactly as above.
- **`LocalizeCoverage`** branches on `isPhone` *after* the loading gate, so the placeholder now
  branches too: a phone gets five placeholder cards, a desktop gets the real six-column table
  with its header.

`UserInterface`'s header has `isMobile` conditionals (4 columns on a phone, 7 on a desktop), so
its widths are built from the same predicates — `interfaceRowWidths` — rather than a fixed list
that would line up on one breakpoint and not the other.

## A seventh thing the screenshot caught

`MonitoringIncidents`' **stat tiles** were the same defect one level up. The first capture of
the fixed page showed, above a now-perfect skeleton:

```
Active alerts 0    This week 0    Most common N/A    Closed 0
```

Every one of those is unknown until the alerts land — `0` says "there are no active alerts" when
the truth is "we have not looked", and `N/A` is the same sentinel BUG-0744 removed from the Report
pages. The tiles now take a `ValueSkeleton` in their value slot while `loading`, and the
`Active alerts` tile's `color` is only decided once the count exists (so it cannot paint a
confident **green** "0 alerts" mid-load).

This is worth stating as a rule: **on a page whose tiles you are skeletonising, the tiles are
part of the job.** Drawing the table and leaving the numbers above it still telling a story is
half a fix.

Deliberately **left alone**, because a small inline spinner is correct there:

- `Coverage`'s 14 px spinner in a category row's chevron slot (per-row refresh), and its 10 px one
- `Coverage`'s drawer body — a drawer has no persistent header or columns to reserve
- `UserInterface`'s button spinners (`submitting`, `importing`) and its dialog's

## Verification

Two new loading-state tests, each checked as a real regression test with
`git stash push -- <the two page files>` — **2 failed / 4 passed** across the two versions:

```
× Models page — first load > draws the table header and placeholder rows instead of a centred spinner
× MonitoringIncidents page — first load > draws placeholder rows in both tables instead of one spinner row spanning them
```

Both assert the *header is still there* and *no `.MuiCircularProgress-root` is present*, which is
what distinguishes a skeleton from a spinner. The Alerts test also asserts no `N/A` and no
"0 active alerts" reach the screen while the data is in flight.

The other four pages needed no new test file — they already have one
(`Coverage`, `UserInterface`, `UserInterfaceReferences`) and it still passes unchanged, which is
the useful signal: hoisting the shell and header did not move what those tests assert on.

Green: `tsc --noEmit` (0 errors), `eslint` on all six pages, `npm run build` (23.74 s), and the
**whole** frontend component suite — **124 files, 656 tests, all passing**.

### The mock trap, again

`MonitoringIncidents`' existing test carries a comment that a hook mock must return stable
function references or the load-on-mount effect never settles. The new test honours it: the
loading state is reached with a `getAllAlerts` that **never resolves**, created once inside the
mock factory, rather than a per-render arrow. Getting this wrong is not a slow test — in the
earlier pass it hung a vitest worker for over two minutes.

## Notes

- Hoisting a table's shell + header into a shared variable is the mechanical part of this change
  and is where the JSX unbalanced twice mid-edit (a duplicated `<TableBody>`, a hoisted `<Table>`
  that nothing closed). Both were caught by `tsc` before anything shipped; `npm run build` ran
  afterwards as a second net.
- `LocalizeCoverage`'s table needed the shell to become a **function of its body**
  (`coverageTable(children)`) rather than a value, because its `<TableBody>` has to live inside the
  same `<Table>` as the header — a hoisted shell alone left the body outside the table element.