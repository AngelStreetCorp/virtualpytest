# BUG-0540 — Any signed-in user could reach the host's admin endpoints through the server auto-proxy

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0540                                   |
| Reported  | 2026-10-15                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | High (security)                            |
| Area      | backend_server / auto_proxy / authz        |
| Fixed in  | build 90145 |
| Commit    | see branch fix/auto-proxy-host-admin-deny  |

---

## Symptom

`GET /server/system/updatePrereqs?host_name=host-clone-1` returned the host's prerequisite JSON for a
non-admin caller (verified live 2026-10-15).

## Root cause

`auto_proxy.py` serves `/server/<path:endpoint>` and forwards it to `/host/<endpoint>` with the server's own API
key. The only guard is the global server auth (viewers blocked from POST; every authenticated user may GET). Its
exclusion list covered `executable/ settings/ teams/ users/ workspaces/ auth/ devices/` only, so every host
`/host/system/*` endpoint without a dedicated server route was reachable by any tester, developer or manager:
`runCommand` (arbitrary shell as the service user), `updateCore`, `applyBundle`, `updatePrereqs`.

## Fix

Default-deny: auto_proxy answers 404 "handled by a dedicated server route" for every `system/` endpoint except an
explicit allowlist (`SYSTEM_PASSTHROUGH_ALLOWLIST`, only `POST system/vnc-info`, which the VNC tile uses to get
the noVNC password and which the viewer role cannot call). All other frontend `/server/system/*` URLs already
have dedicated, permission-checked routes in `server_system_routes.py`. Contract 38.

## Verification

`tests/backend_server/test_auto_proxy_system_deny.py`: updatePrereqs, runCommand, applyBundle, envFiles,
updateCore return 404 without calling the host; `actions/executeBatch` and `system/vnc-info` (POST) still proxy.
