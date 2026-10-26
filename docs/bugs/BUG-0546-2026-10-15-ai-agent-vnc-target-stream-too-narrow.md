# BUG-0546 — AI Agent chat's Target stream stays as a fixed 306×180 sliver on a Windows / VNC host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                |
|-----------|----------------------------------------------------------------------|
| ID        | BUG-0546                                                             |
| Reported  | 2026-10-15                                                           |
| Status    | Fixed (pending deploy)                                               |
| Severity  | Minor (visual only; the chat still works)                            |
| Area      | frontend / agent chat / Target panel / device streaming              |
| Fixed in  | build 90145 |
| Branch    | `fix/vnc-target-stream-width`                                        |

---

## Symptom

On `/ai-agent`, with the **Target** device set to a Windows or any `host_vnc`
host (e.g. `vbox-dockrant1 (vpt_win)`), the device stream renders as a small
window pinned to the top-left of the dashed-border Target panel. Even after
dragging the Target panel to its full width (or with the device panel already
opened to MAX), the iframe itself stays roughly **306×180 px** and the rest of
the wrapper is black.

The mobile / TV (HLS) branch in the same panel correctly fills its container,
because `HLSVideoPlayer` honours `width: '100%' / height: '100%'`. Only the
VNC branch is broken.

A screenshot of the broken state was attached to the report.

## Root cause

`frontend/src/components/agent-chat/DevicePanel.tsx:107` rendered the VNC iframe
against a **hard-coded** target size:

```tsx
<iframe
  src={streamUrl}
  style={{
    border: 'none',
    backgroundColor: '#000',
    pointerEvents: 'none',
    ...calculateVncScaling({ width: 380, height: 180 }), // Panel target size
  }}
  title="VNC Desktop Stream"
/>
```

`calculateVncScaling` in `frontend/src/utils/vncUtils.ts:23-52` returns
`width: 1440px, height: 847px, transform: scale(min)` — the iframe keeps a
**fixed** 1440×847 layout box and shrinks only the render. With the
hard-coded `380×180` target the scale is `min(380/1440, 180/847) ≈ 0.213`,
so the visible iframe ended up as a 306×180 sliver anchored top-left in the
wrapper.

No `ResizeObserver`, no `useLayoutEffect`, no `getBoundingClientRect` anywhere
in `DevicePanel.tsx` (grep confirms), so the scale never updates when the
panel gets wider.

## Fix

Mirror what `frontend/src/components/rec/RecStreamContainer.tsx:246-282`
already does for the VNC live branch on the Rec page: a `ref` on the
dashed-border wrapper, `useLayoutEffect` + `ResizeObserver`, and feed the
**measured** `{ width, height }` into `calculateVncScaling`. The wrapper box
itself is now `display: 'flex', alignItems: 'center', justifyContent:
'center'` so the scaled render sits centred in the panel.

```tsx
const streamAreaRef = useRef<HTMLDivElement | null>(null);
const [measuredArea, setMeasuredArea] = useState<{ width: number; height: number } | null>(null);
useLayoutEffect(() => {
  const el = streamAreaRef.current;
  if (!el || typeof ResizeObserver === 'undefined') return;
  const update = () => {
    const { width, height } = el.getBoundingClientRect();
    setMeasuredArea((prev) =>
      prev && prev.width === width && prev.height === height ? prev : { width, height },
    );
  };
  update();
  const ro = new ResizeObserver(update);
  ro.observe(el);
  return () => ro.disconnect();
}, []);
const streamAreaWidth  = measuredArea?.width  ?? 380; // first-frame fallback == pre-fix target
const streamAreaHeight = measuredArea?.height ?? 180;
const vncScaling = useMemo(
  () => calculateVncScaling({ width: streamAreaWidth, height: streamAreaHeight }),
  [streamAreaWidth, streamAreaHeight],
);

// Wrapper is now a flex centring box; iframe overrides transformOrigin from
// 'top left' (calculateVncScaling default) to 'center center' so the scaled
// render lands centred, and `flexShrink: 0` keeps the layout box at 1440x847.
```

Only `frontend/src/components/agent-chat/DevicePanel.tsx` is changed. No
backend or hook changes. No new dependencies.

## Why the fallbacks are still 380×180

Before the `ResizeObserver` fires (first paint), the iframe would render
against `0×0` and the scaled desktop would be invisible. Using the same
380×180 fallback the old hard-coded code used means the pre-ResizeObserver
frame is identical to the pre-fix behaviour — there is no visible jump.

## Verification

- Type-check (`./node_modules/.bin/tsc --noEmit`) clean on the changed file
  (and on the rest of the project).
- `./node_modules/.bin/eslint src/components/agent-chat/DevicePanel.tsx`
  clean.
- On `/ai-agent` with a Windows / `host_vnc` target:
  - The stream fills the dashed-border Target rectangle on page load (no
    manual resize needed).
  - Dragging the Target divider wider / narrower keeps the stream filling the
    new size on the next frame, no top-left sliver.
  - Mobile / TV (HLS) branch unchanged: still fills its container.
- Confirm on `https://virtualpytest.angelstreet.io/...AgentChat-*.js`: the
  bundle contains the new `streamAreaRef` / `ResizeObserver` / measured-area
  block and no longer mentions the literal `380` / `180` VNC target pair
  (`grep -c 'calculateVncScaling({ width: 380, height: 180 })' dist/assets/*.js`
  must be `0`).
