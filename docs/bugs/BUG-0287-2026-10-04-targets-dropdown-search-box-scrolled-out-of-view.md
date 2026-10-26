# BUG-0287 — The Targets dropdown's search box disappeared when the list was scrolled

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0287                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In the "All Targets" filter dropdown (Dashboard, Device Control), scrolling the target list hid the
search box behind the "Select all / Clear" row, so a search could not be changed without scrolling
back to the top.

## Root cause

`DeviceFilterBar` rendered the search box and the Select all / Clear row as two separate
`ListSubheader`s. Both are `position: sticky; top: 0`, so once the list scrolled the second one
stuck at the same place as the first and covered it.

## Fix

`frontend/src/components/common/DeviceFilterBar.tsx` — the search box and the Select all / Clear
row share one `ListSubheader`, so they stay pinned together at the top of the dropdown.

## Verification

Open the Targets dropdown on a page with many targets, type a search, scroll the list: the search
box and the Select all / Clear row both stay visible.
