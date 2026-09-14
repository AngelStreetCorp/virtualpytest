# BUG-0019 — Deleting a variant orphans its hidden-only nodes/edges

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0019                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend / navigation / variants                  |
| Fixed in  | build 8713                                                   |
| Commit    | `1a1d3a284` (+ `aac39d5ff`)                                  |

---

## Symptom

Deleting a named variant left behind the nodes and edges that existed **only** on that variant.
They became invisible everywhere — hidden in Base and on every other variant — yet still occupied
their node pair, so drawing a new edge between the same two nodes dead-ended on "Edge already
exists" (the same class of stranded row behind [BUG-0014](BUG-0014-2026-07-23-onconnect-blocked-by-hidden-edge.md)).

## Root cause

A variant-only row is stored `hidden_in_base = true` and made visible by an `{enabled:true}` marker
in that variant's overrides. Deleting the variant removed the variant record and its overrides but
**never removed the rows those overrides were the only thing keeping alive** — so they persisted
with `hidden_in_base = true` and no variant enabling them: true orphans.

## Fix

`1a1d3a284`:

- **Cascade on delete** — deleting a variant now also deletes the nodes/edges that were
  `hidden_in_base` and enabled by no remaining variant (i.e. only that variant showed them).
- **Repair endpoint** — `POST /server/userinterface/<id>/variants/sweep-orphans` removes orphans
  already present in existing data (created before this fix). Legacy cross-disable variant rows are
  deliberately **not** touched.
- Drawing on a variant over a pair whose edge *that variant* had disabled now re-enables the edge
  within the variant instead of dead-ending.

## Verification

1. Create a variant, add a variant-only edge between two nodes, delete the variant → the edge is
   gone and the two nodes can be linked again.
2. On a UI with pre-existing orphans, call the `sweep-orphans` endpoint → the orphaned hidden rows
   are removed; base and surviving variants are unchanged.
