# BUG-0691 — Verification and action dropdowns are empty for a host owned by another server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                |
|-----------|----------------------|
| ID        | BUG-0691             |
| Reported  | 2026-10-19           |
| Status    | Fixed (pending deploy) |
| Severity  | Medium               |
| Area      | frontend             |
| Fixed in  | build 90145 |
| Commit    | TBD                  |

---

## Symptom

In the navigation editor, Edit Node on a tree whose device sits on another server (e.g. `stbv1` on the second
server) listed only the verifications already on the node ("Existing"). The type list (image, text, video, color,
audio) and the action list were empty or marked unsupported.

## Root cause

`HostManagerProvider.loadDeviceSchemas` fetched `/server/system/getDeviceActions` from the selected (primary)
server. Each server has its own host registry, so it answered `Host <name> not found` and the device kept no
action or verification schemas. Same class as BUG-0625, which fixed only Take Control and Release.

## Also affected

Every editor call that carries a `host_name` and used `buildServerUrl`: for `vpt-mf1` the primary server answered
`Host "vpt-mf1" not found` on `/server/verification/executeBatch`.

## Fix

`frontend/src/contexts/HostManagerProvider.tsx`: the schema call goes to the host's own `server_url` through
`buildHostServerUrl`. The same fix covers the Edge and Node editors' other host calls: running actions and
verifications (`useAction`, `useVerification`), reference capture / crop / save and text detection
(`useVerificationEditor`, `useReferenceRecapture`, `useNodeEdit`), screenshot and DOM save (`useNode`), and
Go To navigation with its status poll (`executeNavigationAsync`, which now takes the host).

## Verification

After deploy: open Edit Node in the `stb_tv` tree with a device from another server selected; the Verification
dropdown lists all verification types, including `IsStandby`.
