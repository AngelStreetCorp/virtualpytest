# BUG-0436 — BLE remote button overlays misplaced during the pair-success transition

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0436                                                     |
| Reported  | 2026-10-08                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / controller / bluetooth                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

After a successful BLE pair the panel transitions from the
"Start Pairing / Preparing the remote" screen to the visual BLE remote, and
for the first ~150 ms the clickable button overlays are visibly off-position
(shifted, sometimes slightly larger or smaller, occasionally clipped against
the remote's edges). The misplacement is not random — the buttons then
*animate* into the correct position over the 0.2 s `transition: 'all 0.2s
ease-in-out'` baked into the button styles, which is what the user sees as
"misplaced during the animation of showing the BLE pairing success".

Closing the remote panel and re-opening it lands the buttons in the correct
position immediately, with no flash. Same in the action-screen → remote
transition that happens when polling first observes `fullyConnected === true`
on a freshly-paired adapter (e.g. the user dismisses a "Pair again?" prompt
and the panel swaps to the remote image).

## Root cause

`frontend/src/components/controller/remote/BluetoothRemote.tsx` measures the
real `<Box ref={imageBoxRef}>` height in a `useEffect` that fires **after**
paint:

```ts
useEffect(() => {
  const el = imageBoxRef.current;
  if (!el) return undefined;
  const update = () => { setMeasuredImageHeight(el.clientHeight); };
  update();
  const ro = new ResizeObserver(update);
  ro.observe(el);
  return () => ro.disconnect();
}, [fullyConnected, isCollapsed]);
const remoteScale =
  measuredImageHeight > 0
    ? measuredImageHeight / REMOTE_BASE_HEIGHT
    : calculateRemoteScale();
```

The remote image is mounted only when the panel swaps to the remote-image
render path (i.e. the dependency `fullyConnected` flips true). The first
render of that path has `measuredImageHeight === 0` (the ref state is fresh
and the `useEffect` hasn't run yet), so `remoteScale` falls back to
`calculateRemoteScale()`. That fallback is a heuristic derived from
`window.innerHeight - 120` (or the stream container height) — close to the
real flex/aspect-ratio-driven height but off by the flex padding / collapsed
header delta. The button overlays' `left/top/width/height` are computed from
`remoteScale` in absolute pixels, so the first frame paints them in the
heuristic-driven positions, and only after `useEffect` commits the
measurement do they re-render in the real positions. The 0.2 s
`transition: 'all 0.2s ease-in-out'` on the button styles smooths the
re-render, so the user sees a "slide into place" animation rather than a hard
jump.

Why "close and reopen" hides the bug: a remount triggers the same `useEffect`
race, but the panel-open transition already moves everything via the parent
animation, so the user perceives the final frame as "correct" without
noticing the same ~150 ms misplacement that would otherwise be visible.

## Fix

Switch the measurement from `useEffect` to `useLayoutEffect` so the
measurement + `setMeasuredImageHeight` commit synchronously before the
browser paints. The first frame the user sees of the remote image is now
already at the correct scale; there is no fallback-driven flash, so the
button overlays are correctly placed from the first paint.

File touched:

- `frontend/src/components/controller/remote/BluetoothRemote.tsx`
  - Add `useLayoutEffect` to the React import.
  - Change the image-box measurement effect (line ~261) from `useEffect`
    to `useLayoutEffect`, leaving the dependency array
    (`[fullyConnected, isCollapsed]`) and the ResizeObserver wiring
    untouched.

The `calculateRemoteScale()` fallback is intentionally kept as a defensive
guard for the very first frame (when `imageBoxRef.current` could in
principle be `null` on the first render) — but with `useLayoutEffect` it
should never be visible to the user.

## Verification

1. Open the BLE remote panel for a STB whose adapter has no current bond.
2. Click **Start Pairing** and put the STB in pairing mode.
3. Watch the transition from the action screen to the remote image.
4. Before the fix: the button overlays shift visibly (a few pixels to a
   dozen, depending on viewport height) and then animate into place over
   ~0.2 s. Sometimes a button ends up under another button or clipped
   against the remote edge.
5. After the fix: the buttons appear in the correct position from the
   first frame. No animation, no flash.
6. Repeat the test with the panel in collapsed / expanded states and with
   the browser viewport at the minimum supported height (e.g. 600 px) to
   confirm the fallback heuristic is no longer being relied on.
7. `cd frontend && ./node_modules/.bin/eslint
   src/components/controller/remote/BluetoothRemote.tsx` — clean.
8. `cd frontend && ./node_modules/.bin/tsc --noEmit` — clean.
