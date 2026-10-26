# BUG-0590 — Windows VNC desktop is cropped and PyAutoGUI controls stay hidden

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field | Value |
|-------|-------|
| ID | BUG-0590 |
| Reported | 2026-10-17 |
| Status | Fixed (deployed, verified headless on host-clone-1) |
| Severity | Medium |
| Area | frontend / device control |
| Fixed in | build 90145 |

## Symptom

The Windows host's VNC desktop does not fit the device tile or the Take Control stream modal. After taking control, the desktop remote containing PyAutoGUI is absent.

## Root cause

The VNC iframe was sized for a fixed 1440×847 desktop and scaled with CSS. A Windows framebuffer with another resolution was clipped inside that iframe. `useRecModalModes` opened Web for desktop devices but left the desktop remote closed; its toolbar toggle had already been removed.

## Fix

Use noVNC's viewport scaling for the tile and stream modal, with each iframe filling its container. Open the desktop remote when control starts while retaining the Web panel.

## Verification

On a Windows `host_vnc` device, resize the browser and open the stream modal: the entire desktop remains visible. Take control: the PyAutoGUI and Web panels are both present. Check dark and light themes and a non-default theme.

## Not covered

`/device-control` (`controller/av/VNCStream.tsx`) and the agent-chat `DevicePanel` still use the legacy
1440×847 CSS transform, so a Windows framebuffer with another resolution can still be cropped there.
Same fix applies (`withVncViewportScale()` + iframe at 100%), left for a follow-up so this change stays
scoped to the REC tile and the Take Control modal.
