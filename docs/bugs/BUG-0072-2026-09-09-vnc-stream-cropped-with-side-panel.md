# BUG-0072 — Host VNC stream (Windows/Linux desktop) cropped when the remote or web panel is open

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0072                                                                    |
| Reported  | 2026-09-09                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (desktop right edge + taskbar unreachable while controlling a `host_vnc` device) |
| Area      | frontend/src/components/rec/RecStreamContainer.tsx                          |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Open the REC stream modal on a `host_vnc` device (Windows or Linux desktop host), take control and
show the remote / web panel. The desktop is no longer fitted to the stream area: it is flush left
with its right side cut off (the "Learn about this picture" icon, the right of the taskbar), while
without a panel the same desktop is centred with black margins on both sides.

## Root cause

The stream is a noVNC `vnc_lite.html` iframe with a **fixed internal size** (`1440×847`, see
`calculateVncScaling`) fitted into the stream area with a CSS `transform: scale()`. noVNC lite does
no client-side scaling: it paints the remote desktop at native pixel size inside whatever viewport
the iframe gives it.

Two things went wrong once a panel took 20 % of the width:

1. The iframe is a **flex item** of the stream box. Flexbox shrank its real width to the box width
   as soon as that box got narrower than 1440 px, so noVNC's viewport became smaller than the
   desktop and it clipped the right edge. The `scale()` then shrank the already-clipped picture.
2. The scale factor was **guessed**, not measured: it took the layout hook's estimated width (which
   already subtracts the panel) and multiplied it by `0.8` again, so the fitted picture did not use
   the space that was actually available.

## Fix

`RecStreamContainer`:

- `flexShrink: 0` on the iframe — it always keeps its internal size, so noVNC always has a viewport
  at least as large as the desktop and only the transform decides the displayed size.
- The stream box is measured with a `ResizeObserver`; the scale is
  `min(measuredWidth / 1440, measuredHeight / 847)`. Opening / closing the remote or web panel and
  resizing the window re-fit the desktop dynamically. The layout-hook estimate remains only as the
  first-render fallback before the box has been measured.

## Verification

`tsc --noEmit` and `eslint` clean on the changed file. Visual check pending deploy: desktop centred
and fully visible with 0, 1 and 2 panels open.
