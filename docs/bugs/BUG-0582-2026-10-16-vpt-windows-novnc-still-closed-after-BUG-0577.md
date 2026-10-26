# BUG-0582: vpt-windows noVNC still closed after BUG-0577 (nginx + noVNC + TightVNC security)

**Date:** 2026-10-16
**Discovered on:** vpt-windows (joach's Windows PC, French locale, `desktop-uni4mdl`)
**Severity:** high — the BUG-0577 fix unblocked the CORS preflight and made the cookie mint succeed, but the iframe still 401s the vnc_lite.html and the noVNC client can never reach the desktop.
**Status:** fixed (commit pending)

## What BUG-0577 already did

The earlier fix (commits `8babfd82c`, `d0fd16325`, `8616abc68`) took care of the CORS preflight, the device-stream URL picking, and the dropdown bucketing. After deploy, the vpt-windows tile renders correctly in the device grid and `cookieStore` no longer complains about CORS — the cookie IS being stored, and the vnc_lite.html request from the iframe carries it. So we move on to the next layer of the problem.

## What was still broken after BUG-0577

The iframe still says `401 Authorization Required` on the very first navigation, and even when the vnc_lite.html loads (e.g. in a fresh tab with the cookie), noVNC immediately shows `Something went wrong, connection is closed` (code 1005).

### Layer 1 — nginx on pi4: `/host/vpt-windows/` was missing `auth_request` and routed to the wrong upstream

When the dashboard iframe hits `https://<host-server>/host/vpt-windows/vnc_lite.html`, nginx on pi4 matches the existing vpt-windows block:

```
location /host/vpt-windows/ {
    rewrite ^/host/vpt-windows/(.*)$ /host/$1 break;
    proxy_pass http://192.168.x.70:6109;
    ...
}
```

Two problems:

1. **No `auth_request`.** vpt-pi4's own block and vpt-lenovo1's block both have `auth_request /server/host-session/authorize;`, but vpt-windows's didn't (it was added in 2026-10-11 as a copy-paste of vpt-nipogi's "everything proxies to the host API" block). Without `auth_request`, the cookie never gates anything — but since the request DOES get a valid cookie from the iframe, this isn't a 401 by itself.
2. **Proxies to 6109 (vpt-host) instead of 6080 (vpt-websockify).** vpt-windows serves the noVNC assets from `vpt-websockify` (the python WebSockify instance on port 6080 that proxies to tvnserver on 5900), exactly like vpt-lenovo1. vpt-host on 6109 only serves the JSON API — it has no static noVNC HTML, so the `vnc_lite.html` request 401s (X-API-Key required) and the noVNC WebSocket is never reachable. vpt-lenovo1 already has the right two-block pattern (a regex that matches the gated noVNC paths and proxies to 6080, plus a prefix block for the rest of the host API at 6109) — vpt-windows was missing the regex block entirely.

The fix is on pi4 at `/etc/nginx/sites-enabled/rpitest.conf` lines 45-67: add the vpt-pi4/vpt-lenovo1-style regex block for the gated noVNC paths, keep the prefix block unchanged. After the patch, nginx -t and `systemctl reload nginx` are both clean.

### Layer 2 — vpt-windows's noVNC client constructs the wrong WebSocket URL

The official noVNC `vnc_lite.html` builds the WebSocket URL as:

```js
const path = readQueryVariable('path', 'websockify');
url += '://' + host;
url += '/' + path;        // → wss://<host-server>/websockify
```

That's the vpt-pi4 / vpt-lenovo1 default — and it doesn't match any nginx location, so the request falls through to the `/` catch-all, which proxies to vpt-server (5109). Cloudflare returns `101 Switching Protocols` at the edge (it always does for Upgrade requests), but no actual VNC data flows, the WebSocket closes after a couple of bytes, and noVNC reports `code: 1005`.

The vpt-pi4 installation has a *different* `vnc_lite.html` — a patched one with `getDefaultWebsockifyPath()`:

```js
const pathname = window.location.pathname;
let dir = pathname.substring(0, pathname.lastIndexOf('/'));  // /host/vpt-pi4
if (dir.endsWith('/vnc')) dir = dir.substring(0, dir.length - 4);
return dir + '/websockify';                                  // /host/vpt-pi4/websockify
```

That returns the path relative to the iframe's own URL. The vpt-windows noVNC on `C:\virtualpytest\novnc\` was the unpatched upstream version, so it built `/websockify` instead of `/host/vpt-windows/websockify`.

The fix: copy `getDefaultWebsockifyPath()` (and the `if (dir.endsWith('/vnc'))` strip) into vpt-windows's `C:\virtualpytest\novnc\vnc_lite.html`. After the patch the WebSocket URL is `wss://<host-server>/host/vpt-windows/websockify`, which matches the new nginx block.

### Layer 3 — TightVNC 2.x advertises [None, Tight] but rejects None

Once the WebSocket reaches the right place, the VNC handshake still fails. The noVNC client reads the server's security-types list `[0x01 (None), 0x10 (Tight)]` and picks `None` (security type 1) — the noVNC's default preference. tvnserver on vpt-windows then closes the WebSocket without sending a SecurityResult. Confirmed in raw bytes:

```
noVNC  →  ws  :  RFB 003.008\n
server →  ws  :  RFB 003.008\n
server →  ws  :  0x02 (2 security types)
server →  ws  :  0x01 0x10 (None, Tight)
noVNC  →  ws  :  0x01 (chooses None)
(server closes — no SecurityResult)
```

If the client instead sends `0x10` (Tight), the server replies with the standard SecurityResult `00 00 00 00` and the VNC session proceeds normally:

```
noVNC  →  ws  :  0x10 (chooses Tight)
server →  ws  :  00 00 00 00 (SecurityResult: OK)
server →  ws  :  ServerInit (desktop name, framebuffer geometry, …)
```

The `UseVncAuthentication = 0` registry key (already set on vpt-windows) only disables the VNC *password* check — it does not make TightVNC 2.x actually accept a None-authenticated client. The server's security-types list is a default that doesn't reflect what the server will actually honor at the protocol level.

The fix: edit `C:\virtualpytest\novnc\core\rfb.js` `_negotiateSecurity` to iterate the client's *preferred* order (with Tight first, None later as a fallback) instead of the server's offered order. Concretely:

```js
_preferredSecurityTypes() {
    // TightVNC 2.x reports [None, Tight] but rejects None at the
    // protocol level, so prefer Tight when both are offered. Fall back
    // to None for servers that genuinely accept it.
    return [securityTypeTight, securityTypeVNCAuth, securityTypeNone, ...];
}

_negotiateSecurity() {
    ...
    this._rfbAuthScheme = -1;
    for (let type of this._preferredSecurityTypes()) {
        if (types.includes(type)) { this._rfbAuthScheme = type; break; }
    }
    if (this._rfbAuthScheme === -1) {
        // fall back to the server's order
        for (let type of types) {
            if (this._isSupportedSecurityType(type)) { this._rfbAuthScheme = type; break; }
        }
    }
    ...
}
```

After the patch, the vpt-windows noVNC negotiates Tight and the iframe renders the desktop. (Verified: `Connected to desktop-uni4mdl` with a live canvas, side by side with the vpt-pi4 tile which also shows `Connected to vpt-pi4:1 (vpt_user)`.)

## Cache-bust

The browser caches `vnc_lite.html` and the noVNC core/* modules with `max-age=14400` (4 h). When iterating on the rfb.js fix in the same session, the browser kept re-serving the old copy. Appending `?v=20261016b` to the rfb.js imports in `vnc_lite.html` is enough to force a re-fetch and see the new behaviour. Long-term this should be a content-hashed asset URL generated by the build, but for a hand-installed Windows noVNC the query-string version stamp is the lowest-friction fix.

## Files touched

- **pi4**: `/etc/nginx/sites-enabled/rpitest.conf` — added the vpt-windows noVNC regex block (lines 45-67), keeps the prefix block (proxy to 6109) for everything else under `/host/vpt-windows/`. `nginx -t` clean, `systemctl reload nginx` clean.
- **vpt-windows**: `C:\virtualpytest\novnc\vnc_lite.html` — added `getDefaultWebsockifyPath()` and a `?v=20261016b` cache-bust on the `./core/rfb.js` import.
- **vpt-windows**: `C:\virtualpytest\novnc\core\rfb.js` — added `_preferredSecurityTypes()` and the corresponding loop in `_negotiateSecurity` to prefer Tight. All 27 transitive imports inside rfb.js also got `?v=20261016b` so the cache-bust is transitive.

## Lessons

- The vpt-pi4 nginx pattern (a regex block for the gated noVNC paths + a prefix block for the rest of the host API) is the correct template for any new host on the LAN. The vpt-windows block added 2026-10-11 was missing the regex block — that was a one-off mistake, not a template mismatch. New hosts added later should follow vpt-pi4 / vpt-lenovo1 verbatim.
- The official noVNC `vnc_lite.html` default URL is broken for any path-based nginx setup. The `getDefaultWebsockifyPath()` patch from vpt-pi4 should be upstreamed so vpt-windows can use the unpatched upstream release. Until then, the Windows install needs the patched file checked in next to `C:\virtualpytest\novnc\`.
- TightVNC 2.x's security-types list advertises `None` but does not honor it. This will bite every Windows host using TightVNC. The rfb.js patch could be upstreamed too, but it's a one-line change for a very specific case; documenting here is enough.
- `max-age=14400` on noVNC assets + Cloudflare's own caching is a nasty combination for iterative debugging. A `?v=<date>` cache-bust on the imports is a quick way out; the durable answer is a content-hashed asset URL.
