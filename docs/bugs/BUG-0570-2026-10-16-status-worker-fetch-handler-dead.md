---
bug_id: BUG-0570
title: status-worker fetch handler dead after route removal — strip it
summary: With the route `virtualpytest.angelstreet.io/*` deleted from the CF dashboard, the `vpt-status-worker` no longer receives visitor traffic — every line of its fetch handler is unreachable. Strip the handler, the embedded HTML page, and the renderErrorPage helper so a future accidental route re-bind cannot silently bring the proxy back.
tags: [cloudflare, workers, dead-code, status-worker, cron, error-1027]
keywords: [vpt-status-worker, fetch handler, CUSTOM_ERROR_PAGE, renderErrorPage, mTLS, /__mtls, route, scheduled, ExportedHandler, BUG-0570]
created: 2026-10-16
---

# BUG-0570

## Symptom
After the CF dashboard route binding `virtualpytest.angelstreet.io/*` was removed from `vpt-status-worker` (2026-10-16) the Worker no longer receives any visitor request — only the minute-by-minute cron trigger fires. The Worker source still ships a full `async fetch(req, env)` proxy (60+ lines) plus a 56-line `CUSTOM_ERROR_PAGE` HTML constant and a `renderErrorPage()` helper. None of that is reachable: removing the route means CF never routes a request to the Worker, so the `fetch` export never runs.

The dead fetch handler is also a foot-gun: if anyone ever re-binds a route in the CF dashboard (or uncomments the `[[routes]]` block in `wrangler.toml`), the proxy comes back without any code change and the site is back to Error 1027 within hours.

The fetch handler also answered `/__mtls` (a Cloudflare client-certificate introspection endpoint that the operator used once to debug a customer mTLS setup). With no route, that endpoint is gone — if it is ever needed again, the cron-only Worker has to either re-gain a route (and the proxying risk comes back) or expose `/__mtls` through a different mechanism (a dedicated Worker, or a script run via `wrangler dev`).

## Fix

### 1. Drop the unreachable `fetch` handler and its companions
`infra/cloudflare/status-worker/src/index.ts`:
- Remove the entire `async fetch(req, env): Promise<Response>` method from the default export.
- Remove the `CUSTOM_ERROR_PAGE` string constant (the 56-line inlined HTML used to render the smart 5xx page).
- Remove the `renderErrorPage()` helper.
- Keep `escapeHtml()` — it is still used by `renderAlertEmail` and `renderDegradedEmail`.
- Keep `sendEmail`, `renderAlertEmail`, `renderRecoveryEmail`, `renderDegradedEmail`, `readStatus`, `HEARTBEAT_MS`, `KV_KEY`, `DEFAULT_EMPTY`, `OriginStatus`, `Env`, `DEPENDENCY_FIELDS` — all are reachable from the `scheduled` handler.

The top-of-file comment block is rewritten so the next reader sees: one responsibility (cron probe + KV + Resend email), no route binding, branded 5xx page is the dashboard's Custom Pages asset (not the Worker). The `scheduled` handler and the email-rendering helpers are unchanged.

### 2. Update `wrangler.toml` route-binding comment
The previous comment narrated the `<app-host>/*` → `virtualpytest.angelstreet.io/*` typo history (which BUG-0554 already covered). Replace it with a "DO NOT bind a route" warning that points to this BUG, so the next person who pastes a `[[routes]]` block sees why the Worker has to stay cron-only.

### 3. Keep `/__mtls` available off-route
The `/__mtls` diagnostic endpoint was the only non-proxy reason the `fetch` handler existed. Removing it is fine for now — the operator's mTLS question was one-off. If a future debugging session needs it again, add a tiny separate Worker that only answers that path (no proxy logic, no risk of Error 1027).

### Validation

- `npx tsc --noEmit` in `infra/cloudflare/status-worker/` passes (was 0 errors before and after the patch; the patch removes code, no new types).
- The Worker source no longer references `fetch` (grep `async fetch` in `src/index.ts` returns nothing).
- The `scheduled` handler still pings `https://virtualpytest.angelstreet.io/server/health` once per minute and writes to the `STATUS_KV` namespace on state change — confirmed by inspecting the unmodified code path.
- `wrangler deploy` from this directory rolls the Worker; the cron trigger (`crons = ["*/1 * * * *"]` in `wrangler.toml`) is unaffected and continues to fire.

## Why cron-only matters
Cloudflare Workers Free plan: 100,000 requests/day. The Worker now invokes ~1,440/day (one per cron tick). A route binding reintroduces every visitor request as a Worker invocation, plus the proxy fetch to origin counts as a second subrequest per visitor. On a typical day with monitoring tabs open and several users hitting the SPA, the plan limit is hit in well under 24 hours and the site flips back to Error 1027 (the rate-limit page). Stripping the `fetch` handler makes that mistake structurally impossible: a route binding would land on a Worker with no `fetch` export, and CF returns its default 404 — no proxy, no Error 1027.

## Pair with
- BUG-0554 — the typo route that hid the branded 5xx page; that one is fixed in the CF dashboard route, not in code.
- `infra/cloudflare/custom-pages/5xx-error.html` — the still-wired Custom Pages asset that the Worker used to duplicate.