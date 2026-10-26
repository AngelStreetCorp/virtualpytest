# BUG-0465 — Rec preview tile stays black on first page mount

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0464                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (every preview tile is invisible until a modal opens)   |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

## Symptom

On a fresh load of `/device-control` (which mounts `<Rec />`), every device
tile renders as a black rectangle. The HLS console logs read normally —
`URL changed - initializing`, `Initializing HLS stream`, `HLS manifest parsed
successfully`, `Resuming stream (non-destructive)` — so `hls.js` is alive and
streaming, but no frame is ever composited. Tiles stay black until the user
opens and closes the fullscreen modal on that device (which moves the player
between slots and incidentally re-attaches it).

Not related to host load — `vpt-mf1` was at `load 4.57 / 5.24 / 5.30` on its
4 cores at report time, which is busy but not the cause of a literal black
screen with healthy `FRAG_LOADED` traffic.

## Root cause

`feat(rec): preserve stream between preview and modal` (commit `a46287179`)
moved the HLS player out of the React tree and into a portal whose target is
a detached `<div>` created in `useState`:

```js
const [persistentStreamRoot] = useState(() => {
  const root = document.createElement('div');
  // …width/height/position/overflow/background…
  return root;
});
```

That div is supposed to be moved into the per-tile slot by a `useLayoutEffect`:

```js
useLayoutEffect(() => {
  const target = isSelectedForModal && persistentStreamTarget
    ? persistentStreamTarget
    : previewStreamSlotRef.current;
  if (target && persistentStreamRoot.parentElement !== target) {
    target.appendChild(persistentStreamRoot);
  }
}, [isSelectedForModal, persistentStreamRoot, persistentStreamTarget]);
```

The effect runs **once on mount**. On that mount, `useStream` is still in its
initial `null` state, so the HLS branch is not rendered yet,
`<Box ref={previewStreamSlotRef}>` is not in the DOM, and
`previewStreamSlotRef.current` is `null`. The effect no-ops.

When `useStream` later resolves and `setStreamUrl(url)` lands, RecHostPreview
re-renders, the slot Box finally appears, and the ref is populated — but
**the effect does not re-run**, because none of its declared deps changed.

`persistentStreamRoot` stays a detached orphan. The portal keeps rendering
the HLS player into it, so `hls.js` happily attaches media, fetches the
manifest, and decodes segments against a `<video>` that is not in the
document tree — that is why the console shows a healthy stream lifecycle
while the screen stays black.

The modal path worked only by accident: opening a modal flips
`isSelectedForModal` to true and sets `persistentStreamTarget`, which is in
the dep list, so the effect finally re-ran and attached the orphan to
*somewhere*.

## Fix

`frontend/src/components/rec/RecHostPreview.tsx` — add `streamUrl` to the
`useLayoutEffect` deps so the effect re-runs when the HLS branch first
appears. The effect body is idempotent (the `parentElement !== target` guard
skips the no-op case), so the extra runs are free.

```diff
-  }, [isSelectedForModal, persistentStreamRoot, persistentStreamTarget]);
+  }, [isSelectedForModal, persistentStreamRoot, persistentStreamTarget, streamUrl]);
```

`streamUrl` is already in scope from the `useStream` destructure at the top
of the component.

## Verification

- Load `/device-control` after the fix is deployed.
- All visible tiles must paint the first segment within ~1–2 s, no full
  black rectangle.
- Open and close the fullscreen modal on a tile — it must keep playing,
  no remount flash.
- Switch server and reload — tiles still paint.
- `useLayoutEffect` should fire once on mount (slot absent) and once after
  the URL resolves (slot appears), not 6–8 times per tile.