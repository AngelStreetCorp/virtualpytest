# BUG-0365 — Cloudflare cached a chunk's 500 for a year after a frontend deploy

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0365                                                     |
| Reported  | 2026-10-05 (user, recurring after frontend deploys)          |
| Status    | Fixed on the proxy; poisoned entries need a Cloudflare purge |
| Severity  | High — Device Control unusable for everyone until purge      |
| Area      | proxy `.107` nginx — `/etc/nginx/sites-enabled/virtualpytest` |
| Fixed in  | — (internal)                                                 |
| Commit    | n/a (proxy config is not in the repo)                        |

---

## Symptom

`/device-control` showed *Failed to fetch dynamically imported module: …/assets/Rec-D5YOV9Ev.js*, on every load and every reload, while `curl` of the same URL returned 200.

## Root cause

`snippets/vpt-app-locations.conf` sets `Cache-Control: public, max-age=31536000, immutable` on `/assets/*.js|css` with **`always`**, so nginx stamps it on error responses too. The deploy restarts `vpt-frontend-prod` after swapping `dist`; chunks requested in those seconds got an nginx 500 marked immutable, and Cloudflare cached it — only for the `Origin`-carrying variant, which is what a browser's `import()` sends (plain curl sends no `Origin`, hence 200). 11 chunks were poisoned (Rec, RecHostPreview, RemotePanel, WebPanel, …).

## Fix

The vhost now declares the same `/assets/` regex location **before** both `include snippets/vpt-app-locations.conf` lines (first regex match wins), with the header **without `always`** — nginx then adds it only to 2xx/3xx responses, so a 5xx is never cached. Backup: `~/virtualpytest.nginx.bak.20261005-050435` on the proxy. The existing poisoned entries must be purged in Cloudflare (Caching → Purge, prefix `virtualpytest.angelstreet.io/assets/`).

## Verification

- `nginx -t` OK, reloaded; a hashed asset still answers 200 with the 1-year immutable header.
- After the purge: `curl -H "Origin: https://virtualpytest.angelstreet.io" …/assets/Rec-D5YOV9Ev.js` → 200.
