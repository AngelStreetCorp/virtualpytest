# BUG-0022 — Navigation edges draw in a normalized (wrong) direction; selection panel orientation flipped

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0022                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation                                       |
| Fixed in  | build 8713                                                   |
| Commit    | `93f30c43f` (+ `a2e6c3f26`)                                 |

---

## Symptom

An edge did not render straight from the source handle you dragged from to the target handle you
dropped on — it routed through the wrong sides/handles. Because different node pairs got routed onto
overlapping paths, edges **overlapped and stole each other's clicks**. Separately, in the Edge
Selection panel the reverse action-set card flipped to `target → source` while the forward card
read `source → target`, so the two directions of one bidirectional edge were shown in **opposite
orientations**.

## Root cause

A leftover **lexicographic coordinate normalization** in the edge router — a holdover from when a
bidirectional pair was stored as *two* rows that had to be collapsed onto one drawn line. It sorted
the two endpoints by coordinate and always drew from the "smaller" one, ignoring which handle was
actually the source. Post-migration each bidirectional pair is a **single row**, so normalizing no
longer collapses anything — it only flips the drawn handles and mis-routes edges. The panel derived
one card's orientation from the reverse action set instead of always presenting source → target.

## Fix

`a2e6c3f26` + `93f30c43f`:

- Removed the lexicographic normalization; the router is passed the real **source/target handle
  positions** (Left/Right/Top/Bottom) and draws straight between them. Applies to existing edges on
  reload, not only newly drawn ones.
- Both action-set cards in the selection panel now read **source → target** (which direction each
  card travels is conveyed by its action rows, e.g. key RIGHT vs key LEFT). The Edit-Edge dialog
  still labels a reverse action set `target → source`.

## Verification

1. Draw edges between several node pairs from specific handles → each routes straight through the
   handles you used; no overlap or click-stealing between different pairs.
2. Reload → existing edges keep the correct sides.
3. Open a bidirectional edge in the panel → both cards read source → target in the same orientation.
