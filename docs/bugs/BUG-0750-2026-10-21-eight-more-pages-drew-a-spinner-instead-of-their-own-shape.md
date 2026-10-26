## Summary (BUG-0750 — Eight more pages drew a centred spinner in an empty area instead of their own shape)

# BUG-0750 — Eight more pages drew a centred spinner in an empty area instead of their own shape

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0750                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                      |
| Component | frontend                                                    |
| Related   | BUG-0744, BUG-0747, BUG-0748                                 |

## Summary

BUG-0744 fixed the four Report pages. BUG-0747 added the four Model/Dependency pages. BUG-0748
caught six more pages in the same defect class. This bug covers the **third sweep**, which
found eight more pages still rendering `<CircularProgress />` centred in an empty area on
cold or in-app navigation, while the page chrome (PageTitle, Save bar, tabs, table headers)
would have been perfectly mountable.

## Pages changed

| Route | Page | Was | Is |
|-------|------|-----|----|
| `/configuration/settings` | `frontend/src/pages/Settings.tsx` | `if (loading) return <CircularProgress />` — every tab replaced by a spinner | `SettingsPanelSkeleton` per tab; tabs + save bar + alerts stay mounted |
| `/monitoring/ai-queue` | `frontend/src/pages/AIQueueMonitor.tsx` | tile row +12-row Analyzed table gated on `queueStatus` | while loading, four bordered tiles (matches StatTileSkeleton) and a `<TableRowsSkeleton … rows={12} rowHeight={40} />` inside the real `<TableHead>` |
| `/test-plan/requirements` | `frontend/src/pages/Requirements.tsx` | inline spinner, then `{!isLoading && (...Toolbar + Card+Table…)}` — toolbar and head erased with the spinner | toolbar + Card + TableHead stay mounted; body becomes a 10-row skeleton matching the colgroup |
| `/users` | `frontend/src/pages/Users.tsx` | `if (isLoading) return <CircularProgress />` | Card + TableHead + colgroup always rendered; body is a 7-column 8-row skeleton |
| `/teams` | `frontend/src/pages/Teams.tsx` | same | same |
| `/roles` | `frontend/src/pages/Roles.tsx` | same | same, 5-column 6-row |
| `/workspaces` | `frontend/src/pages/Workspaces.tsx` | same | same (8 columns, "Built-in All" row was inside the body — moved inside the `: (...loading ? skeleton : body)` ternary with a fragment) |
| `/configuration/mobile-app` | `features/mobile-app/frontend/MobileAppPage.tsx` | `if (loading) return <CircularProgress />` — replaced the QR download card too | QR card (no data dep) stays visible; only the phone-slot table skeletonizes via `<TableRowsSkeleton widths={[80,240,100,120]} />` |
| `/mobile-app/this-phone` | `features/mobile-app/frontend/ThisPhonePage.tsx` | `if (loading) return <CircularProgress />` | page chrome (title, error Alert) + 4 status-row skeletons + 4 permission-row skeletons (circular + text) replace the spinner |
| `/test-execution/cicd` | `features/cicd/frontend/RunCICDPage.tsx` | `if (loading) return <CircularProgress />` | `<Paper>` shell + form-row + three runner-row skeletons + a Live-pane skeleton stay mounted |
| `/api/workspace/:workspaceId` | `frontend/src/pages/UserApiWorkspaceDetail.tsx` | full-screen fixed `<CircularProgress />` overlay | new `UserApiWorkspaceDetailSkeleton` that mirrors the three-pane layout (top bar + collections list + request list + response) |

## Why the chrome stays mounted

Two reasons the first cut of these pages discarded everything on `loading`:

1. The `{loading ? <spinner /> : <Card />}` ternary throws away the `<TableHead>` along with the spinner, so the user sees a flash of an empty area then a flash of a real table — the page never sits on one shape.
2. `if (loading) return <Box><CircularProgress /></Box>` discards the page chrome too, so the user loses the PageTitle, action buttons, segmented toggles, and error alerts they would use while the data is still in flight.

`UI_STYLE §10 S6` says: "the loading state is the size of the content it replaces". The fix follows it by hoisting the table shell + header (when there is one) above the gate and putting the skeleton inside the body. For pages without a table, the page chrome (title, action bar, errors) stays mounted and the body skeleton mirrors the real layout.

## What is intentionally still a spinner

- **Per-cell spinners** (the inline loading indicator that appears in a single `<TableCell>` while one row's data is still in flight) — small, contextual, not "centred in an empty area".
- **Per-row spinners** (e.g. `Requirements.tsx` per-expanded-requirement coverage loader) — small, attached to the row, not the whole page.
- **`<VariantsCell>` per-cell 14×14 spinner** in `/configuration/interface` — explicitly left alone (it's a per-thing loading indicator, not a page-level skeleton).
- **`Teams.tsx` `TeamRowDetail` "Loading members…" 16×16** and **Workspaces.tsx `ExpandedRow` "members loading" 20×20** — both small inline, not page-level.
- **App-level `MuiBackdrop` 40×40 with `colorInherit`** — sits over every page during boot; outside this change's scope.

The defect class the user originally called out — "centred spinner in empty space" — is gone from the eleven pages above.

## Lessons added to agent memory

- `mavis` agent memory already carries the **MUI `sx` rule** (bare numbers get × theme.spacing 8). Every new `paddingY`/`mt`/`py` here is `'\Npx'` literal; jsdom + `TableCell` cannot test it, so the test lives on the pure helper (`rowPaddingY`) — same pattern as BUG-0744.
- A **hook mock returning a fresh arrow per render** causes the dep array to look changed every render and the page never settles — confirmed in BUG-0748 still, while testing a Dependency Report tile. The fix is to **hoist the mock reference outside the factory**.
- A **simple ternary inside JSX** wraps to `<>...</>` when the body has more than one element at the top level. Forgetting that fragment is the whole reason this report has the "the JSX expects a `)`" half of the diff.

## Verified

- `tsc --noEmit -p tsconfig.json`: 0 errors.
- Subsequent deploy verified via the `vpt-headless-verify` recipe (cold-cache probe, sample the first frame where page chrome is up but data has not landed; `document.querySelectorAll('.MuiCircularProgress-root').length === 0` for each route).

## Files

- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/AIQueueMonitor.tsx`
- `frontend/src/pages/Requirements.tsx`
- `frontend/src/pages/Roles.tsx`
- `frontend/src/pages/Users.tsx`
- `frontend/src/pages/Teams.tsx`
- `frontend/src/pages/Workspaces.tsx`
- `frontend/src/pages/UserApiWorkspaceDetail.tsx`
- `frontend/src/components/common/ReportSkeleton.tsx` (reused — no changes; the existing `TableRowsSkeleton` and `StatTileSkeleton` covered every consumer in this batch)
- `features/mobile-app/frontend/MobileAppPage.tsx`
- `features/mobile-app/frontend/ThisPhonePage.tsx`
- `features/cicd/frontend/RunCICDPage.tsx`
