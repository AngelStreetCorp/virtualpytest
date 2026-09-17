# BUG-0011 — Test Reports filters keep the previous workspace's devices after switching workspace

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0011                                                     |
| Reported  | 2026-07-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / TestReports                                       |
| Fixed in  | build 8414                                                   |
| Commit    | `66eb486e1`                                                  |

---

## Symptom

On `/test-results/reports`, changing the active workspace refreshed the table
rows but the **filter dropdowns did not update**: the Target (and Test /
Campaign) options, and any selected filter value, still reflected the previous
workspace — so devices that don't belong to the newly selected workspace stayed
listed and selectable in the filters.

## Root cause

The dropdown option lists (`knownTargets`, `knownScripts`, `knownCampaigns`)
are populated only once on the first load, guarded by `initialLoadDone.current`,
and the selected filters (`filterTarget` / `filterScript` / `filterCampaign` /
`selectedFolder`) were never cleared on workspace change. A reset effect already
existed for **server** changes (drop cached results + options, clear filters,
reset the load guards, refetch) but there was **no equivalent for workspace
changes**. The workspace change did retrigger the row fetch (via the derived
`workspaceHostFilter`), but nothing rebuilt the filter UI, so it kept showing
the old workspace's devices.

## Fix

`frontend/src/pages/TestReports.tsx` — added a workspace-change reset effect
(keyed on `activeWorkspace?.id`, mirroring the existing server-change effect)
that:

- clears `knownScripts` / `knownTargets` / `knownCampaigns` and the selected
  `filterScript` / `filterTarget` / `filterCampaign` / `selectedFolder`,
- resets the `initialLoadDone` / `campaignLoadDone` guards so options repopulate,
- explicitly reloads scripts scoped to the new workspace's hosts (so options
  refresh even when no filter was selected — a cleared `filterTarget` wouldn't
  by itself retrigger the load effect) and reloads campaigns.

## Verification

On the Test Reports page, switch the active workspace: the Target/Test/Campaign
dropdowns now rebuild from the new workspace's data and any prior selection is
cleared, so no device from the previous workspace remains in the filters.
