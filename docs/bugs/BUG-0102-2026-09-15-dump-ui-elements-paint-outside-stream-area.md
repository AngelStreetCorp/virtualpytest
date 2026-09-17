# BUG-0102 — Dump UI element boxes are scaled to the wrong rect and paint over the whole page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0102                                                                    |
| Reported  | 2026-09-15 (REC stream modal, `S21x` Android Mobile, reported from a screenshot) |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (the UI-dump overlay is unusable in the modal — boxes land on the wrong pixels and obscure the app chrome; taps outside the phone screen map to bogus device coordinates) |
| Area      | `frontend/src/components/controller/remote/AndroidMobileOverlay.tsx`, `AndroidMobileRemote.tsx`, `frontend/src/hooks/rec/useRecStreamLayout.ts` |
| Fixed in  | build 9151                                                                  |
| Commit    | f432abb023                                                                  |

---

## Symptom

In the REC stream modal with the Android Mobile remote open, **Dump UI** (10 elements) drew its
highlight rectangles far outside the video: wide boxes spanning the entire stream area, one of them
sitting on top of the VirtualPyTest navigation bar above the modal, another overlapping the
"Select an app…" / "Refresh Apps" controls in the remote panel on the right. Nothing lined up with
anything on the phone screen.

## Root cause

Two independent defects, one of them dominant.

**1. The overlay scaled against the wrong fit mode.** `AndroidMobileOverlay` computed its content
rect with **cover** logic — fill the panel, crop the overflow — matching `HDMIStream`, which does
use `objectFit: 'cover'` for mobile devices (`HDMIStream.tsx:533`). But the REC modal does not
render `HDMIStream`; it renders `EnhancedHLSPlayer`, whose `layoutConfig` is hardcoded to
`objectFit: 'contain'` (`EnhancedHLSPlayer.tsx:541`). The two disagree, and in the modal the panel
is landscape while the phone is portrait, so the disagreement is enormous:

| | panel | device | virtual frame | offset applied |
|---|---|---|---|---|
| cover (what the overlay did) | 1313×739 | 1080×2340 | 1313×2845 | `cropY` = **−1053 px** |
| contain (what the player does) | 1313×739 | 1080×2340 | 341×739 | `hOffset` = +486 px |

Every box came out ~1.22× too large and ~1053 px too high — i.e. above the modal, on the navbar —
and a full-width element rendered 1313 px wide instead of 341 px.

**2. Nothing clipped the overlay.** The elements layer was sized to the panel rect with no
`overflow`, so an out-of-range box was free to paint anywhere on the page, including over the
remote panel. The base tap layer had the same problem in reverse: sized to the cover rect, it
accepted clicks outside the phone screen and mapped them to device coordinates that do not exist.

**3. (Related) The panel rect went stale on resize.** `useRecStreamLayout` reads
`window.innerWidth`/`innerHeight` inside a `useMemo` whose deps were `[isDesktopDevice, showRemote,
showWeb]`, with no `resize` listener — `isWindowReady` only flips once on mount. The overlay is
portalled to `document.body` and positioned in *page* coordinates against those numbers, so after
any window resize it kept using the pre-resize geometry.

## Fix

`AndroidMobileOverlay` now computes the content rect for **either** fit mode from one shared
calculation — the virtual (uncropped) frame, then `contentWidth/Height` clamped to the panel, with
whatever sticks out becoming `cropX/cropY` and whatever is missing becoming a centring offset. A
new `streamObjectFit` prop picks the mode, and `AndroidMobileRemote` passes `'contain'` when it has
`streamContainerDimensions` (the modal, `EnhancedHLSPlayer`) and `'cover'` otherwise (the floating
panel, `HDMIStream`), so the floating-panel behaviour is unchanged.

Both layers — the base tap layer and the elements layer — are now positioned on that content rect,
and the elements layer carries `overflow: 'hidden'`, so a dump can never paint outside the stream
content area regardless of what the scaling produces.

`useRecStreamLayout` tracks the viewport in state behind a `resize` listener and takes it as a
dependency, so the container dimensions the overlay is positioned against follow the window.

## Verification

- `npx tsc --noEmit` and `npm run build` clean.
- Arithmetic check at the reported geometry (window 1728×1117 → panel 1313×739, device 1080×2340):
  cover yields `y = 100·1.216 − 1053 = −931` for an element at device `y=100` and a 1313 px-wide
  full-width box — reproducing the screenshot exactly; contain yields `y = 31.6`, a 341 px-wide box
  inside a strip centred 486 px from the panel's left edge.
- Not yet checked against a live device in the deployed app.
