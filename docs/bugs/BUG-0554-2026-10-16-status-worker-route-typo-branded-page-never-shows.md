# BUG-0554 — Cloudflare status worker route typo: branded 5xx page never showed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0554                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | infra / cloudflare worker                                    |
| Fixed in  | build 90145 |
| Commit    | 304852ad4                                                    |

---

## Symptom

Visiting `https://virtualpytest.angelstreet.io/` while the origin was down
returned Cloudflare's **generic** "Connection timed out / Error code 522"
page — `virtualpytest.angelstreet.io Host Error` shown with the stock CF
branding — instead of the branded page the `vpt-status-worker` is supposed
to render (the one with the gold "VirtualPyTest — Service temporarily
unavailable" card and a Retry button).

The email side worked: the worker DID detect the outage and DID send the
`[VirtualPyTest] origin DOWN — 2 consecutive failures` email through Resend
(delivered to the operator inbox, 2026-10-16 04:49:57 UTC). The cron probe,
KV, Resend, and the alert email path were all healthy.

So the failure was one-sided: the **fetch handler** never ran for real
traffic, only the **cron handler** ran.

## Root cause

The Cloudflare dashboard route binding for the worker was created with a
typo in the URL pattern:

```
pattern = "<app-host>/*"     # missing "py"
script  = "vpt-status-worker"
```

The Worker is bound to a non-existent host. Every request to the actual
public hostname `virtualpytest.angelstreet.io` matched the **origin** route
(Cloudflare → tunnel → nginx → Flask) directly, never the Worker route, so
the Worker's fetch handler — which renders the branded error page when
the origin 5xx / times out — never had a chance.

The same typo lived in two repo files:

- `infra/cloudflare/status-worker/wrangler.toml` (the `[[routes]]` block
  was commented out, but the comment still showed the wrong pattern, so
  anyone who uncommented it would have re-created the bad binding).
- `infra/cloudflare/status-worker/README.md` step 5 (`Add route: virtualtest...`).

Verified via the Cloudflare API:

```
GET /zones/<zone>/workers/routes
{
  "result": [{
    "id": "dc722dcc8ee14692be3c8b9152488c84",
    "pattern": "<app-host>/*",
    "script": "vpt-status-worker",
    "request_limit_fail_open": false
  }]
}
```

`vpt-status-worker`'s KV had the right state
(`{"ok":false,"err":"HTTP 522","consecutiveFailures":2,"alertSent":true, ...}`),
so the Worker *code* is fine — only its route was wrong.

## Fix

1. **PATCH the route pattern** in the dashboard (via the CF API, because
   the `[[routes]]` block in `wrangler.toml` is intentionally commented
   out — the dashboard is the source of truth for this binding):

   ```
   PUT /zones/<zone>/workers/routes/<route>
   { "pattern": "virtualpytest.angelstreet.io/*",
     "script":  "vpt-status-worker" }
   ```

   Verified at 2026-10-16 05:36 UTC: a `curl -i https://virtualpytest.angelstreet.io/`
   now returns HTTP 522 with the branded page (size 2 323 bytes,
   `<title>VirtualPyTest — Service temporarily unavailable</title>`).

2. **Fix the typo in `wrangler.toml`** (the comment around the
   commented-out `[[routes]]` block) and in `README.md` (step 5), and add
   an inline warning in both files so a copy-paste can't silently re-create
   the bad binding.

   The `[[routes]]` block stays commented because the dashboard is the
   source of truth for the route; uncommenting it would cause `wrangler
   deploy` to manage the route itself, which is a different workflow.

## Verification

- `curl -i https://virtualpytest.angelstreet.io/` → 522, branded page, cf-ray
  in the rendered meta line.
- `GET /zones/<zone>/workers/routes` → `pattern: "virtualpytest.angelstreet.io/*"`,
  `script: "vpt-status-worker"`.
- KV `origin-status` reads `ok:false, err:"HTTP 522", consecutiveFailures:2,
  alertSent:true` — the cron probe is still firing (Resend shows the
  `[VirtualPyTest] origin DOWN` email was delivered at 04:49:57 UTC).

## Lessons

- **A typo in a route pattern is silent**: CF happily creates the binding,
  the Worker deploys cleanly, the cron path is fully exercised, but real
  traffic never hits the Worker. Add a deploy-time check that compares the
  Worker script's `wrangler.toml` `ORIGIN_URL` and the actual route
  pattern and refuses the deploy if they don't share the same parent host.
- **Treat the route binding as a first-class deploy artifact**: keep
  `[[routes]]` in `wrangler.toml` uncommented (or generate it from
  `ORIGIN_URL`) so a typo in one place can't drift from the other. For
  now the dashboard wins and the repo files are documentation + warning.
- **The alert email is not enough for users**: users hitting the CF edge
  see CF's stock page, not the branded one. If the Worker doesn't render
  the page, the only people who learn about the outage from this Worker
  are operators in their inbox.