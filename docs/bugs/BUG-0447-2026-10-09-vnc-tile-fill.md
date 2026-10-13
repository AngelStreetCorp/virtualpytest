# BUG-0447 — host_vnc preview sits as a tiny 255×150 box in any large layout (e.g. "One full")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0447                                                                    |
| Reported  | 2026-10-09 (operator on `/device-control`, vpt-pi3 in "One full" view)       |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (host_vnc previews unusable in the "One full", "Focus + below/right" and any single-tile layout) |
| Area      | `frontend/src/components/rec/RecHostPreview.tsx`                            |
| Fixed in  | Unreleased                                                                  |
| Commit    | TBD                                                                         |

---

## Symptom

On `/device-control`, picking the **One full** (or any focus) layout for a page that contains a
`host_vnc` device (e.g. `vpt-pi3`) renders a tiny ~255×150 desktop centred in a huge black card
that takes the entire stage. The card is `online`, noVNC loads, the WebSocket upgrade succeeds,
and the same host renders correctly when opened in the stream modal — so nothing is wrong
below the browser; the preview is just at the wrong scale.

```
appletv1 - vpt-mf1 (HLS path)            vpt-pi3 (host_vnc path)
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ ███ image fills the whole card █ │    │ Device                  online   │
│ ████                            █│    ├──────────────────────────────────┤
│ ███ image fills the whole card █ │    │                                  │
└──────────────────────────────────┘    │            ░░░░                  │
                                        │       ░░ tiny desktop ░░         │
                                        │            ░░░░                  │
                                        │                                  │
                                        │       (mostly black)             │
                                        └──────────────────────────────────┘
```

Screenshots attached to the original report.

## Root cause

`RecHostPreview.tsx` hardcoded the VNC preview's target box to `300×150` regardless of the
actual tile size:

```ts
const previewVncScaling = useMemo(
  () => calculateVncScaling({ width: 300, height: 150 }),
  [],
);
const previewVncSize = useMemo(() => vncScaledSize({ width: 300, height: 150 }), []);
```

`vncScaledSize(300,150)` returns `255×150`, which is correct for the default 300-ish-px-wide
tile in a 12/24/48-per-page grid, and so the small-tile case looks fine. But the same wrapper
size is used when the card is stretched to a single-tile layout (`One full`:
`{ slots: 1, columns: '1fr', rows: '1fr' }`), so the painted iframe is still 255×150 inside a
~1800×830 stream area. The wrapper is the flex item and stays the painted size; the
transform-scaled iframe is centred in the black card.

The modal (`RecStreamContainer.tsx`) already does the right thing — a `ResizeObserver` on the
stream-area box re-measures on every layout change and feeds the live size into
`calculateVncScaling` / `vncScaledSize`. The preview was the only place left that pinned a
fixed target.

## Fix

Mirror the modal's pattern in `RecHostPreview.tsx`:

1. `useLayoutEffect` with `ResizeObserver` measures the actual stream area Box (the
   `position: relative; width: 100%; height: 100%` parent of the VNC branch) on every layout
   change, window resize or pagination shift.
2. `previewVncSize` and `previewVncScaling` are now derived from that measured size (with a
   `300×150` fallback for the first paint, so the iframe never collapses to `0×0` before the
   observer fires).
3. The VNC branch's outer Box now carries `ref={vncStreamAreaRef}`. The rest of the
   rendering tree (flex centring, the wrapper that holds the painted size, the iframe's
   1440×847 layout box + transform) is unchanged — the same code path that handles the small
   grid tile now also handles the single-tile and focus layouts.

Why a `useLayoutEffect` (not `useEffect`): the size is needed before the first paint to
avoid flashing the old 255×150 iframe inside the huge card; the modal uses the same hook for
the same reason.

Why the observer is only created when `isVncDevice` is true: non-VNC tiles (HLS path) never
mount the VNC branch, and the ref is only set on a Box that exists in the VNC branch.
Toggling the target filter or the device model in the dropdown mounts/unmounts the box
naturally, and the effect re-runs on the `isVncDevice` change.

## Verification

- `cd frontend && ./node_modules/.bin/tsc --noEmit` — clean for the modified file.
- `cd frontend && ./node_modules/.bin/eslint src/components/rec/RecHostPreview.tsx` — clean.
- Manual check on a VNC host (e.g. vpt-pi3):
  1. `/device-control` → **One full** view → the iframe now fills the card (16:9 letterboxed
     in the available area, no longer 255×150).
  2. Switch back to **12 per page** → the small tile still renders the desktop in its
     300×150 area (same look as before this change).
  3. Hover/leave the tile under snapshot mode → the live branch swaps in with the same
     scaled size; leaving goes back to the snapshot.
  4. Open the stream modal → unchanged behaviour (modal already used the right pattern).
