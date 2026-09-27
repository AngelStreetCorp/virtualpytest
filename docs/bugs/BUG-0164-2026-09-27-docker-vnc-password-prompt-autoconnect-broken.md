# BUG-0164 — Docker host's noVNC asks for a password; the auto-connect fix never ran

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0164                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed in code, not yet verified on a Docker host             |
| Severity  | Medium                                                       |
| Area      | backend_host, frontend (VNC iframe), setup/docker            |
| Fixed in  | —                                                            |
| Commit    | —                                                            |

---

## Symptom

On a Docker install (`setup/docker`) the host's VNC tile on `/device-control` shows noVNC's
"Password required:" prompt. Hosts installed the native way connect without one.

## Why native hosts don't prompt

Not because they are configured better. Their deployed `/usr/share/novnc/vnc_lite.html` is an
old copy that hardcodes `readQueryVariable('password', 'admin1234')`, and their VNC password is
still `admin1234` ([BUG-0107](BUG-0107-2026-09-15-vnc-console-and-websockify-open-to-the-internet.md)
left it unrotated on purpose). The Docker image serves Debian's stock noVNC page (`novnc` 1:1.6.0-2,
`/usr/share/novnc/vnc_lite.html`, `readQueryVariable('password')` with no default) and a
per-install password from `entrypoint.sh`, so noVNC has nothing to send and prompts.

## Root cause of the failed fix (`ef8e0fc4ca`)

`ef8e0fc4ca` added `/host/system/vnc-info` to hand the frontend the password. It could not run:

- The frontend calls `POST /server/system/vnc-info`. `auto_proxy.py` forwards the method
  unchanged (it only rewrites POST→GET for `av/getStreamUrl` / `av/getStatus`), and the host
  route accepted only `GET` → 405 → the hook fell back to the plain URL → prompt.
- Once the 405 was gone, it would have broken every native host: the hook replaced the
  frontend's resolved stream URL with the host's raw `HOST_VNC_STREAM_PATH`. That value is
  `/vnc_lite.html` on those hosts, which `useStream` normally prefixes with `/host/<name>`, so
  the iframe would have loaded the frontend's own origin. It would also have put the password
  back in the URL behind the .107 proxy, which BUG-0107 removed on purpose.
- Its reasoning that nginx `auth_request` protects the page is false on the Docker VM, where
  cloudflared sends the noVNC hostname straight to `:6080` with no gate. There, the VNC
  password is the only access control.
- `setup/docker/docker-compose.yml` hardcoded that one VM's `vncgcloud.virtualpytest.com` as
  `HOST_VNC_STREAM_PATH` for every Docker install.

## Fix

- `POST /host/system/vnc-info` returns only `{password}`, and only when the host sets
  `HOST_VNC_AUTOCONNECT=true`. Every other host returns `''`, so its URL stays password-free.
- The frontend hook `useVncPassword` appends `password=` to the URL `useStream` already
  resolved, instead of replacing that URL. The iframe waits for the answer, so it never loads
  once without the password.
- `HOST_VNC_STREAM_PATH` in the compose file is `${HOST_VNC_STREAM_PATH:-http://${PUBLIC_HOST}:6080/vnc_lite.html}`.

With `HOST_VNC_AUTOCONNECT=true`, app users connect without typing the password. A direct
hit on `vnc_lite.html` still prompts, because that URL carries no password and the stock page
has no default. The password does appear in the iframe URL, so it lands in the access logs of
any proxy in front of noVNC.

Who can obtain it, checked 2026-09-27 against the code and the gcloud VM:
- `/server/system/vnc-info` is not in `UNAUTHENTICATED_SERVER_PREFIXES`, so it needs a user
  JWT or the `X-API-Key`.
- The route is **POST on purpose**: `enforce_viewer_read_only` rejects every non-GET from a
  `viewer`, and a fresh signup is a `viewer` (`handle_new_user` in `051_tenants.sql`). Signup
  is open with auto-confirm on the gcloud VM, so a GET route would hand the password to
  anyone who registers. Viewers get a 403, the hook falls back to `''`, and they see the prompt.
- Nothing logs it on the way: `proxy_to_host` prints endpoint and method only, websockify
  writes no HTTP request lines, and cloudflared logs no per-request URLs at its current level.

## Verification

Done: `tsc --noEmit` and eslint are clean for the touched files. By reading the code: the
route is registered as `POST`, and `auto_proxy` forwards `POST /server/system/vnc-info` to it.
Not done: a live check on the Docker VM (needs a new image release plus the `.env` keys).
