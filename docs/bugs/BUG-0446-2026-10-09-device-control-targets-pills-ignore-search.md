# BUG-0446 — Device Control: Targets host-toggle pills ignore the in-dropdown search box

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0446                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

## Symptom

On `/device-control` (Desktop → Device) the **All Targets** dropdown shows
the new host-toggle pills introduced by the `feat(filter): host toggle pills
in the Targets dropdown` change (commit `da4d73e84`). Typing a query into
the in-dropdown search box filters the targets list below, but the host
pill row at the top is **unaffected** by the search: every host with two or
more targets shows up no matter what the user typed. So typing `mf1` to
find `vpt-mf1` still shows the `vpt-pi1` and `vpt-pi3` pills alongside the
`vpt-mf1` result — the search and the pill row contradict each other and
the user has to scan three pills to find the one matching their query.

Repro from `virtualpytest.angelstreet.io/device-control`:

1. Open the page with at least these hosts online: `vpt-mf1`, `vpt-pi1`,
   `vpt-pi3` (each with 2+ devices).
2. Click **All Targets** → the dropdown opens, search box at the top,
   **Select all / Clear** row, then three host pills: `vpt-mf1 7/7`,
   `vpt-pi1 0/3`, `vpt-pi3 0/4`.
3. Type `mf1` into the search box. The targets list below narrows to the
   seven `vpt-mf1` targets, but the pill row still shows `vpt-mf1`,
   `vpt-pi1` and `vpt-pi3` — the two unrelated hosts should be hidden.
4. Clear the search. The pill row is unchanged (it never narrowed in the
   first place).

## Root cause

`frontend/src/components/common/DeviceFilterBar.tsx` builds the pill row
from the **full** `targetOptions` list:

```ts
const hostGroups = useMemo(() => {
  const byHost = new Map<string, string[]>();
  targetOptions.forEach((option) => { /* group by host */ });
  return Array.from(byHost.entries())
    .filter(([, targets]) => targets.length >= 2)
    .map(([host, targets]) => ({ host, targets, selectedCount: ... }));
}, [targetOptions, targetFilter]);
```

The targets list itself is correctly narrowed by the search — that lives
in the `visibleTargetOptions` `useMemo` immediately above — but
`hostGroups` never consults it. So the displayed pills always reflect
"every host with ≥ 2 targets", regardless of what the user typed in the
search box. The pill click still has to act on the whole host (that is
intentional: a click on `vpt-mf1` should select every device on the host,
even when only some of them are visible), but the **visibility** of the
pill should follow the search.

## Fix

`frontend/src/components/common/DeviceFilterBar.tsx`:

`hostGroups` still groups from `targetOptions` so the pill click toggles
the full host rack, but the displayed pills are then narrowed to hosts
that have at least one target matching the active search:

```ts
const visibleSet = new Set(visibleTargetOptions);
return Array.from(byHost.entries())
  .filter(([, targets]) => targets.length >= 2)
  .filter(([, targets]) => targets.some((t) => visibleSet.has(t)))
  .map(([host, targets]) => ({ host, targets, selectedCount: ... }))
  .sort((a, b) => a.host.localeCompare(b.host));
}, [targetOptions, visibleTargetOptions, targetFilter]);
```

Effect:

- Empty search → all qualifying hosts shown (unchanged).
- Search `mf1` → only `vpt-mf1` (host name contains `mf1`) shown; the two
  unrelated hosts disappear from the pill row and the targets list below
  matches the same set.
- Clearing the search → the full pill row reappears.

The pill click semantics ("toggle every target on this host") are
preserved — the pill owns the full host's target list, not just the
visible slice.

## Verification

- Throwaway vitest spec (`frontend/dev-filter-bar.spec.tsx`,
  `vitest.config.local.ts`) renders `<DeviceFilterBar>` with three
  host groups (14 targets total: 7 on `vpt-mf1`, 3 on `vpt-pi1`, 4 on
  `vpt-pi3`), opens the dropdown, asserts all three host pills are
  present with an empty search, types `mf1`, asserts `vpt-mf1` is still
  there and `vpt-pi1` / `vpt-pi3` are gone, then clears the search and
  asserts all three are back. With the fix → green. With the fix
  reverted (the old file content) → fails on the "vpt-pi1 must not be
  visible" assertion.
- Manual check on `virtualpytest.angelstreet.io/device-control` (desktop,
  logged in) once this build is deployed: type `mf1` (or `pi1` / `pi3`)
  in the Targets dropdown search box — only the matching host pill
  remains.

The throwaway spec and its `vitest.config.local.ts` are not committed
(removed locally); no test-framework dependency lands in `package.json`.
