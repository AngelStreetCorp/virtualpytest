# BUG-0174 — AI Agent Target panel shows a black VNC stream unless another page opened the stream in the last 10 minutes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0174                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend AI Agent page (agent-chat DevicePanel)              |
| Fixed in  | Unreleased (the cut sets the build — never copy VERSION.txt)  |
| Commit    | 94c99c42b                                                    |

---

## Symptom

On `/ai-agent` with a `host_vnc` target (e.g. `host-clone-1`), the right-hand **Target** panel
stays black and the browser logs `401 GET /host/host-clone-1/vnc_lite.html`. The recorded AI-agent
promo video shows exactly this.

It looks intermittent. After the Device page stream has been opened in the same browser, the panel
works for about 10 minutes, and the connection then stays up.

Reproduced on prod in two clean headless browsers: opening `/ai-agent` directly gives 401 and a black
panel. Minting `/server/host-session/session` first gives 200 and a live desktop.

## Root cause

BUG-0107 step 2 put `/host/<name>/…` behind nginx `auth_request`, which accepts only the HttpOnly
host-session cookie (`server_host_session_routes.py:host_session_authorize`, 10-minute TTL). Every
VNC iframe must mint that cookie before it gets a `src`. `RecHostPreview` and `RecStreamContainer`
do this with `useHostSession`; `components/agent-chat/DevicePanel.tsx` gave the iframe its `src`
right away.

## Fix

`DevicePanel` calls `useHostSession(streamUrl, false)` for `host_vnc` and renders the iframe only
once the mint resolves, showing "Loading stream..." until then. This is the same pattern as
`RecHostPreview`.

## Verification

In a clean browser, open `/ai-agent`, pick `host-clone-1` and show the device panel. The request
`vnc_lite.html` returns 200 and the panel shows the desktop, with no Device page visit before.
