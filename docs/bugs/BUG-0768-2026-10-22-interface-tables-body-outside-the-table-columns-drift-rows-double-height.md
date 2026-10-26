# BUG-0768 — The Interface, Device Models and References tables lost their body: misaligned columns and double-height rows

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0768                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (three configuration pages render a broken table — every column drifts from its header and every row is twice as tall as designed) |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

`/configuration/interface` (58 interfaces) shows the header and the rows in two different
geometries:

- **Columns do not line up.** "Models" sits under the gap after "Models", "Version" is well
  left of its header, "Variants" further still, and the Navigation / References / Actions icons
  bunch up against the middle of the card while the header labels run off to the right edge.
  The drift grows the further right the column sits.
- **Rows are about twice as tall as they should be.** Two interfaces that used to fit in the
  space one row takes now push the list past the fold.

Reported by the owner from a screenshot of the deployed page, 2026-10-22.

## Root cause

`57f6cdac9` ("six more pages drew a spinner in an empty area instead of their own shape") replaced
three centred-spinner loading states with a table skeleton, and to make the placeholder share the
live table's geometry it hoisted the table header into a const:

```tsx
const interfaceShell = (        // <-- the WHOLE <Table>, not just the <TableHead>
  <Table size="small" sx={{ tableLayout: 'fixed', '& .MuiTableCell-root': { py: 0.5, px: 1 } }}>
    <TableHead>…</TableHead>
  </Table>
);
…
<TableContainer component={Paper}>
  {interfaceShell}
  <TableBody>…</TableBody>      {/* <-- now a SIBLING of the table, not a child */}
</TableContainer>
```

The hoisted piece carried the `<Table>` **opening tag** with it. The `<TableBody>` written below
it was therefore no longer inside a table, and the rendered DOM became:

```html
<div class="MuiTableContainer-root">
  <table class="MuiTable-root"><thead>…</thead></table>   <!-- the header -->
  <tbody>…</tbody>                                        <!-- a second, separate "table" -->
</div>
```

React renders that tree verbatim (it builds nodes with `createElement`, it does not run the HTML
parser's content-model fixups), so the browser keeps a `<tbody>` whose parent is a `<div>`. CSS
anonymous-table fixup then wraps it in an anonymous table box. The result is **two independent
tables**, and each symptom follows from one of them:

1. **Misaligned columns.** The header is still `tableLayout: fixed` with explicit `width: '24%'`,
   `'22%'`, `'12%'`, … and `width: '100%'`, so it fills the card and pins every column to its
   declared percentage. The orphaned body has no such rule, so it falls back to content-based
   **auto** layout and, with `width: auto`, shrink-to-fit: each column is sized by its content and
   the table collapses to the sum. Two different column algorithms, so the columns cannot agree —
   and the body does not even inherit the header's `<colgroup>` on the Device Models page.

2. **Double-height rows.** The compact padding lives in the header `<Table>`'s `sx`:

   ```tsx
   '& .MuiTableCell-root': { py: 0.5, px: 1 }
   ```

   It is a **descendant** selector. With the body no longer a descendant of that `<Table>`, every
   body cell reverted to the theme's default `MuiTableCell` padding — measured `16px` on all four
   sides instead of `4px 8px`. A 20px chip in 32px of vertical padding is a 60px row.

Measured on the deployed page before the fix (1600×1000 viewport, `getBoundingClientRect()`):

| | header table | body (`<tbody>`) |
|---|---|---|
| width | 1132px (fills the card) | **823px** (shrink-to-fit) |
| `Models` cell `x` | 510 | 522 |
| `Version` cell `x` | 767 | **681** |
| `Variants` cell `x` | 907 | **735** |
| `Actions` cell `x` | 1245 | **995** |
| row height | 31px | **60px** |
| body cell padding | `py: 0.5` → 4px | `16px` |

## Blast radius

Three of the six pages changed by `57f6cdac9` hoisted the `<Table>` instead of the `<TableHead>`.
All three were broken the same way, in both their live and their loading branch:

| Page | Const | Route |
|---|---|---|
| `frontend/src/pages/UserInterface.tsx` | `interfaceShell` | `/configuration/interface` |
| `frontend/src/pages/Models.tsx` | `modelsShell` | `/configuration/models` |
| `frontend/src/pages/UserInterfaceReferences.tsx` | `referencesShell` | `/configuration/interface/:name/references` |

The other three are correct, and are the shape to copy: `MonitoringIncidents.tsx` kept the whole
`<Table>` inline, `Coverage.tsx` uses a wrapper component, and `LocalizeCoverage.tsx` passes the
body **in as an argument** — which is also what the commit message itself warned about:

> "LocalizeCoverage branches on isPhone AFTER the loading gate, so the placeholder branches too …
> Its shell became a function of its body (coverageTable) — as a value the TableBody ended up
> outside the Table element."

The failure mode was already known and named in that commit; it just did not get checked on the
three pages that kept a value.

Nothing caught it: `tsc` and eslint are both happy with a `<tbody>` in a `<div>`, the build
succeeds, and the existing tests assert that a header exists and no spinner is present — all of
which remained true. The two tests added by that commit kept passing.

## Fix

Hoist the `<TableHead>` (plus the `<colgroup>` on Device Models), **not** the `<Table>`, and
assemble head and body through a function that takes the body as an argument:

```tsx
const interfaceTable = (body: React.ReactNode) => (
  <Table size="small" sx={{ … }}>
    {interfaceHead}
    {body}
  </Table>
);
…
{interfaceTable(<TableBody>…</TableBody>)}
```

Both branches — the placeholder and the live rows — go through it. The `<tbody>` is now lexically
inside the `<table>` that closes it, so "the body escaped the table" stops being something a later
edit has to remember. This is `LocalizeCoverage`'s `coverageTable(body)` shape, adopted for
consistency.

Two row-height details shipped with it:

- `INTERFACE_ROW_HEIGHT` is now read by both the live `<TableRow>`'s `height` and the skeleton's
  `rowHeight`. The skeleton previously asked for `44px` against a real row of 36px, so every list
  visibly jumped when its rows arrived; a `<tr>` also grows to its tallest cell, so pinning the live
  row keeps a long name from pushing a row past the placeholder it replaces.

  The constant is **36**, derived from the tallest child in a row — and that is not the chip. The
  20px chips are shorter than the action `IconButton`s (`sx={{ p: 0.5 }}`, small `SvgIcon`), which
  measure 26.6px; 26.6 + `py: 0.5` above and below (4px each) + the row's 1px bottom border =
  35.6px. The first attempt used 29px, from the chip's 20px; the browser disagreed, which is how
  the 26.6px button was found. A `<tr>` `height` is a minimum, so the row rendered at its natural
  36px and the constant was corrected from the measurement.
- The two `& .MuiTableBody-root …:hover` / `& .MuiTableHead-root …:hover` overrides collapse to
  one `& .MuiTableRow-root:hover`. They were separate rules over a structure that no longer
  existed.

## Tests

`tests/frontend/TableBodyInTable.test.tsx` — 6 cases, both branches of all three pages. For each
it asserts the `<tbody>` has a `<table>` ancestor, that the same table also holds the `<thead>`,
and that the header and body row have the same number of cells.

This is deliberately a **DOM-structure** assertion and not a computed-style one. jsdom resolves
`closest('table')` faithfully but does not inject `sx` classes into `TableCell`, so an assertion on
padding or a generated class would pass here regardless of the bug — see BUG-0744. Structure does
not have that problem, which is why the geometry could be pinned in a unit test at all.

Verified against the pre-fix sources via `git stash`: **6 failed / 6 passed**; on the fixed sources
**6 passed**. All 6 failures name the page and the branch.

## Verification

`tsc --noEmit` 0 errors · eslint clean on the three files · the four pre-existing suites for these
pages (`UserInterface`, `Models`, `UserInterfaceReferences`, `MonitoringIncidents`) 6/6 passing
unchanged · `npm run build` succeeds · whole frontend component suite 126 files / 671 tests.

Re-measured on the deployed page after the deploy (1600×1000, `getBoundingClientRect()`):

| | before | after |
|---|---|---|
| `<tbody>`'s parent | `DIV` | **`TABLE`** |
| same table as the `<thead>` | no | **yes** |
| body table width | 823px (shrink-to-fit) | **1132px** (fills, same as the head) |
| column drift (Models → Actions) | 12 / 86 / 172 / 250px | **0 / 0 / 0 / 0px** |
| body cell padding | `16px` | **`4px 8px`** |
| row height | 60px | **36px** |

`/configuration/models` measured the same way: drift 0px on all six columns, padding `4px 8px`,
rows 36px.