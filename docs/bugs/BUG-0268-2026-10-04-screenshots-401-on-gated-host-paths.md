# BUG-0268 — Screenshots 401 on gated host paths (vpt-pi1, vpt-pi3)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0268                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed — proxy + frontend deployed and verified 2026-10-04    |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `16f33780a`, `0436f415c`, `af1f318e4`                        |

---

## Symptom

Every screenshot in the screen modal for `vpt-pi1` / `vpt-pi3` showed nginx
`401 Authorization Required`, e.g.
`GET https://virtualpytest.angelstreet.io/host/vpt-pi1/stream/capture3/captures/capture_000185452.jpg → 401`.
The same kind of URL on `host-clone-1` loaded.

## Root cause

`/host/<name>/stream/` is behind the proxy's `auth_request` gate, which needs the
`vpt_host_session` cookie (path-scoped to `/host/<name>/`). Only the HLS/VNC players mint that
cookie (`ensureHostSession` in `frontend/src/utils/buildUrlUtils.ts`); a plain `<img>` never
does. A host whose player had minted a cookie on the page's origin (host-clone-1) worked by
accident; the Pis, whose player had not, got 401 on every capture.

The proxy and server side were verified correct: minting via
`POST /server/host-session/session` then fetching the same capture returns 200 for vpt-pi1.

## Fix

`frontend/src/utils/installHostImageSession.ts` (installed from `main.tsx`): a capture-phase
`error` listener mints the session at the image's own origin and reloads a failed gated
`<img>`. The retry guard is per source, not per element: the screen modal reuses one `<img>`
for every screenshot, so a per-element guard left everything after the first cookie expiry
(10 min) broken.

## Verification

With an authenticated session, open the screen modal on vpt-pi1, take a screenshot: it loads
(one 401 then 200 with `_hs=` in the network tab). Leave it open > 10 minutes and take another:
it still loads.

### Verified on the deployed site — 2026-10-04 14:02–14:14 UTC

Live frontend `main-2026.10.04-9755` (commit `fda731faf`, deployed 13:00 UTC) contains both
fix commits. Headless Chromium (Playwright) opened `https://virtualpytest.angelstreet.io/` with
auto-sign, dropped all cookies, then loaded fresh `takeScreenshot` captures into **one reused
`<img>`** (the screen modal's pattern) for each host:

| Host          | Fresh       | Cookies dropped (expiry simulated) | Same page after 11 min (real expiry) |
|---------------|-------------|------------------------------------|--------------------------------------|
| vpt-pi1       | 1280×720 ok | ok                                 | ok                                   |
| vpt-pi3       | 1280×720 ok | ok                                 | ok                                   |
| host-clone-1  | 720×1280 ok | ok                                 | ok                                   |

Every load showed the expected sequence, e.g. after the 11-minute wait:

```
GET  401 /host/vpt-pi3/stream/capture3/captures/verification_source.jpg?t=1791123247898
POST 200 /server/host-session/session
GET  200 /host/vpt-pi3/stream/capture3/captures/verification_source.jpg?t=1791123247898&_hs=1791123248112
```

host-clone-1 now takes the same 401 → mint → 200 path: the cookie is scoped per host, so it
no longer depends on a player having minted one by accident.

The verification above only covered a screenshot shown in an `<img>`. It missed two faults.

## Reopened — 2026-10-04: two more faults (vpt-nipogi, screenshot opened in a new tab)

Reported: `https://virtualpytest.angelstreet.io/host/vpt-nipogi/stream/capture17/captures/capture_000006075.jpg`
still answered 401.

1. **The screenshot button opens the capture in a new tab and never minted the cookie.** The Rec
   modal's screenshot (`useRecCaptureActions`) and the node dialog's "open screenshot" button call
   `window.open(url)`. That is a top-level navigation, not an `<img>`, so
   `installHostImageSession` never sees the 401. Fix: `openHostUrl()` in
   `frontend/src/utils/buildUrlUtils.ts` mints the host session, then opens the tab.
2. **The main proxy had no route to vpt-nipogi.** Hosts registered with the Pi-side server are
   proxied by `virtualpytest.angelstreet.io` only when they match `^/host/(vpt-pi[0-9]+)/stream/`.
   vpt-nipogi fell through to the generic block, which has no IP for it, so even a valid cookie
   got a Cloudflare 502. Fix, on the proxy VM `/etc/nginx/sites-enabled/virtualpytest` (main and demo
   vhosts): the regex is now `(vpt-pi[0-9]+|vpt-nipogi)`. Backup:
   `~/virtualpytest.nginx.bak.20261004_163312` on the proxy. `nginx -t` ok, reloaded 2026-10-04.
   A new host on the Pi-side server needs the same addition.

Proxy check after the reload (curl, cookie minted with `POST /server/host-session/session`):

```
vpt-nipogi capture_000006075.jpg  no cookie 401 · mint 200 · with cookie 200 image/jpeg 24190 B
vpt-pi1, host-clone-1             with cookie 200
```

Frontend fix `af1f318e4` live as `main-2026.10.04-9777` (14:36 UTC). Verified in the real UI
(Playwright, cookies cleared first): Device Control → device card → stream modal → **Take
Screenshot** (`RecStreamModalHeader`) → new tab.

```
vpt-nipogi "HLS Apple bipbop 16x9 234p"  POST session 200 · GET 200 capture17/captures/capture_000009165.jpg
vpt-pi1    "stb3"                        POST session 200 · GET 200 capture3/captures/capture_000036008.jpg
vpt-pi3    "appletv"                     POST session 200 · GET 200 capture3/captures/capture_002622098.jpg
```

A tab still running a bundle from before 14:36 UTC keeps the old behaviour until it is reloaded.
