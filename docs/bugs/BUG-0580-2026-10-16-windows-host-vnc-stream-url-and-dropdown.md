# BUG-0580: Windows host_vnc device — wrong stream URL, missing from All Targets dropdown, noVNC iframe 401s

**Date:** 2026-10-16
**Discovered on:** vpt-windows (joach's Windows PC, French locale, `desktop-uni4mdl`)
**Severity:** medium — vpt-windows devices are present on the dashboard but two of the three user-facing affordances (dropdown filter, stream preview) are broken
**Status:** fixed (commit pending)

## Three symptoms, one root cause family

After the BUG-0576 service_health fix landed, the vpt-windows card showed everything green, but the device page still had three visible problems:

1. **vpt-windows missing from the "All Targets" dropdown** on `/device-control`. The pill row showed `vpt-lenovo1 0/6`, `vpt-nipogi 0/24`, `vpt-pi4 0/4` — but no `vpt-windows 0/2` next to them, even though the device-control grid on page 2 was rendering the vpt-windows tile correctly.
2. **No stream on the vpt-windows tile** — the iframe area was rendering a 404 ("The requested URL was not found on the server").
3. **URL issue for VNC** — even when a noVNC URL was set in `.env`, the iframe src still pointed at the HLS endpoint, so the user got `/host/stream/device1` (the wrong path) instead of `/host/vpt-windows/vnc_lite.html` (the right path). The noVNC iframe then 401'd because the host-session cookie was never minted.

## Root causes

### Bug 1 — `video_stream_path` was set to the HLS path even for `host_vnc` devices

`backend_host/src/controllers/controller_manager.py` builds the device dict from the `DEVICE{i}_*` env vars. For every device it stores `video_stream_path = DEVICE{i}_VIDEO_STREAM_PATH`, which the .env spells as `/host/stream/deviceN` (the HLS capture path).

`shared/src/lib/utils/build_url_utils.py:buildStreamUrl` then sees `device_model == 'host_vnc'`, takes `video_stream_path` as the VNC URL, and returns `/host/stream/device1` as the stream URL. The dashboard's iframe src becomes `https://<host-server>/host/stream/device1?_vpt=…`, which 404s on pi4's nginx (no proxy for that path), and the noVNC session cookie is never primed because the buildStreamUrl output never matches `GATED_HOST_PATH_RE`.

The env var `DEVICE{i}_HOST_VNC_STREAM_PATH` (e.g. `http://localhost:6080/vnc_lite.html`) was set on vpt-windows, but `controller_manager.py` was not reading it.

### Bug 2 — `hostGroups` bucketed host_vnc devices under their own device name

`frontend/src/components/common/DeviceFilterBar.tsx:hostGroups` splits each target option on the last ` - ` and treats the suffix as the host bucket. For host_vnc devices, `getDeviceTargetLabel` returns the bare device name (e.g. `Host_Windows`) without a ` - <host_name>` suffix, so the bucket was the device name itself. Each vpt-windows device landed in a one-member group, the `targets.length >= 2` filter dropped both, and vpt-windows disappeared from the dropdown while vpt-lenovo1 / vpt-nipogi / vpt-pi4 (all multi-device Linux hosts) stayed visible.

### Bug 3 — no CORS on `/server/host-session/session`

`backend_server/src/routes/server_host_session_routes.py` was the only blueprint serving `/host/<name>/...` cookie minting that had **no** `after_request` CORS handler. The browser's preflight `OPTIONS /server/host-session/session` returned 405 with no CORS headers, the actual POST never happened, no cookie was stored, and even after Bug 1 was fixed the noVNC iframe 401'd because nginx's `auth_request` gate has no cookie to validate.

The vpt-pi4 iframe looked like it worked only because the cookie had been minted in a previous session and was still within the 10-min TTL. A fresh visit (or a different host) was always going to 401.

## Fix

### Fix 1 — `controller_manager.py`: route host_vnc to the noVNC URL

For `device_model == 'host_vnc'`, override `video_stream_path` with `DEVICE{i}_HOST_VNC_STREAM_PATH` if set, otherwise default to `/host/<HOST_NAME>/vnc_lite.html` (the nginx-proxied noVNC URL that the dashboard's `useStream` already knows how to resolve against the host's `server_url`).

The vpt-windows `.env` had `DEVICE1_HOST_VNC_STREAM_PATH=http://localhost:6080/vnc_lite.html` — which is wrong for cross-host iframe usage. The env var was changed to `/host/vpt-windows/vnc_lite.html` (the proxy path) so the URL is resolved by the dashboard against the owning server's origin (`https://<host-server>`), then nginx proxies the request to vpt-windows.

### Fix 2 — `DeviceFilterBar.tsx`: bucket host_vnc devices under their owning host

When the target label has no ` - ` separator, resolve the host bucket from `targetKeys[option].host_name` instead of using the bare device name. This puts `Host_Windows` and `Mobile_Emulator` under the same `vpt-windows` bucket (2 targets), the `>= 2` filter keeps the group, and the pill row shows `vpt-windows 0/2` alongside the other hosts.

### Fix 3 — `server_host_session_routes.py`: add CORS preflight + after_request

Added a `DEFAULT_HOST_SESSION_CORS_ORIGINS` constant listing the frontends the user actually runs (`https://virtualpytest.angelstreet.io`, `https://<host-server>`, `https://gcloudstandalone-api.virtualpytest.com`, `capacitor://localhost`, `https://localhost`), an `after_request` hook that echoes the requesting origin (so credentials work — `*` is rejected with `Access-Control-Allow-Credentials: true`), and an explicit `OPTIONS` handler so the blueprint returns 204 with CORS headers instead of Flask's default 405.

The origin list is overridable via `HOST_SESSION_CORS_ORIGINS` env var for new frontends without a code change.

## Verification on vpt-windows

After the fix, with the dashboard at `https://virtualpytest.angelstreet.io/device-control?server=vpt-pi4&page=2`:

- `POST /server/av/getStreamUrl` for `vpt-windows:device1` returns `{"stream_url": "/host/vpt-windows/vnc_lite.html", "success": true}` (was `/host/stream/device1`).
- The "All Targets" pill row shows `vpt-windows 0/2` next to `vpt-lenovo1 0/6`, `vpt-nipogi 0/24`, `vpt-pi4 0/4` (was missing).
- The vpt-windows tile's iframe src is `https://<host-server>/host/vpt-windows/vnc_lite.html?_vpt=…` (was `/host/stream/device1`).
- The browser successfully mints the `vpt_host_session` cookie via the preflighted POST and stores it for `/host/vpt-windows/` with `Path=/host/vpt-windows/; HttpOnly; Secure; SameSite=None`.

## Reproduction recipe (for other Windows / host_vnc hosts)

1. Install a Windows host with `DEVICE{N}_MODEL=host_vnc`.
2. Add `DEVICE{N}_HOST_VNC_STREAM_PATH=/host/<host_name>/vnc_lite.html` to the host `.env` (do **not** use a full `http(s)://...` URL — the dashboard prepends the owning server's origin and the proxy then needs to forward to the host).
3. Open the dashboard with a different origin than the owning server (e.g. `https://virtualpytest.angelstreet.io` against a vpt-pi4 host).
4. The vpt-windows tile iframe will 401; the All Targets dropdown will be missing the host; the dashboard will be unable to mint the host-session cookie.

## Workaround for hosts that haven't picked up the fix yet

- Open the dashboard directly on the owning server's origin (e.g. `https://<host-server>/device-control`) — the same-site request skips the CORS preflight and the cookie is set.
- Manually run `curl -X POST -H "Origin: <frontend>" .../server/host-session/session -d '{"host_name":"..."}'` to mint the cookie before opening the dashboard.

## Files changed

- `backend_host/src/controllers/controller_manager.py` — route host_vnc `video_stream_path` to the noVNC URL.
- `frontend/src/components/common/DeviceFilterBar.tsx` — host grouping uses `targetKeys[option].host_name` when no ` - ` separator is present.
- `backend_server/src/routes/server_host_session_routes.py` — CORS preflight + after_request hook so the host-session cookie can be minted cross-origin.
- vpt-windows native `.env`: `DEVICE1_HOST_VNC_STREAM_PATH=/host/vpt-windows/vnc_lite.html`.
