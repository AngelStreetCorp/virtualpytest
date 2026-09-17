# Stream / VNC access gate

> Bug history: [BUG-0107](../bugs/BUG-0107-2026-09-15-vnc-console-and-websockify-open-to-the-internet.md)

What protects a device's live desktop (VNC) and live/archive video (HLS) from anyone who
can guess or leak a `/host/<name>/...` URL, why it needs two independent layers, and what
happens if either one is removed. Read this **before** editing any nginx config that touches
a `/host/<name>/` location, and before generating a customer package from one of the
templates in `infra/proxy/nginx/config/`.

## What's gated

Every proxied path under `/host/<name>/` that serves live device state to a browser:

| Path pattern | What it is |
|---|---|
| `vnc_lite.html`, `websockify`, `vnc/`, `core\|vendor\|include\|app\|utils/` | The noVNC console + its websocket |
| `stream/(.+)` | Live and archive HLS (manifest + segments), plus `stream/<device>/hot/running.log` |

`/host/<name>/api/` and the rest of `/host/<name>/` are **not** gated by this mechanism — those
are the host's own Flask API, protected separately (`X-API-Key`, per
`docs/agent/platform/SERVER_AUTH.md`).

**`phone/socket.io/(.*)` (the paired-phone live control channel, TASK-17) was briefly added here
2026-09-16 and removed the same day (TASK-19)**: its client is the native phone_agent Android
app, which holds neither the `vpt_host_session` cookie (no browser session) nor the service
`X-API-Key` (never shipped in a public APK) — only its own one-time pairing token or rotating
device_secret, exchanged in the first Socket.IO message *after* the WS upgrade, which
`auth_request` cannot see beforehand. Gating it here 401s every real phone connecting from
outside the host's LAN. See the comment on that location in
`infra/proxy/nginx/config/production-https.conf` and
`backend_server/src/routes/server_host_session_routes.py`'s module docstring. Its protection is
nginx `limit_req` + a hello-attempt lockout in `features/mobile-app/backend_host/bridge.py`
instead — the real per-device check already happens in that `hello` handler.

## Why two layers, not one

**Layer 1 — network allowlist.** A `geo`/`map` on the client IP (`CF-Connecting-IP` behind
Cloudflare, `$remote_addr` otherwise), `return 403` for anyone not on it. Cheap, and it was the
first fix (BUG-0107, 2026-09-15) because it needed no application change at all. It is **not
sufficient alone for a public deployment**: a real customer has no fixed IP to allowlist, and
widening the list to arbitrary IPs is the same "allow all" hole this exists to close. It also
never covered `stream/` or `phone/socket.io/` — only the VNC paths.

**Layer 2 — `auth_request` + a minted cookie.** The layer that actually stops an outsider with
a leaked or guessed URL, independent of network origin — this is what makes the gate work for
a public customer, not just a known set of operator IPs. Added 2026-09-16.

Deliberately **not** a reuse of `vpt_jwt` (the existing navigation cookie from
`installFetchAuth.ts`): that cookie is written via `document.cookie` by page JS, so it can't be
`HttpOnly`, and it's a general-purpose credential — everything the user's role can do, for up
to an hour. Gating a live remote-desktop socket or a device's video feed with it would mean any
XSS that reads it also gets that access.

## How Layer 2 works

```
Frontend (logged in)                    Proxy (nginx)                 Backend server
      |                                       |                             |
      |-- POST /server/host-session/session ->|---------------------------->|
      |   { host_name }                       |   (normal /server/ proxy)   | mint HS256 token
      |                                       |                             | {host, sub, exp}
      |<---------- Set-Cookie: vpt_host_session ------------------------- --|
      |   HttpOnly, Secure, SameSite=Strict,  |                             |
      |   Path=/host/<name>/, 10 min TTL      |                             |
      |                                       |                             |
      |-- GET /host/<name>/stream/.../*.m3u8 ->|                            |
      |   (cookie rides automatically,        |-- auth_request subrequest ->|
      |    Path matches)                      |   GET /server/host-session/ |
      |                                       |       authorize             |
      |                                       |   X-Original-URI: <uri>     | validate cookie
      |                                       |<-- 200 / 401 / 403 ---------|
      |<----------- proxied response ---------|                             |
```

- **Mint**: `POST /server/host-session/session` — requires the normal Supabase user JWT
  (`@require_user_auth`), checks the host exists, signs `{host, sub, iat, exp}` with
  `SUPABASE_JWT_SECRET` (or `HOST_SESSION_SECRET` if set), sets it as a real `Set-Cookie`
  (`vpt_host_session`) scoped to `Path=/host/<name>/` — real `HttpOnly`, unlike `vpt_jwt`,
  because it's set server-side via a response header, not `document.cookie`.
- **Authorize**: `GET /server/host-session/authorize` — the `auth_request` target. Carries no
  user JWT (an iframe/HLS navigation can't attach one). It decides for itself, from
  `X-Original-URI`, whether the path is one it gates at all — so nginx's own location matching
  (duplicated across vhosts/templates) never has to agree with it byte-for-byte. Also accepts
  the shared service `X-API-Key` as an alternative to the cookie, for server-to-server callers
  that fetch these same URLs with no browser session (`screenshot_capture.py`,
  `heatmap_processor.py`).
- **Frontend**: `frontend/src/hooks/useHostSession.ts` mints (and, for HLS, periodically
  re-mints — see below) before a VNC iframe or `HLSVideoPlayer` is given the real URL. Gated at
  the one sink every stream path converges on (`HLSVideoPlayer.tsx` itself), not at each
  producer, so it covers `buildStreamUrl`, the `useStream` hook, and `EnhancedHLSPlayer`'s own
  fallback chain uniformly.

## VNC vs. HLS: why the refresh behavior differs

VNC's `auth_request` check only ever runs **once**, at the initial websocket upgrade — after
that it's a raw TCP tunnel, independent of cookie expiry, same as an SSH session not dropping
because you rotated the key afterward. A 10-minute TTL, minted once, is enough.

HLS is not one persistent connection: the player re-fetches segments for as long as playback
continues, and **every** fetch goes back through `auth_request`. A dashboard left open for 20
minutes would 401 mid-stream once the cookie's TTL elapsed. `useHostSession(url, keepAlive)`
re-mints every 4 minutes (comfortably inside the 10-minute TTL) when `keepAlive: true` — pass
`true` for anything HLS, `false` for VNC (a repeating mint there would be a wasted request).

## The Host-header gotcha (cost a round of debugging, 2026-09-16)

The internal `auth_request` location **must** set `proxy_set_header Host $host;`. Without it,
nginx defaults `Host` to the **upstream block's literal name** (e.g. `backend_server`) for a
bare `proxy_pass http://backend_server/...`, which trips the app's own host-trust check
(`400 Host 'backend_server' is not trusted.`) — and nginx turns any non-200/401/403 subrequest
response into `auth request unexpected status: 400` → a `500` to the real client. If a
customer support case is "VNC/streams suddenly 500 for everyone," check this first.

## Where this lives per deployment

**Production proxy (`proxy` / `.107`, hand-maintained, not in git).** The real VNC/stream
location blocks live in a **root-owned** `snippets/vpt-app-locations.conf`, which `jndoye`
cannot edit. So instead of editing them in place, matching shadow `location` blocks (identical
regex, `auth_request` added) are declared directly in the writable
`/etc/nginx/sites-enabled/virtualpytest`, **before** the `include` line — nginx picks the first
matching regex location in file order, so these win. This is the same trick already used there
for the phone Socket.IO path (pre-existing, TASK-17). Backups before each edit:
`~jndoye/virtualpytest.nginx.bak-<date>-<label>` on the proxy host.

**Packaged templates (`infra/proxy/nginx/config/*.conf`, IS in git, used to generate customer
installs).** These are standalone, single-file server blocks with no root-owned snippet
problem — `auth_request` is added directly to each real location, no shadowing needed.
`production-https.conf` carries the full gate (both layers) on VNC and `stream/`, and
`limit_req` (no `auth_request` — see above) on `phone/socket.io/`. **The other five templates
(`proxmox.https.conf`, `proxmox.local.conf`, `proxmox.local.https.conf`, `docker.conf`,
`local-http.conf`) do not yet have either layer on their VNC locations, and none of the six
had Layer 2 on `stream/` before 2026-09-16.** Check each template's `geo $vnc_client_allowed`
(Layer 1) and `auth_request` lines (Layer 2) are present on every `vnc_lite.html`, `vnc/`,
`websockify`, `core|vendor|include|app|utils/`, and `stream/` location before shipping a package
built from it — **a package built from an unpatched template reintroduces the original BUG-0107
hole from scratch.** Do not add `auth_request` to `phone/socket.io/` — see the exception above.

## Verifying the gate (don't trust a browser tab alone)

A VNC iframe or HLS player, once connected, keeps running independent of cookies, logout, or
even later config changes — a long-open browser tab will look "still working" and prove
nothing. To actually test:

```bash
# No cookie, from an allowlisted IP -> should be 401 (proves Layer 2)
curl -s -o /dev/null -w "%{http_code}\n" 'https://<host>/host/<name>/vnc_lite.html?_fresh=<random>'
curl -s -o /dev/null -w "%{http_code}\n" 'https://<host>/host/<name>/stream/capture/segments/output.m3u8?_fresh=<random>'

# From a genuinely non-allowlisted network (phone on cellular, a VPN exit) -> tests Layer 1
```

Always use a fresh, never-before-used query string — a repeated one may be answered by an
already-open connection or a stale browser cache/back-forward-cache entry, not a new request
that actually went through the gate.

## Rotating/removing the mechanism

- `SUPABASE_JWT_SECRET` compromise also invalidates `vpt_host_session` tokens; a dedicated
  `HOST_SESSION_SECRET` env var (checked first, before falling back to the JWT secret) lets you
  rotate this independently without touching user auth.
- The IP allowlist (Layer 1) can be safely removed once every VNC/stream location also has
  `auth_request` — Layer 2 alone is what's designed to carry public traffic. Don't remove
  Layer 1 on a deployment where any gated location is still missing `auth_request`.
  `phone/socket.io/` is never part of this — it relies on `limit_req` + the `hello` handshake
  instead (see "What's gated" above), independent of whether Layer 1 is removed elsewhere.
