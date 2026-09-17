# BUG-0107 — Any device console was a remote desktop for the open internet, and the VNC password rode in the URL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0107                                                                     |
| Reported  | 2026-09-15 (noticed from a shared preview URL containing `?password=`)        |
| Status    | FIXED — network gate (2026-09-15) + application auth gate (2026-09-16)       |
| Severity  | **Critical** — unauthenticated remote desktop on every VNC host               |
| Area      | `proxy` nginx (`snippets/vpt-app-locations.conf` locations), `controller_manager.py`, `build_url_utils.py` |
| Fixed in  | build 9151                                                                   |

| Commit    | this commit                                                                  |

---

## Symptom

A device preview URL looked like this, with the VNC password in plain sight:

```
https://virtualpytest.angelstreet.io/host/host-clone-1/vnc_lite.html?password=admin1234
```

The password in the address bar is what got noticed. It was the least of it.

## Cause

Three separate things, each harmless-looking on its own.

**1. Nothing authenticated the VNC paths.** `/host/<name>/vnc_lite.html`, its noVNC static
assets and `/host/<name>/websockify` were proxied straight through with no session check of
any kind. A WebSocket upgrade from an ordinary internet host answered:

```
HTTP/1.1 101 Switching Protocols
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
Access-Control-Allow-Origin: *

<0x..>RFB 003.008
```

That is a live VNC server greeting an anonymous caller. Five hosts answered:
`host-clone-1`, `labox-web`, `labox-dongle`, `labox-mobile`, `labox-tablet`.

**2. Removing the query parameter would have fixed nothing.** The `vnc_lite.html` the hosts
actually serve (`/usr/share/novnc/vnc_lite.html`, from `websockify --web /usr/share/novnc`)
hardcodes the fallback:

```js
const password = readQueryVariable('password', 'admin1234');
```

So the page auto-submits the default whether or not the URL carries one. The repo's own
`backend_host/config/services/*/vnc.lite.example` had already been corrected to
`readQueryVariable('password', null)` — the deployed hosts were running a stale copy.

**3. The password was the only barrier, and it was the documented default.** RFB offered
`VeNCrypt, VNC Auth`, so a credential *was* required — and `vncpasswd -f` is deterministic,
so hashing `admin1234` and comparing against each host's `.vnc/passwd` confirmed (not
guessed) that all five still used it. It is printed in this repo's own docs.

Taken together: anyone who guessed a host name got a desktop. `Access-Control-Allow-Origin: *`
plus websockify's missing origin check means any web page an operator visited could script
those desktops silently — browsers do not apply CORS to WebSockets.

### The trap in the fix

The obvious fix — `allow <operator IP>; deny all;` — **would have blocked everyone**. There
is no `real_ip_header` anywhere in the proxy config, so `$remote_addr` is the *Cloudflare edge
IP*, not the client. Worse, adding `real_ip_header` globally would have made the existing
`snippets/cloudflare-only.conf` (`allow <CF ranges>; deny all;`) reject **every** request to
every `angelstreet.io` site, because real client IPs are not in the CF ranges.

## Fix

**Gate (proxy).** The client is read from `CF-Connecting-IP` instead, which cannot be forged
here precisely because `cloudflare-only.conf` already restricts `$remote_addr` to the CF
ranges plus the LAN — only Cloudflare can set it. Implemented as three `map`s plus one
server-level `if ($vnc_denied) { return 403; }` in each VPT server block, so the root-owned
`snippets/vpt-app-locations.conf` needed no edit at all:

```nginx
map $uri $vnc_is_gated_path {
    default 0;
    "~^/host/[^/]+/(vnc_lite\.html|websockify|vnc/|core/|vendor/|include/|app/|utils/)" 1;
}
map $http_cf_connecting_ip $vnc_client_allowed {
    default 0;
    ""      1;   # not via Cloudflare = LAN, already vetted by cloudflare-only.conf
    "<operator egress>" 1;
}
map "$vnc_is_gated_path:$vnc_client_allowed" $vnc_denied { default 0; "1:0" 1; }
```

**Password out of the URL.** `HOST_VNC_STREAM_PATH` on `host-clone-1` and `labox-web` carried
`?password=admin1234`; both are now `/vnc_lite.html` (single-line edit, `.env` backed up).
The two code paths that rebuilt it are gone: `controller_manager.py` no longer appends the
password when auto-constructing the path, and `build_url_utils.py` no longer appends it in
direct mode. The console still connects because the page supplies the credential itself.

A credential in a query string is not merely visible — it lands in browser history, in the
`Referer` of every sub-request the page makes, and in the access logs of every proxy it
crosses, including Cloudflare's.

`infra/proxy/nginx/config/production-https.conf` carries the same gate (as a `geo` allowlist
on `$remote_addr`, with the `real_ip` caveat documented) so a fresh install is not born open.

## Verification

From an external host outside the allowlist, before → after, on both `virtualpytest` and
`virtualpytest-demo`:

| Path                                  | Before | After |
|---------------------------------------|--------|-------|
| `/host/<h>/websockify` (WS upgrade)    | `101` + RFB | `403` |
| `/host/<h>/vnc_lite.html`              | `200`  | `403` |
| `/host/<h>/core/rfb.js`                | `200`  | `403` |

Unaffected, confirmed after the reload: both app roots `200`, `rpitest` `200`,
`kozy.angelstreet.io` `302`, and `/host/<h>/stream/...` still `308` (streams are deliberately
outside the gate). An allowlisted client still gets `200` / `101`.

## Not a finding (recorded so it is not re-investigated)

`rpitest.angelstreet.io` first looked identically exposed — `curl` reported `101` for *any*
host name, including invented ones. It is a **false positive**: no valid WebSocket handshake
and no RFB bytes come back, and its real host route answers
`401 {"error":"Authentication required","message":"X-API-Key header is required"}`. That
deployment does not transit the proxy at all (a `cloudflared` tunnel on the Pi serves it
directly), so it never had this hole. **A `101` status alone does not prove exposure — the RFB
payload does.**

## Step 2 — application auth gate (shipped 2026-09-16)

The allowlist alone does not survive going public: it is a static list of known egress IPs,
and a real customer has no fixed IP to enumerate. Widening it to let public customers through
would mean widening it to `allow all`, which is the same open-desktop hole this bug fixed.

Deliberately **not** a reuse of the existing `vpt_jwt` navigation cookie (`installFetchAuth.ts`):
that cookie is written via `document.cookie` by page JS, so it cannot be `HttpOnly`, and it is
a general-purpose credential (everything the user's role can do, for up to an hour). Gating a
live remote-desktop socket with it would mean any XSS that reads it also gets full device
control. Instead:

- `POST /server/vnc/session` (`backend_server/src/routes/server_vnc_routes.py`) — requires the
  normal Supabase user JWT, checks the host exists, and mints a narrow HS256 token
  (`{host, sub, exp}`, 10 min TTL, signed with `SUPABASE_JWT_SECRET`) as a real `Set-Cookie`
  (`vpt_vnc`, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/host/<name>/`) — unreadable by
  page JS, unlike `vpt_jwt`.
- `GET /server/vnc/authorize` — the `auth_request` target, called by nginx once per request
  under a gated VNC path. Carries no user JWT (an iframe navigation can't attach one); it
  decides which paths are gated at all, reads `X-Original-URI`, and validates the `vpt_vnc`
  cookie's signature/expiry/host-match. 2xx = allow, 401/403 = deny.
- Frontend (`buildUrlUtils.ts: ensureVncSession`, called from `RecStreamContainer.tsx` and
  `RecHostPreview.tsx`) awaits the mint call before ever giving the VNC iframe a `src` — the
  cookie must exist before the browser navigates, or `auth_request` rejects the navigation.
- nginx: one internal `location = /server/vnc/authorize` plus `auth_request` added to 4
  locations shadowing `snippets/vpt-app-locations.conf` (root-owned, same trick already used
  above for the phone Socket.IO path) in both `virtualpytest` and `virtualpytest-demo`. The
  IP allowlist stays underneath as defense in depth; it will need loosening separately when
  public customers with arbitrary IPs are onboarded — the cookie gate is what carries that.

**Gotcha hit during rollout:** the internal `auth_request` location did not set
`proxy_set_header Host $host;`. nginx's default `Host` for a `proxy_pass http://backend_server/...`
is the **upstream block's name itself** ("backend_server"), not the real hostname — which
tripped the app's own host-trust check (`400 Host 'backend_server' is not trusted.`) and
surfaced to clients as `auth request unexpected status: 400` → nginx 500. Any new
`auth_request` internal location needs an explicit `Host` header; nothing else in this file
needed one because every other location already proxies to a `$backend_host_ip`/named upstream
with `proxy_set_header Host $host;` copied in from day one.

**Verified 2026-09-16:** `/host/host-clone-1/vnc_lite.html` with no cookie → `401` on both
`virtualpytest` and `virtualpytest-demo` (previously `200`/allowed for any allowlisted IP,
which by definition includes every real operator). Unaffected: app root `200`,
`heartclaws.angelstreet.io` `200`.

## Step 3 — generalized to HLS streams and the phone link (2026-09-16)

The same question came up for the live/archive video feed: an IP allowlist can't survive going
public, and the reasoning that justified Step 2 for VNC applies identically to
`/host/<name>/stream/...` and the phone Socket.IO link. Rather than a VNC-specific fix,
`server_vnc_routes.py` → `server_host_session_routes.py`, one cookie now gates all three.
Full design, the deployment-template gap this surfaced (five of six shipped nginx templates
had **no** VNC protection at all, let alone the stream gate), and how to verify it:
[docs/security/STREAM_ACCESS_GATE.md](../security/STREAM_ACCESS_GATE.md).

## Follow-ups

- **Roaming operators still need the IP allowlist for now.** Any new egress IP must be added
  to the `$vnc_client_allowed` map on the proxy — Step 2 adds a second, independent gate, it
  does not yet remove the first one.
- **Loosen or remove the IP allowlist when onboarding public customers.** It cannot be widened
  to arbitrary customer IPs without becoming `allow all`; the cookie gate is designed to carry
  that weight alone once it does.
- **`admin1234` is unchanged on all five hosts**, by explicit decision — it is gated now, but
  it is still the published default and still hardcoded in the stale page each host serves.
  Rotating it and deploying the corrected `vnc.lite.example` remains outstanding
  (TASK-14 item A6).
- `Access-Control-Allow-Origin: *` on the websockify block is now moot for outsiders, but
  should still be narrowed.
