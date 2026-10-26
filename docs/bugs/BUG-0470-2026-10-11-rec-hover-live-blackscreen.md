# BUG-0470 — Hover-live preview tile is black in snapshot mode

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0470                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (hover-live, the only live view in snapshot mode, shows nothing) |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

## Symptom

On `/device-control` with more tiles than the live limit, tiles show the
latest snapshot image (TASK-48). Hovering a tile is meant to swap it to the
live stream, but the tile turns black. The console shows a healthy HLS
lifecycle (`URL changed - initializing`, `HLS manifest parsed successfully`,
`Resuming stream (non-destructive)`) and then `Component unmounting` when the
cursor leaves.

## Root cause

Same mechanism as [BUG-0465](BUG-0465-2026-10-11-rec-preview-tile-blackscreen-on-first-mount.md),
reached through a different path. The player renders through a portal into a
detached `persistentStreamRoot`, which a `useLayoutEffect` appends to the
preview slot (`previewStreamSlotRef`). The slot only exists in the live branch
of the render. In snapshot mode that branch only appears on hover, and
`showSnapshotImage` changing was not one of the effect's deps. As a result, the
effect never re-ran, the root stayed detached, and hls.js played into a
`<video>` that was not in the document.

## Fix

`frontend/src/components/rec/RecHostPreview.tsx` — add `showSnapshotImage` to
the attach effect's deps. The body is idempotent (the `parentElement !== target`
guard), so the extra run costs nothing.

## Verification

- `/device-control` in snapshot mode: hover a tile for >400 ms → live video
  paints; leave → snapshot returns; hover again → live again.
