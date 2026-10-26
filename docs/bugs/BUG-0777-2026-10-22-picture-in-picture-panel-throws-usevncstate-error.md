# BUG-0777 — The Picture-in-picture panel never appears: choosing a browser device throws "useVNCState must be used within a VNCStateProvider"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0777                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding CHAOS-10, in `docs/tasks/QA-CHAOS-findings.md`); reproduced against the live app.

- **Page / route:** every page (mod enabled by default); confirmed on /, /builder/test-builder, /builder/quick-test
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open the app.
2. Click the Picture-in-picture icon in the top bar (next to the bell).
3. Click a device with a `host_vnc` model, for example `host-clone-1_Host`.
4. Check the console.

**Expected:** The device stream floats in the corner of the page.

**Actual:** The component throws while rendering (`Error: useVNCState must be used within a VNCStateProvider`) so the panel is never painted: a dead button and a console error. Reproduced 3 of 3 pages. The two builder pages also mount `DeviceControlPanels` outside a provider.

Evidence:

- [verify-pip-1-home.jpg](../tasks/qa-evidence/chaos/verify-pip-1-home.jpg)
- [verify-pip-2-home.jpg](../tasks/qa-evidence/chaos/verify-pip-2-home.jpg)
- [verify-vncstate-mods-pip.jpg](../tasks/qa-evidence/chaos/verify-vncstate-mods-pip.jpg)
- Fix evidence: [after](../tasks/qa-evidence/fix/bug-0777-after.png)

Related bugs: BUG-0192 (same error on QuickTest, fixed there).

## Root cause

`VNCStream.tsx:175` calls `useVNCState()`, which throws on a null context (`contexts/VNCStateContext.tsx:20-25`). The provider is mounted only in the navigation editor, `RecHostStreamModal` and `AgentChat`; the PiP mod (`features/mods/frontend/pip/register.tsx`, `PipOverlay.tsx:299` -> `DeviceControlPanels.tsx:193`) and `pages/TestCaseBuilder.tsx:1017` render outside it. QuickTestBuilder now wraps its page (BUG-0192, the same error), so check that one first.

Two more things kept the panel from being usable once the crash was gone, and both are part of the
same "the panel never appeared" defect:

- **The panel grew away from its anchor.** `VNCStream` / `HDMIStream` draw the visible panel
  inside an outer box that only carries the offsets (`right: 20px`, `bottom: 56px`) and has no
  size of its own; the panel inside it grew to the **right** of that anchor (`left: 0`). With a
  right anchor the panel therefore started at the anchor and ran past the right edge of the
  screen instead of ending on it.
- **The offsets were applied twice.** The overlay's shell is already anchored in the viewport
  (bottom-right, 20 px from the edge, 56 px above the bottom), and it passed the same offsets
  down to the panel — which reads them against the shell. The panel ended up 20 px further from
  the right edge and 56 px higher than the documented anchor.

## Fix

1. **The state is provided where the player is rendered.** `VNCStateContext.tsx` gains a
   `VNCStateBoundary`: a provider that yields to an ancestor's provider and gives the page its
   own when there is none. `DeviceControlPanels` wraps its panels in it, so every page that
   renders a player — the picture-in-picture overlay, the test case builder, the virtual scripts
   page — has the state, and the pages that share it (navigation editor, Rec modal, AgentChat,
   Quick Test) still share it. The provider is always rendered, so nothing remounts when the
   state changes.
2. **A right-anchored panel grows to the left of its anchor**
   (`frontend/src/components/controller/av/panelAnchor.ts`, used by `VNCStream` and `HDMIStream`).
3. **The overlay anchors the panel to its own shell** (`PipOverlay.tsx`): the shell keeps the
   20 px / 56 px margin from the screen edge, the panel gets `right: 0` / `bottom: 0` (or
   `left: 0` when the remote is shown) relative to it.

## Tests

- `tests/frontend/PipPanel.test.tsx` — 2 cases: the panels render a `host_vnc` player **without a
  provider above them** (the mock player reads the real `useVNCState()`, so the test fails with
  the reported error when the boundary is gone), and a right-anchored panel grows to the left.
- `tests/frontend/PipOverlayAnchor.test.tsx` — 2 cases: the overlay gives the panel an offset
  relative to its shell (`{right: '0px', bottom: '0px'}`, and `{left: '0px', bottom: '0px'}`
  with the remote shown), not the viewport offsets.

Verified against the pre-fix sources via `git stash`: **3 failed / 1 passed**; on the fixed
sources **4 passed**.

## Verification

In a real browser at 1440 px (Vite dev + the live backend), picking `host-clone-1_Host`
(`host_vnc`) in the PiP menu of the header:

| | before | after |
|---|---|---|
| page errors | `useVNCState must be used within a VNCStateProvider` × 2 | none |
| panel on screen | not painted | **370 × 240 at x 1050–1420, y 604–844** |
| margin from the screen edge | — | 20 px right, 56 px above the bottom (as documented) |

Before the fix the panel box was measured at x 1400–1770 — it hung 330 px past the right edge
of the screen. Screenshot above.

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
