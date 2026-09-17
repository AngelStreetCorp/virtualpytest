# BUG-0013 — Deleting an edge direction under a variant scope deletes it from base

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0013                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend / navigation / variants                            |
| Fixed in  | build 8414                                                   |
| Commit    | `51a32d479`                                                 |

---

## Symptom

In the navigation editor, with a **variant** selected in the viewing-scope chip, deleting
an edge direction from the Edge Selection panel (the per-action-set trash icon) removed
that direction from the **base** tree, not just the variant. If both directions ended up
empty, the whole **base** edge was deleted. Base navigation was silently mutated while the
author believed they were only editing the variant. A 2-variant composition was just as
broken: it either hit base the same way, or (via keyboard delete) dead-ended on a
"select a single variant" toast and did nothing.

## Root cause

The Edge Selection panel's per-direction trash icons were wired straight to
`navigation.deleteEdgeDirection` (`NavigationContext.tsx`), which is **variant-blind** — it
mutates `edge.data.action_sets` on the base edge, saves the base edge, and removes the base
edge entirely when both directions go empty. It never reads the viewing scope, so selecting
a variant changed nothing.

The variant-aware delete (`wrappedDeleteSelected` in `NavigationEditor.tsx`) was only
reachable from the keyboard and the whole-edge delete on an *empty* edge — not from the
per-direction trash icons the UI actually presents. Its composition branch, meanwhile, only
showed a toast instead of disabling on the selected variants.

## Fix

`frontend/src/pages/NavigationEditor.tsx`:

- New scope-aware `deleteEdgeDirectionScoped(edgeId, actionSetId)` behind both panel trash
  icons. Base scope keeps the existing `deleteEdgeDirection` behaviour. A single variant /
  composition removes that one action_set from **each** selected variant's
  `edge_overrides[edgeId].action_sets` (the full-replacement model — the variant's own
  override if present, else a deep copy of base), leaving **base untouched**. Deleting the
  last remaining direction writes `{disabled:true}` instead of an empty array (an empty
  array falls through to base per the resolver). Batched with `skipRefresh` + one
  `refresh()` (VARIANT.md pitfall #5); no-op guard for the phantom `'fallback'` reverse so
  it never mints a spurious override / `v` chip. Topology/conditional links stay base-only,
  so — unlike the base path — it deliberately does not touch conditional siblings.
- `wrappedDeleteSelected`'s composition branch now disables the row on **each** selected
  variant instead of the dead-end toast.

## Verification

1. Register two variants on a UI with a bidirectional edge that has actions on both
   directions.
2. Select `variant1` in the viewing-scope chip. Delete one direction from the Edge panel
   → the direction disappears on `variant1`; **base and the other variant still show both
   directions**. DB: `variant1.edge_overrides[<edge_id>].action_sets` holds only the
   remaining direction; base `navigation_edges` row unchanged.
3. Delete the remaining direction on `variant1` → the edge is hidden on `variant1`
   (`{disabled:true}`); base and the other variant keep the edge.
4. Select `variant1 + variant2` (composition). Delete a direction → it is removed on
   **both** variants; base unchanged.
5. Select `Base`. Delete a direction → unchanged legacy behaviour (base edge edited).
