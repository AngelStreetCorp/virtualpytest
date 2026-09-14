# BUG-0055 — Heatmap stopped refreshing: the processor got 401 from its own server after the /server/* lockdown

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0055                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (silent: heatmap frozen, MCP tools and DB-backup status broken) |
| Area      | backend_server auth guard / heatmap processor / MCP client / db backup cron |
| Fixed in  | build 8713                                                   |
| Commit    | `1d2e70e0f`                                                  |

---

## Symptom

The Heatmap page showed stale mosaics: the newest minute never advanced past 16:16 CEST on
2026-09-07. `vpt-heatmap.service` was `active (running)` on both servers (rpi-server and the
.103 server) with a process alive since June, so nothing looked down. Its log told the story
once a minute:

```
16:18:00 [HEATMAP]  Making API request to: http://localhost:5109/server/system/getAllHosts
16:18:00 [HEATMAP]  Response status: 401
16:18:00 [HEATMAP]  Server API returned status 401
16:18:00 [HEATMAP]  No hosts available for 1418
```

Last good line: `Generated heatmap for 1416 (4 devices)` at 16:16. First 401 at 16:18, which
is when build `main-2026.09.07-8654` landed on the servers.

## Root cause

TASK-09 (`be7dfa7c9`, "/server/* closed by default — require a credential") made the global
`before_request` guard in `backend_server/src/app.py` reject every `/server/*` request that
carries none of: service `X-API-Key`, a user JWT, the auto-sign token, or `X-Server-Key`.

Hosts were already sending `X-API-Key` (host → server register/ping went through
`server_auth_headers()`), so the fleet stayed registered and the regression was invisible from
the host side. But four *in-process / cron* callers still hit `localhost:5109` bare:

| Caller | Effect |
|---|---|
| `backend_server/scripts/heatmap_processor.py` | `getAllHosts` → 401 → no devices → no mosaic, every minute |
| `backend_server/src/mcp/utils/api_client.py` (get/post/put/delete) | every MCP tool that proxies to `/server/*` returns `HTTP 401` |
| `backend_server/src/agent/tools/page_interaction.py` | Atlas "alerts" tool → `raise_for_status()` → tool error |
| `setup/local/linux/database/vpt-db-backup.sh` | status POST rejected, but `curl -s` without `-f` still printed "Status reported to backend", so the backup-age alert would have fired falsely ~26 h later |

Note the heatmap processor loads `/opt/virtualpytest/.env`, which holds the right `API_KEY`;
it simply never sent it. (The older, readable `/home/<pi-user>/virtualpytest/.env` on the Pi has
a *different*, stale `API_KEY` — testing with that one also gives 401, which cost a few minutes.)

## Fix

`1d2e70e0f` — every Python caller reuses the existing
`shared.src.lib.utils.build_url_utils.server_auth_headers()` (returns `{'X-API-Key': API_KEY}`,
empty dict when no key is configured, so open-mode dev setups are unchanged):

- `heatmap_processor.get_hosts_devices()` passes it to `requests.get`;
- `MCPAPIClient.get/post/put/delete` pass it on every request;
- `page_interaction` alerts fetch passes it.

The backup script runs on the database VM, which has no repo and no `.env`, so it reads a
`VPT_API_KEY` environment variable and adds `X-API-Key` when set. Both cron installers
(`install_supabase.sh`, `patch_add_backup_cron.sh`) now write `VPT_API_KEY=` into
`/etc/cron.d/vpt-db-backup` (from `$VPT_API_KEY`, or the project `.env` `API_KEY` when the VM has
one) and `chmod 600` the file since it now carries a secret. `curl` gained `-f`, so a 401 lands
in the existing "WARNING: Could not report status" branch instead of a false success.

**Deploy note (not automatic):**
- `vpt-heatmap.service` is *not* restarted by `update_core.sh` — restart it on each server after
  the deploy (the process re-reads the script only on start).
- On the existing database VM, add `VPT_API_KEY=<backend API_KEY>` to `/etc/cron.d/vpt-db-backup`
  by hand (or re-run `patch_add_backup_cron.sh` with `VPT_API_KEY` exported) — the installer
  change only helps fresh installs.

## Verification

On rpi-server (vpt-pi1), against the deployed build 8654, read-only curl from the Pi itself:

```
no key:        401
with /opt key: 200   → hosts: vpt-pi1
```

i.e. the exact header the patched processor now sends is accepted by the exact guard that was
rejecting it. Post-deploy check: `tail -f /tmp/heatmap.log` on the server should show
`Response status: 200` followed by `Generated heatmap for HHMM (N devices)` within one minute of
restarting `vpt-heatmap`, and the Heatmap page's newest minute advances again.
