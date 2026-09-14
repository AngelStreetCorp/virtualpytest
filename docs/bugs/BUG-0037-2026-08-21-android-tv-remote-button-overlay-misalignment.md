# BUG-0037 — Android TV remote button overlays don't line up with the remote artwork

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0037                                                     |
| Reported  | 2026-08-21                                                   |
| Status    | Closed                                                        |
| Severity  | Low (cosmetic / hit-target precision, remote still functional) |
| Area      | frontend — `AndroidTvRemote.tsx`, `config/remote/androidTvRemote.ts` |
| Fixed in  | build 8713                                                   |
| Commit    | `219a86689`, `63b83217b`, `17e9878dc`                        |

---

## Symptom

On the Android TV remote (both the floating/collapsed panel and, intermittently, the
recording-modal panel), the invisible clickable overlay circles don't sit on top of the
buttons drawn in `androidtv_remote.png`. Visible as a second, offset outline next to each
icon (power, back/home/menu, rewind/play/fast-forward, volume +/−, mute), growing more
pronounced the further down the remote a button sits — barely noticeable on the power
button near the top, clearly offset by the time you reach mute at the bottom.

## Root cause

Two separate issues in the same component/config pair:

1. **`button_layout`** (the array used by the floating, non-modal remote panel) had
   `position` values that were simply wrong — verified by detecting the real icon-center
   pixel coordinates in `androidtv_remote.png` (white-glyph blob centroids for icons,
   Hough-circle detection for the blank D-pad ring) and converting them into the
   component's `640×1800` canvas coordinate space. The stored positions drifted from the
   computed correct ones by ~10 canvas units near the top of the remote to ~135 near the
   bottom — a genuine authoring error, not a rendering bug.
2. **`remoteScale`** (`AndroidTvRemote.tsx`) was computed from an *estimate*
   (`streamContainerDimensions.height - 20`, or `window.innerHeight - 120` outside a
   modal) rather than the container's actual rendered pixel height. `button_layout_recmodal`
   (the array used inside the recording modal) turned out to already have numerically
   correct positions when checked the same way — so any visible drift there has to come
   from this estimate silently diverging from the true CSS-computed size (the container's
   `aspectRatio: '640/1800'` box), which produces exactly the same "grows with distance
   from top" misalignment pattern.

## Fix

- `frontend/src/config/remote/androidTvRemote.ts` — recomputed every `button_layout`
  position from the measured icon/ring centers (top-left-corner convention: `position =
  center - (size * button_scale_factor) / 2`, with the `background-size: contain`
  letterbox margin accounted for). `button_layout_recmodal` was left untouched — it was
  already correct.
- `frontend/src/components/controller/remote/AndroidTvRemote.tsx` — added a ref on the
  image container plus a `ResizeObserver`, and `remoteScale` now uses the container's
  measured `getBoundingClientRect().height` when available, falling back to the old
  estimate only before the first measurement (avoids a flash of zero-sized buttons on
  first paint).

## Verification

Built a throwaway local HTML harness that reproduces the exact CSS/positioning formula
from the component against a copy of `androidtv_remote.png`, screenshotted it with
Puppeteer, and cropped in on each button row — confirmed every button (power, D-pad ring
+ up/down/left/right zones, back/home/menu, rewind/play/fast-forward, volume ±, mute) now
sits tightly centered on its artwork. `tsc --noEmit` and `eslint` clean on both changed
files. Documented the reusable harness workflow in
`docs/agent/devices/REMOTE_BUTTON_ALIGNMENT.md` (internal) for future remote
fixes.

## Follow-up: the `remoteScale` fix from the first pass didn't actually apply (`63b83217b`)

The harness proved the *config values* were sound, but a real screenshot of the deployed
RecModal after the first fix still showed the exact same offset on
back/home/menu/rewind/play/fast-forward. Drove the live page with Puppeteer (auto-signed
token, RPI1-server, `mi` device, Take Control) and read the actual DOM: the container's
measured box was `315.0 × 886px`, matching the declared `640/1800` CSS aspect ratio
exactly (`315.0/886 = 0.3556 = 640/1800`) — so the "CSS estimate vs actual size" theory
from the first pass was wrong; the aspect-ratio box renders exactly as declared.
Back-solving from the *actually rendered* button pixel positions showed `remoteScale` was
still `≈0.445`, not `measuredContainerHeight/1800 ≈ 0.492` — i.e. `measuredContainerHeight`
was still `null` at render time, silently falling back to the old estimate the first pass
was meant to replace.

Root cause of *that*: the first pass used `useRef` + `useLayoutEffect` keyed on
`[isCollapsed, streamContainerDimensions]`. The image container only mounts once
`session.connected` becomes true (`renderRemoteInterface()` returns an entirely different,
ref-less tree while disconnected) — a transition neither dependency captures. The effect's
first (and only, until one of its deps changes) run typically lands while the ref is still
null, and never re-fires once the container actually mounts, so the `ResizeObserver` is
never attached and `measuredContainerHeight` stays `null` forever.

Fixed by switching to a callback ref (`setRemoteContainerEl` as the `ref` prop, `useEffect`
keyed on the resulting element state) — callback refs fire on every mount/unmount
regardless of what else changed, so the observer attaches reliably the moment the
connected view actually renders.

**Lesson for next time:** don't trust a config-only harness as full verification when the
positioning math also depends on a runtime DOM measurement — that plumbing needs its own
live-app check, not just a plausibility argument. A `console.log` of the actual `remoteScale`
value (or, faster, driving the real page and back-solving `remoteScale` from a couple of
rendered button rects) would have caught this in one pass.

**Confirmed fixed live** (build main-2026.08.21-8528): a temporary `console.log` of
`measuredContainerHeight`/`remoteScale` deployed alongside the callback-ref fix showed the
value correctly settling to `measuredContainerHeight: 886, remoteScale: 0.4922` (matching
the container's real `886px` height) a few renders after the remote connects — the earlier
"still broken" read was this session's Puppeteer script querying the DOM before that
settle, not an actual live bug. A follow-up screenshot of the real RecModal (RPI1-server,
`mi`/Android_TV device, Take Control) shows every button overlay precisely centered on its
artwork. Debug logging removed before the final deploy.
