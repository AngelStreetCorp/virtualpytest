# BUG-0473 — Host VNC preview renders flush top-left instead of centred in its card

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0473                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (host_vnc previews look broken; render sits off-centre with dead space) |
| Area      | `frontend/src/components/rec/RecHostPreview.tsx`             |
| Affected  | Every `host_vnc` device tile on `/device-control`            |
| Fixed in  | build 90145 |
| Commit    | _pending_                                                    |

## Symptom

On `/device-control`, a `host_vnc` preview (vpt-mf1, labox-web, vpt-pi1/3) renders its remote
desktop **flush against the top-left of its tile**, with a wide band of dead black space to the
right. The picture is the right size and the right aspect — it is simply not centred, so the
tile looks broken.

Measured off the operator's screenshot (638×428 crop, vpt-mf1):

```
card          x  20..571   (552 px)
noVNC render  x  20..395   (376 px)      gap left = 2, gap right = 176
```

The desktop also sat high in the tile, not vertically centred.

## Cause

A regression from the `persistentStreamRoot` work (BUG-0465 / BUG-0470), not from the sizing fix
it looked like it belonged to.

BUG-0447 had made the preview measure its stream area with a `ResizeObserver` and centre the
painted render by making it a **flex child** of the stream-area `Box`:

```
<Box ref={vncStreamAreaRef} sx={{ display:'flex', alignItems:'center', justifyContent:'center', … }}>
  <Box sx={{ width: previewVncSize.width, height: previewVncSize.height }}>  ← the flex item
```

That contract was explicitly documented in the code — the centring was safe *only* because the
flex item is the fixed-size wrapper and never the 1440×847 iframe box (BUG-0104).

BUG-0465/0470 then introduced `persistentStreamRoot`, a plain `div` created in a `useState`
initializer that the player is portal-rendered into, and which is then **re-parented between the
preview slot and the modal slot**:

```
target.appendChild(persistentStreamRoot)          // RecHostPreview.tsx:295
```

That changed the DOM to:

```
<Box ref={vncStreamAreaRef} sx={{ display:'flex', alignItems:'center', justifyContent:'center' }}>
  <Box ref={previewStreamSlotRef} sx={{ position:'absolute', inset:0 }} />   ← absolute: NOT a flex item
     └─ persistentStreamRoot   (position:relative; width/height:100%)
          └─ wrapper Box      (width/height: previewVncSize)                  ← static position
```

Two things break at once:

1. **The flex centring no longer applies.** `previewStreamSlotRef` is `position: absolute`, so it
   is not an in-flow flex item and `alignItems`/`justifyContent` have nothing to align. The
   stream area's centring became dead CSS.
2. **The wrapper is a plain static block** inside `persistentStreamRoot`, so it is placed at the
   container's top-left corner.

Sizing was unaffected — `vncScaledSize` still fits 1440×847 into the measured area — which is why
the render was the correct size and the correct aspect ratio, just parked in the wrong corner.
The `ResizeObserver` also kept working because it observes `persistentStreamRoot`, which is still
`width/height: 100%` of the area.

**The modal was never affected** because, when the modal owns the device, the root is moved into
the *modal's* slot, and the modal's own container still centres it (measured 81 px / 81 px in the
operator's modal screenshot). Only the preview path regressed.

## Fix

Centre the wrapper against the portal root instead of relying on the stream area's flex:

```tsx
position: 'absolute',
top: '50%',
left: '50%',
transform: 'translate(-50%, -50%)',
```

`persistentStreamRoot` is already `position: relative`, so these offsets are relative to the render
box. This holds wherever the root is attached — preview tile or modal slot — so the two paths
cannot drift apart again.

It cannot reintroduce BUG-0104: the wrapper is still the fixed painted size
(`previewVncSize`), never the iframe's 1440×847 box, so the transform is applied to a box that is
already the size it should paint at.

The flex properties on the stream-area `Box` are kept (the pause overlay is still an in-flow flex
child and relies on them) with a comment recording that they no longer centre the VNC render.

## Verification

- `tsc --noEmit` — clean.
- `eslint src/components/rec/RecHostPreview.tsx` — clean.
- DOM reproduction of the exact structure, rendered headless (548×225 area, 382×225 wrapper):

  | | card | render | gap L | gap R | |
  |---|---|---|---|---|---|
  | before | 24..575 | 25..406 (382w) | 1 | 169 | off by 168 px |
  | after  | 608..1159 | 695..1074 (380w) | 87 | 85 | centred |

  The "before" column reproduces the operator's screenshot (376 px render, gap L 2 / R 176),
  which confirms the mock is faithful rather than merely plausible.

Manual check on a VNC host (`/device-control`): the desktop should now sit centred in its tile at
every tile size and in every layout (Grid 12/24/48, Side by side, Stacked, Focus, One full), with
equal black margins left and right.