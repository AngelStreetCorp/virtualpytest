# BUG-0017 — Variant edge panel doesn't refresh when an action set is deleted

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0017                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / navigation / variants                            |
| Fixed in  | build 8713                                                   |
| Commit    | `aac39d5ff`                                                 |

---

## Symptom

Deleting an edge action set from the Edge Selection panel updated the panel instantly **in Base**,
but with a **variant** selected you had to click the edge again for the panel to reflect the
deletion — the stale card lingered until re-selection.

## Root cause

The selected edge in the panel is a **snapshot** taken at click time. In Base, the delete mutated
that same edge object in place, so the panel saw the change. On a variant, the delete instead
**recomposes the graph** (base edge + variant overrides → a fresh composed edge object); the panel
still pointed at the pre-delete snapshot, which no longer existed in the recomposed graph, so it
showed stale data until the user re-clicked and captured a new snapshot.

## Fix

`frontend/src/pages/NavigationEditor.tsx` (`aac39d5ff`): after a variant action-set delete, the
selection re-points at the recomposed counterpart of the same edge automatically (matched by edge
id), so the panel updates in place without a manual re-select.

## Verification

Select a variant, open an edge with two action sets in the Edge panel, delete one action set: the
panel updates immediately to show the remaining direction, with no need to re-click the edge. Base
behaviour is unchanged.
