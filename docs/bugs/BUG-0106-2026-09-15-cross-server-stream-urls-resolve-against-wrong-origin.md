# BUG-0106 — Another server's devices stream from THIS server's proxy (wrong desktop, or Bad gateway)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                     |
|-----------|---------------------------------------------------------------------------|
| ID        | BUG-0106                                                                  |
| Reported  | 2026-09-15 (VirtualPyTest frontend, Server selector switched to QualiAI)   |
| Status    | FIXED                                                                     |
| Severity  | High — silently shows a *different machine's* screen under the right name  |
| Area      | `frontend/src/hooks/controller/useStream.ts`                              |
| Fixed in  | build 9151                                                                |

| Commit    | this commit                                                               |

---

## Symptom

On `virtualpytest.angelstreet.io` with **Server = QualiAI**, the Device page showed:

- `Android_Mobile` / `Android_Tablet` / `Android_TV` — stuck on "Loading stream..."
- `host-clone-2`, `host-clone-3` — a Cloudflare **Bad gateway** page inside the preview
- `host-clone-1` — a desktop, but **VirtualPyTest's own `host-clone-1`, not QualiAI's**

QualiAI's own UI showed all 12 devices streaming correctly, so the hosts were healthy.

The third bullet is the dangerous one: nothing looked broken, it was just the wrong machine.

## Cause

Hosts register a **relative** `host_url` (`/host/<name>`) that only resolves on their own
server's proxy. `ServerManagerProvider` already stamps `server_url` on every host for exactly
this reason, and `buildUrlUtils.ts` already honours it via `resolveHostUrlOrigin()`.

`useStream.ts` did not. It hand-rolled the resolution and fell back to
`window.location.origin`, so every QualiAI host was resolved against **VirtualPyTest's** proxy:

```
qualiai.io/host/host-clone-{1,2,3}/vnc_lite.html   -> 200
angelstreet.io/host/host-clone-2/vnc_lite.html     -> 502   (Bad gateway card)
angelstreet.io/host/host-clone-1/vnc_lite.html     -> 200   (VPT's OWN machine)
```

`host-clone-1` exists on both servers, so the name collided and the request quietly succeeded
against the wrong host. Names that exist on neither 502 or never load.

Two further collisions in the same file had the same root cause — host names are only unique
*within* a server:

- the 24h client-side stream-URL cache was keyed `host_name:device_id`, so one server served
  the other's cached URL for 24h;
- `deviceKey` (which gates refetching) was keyed `host_name-device_id`, so switching servers
  between two same-named hosts was not detected as a change and never refetched.

## Fix

Resolve against the origin of the server that **owns** the host (`host.server_url`), falling
back to `window.location.origin` only when it is absent or malformed — same rule as
`resolveHostUrlOrigin()`. Key the cache and `deviceKey` by `server_url` as well.

`f1768c6e6f` fixed this class of bug in `buildUrlUtils.ts` but missed `useStream.ts`, which is
the path that actually produces the URL the preview components consume.
