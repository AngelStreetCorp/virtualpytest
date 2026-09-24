# BUG-0143 — The stream access gate locked the mobile app out of every stream

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                            |
|-----------|----------------------------------------------------------------------------------|
| ID        | BUG-0143                                                                         |
| Reported  | 2026-09-17                                                                       |
| Status    | Fixed (committed; needs a server + host + frontend deploy and an APK rebuild)     |
| Severity  | High (no video anywhere in the mobile app — every live and archive stream blank)  |
| Area      | `backend_server/src/routes/server_host_session_routes.py`, `backend_host/src/routes/host_stream_routes.py`, `frontend/src/components/common/HLSVideoPlayer.tsx` |
| Fixed in  | Unreleased                                                                       |
| Commit    | `7028cf2438`                                                                     |

---

## Symptom

After the host-session gate shipped ([BUG-0107](BUG-0107-2026-09-15-vnc-console-and-websockify-open-to-the-internet.md)
step 2, `94cba88862`), the mobile app showed no stream on any screen — Rec, the device grid, the
stream modal, fullscreen. The web frontend on the deployment's own domain was unaffected, which
is why the gate shipped looking healthy.

The app was not failing to *ask* for access. It minted a session successfully and then 401'd on
everything:

```
POST /server/host-session/session   -> 200  {"success":true,"expires_in":600}
GET  /host/<name>/stream/output.m3u8 -> 401  (nginx auth_request)
```

## Root cause

Three faults, all of them invisible from a browser sitting on the deployment's own domain, and
all of them reachable only from a **cross-site** client. The mobile app is exactly that: a
Capacitor shell that serves the bundled frontend from its own fixed origin, `https://localhost`
(which is why that origin is already in `DEFAULT_CORS_ALLOWED_ORIGINS`). Every call the APK makes
to a deployment is cross-origin *and* cross-site.

**1. The cookie could not cross a site boundary.** It was minted `SameSite=Strict`. A Strict (or
Lax) cookie is neither stored nor replayed in a cross-site context, so the 200 from the mint was
real but the cookie never came back on a single stream request. Only `SameSite=None; Secure` may
cross sites at all.

**2. Nothing asked the browser to send it.** hls.js defaults `withCredentials` to `false`, and the
`<video>` element carried `crossOrigin="anonymous"` — which means "CORS, no credentials" outright.
On the web this is invisible: the stream is same-origin with the page, so the cookie rides along
by default. Cross-origin, it is omitted. So even with fault 1 fixed, the APK would have held a
valid cookie and never presented it.

**3. The stream path answered with a wildcard.** `host_stream_routes.py`'s `after_request` set
`Access-Control-Allow-Origin: *`. A credentialed request rejects a wildcard allow-origin outright
— the browser discards the response whatever the status, including a perfectly good 200. So even
with faults 1 and 2 fixed, every segment would still have been thrown away.

Each fault alone is enough to blank the video, which is why this reads as "the gate broke
streaming" rather than as three separate defects.

## Fix

| # | Change |
|---|---|
| 1 | Mint the cookie `SameSite=None` (it was already `Secure`, which `None` requires). |
| 2 | `HLSVideoPlayer` sets `xhrSetup: xhr.withCredentials = true` and `crossOrigin="use-credentials"` — but **only** for URLs `isGatedHostPath()` matches, so ungated public assets keep their uncredentialed wildcard fetch. |
| 3 | The stream blueprint echoes the caller's `Origin` and adds `Access-Control-Allow-Credentials: true` **when that origin is on the allowlist**, with `Vary: Origin`; it still answers `*` to a caller that sends no origin or an unlisted one, so uncredentialed public consumers are unchanged. |

`_cors_allowed_origins()` in `shared/src/lib/utils/app_utils.py` gained a cross-module consumer and
so is now public, `cors_allowed_origins()`.

### Why `SameSite=None` is not a step backwards here

The attribute defends against CSRF, which needs a state-changing request. There is none behind
this gate: it authorizes `GET`s of one host's media and nothing else. The cookie stays HttpOnly,
stays scoped to a single host's path, and still expires in 10 minutes. A hostile page can make a
browser *send* it, but cannot *read* the response — the origin allowlist still applies, and fix 3
deliberately withholds the credentialed echo from any origin not on it.

## Gate

`tests/backend_server/test_host_session.py` gained two tests that assert the cross-site client's
two requirements. Against the live, unfixed deployment they fail with exactly the two faults:

```
FAILED test_minted_cookie_can_cross_sites
  - samesite=none not in 'vpt_host_session=...; Secure; HttpOnly; Path=/host/host-clone-1/; SameSite=Strict'
FAILED test_gated_stream_answers_a_cross_origin_caller_without_a_wildcard
  - https://localhost  +  *
7 passed (the pre-existing gate coverage is unaffected)
```

The first asserts on the raw `Set-Cookie` header, not the parsed jar: `requests` keeps a Strict
cookie quite happily, so a jar-level check passes while a real WebView drops it.

Locally, against the fixed blueprint:

| Caller's `Origin` | `Access-Control-Allow-Origin` | `Allow-Credentials` |
|---|---|---|
| `https://localhost` (the app) | `https://localhost` | `true` |
| `https://evil.example.com` | `*` | *(absent)* |
| *(none sent)* | `*` | *(absent)* |

## The fullscreen page had never minted at all

Found while fixing the above, and fixed with it. `FullscreenPlayer.tsx` (the "watch in best
quality" tab) runs its own hls.js instance and never called `useHostSession` — it was not part of
the "one sink every stream path converges on" claim, because it does not use `HLSVideoPlayer`. It
worked on the web only by accident: the tab that opened it had usually already minted a cookie for
that host, and `Path=/host/<name>/` means the new tab inherits it. Open that URL in a fresh
session, or let the 10-minute TTL lapse on a page designed to be left running, and it 401s. In the
app it could never work at all. It now mints its own session, re-mints while it runs, and sends
credentials on a gated URL.

## Fault 4, found only after deploying: the proxy overwrote the fix

The three fixes above deployed and the app was still blank. The backend host was answering
correctly — verified directly on its own port, bypassing the proxy:

```
$ curl -i -H 'Origin: https://localhost' http://<host>:6109/stream/capture1/hot/segments/output.m3u8
Access-Control-Allow-Origin: https://localhost
Access-Control-Allow-Credentials: true
Vary: Origin
```

…and the public URL answered `Access-Control-Allow-Origin: *` for the same request. The live
proxy config had, in each of the four `/host/<name>/stream/` locations:

```nginx
proxy_hide_header Access-Control-Allow-Origin;
add_header Access-Control-Allow-Origin "*" always;
```

It was added for a real reason — BUG-0101, where a 404/502 with no CORS header made a missing
manifest on one device look like a site-wide CORS fault. But `proxy_hide_header` means **no
app-side CORS fix can ever reach a browser**: the app decides, and nginx overwrites the decision.
The `Vary: Origin` and `Allow-Credentials` from fault 3's fix were arriving intact — only the
allow-origin was being replaced — which is what made it look like the app had not been deployed.

Fixed by dropping those lines from the four stream locations so the upstream header passes
through, leaving the VNC and websockify locations untouched (an iframe and a websocket, neither
a credentialed XHR). The app sets CORS headers on its own error responses, which is what BUG-0101
actually needed, so only nginx-generated responses — the gate's own 401, or a 502 with the host
down — now reach a cross-origin caller without one.

**The repo template never had this.** `infra/proxy/nginx/config/production-https.conf` and the
live `/etc/nginx/sites-enabled/virtualpytest` had drifted; the wildcard existed only in live. The
template now carries a comment saying not to add it, since that is the only way this is caught
next time.

## Verified live after the proxy fix

| Check | Result |
|---|---|
| Manifest, cross-origin + cookie | `200`, `Access-Control-Allow-Origin: https://localhost`, `Allow-Credentials: true` |
| Segment, cross-origin + cookie | `200`, 27,636 B, same headers |
| Same URL, no cookie | `401` — the gate still denies anonymous |
| `tests/backend_server/test_host_session.py` | 9 passed against the deployed server |

## Still to do

Deploying the three services and rebuilding the APK is what actually closes this for the app —
the fix is committed, not yet live.

An expired or missing session still surfaces in the WebView as an opaque CORS failure rather than
a 401, because nginx generates the `auth_request` denial itself and attaches no CORS headers to
it. That costs diagnosability, not function: `useHostSession` re-mints every 4 minutes against a
10-minute TTL, so a 401 should not occur in steady state. Adding CORS headers to the gate's own
401 needs an `error_page` block in `infra/proxy/nginx/config/production-https.conf` and a proxy
deploy to verify; it was deliberately left out of this change rather than shipped untested.
