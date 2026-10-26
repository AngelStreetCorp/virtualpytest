# vpt-status-worker

Cloudflare Worker that:

1. **Cron probe** — every minute pings `<ORIGIN_URL><HEALTH_PATH>` (default
   `https://virtualpytest.angelstreet.io/server/health`) and stores
   `{ok, err, lastChecked, lastOk, consecutiveFailures, alertSent}` in the
   `STATUS_KV` namespace — only when that state changes, plus an hourly
   heartbeat. Free-plan KV allows 1,000 writes/day; a write per tick (1,440)
   blows it ([BUG-0468](../../../docs/bugs/BUG-0468-2026-10-11-status-worker-kv-daily-write-quota.md)).
2. **Email alert via Resend** — fires on `ALERT_AFTER_FAILURES` consecutive
   failures (default 2). Sticky until the next successful probe fires a
   recovery message; one email per outage, no spam. Free tier (100/day,
   3k/month) covers any realistic incident rate.
   A 200 whose JSON reports `supabase` or `redis` other than `connected` is
   **DEGRADED**: same rule (N consecutive probes → one email, one recovery
   email when it clears), but `ok` stays true so the site is not swapped for
   the error page — e.g. the storage VM froze for 5.5 h on 2026-10-12 with
   Redis gone and no alert ([BUG-0475](../../../docs/bugs/BUG-0475-2026-10-12-server-health-slow-when-redis-unreachable.md)).
3. **Outage page** — only when Cloudflare cannot reach proxmox (`fetch`
   throws, or status 520–524). A Flask or nginx 5xx is passed through, so
   a dead server process does not replace the frontend. The page says the
   service is temporarily unavailable and offers **Try again**. No host,
   status code, or request id.

   Without this Worker, users see Cloudflare's generic "Connection timed out
   / Error 522" page; with it they see the same brand as the rest of the
   app and an operator alert has already fired on email.

The frontend bundle and the API are both served by the origin (proxmox VM →
nginx → Flask). When the origin dies, both die — the Worker is the only
layer that can render something useful while origin is down, because it runs
on Cloudflare's edge, not on the origin.

## Why Resend and not SMTP

Cloudflare Workers cannot open arbitrary TCP sockets, only `fetch()` to
HTTP/HTTPS. SMTP is TCP (587/465/25), so the Worker cannot talk to the
PrivateEmail / Namecheap SMTP server directly. Resend exposes an HTTP API
(`/emails`) that works from Workers — that is the only sensible path.
The SMTP creds in `.env` (used by Grafana's `[smtp]` block) stay for the
Python backend to use.

## Why virtualpytest.com needs verification in Resend

Resend rejects sends from any address whose domain is not added in the
Resend dashboard. To send `noreply@virtualpytest.com`:

1. Resend → **Domains → Add domain** → `virtualpytest.com`
2. Resend shows DKIM + SPF records — add those at Namefind
   (`virtualpytest.com` is hosted at `ns1/ns2.namefind.com`, NOT in the
   `angelstreet.io` Cloudflare zone, so this is a Namefind dashboard task)
3. Wait for Resend to verify (a few minutes after DNS propagates)

Until that is done, sends return `403 — domain not verified`.

## Files

| File | Purpose |
|---|---|
| `src/index.ts` | Worker source (fetch override + cron probe) |
| `wrangler.toml` | Worker config (cron, vars, KV binding) |
| `tsconfig.json` | TypeScript config (strict, workers-types) |
| `package.json` | dev deps (`wrangler`, `typescript`, `workers-types`) |
| `../custom-pages/5xx-error.html` | Static branded page for CF dashboard → Custom Pages → 5XX Errors (fallback when the Worker is not bound) |

## Deploy

```bash
# 0. Once per machine: install deps
npm install

# 1. Login (opens browser, picks the angelstreet.io account)
npx wrangler login

# 2. Create the KV namespace; paste the printed id into wrangler.toml
npx wrangler kv:namespace create STATUS_KV
#   → edit wrangler.toml and replace `id = "REPLACE_AFTER_wrangler_kv_namespace_create"`
#     with the printed id

# 3. Set the Resend secrets (paste from `.env`)
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put RESEND_TO_ADDRESS    # comma-separated, e.g. you@x.com,ops@y.com

# 4. Deploy
npx wrangler deploy

# 5. Bind the route (Workers & Pages → vpt-status-worker → Triggers →
#    Add route): virtualpytest.angelstreet.io/*  zone: angelstreet.io
#    OR uncomment [[routes]] in wrangler.toml and re-deploy.
#
#    The pattern MUST be the real public hostname. A typo here
#    (`virtualtest.angelstreet.io/*` — missing "py") made the Worker never
#    fire on the real domain, so users saw the CF generic 522 page instead
#    of the branded one (see BUG-NNNN). If you copy this from an old doc,
#    double-check.
```

The CF API token in `.env` (`CLOUDFLARE_API_TOKEN`) needs scope **Account >
Workers Scripts:Edit**, **Account > Workers KV Storage:Edit**, **Zone >
Workers Routes:Edit**, **Zone > Custom Pages:Edit** on `angelstreet.io`. The
tunnel-only token from `.env` is too narrow — create a fresh one at
https://dash.cloudflare.com/profile/api-tokens.

## Verify

```bash
# Tail Worker logs (after deploy)
npx wrangler tail

# Local dev (override ORIGIN_URL to a fake to watch the Worker render the
# 5xx page; cron probe still runs every minute in dev)
npx wrangler dev
curl -i http://localhost:8787/
```

## Tunables

| var / secret | default | meaning |
|---|---|---|
| `ORIGIN_URL` | `https://virtualpytest.angelstreet.io` | URL the cron pings |
| `HEALTH_PATH` | `/server/health` | path joined to `ORIGIN_URL` |
| `ALERT_AFTER_FAILURES` | `2` | consecutive cron failures before email fires |
| `RESEND_FROM_ADDRESS` | `noreply@virtualpytest.com` | must be on a Resend-verified domain |
| `RESEND_FROM_NAME` | `VirtualPyTest` | shown in mail clients |
| secret `RESEND_TO_ADDRESS` | unset → no alerts | comma-separated recipients |
| secret `RESEND_API_KEY` | unset → no alerts | Resend API key (`re_…`) |

## Pair with the static CF Custom Pages 5XX

The static `../custom-pages/5xx-error.html` is a fallback for when this
Worker is not bound to the route (broken deploy, route removed, etc.).
Paste it into **CF dashboard → Custom Pages → 5XX Errors**. The Worker
overrides it whenever it is bound.

## Notes for the operator

- The KV namespace holds at most one record (`origin-status`) with a 24 h
  expiration; nothing else is written. Safe to delete and recreate.
- The public error page does not show a request id. Look up the incident
  in the alert email, or in CF → Security → Events by time.
- The cron probe has an 8 s `AbortSignal.timeout`; anything slower counts
  as a failure.
- Resend free tier: 100 emails/day, 3k/month — way above any
  realistic incident rate. If you ever blow past it, you'll get a `429`
  from `/emails` and the Worker just logs and continues.
- The Worker does **not** cache anything — it forwards every request to
  the origin and only substitutes the outage page when Cloudflare cannot
  reach proxmox (connection failure or status 520–524).