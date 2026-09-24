# BUG-0107 — Any device console was a remote desktop for the open internet, and the VNC password rode in the URL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0107                                                                     |
| Reported  | 2026-09-15 (noticed from a shared preview URL containing `?password=`)        |
| Status    | FIXED — network gate (2026-09-15) + application auth gate (2026-09-16, **regressed off the proxy and re-deployed 2026-09-20** — see Step 4) |
| Severity  | **Critical** — unauthenticated remote desktop on every VNC host               |
| Area      | `proxy` nginx (`snippets/vpt-app-locations.conf` locations), `controller_manager.py`, `build_url_utils.py` |
| Fixed in  | build 9151                                                                   |

| Commit    | this commit                                                                  |

---

> **Redacted for publication.** This report is published at `/docs/bugs` and ships in customer bundles. The credential values, the reproduction URL and the current state of the affected hosts have been removed: they are an attack recipe, not an engineering record. The full account is in this repository's history and in the internal task notes.

## Symptom

A device preview URL looked like this, with the VNC password in plain sight:

```
https://<deployment>/host/<host-name>/vnc_lite.html?password=<the-default>
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

That is a live VNC server greeting an anonymous caller. Five hosts answered.

**2. Removing the query parameter would have fixed nothing.** The `vnc_lite.html` the hosts
actually serve (`/usr/share/novnc/vnc_lite.html`, from `websockify --web /usr/share/novnc`)
hardcodes the fallback:

```js
const password = readQueryVariable('password', '<hardcoded default>');
```

So the page auto-submits the default whether or not the URL carries one. The repo's own
`backend_host/config/services/*/vnc.lite.example` had already been corrected to
`readQueryVariable('password', null)` — the deployed hosts were running a stale copy.

**3. The password was the only barrier, and it was the documented default.** RFB offered
`VeNCrypt, VNC Auth`, so a credential *was* required — and `vncpasswd -f` is deterministic,
so hashing the shipped default and comparing against each host's `.vnc/passwd` confirmed
(not guessed) that all five still used it.

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

**Password out of the URL.** `HOST_VNC_STREAM_PATH` on two hosts carried the password as a
query parameter; both are now `/vnc_lite.html` (single-line edit, `.env` backed up).
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

## Step 4 — the gate was not live on the proxy (regression found 2026-09-20)

Step 2 and Step 3 above are accurate about what was built and what was deployed on
2026-09-16. They are wrong about what was still running four days later.

On 2026-09-20 the live `sites-enabled/virtualpytest` contained **no `auth_request` anywhere**.
The only thing gating a VNC console was Step 1's `if ($vnc_denied) { return 403; }`; the four
shadow locations Step 2 added, and the generalization Step 3 made, were simply absent from the
file. The application half had never broken — `/server/host-session/authorize` answered
correctly, the signing secret resolved via the `FLASK_SECRET_KEY` fallback, and the live
frontend bundle still called `ensureHostSession` — so every check that looks at the *code*
said the gate was fine. Only nginx had lost it.

**How it went unnoticed.** With the cookie gate gone the allowlist was doing all the work, and
the allowlist admits exactly two egress IPs plus the LAN. From an allowlisted network nothing
looked wrong; from anywhere else every console answered a bare nginx `403` with no explanation.
That reads as "the host is broken", not "you are not allowed" — it was first reported as a
*random* 403, random being the operator moving between networks. The status table in this very
report said the gate shipped, which made the nginx config the last place anyone looked.

**Why the file could lose it.** `sites-enabled/virtualpytest` is a **regular file** of mode
`-rw-rw-rw-`, not a symlink to `sites-available` like its neighbours, and it carries a crowd of
`.bak`/`.backup-<date>` siblings. Any restore-from-backup silently reverts the vhost to whatever
gate that copy predates, and nothing fails loudly when it does. Worth fixing independently of
this bug: make it a root-owned symlink and keep backups out of `sites-enabled/`.

**Re-deployed at server level, not as shadow locations.** Both `virtualpytest` and
`virtualpytest-demo` now carry one directive and one internal location:

```nginx
auth_request /__vnc_authz;

location = /__vnc_authz {
    internal;
    proxy_pass http://backend_server/server/host-session/authorize;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header Host $host;          # the Step 2 gotcha above — still required
}
```

Server level is correct here rather than lazy: `authorize` reads `X-Original-URI` and decides
for itself whether a path is gated, returning `200` for everything that is not. That is exactly
why the endpoint takes the URI as a header. The payoff is that the gate no longer lives in
`snippets/vpt-app-locations.conf` at all, so a snippet redeploy cannot remove it the way
something removed the Step 2 wiring. The cost is one subrequest per request on non-gated
traffic, which matters most for HLS segment fetches and should be watched.

The `$vnc_client_allowed` / `$vnc_denied` maps are deliberately left in the file, now
unreferenced: restoring the single `if ($vnc_denied) { return 403; }` line reverts to the IP
allowlist in one edit.

**Verified 2026-09-20 from an egress IP that is _not_ in `$vnc_client_allowed`** — i.e. the
case that was previously a flat `403`:

| Request | Before | After |
|---|---|---|
| `/host/host-clone-1/vnc_lite.html`, no session | `403` | **`401`** |
| `/host/host-clone-2/websockify`, no session | `403` | **`401`** |
| `/host/host-clone-1/core/rfb.js`, no session | `403` | **`401`** |
| same, with service `X-API-Key` | `403` | **`200`** |
| `/` and `/assets/*` | `200` | `200` |
| `virtualpytest-demo`, same three | — | `401` / `200` / `200` |

**Two deploy hazards worth recording**, both of which cost a cycle here:

- A backup written to `sites-enabled/virtualpytest.bak-*` is picked up by the `sites-enabled/*`
  glob and loaded as a second copy of the vhost — `nginx: [emerg] duplicate upstream
  "rpitest_origin"`. Backups belong anywhere but that directory.
- In a plain `root` shell on the proxy, `/usr/sbin` is not on `PATH`, so a bare `nginx -t`
  exits `127 command not found`. Chained behind `&&` that reads as a failed config test and
  triggers a rollback of a change that was never actually tested. Use `/usr/sbin/nginx -t`
  (`sudo` works because its `secure_path` includes `/usr/sbin`).

## Follow-ups

- ~~**Roaming operators still need the IP allowlist for now.**~~ Resolved by Step 4: the
  allowlist is no longer referenced, so a roaming operator needs only to be signed in. Adding an
  egress IP to `$vnc_client_allowed` now has no effect unless the `if ($vnc_denied)` line is
  restored with it.
- **The IP allowlist is no longer a second gate.** Step 2 described it as defense in depth
  underneath the cookie; Step 4 removed it from the request path rather than loosening it,
  because it had spent four days being the *only* gate and was refusing legitimate operators.
  The cookie gate now carries this alone — which was always the design, but it is now load
  bearing with nothing under it.
- **The second environment (node 3) has no gate at all.** `virtualpytest.qualiai.io` serves the
  same `/host/<name>/...` surface from a different proxy, and on 2026-09-20
  `/host/host-clone-2/vnc_lite.html` answered **`200` with no credential of any kind** — five
  hosts, including the Android emulators. This is the deployment-template gap
  [STREAM_ACCESS_GATE.md](../security/STREAM_ACCESS_GATE.md) already warns about, observed live.
  It needs its own bug id and cannot simply be copied across: QualiAi embeds those streams with
  a bare `<iframe src=…>` and never mints a host session, so enabling the gate there breaks its
  Devices page until QualiAi either mints a cookie or proxies the stream server-side with the
  service key it already holds.
- Credential rotation and redeploying the corrected `vnc.lite.example` are tracked in the
  internal task notes.
- `Access-Control-Allow-Origin: *` on the websockify block is now moot for outsiders, but
  should still be narrowed.
