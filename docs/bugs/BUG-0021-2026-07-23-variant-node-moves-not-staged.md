# BUG-0021 — Variant node moves don't stage, save, or survive reload

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0021                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation / variants                            |
| Fixed in  | build 8713                                                   |
| Commit    | `4dcc21ac6` (+ `99114b9ad`)                                 |

---

## Symptom

With a variant selected, dragging a shared node looked like it moved on the canvas, but **Save had
nothing to flush** (no yellow unsaved indicator), so the move was lost on navigate-away. And even in
the cases where a variant layout *did* persist, it **snapped back to the base position after a page
reload**.

## Root cause

Two stacked defects:

1. **Nothing was staged.** ReactFlow's drag-end (`onNodeDragStop`) event does not carry the node's
   new position; the handler read the (absent) position and staged nothing, so the canvas showed
   the drag but the staged diff stayed empty.
2. **The override was dropped on reload.** The variant composition resolver discarded
   **position-only** overrides when composing the graph, so a persisted per-variant position was
   ignored on the next load and the node rendered at its base coordinates.

## Fix

`4dcc21ac6` + `99114b9ad`:

- Variant node moves now read the position from ReactFlow's node state (not the empty drag-end
  payload) and **stage** it like every other edit: the node follows the cursor, the yellow **Save**
  arms, the position persists to the variant's node-position override only on **Save**, and
  **Discard** reverts it. Staged moves are kept **per-variant** so switching the canvas scope with
  unsaved changes never drops another variant's positions.
- The composition resolver now **keeps position-only overrides**, so a saved per-variant layout
  renders from the override after reload.

## Verification

On a variant, drag a shared node → the yellow Save arms; click Save, then reload → the node stays
where you put it. Base and other variants keep their own layout; Discard reverts a staged move.
