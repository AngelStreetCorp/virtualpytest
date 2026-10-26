# BUG-0537 — Agent Chat Target panel can be dragged into an unreadable thin strip

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0537                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / agent-chat / device panel                         |
| Fixed in  | build 90145 |
| Commit    | `8d4471082`                                                 |

---

## Symptom

On `/ai-agent` (AI Agent chat), dragging the divider between the chat and the
**Target** panel — the panel that hosts the live phone/TVR stream — could stop
at 180 px wide. The 9:18 mobile preview inside then collapsed into a thin
vertical strip with unreadable icons, weather text and dock labels (see the
screenshot attached to the report). The chat was usable; only the Target panel
looked broken.

`frontend/src/pages/AgentChat.tsx` line ~1035 shared one `MIN = 180` constant
across the three side panels (history, device, remote). The history and remote
panels only carry text, so 180 px is fine for them; the device panel hosts a
video tile whose aspect ratio it cannot honour, so the floor needs to be higher
than the shared minimum.

## Root cause

`AgentChat.tsx` resize `useEffect`:

```ts
const MIN = 180;
const MAX = 720;
…
} else if (resizingPanel === 'device') {
  const fromRight = window.innerWidth - e.clientX - (showRemote ? remotePanelWidth : 0);
  setDevicePanelWidth(Math.min(Math.max(fromRight, MIN), MAX));
}
```

`MIN` was a single shared value. The device panel could be set as narrow as
180 px, below which the 9:18 HLS preview renders as a sliver.

## Fix

Add a device-panel-specific minimum and use it only on the device branch:

```ts
const MIN = 180;
const MAX = 720;
// Target/device panel needs to stay wide enough to show a 9:16 mobile preview
// without squashing the phone to an unreadable strip. Below this, the icons and
// text inside the stream become a thin sliver (see the pre-fix screenshot).
// The other panels keep the generic MIN — they only carry text, not a video tile.
const DEVICE_PANEL_MIN = 240;
…
} else if (resizingPanel === 'device') {
  …
  setDevicePanelWidth(Math.min(Math.max(fromRight, DEVICE_PANEL_MIN), MAX));
}
```

History and remote keep the 180 px generic minimum; only the Target panel floor
moves to 240 px.

`frontend/src/pages/AgentChat.tsx:1035-1055` is the only changed block — a new
constant and one substitution in the device branch.

## Verification

- Type-check (`tsc --noEmit`) and lint (`eslint src/pages/AgentChat.tsx`)
  pass on the changed file.
- Deployed to `node1-vpt`. The shipped bundle
  `https://virtualpytest.angelstreet.io/assets/AgentChat-DW6LQnRq.js`
  contains the new constant:
  `const j=180,I=720,z=240` and the device branch uses `z`:
  `yt==="device"){const N=window.innerWidth-M.clientX-(w?Be:0);Ne(Math.min(Math.max(N,z),I))}`.
- On `/ai-agent`, drag the divider next to the **Target** header all the way
  left: the panel stops at 240 px, the 9:18 stream inside still fits without
  the previous vertical-strip shape.