# BUG-0038 — Status page shows wrong health/backup/runner info, and 403s on refresh

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0038                                                     |
| Reported  | 2026-09-01                                                   |
| Status    | Closed                                                        |
| Severity  | Medium (misleading infra status; one path was a hard 403 for real users) |
| Area      | `infra/proxy/nginx/config/*.conf`, `frontend/src/pages/Status.tsx` |
| Fixed in  | build 8713                                                   |
| Commit    | `fdba2d6fc`, `7b7ee83d2`                                     |

---

## Symptom

Customer reported the Status (`/status`) page showing persistent warnings — Nginx/Supabase/Redis
stuck on "health check unreachable — retrying", DB Backup showing "No backup status — backup may
never have run" despite backups running nightly, and GitHub Runners showing "GITHUB_TOKEN not
set" — and separately, refreshing the browser on `/status` returned a plain nginx "403 Forbidden"
page instead of the app.

## Root cause (two independent bugs)

**1. `/status` path collision (the 403).** Every nginx config template bound its internal
`stub_status` metrics endpoint to `location /status`, restricted to the LAN (`deny all` for
everyone else). The React app also has a client-side route at `/status`
(`frontend/src/App.tsx:510`). Client-side navigation to `/status` never hits nginx, so it worked;
a full page load or browser refresh sent a real `GET /status`, which the `stub_status` block
matched first and rejected with 403 before the request ever reached the SPA. Reproduced directly:
`curl https://virtualpytest.angelstreet.io/status` → 403 (nginx).

**2. Wrong-server routing (the misleading statuses).** Every check on the Status page — including
DB Backup and GitHub Runners — was built with `buildServerUrl()`, which resolves through
whichever server is currently selected in the server picker (`localStorage['selectedServer']`),
not necessarily the primary server. Tested both registered servers directly and matched the
customer's exact wording:

| Check | primary (`virtualpytest.angelstreet.io`) | secondary (`rpitest.angelstreet.io`) |
|---|---|---|
| `/server/health` | 200 OK, redis+supabase connected (0.5s) | **times out, no response (12s+)** |
| `/server/storage/health` | ok, r2_configured (0.5s) | ok, r2_configured (0.2s) |
| `/server/system/backup/status` | ok, backup 9.5h old | **"No backup status — backup may never have run"** |
| `/server/ci-reports/runners` | success, runner data | **"GITHUB_TOKEN not set"** |

DB Backup and GitHub Runners are global facts (one shared database with one backup cron; one
GitHub repo with one runner pool) — they were never supposed to vary by which server is selected.
`/server/health` and `/server/storage/health` legitimately *should* stay server-scoped (they
reflect that specific backend instance's own connectivity), so the secondary server's `/server/health`
hang there is a real, separate infra issue on that host (not yet fixed — flagged for follow-up),
distinct from the frontend routing bug.

## Fix

- `infra/proxy/nginx/config/*.conf` (all 6 variants) — renamed the `stub_status` location from
  `/status` to `/_nginx_status` so it no longer shadows the SPA route. Applied live on the proxy
  VM (backed up the deployed config first, `nginx -t` validated, then reloaded).
- `frontend/src/pages/Status.tsx` — `checkDbBackup()` and `checkRunners()` now use the existing
  `buildPrimaryServerUrl()` helper (already used elsewhere for CI/CD resources that "only ever
  live on the main server regardless of the server-picker selection") instead of `buildServerUrl()`,
  so both always reflect the one true global answer.

## Verification

- `curl https://virtualpytest.angelstreet.io/status` → 200, `text/html` (was 403).
- `curl https://virtualpytest.angelstreet.io/_nginx_status` → 403 from a public IP (metrics
  endpoint moved and still correctly LAN-restricted).
- `tsc --noEmit` clean on `Status.tsx` (one pre-existing, unrelated error in
  `VerificationItem.tsx` confirmed present before this change).

## Follow-up (not fixed here)

`rpitest.angelstreet.io`'s own `/server/health` route hangs to a full timeout (12s+, no response)
while its sibling endpoints on the same host answer in ~0.2-0.3s — a real, host-specific bug worth
investigating on that server independently of the frontend routing fix above.
