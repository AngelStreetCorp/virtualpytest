# BUG-0192 — QuickTest crashed as soon as control was taken on a web (host_vnc) device

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0192                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (QuickTest unusable on every web target)                |
| Area      | frontend (`features/quicktest`)                              |
| Fixed in  | build 90145 |
| Commit    | `06a9cf847`                                                  |

---

## Symptom

On `/builder/quick-test`, pick Target `host-clone-1`, Interface `youtube-web`, click **Control**:
the whole page is replaced by "This page hit an error — useVNCState must be used within a
VNCStateProvider". No step can be added. Set-top box and phone targets are not affected.

## Root cause

Taking control of a `host_vnc` device mounts its player and web panel (`VNCStream`,
`PlaywrightWebTerminal`), which read `useVNCState()`. The Navigation editor
(`NavigationEditorProvider`), the AI chat (`AgentChat`) and the stream modal
(`RecHostStreamModal`) wrap their pages in `VNCStateProvider`; `QuickTestBuilder` only wrapped
its content in `NavigationConfigProvider` and `DeviceDataProvider`, so the hook threw.

## Fix

`features/quicktest/frontend/QuickTestBuilder.tsx`: wrap `QuickTestBuilderContent` in
`VNCStateProvider`.

## Verification

Local Vite with the fix against the prod API: QuickTest → `host-clone-1` / `youtube-web` →
Control → the VNC panel and the browser control panel appear, **+ Go to node** adds a step,
Release frees the device. Before the fix the same steps crash the page.
