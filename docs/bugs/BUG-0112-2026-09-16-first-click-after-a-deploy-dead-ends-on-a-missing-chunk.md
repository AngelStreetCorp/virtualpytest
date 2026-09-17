# BUG-0112 — The first click after a deploy dead-ends on "Failed to fetch dynamically imported module"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                    |
|-----------|------------------------------------------------------------------------------------------|
| ID        | BUG-0112                                                                                   |
| Reported  | 2026-09-16                                                                                 |
| Status    | **Fixed (pending deploy).**                                                                |
| Severity  | Medium (any page, for any user whose tab was open when we deployed; recoverable by reload) |
| Area      | `frontend/src/main.tsx`                                                                   |
| Fixed in  | build 9151                                                                                |

---

## Symptom

Opening a page — `/device-control` in the report, but it is not specific to that page — showed
the app chrome and then, where the page should be:

> **This page hit an error**
> Failed to fetch dynamically imported module: https://…/assets/Rec-DZ70uvj7.js

with a **Try again** button that did nothing. The console carried one line per chunk the page
wanted:

```
RecHostPreview-BIcE31k2.js:1  Failed to load module script: Expected a JavaScript-or-Wasm
    module script but the server responded with a MIME type of "text/html". Strict MIME type
    checking is enforced for module scripts per HTML spec.
…  (Rec, RunningScriptNameBadge, ConfirmDialog, RemotePanel, WebPanel, useRec, useMonitoring, …)
[RouteErrorBoundary] page crashed: TypeError: Failed to fetch dynamically imported module …
```

Reported as happening *often, on first load*, and as new — "never had that before".

## Root cause

Two things, and the second is what made it visible.

**1. The chunk really was gone, and that is normal.** Every route in `App.tsx` is lazy-loaded,
so a page names its chunk — `/assets/Rec-<hash>.js` — only when the user navigates to it. A
deploy gives every chunk a new hash and replaces the whole bundle directory
(`scripts/ensure_dist.sh` builds `dist.new` and swaps it over `dist`). A tab that was loaded
*before* the deploy is still running the old `main-*.js`, which knows only the old hashes — so
the first click in that tab asks for a file that no longer exists. In the reported case the tab
had been open across the 09:00 deploy: it was running `main-CBtbF5dt.js` while the server had
moved to `main-DUronQom.js`.

`serve -s` answers a missing file with `index.html` and a **200**, not a 404, which is why the
browser complains about the MIME type rather than reporting a 404.

**2. The auto-reload that used to hide this had been switched off the day before.** `main.tsx`
has carried a window `error` listener since long before this report — *"Auto-reload on chunk
loading failure (fixes deployment 404s)"* — which reloaded the tab onto the current bundle. It
worked because React 18 **rethrows an uncaught render error on the window**, where that listener
saw it.

`d4f2307e60` (2026-09-15, *"fix(mobile-app): 'This phone' crashed to a blank screen on every
open"*) added `RouteErrorBoundary` so that one crashing page could no longer unmount the whole
app. It does that correctly — and, as a side effect, **catches the chunk error too**. A caught error is
never rethrown, so the window listener stopped firing and the reload stopped happening. The
error that a reload used to paper over became a dead end.

Measured directly, with the chunk request aborted so the import fails exactly as in production:

| build | page loads | user sees |
|---|---|---|
| before `d4f2307e60` (no boundary) | 2 — reloaded itself | nothing, the page just works |
| `d4f2307e60` (boundary added) | 1 — never reloaded | **"This page hit an error"** |
| with this fix | 2 — reloaded itself | nothing, the page just works |

One smaller fault in the same path: the guard was `sessionStorage['chunk-load-reload'] = 'true'`,
set once and never cleared, so a tab could recover from its **first** deploy and from none after it.

## Fix

**Listen to the event Vite raises for this, not to what React lets through.** In a production
build every `import()` behind `React.lazy` is emitted through Vite's preload helper, which
dispatches **`vite:preloadError`** on `window` when the chunk fails to load — *before* the
rejection reaches React, so whether an error boundary sits above the route makes no difference.
`main.tsx` now listens to that event and reloads the tab onto the current bundle; the previous
`error` listener, which only ever worked by way of React's rethrow, is gone. This is Vite's
documented pattern for the problem.

**Let a long-lived tab recover more than once.** The guard is a timestamp with a 30s window
rather than a permanent flag: long enough that a chunk missing for good surfaces as an error
instead of looping, short enough that a tab open across two deploys recovers from both.

The whole fix is one listener. Nothing else changes — `RouteErrorBoundary` keeps doing exactly
what it was added for.

## Verification

In a real browser against a real `serve -s` bundle, with the unchanged `RouteErrorBoundary`
above a plain `React.lazy` route and the chunk request aborted so the import fails exactly as
in production:

- **Stale tab across a deploy** — the tab reloads itself (1 → 2 loads) and shows no error.
- **Chunk missing for good (a broken deploy, where reloading cannot help)** — reloads exactly
  once, then the boundary shows the error. No reload loop.

The regression itself was confirmed the same way against the pre-boundary and post-boundary
builds — the table above.

## Not fixed here

A missing `/assets/*.js` is answered **200 + `index.html`**, and the proxy's
`location ~* ^/assets/.*\.(js|css)$` stamps that response with
`Cache-Control: public, max-age=31536000, immutable` on the URL's say-so, without looking at what
came back. A request that lands in the directory-swap window of `ensure_dist.sh` can therefore
get a *current* chunk URL cached as HTML — in the browser, and at Cloudflare — for a year. That
is a proxy-side change (`snippets/vpt-app-locations.conf`, which is hand-maintained on the proxy
and not in this repo); tracked separately.
