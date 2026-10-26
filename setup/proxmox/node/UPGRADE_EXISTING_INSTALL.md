# Node and customer upgrade runbook

Use this when a node or a customer stack is behind `main` (a different `update_core.sh`, a database without the newest tables, old unit names). `update_core.sh` copies code and restarts services. It does **not** apply database migrations, install server units, set `.env` keys or install sudoers. Those are the steps below. The facts here come from bringing one node level with another on 2026-10-19.

## 0. Before you start

1. Read `docs/release_note/README.md` → **Upgrade** for everything between the install's build (`cat /opt/virtualpytest/VERSION.txt`) and `main`. Renamed units, new `.env` keys and manual steps are listed there.
2. Lease check: `ssh proxmox '~/bin/vpt-lease check <env>'` (the node's `LEASE_ENV`). A customer install needs the owner's go-ahead.
3. Back up the database before touching it (57 MB on the node this was written from):
   `docker exec supabase_db_supabase pg_dump -U postgres -Fc postgres > ~/backups/<name>-pre-<date>.dump`

## 1. The deploy script on the node

The copy of `update_core.sh` on a node keeps **that node's own** settings, so never overwrite it with the repo file as is. Take `setup/proxmox/node/update_core.sh` and change only:

| Line | Set it to |
|---|---|
| `SERVER_IP`, `FRONTEND_IP`, `HOST_IPS`, `RUNNER_IPS`, `HOST_WINDOWS_IPS`, `DOCKER_IPS` | this node's own targets — the value inside `"${KEY:-…}"`, which stays the default and can be overridden by the environment |
| `SSH_USER` | the account that owns the checkout and has SSH on the targets |
| `REPO_DIR` default | the node's checkout, e.g. `/opt/virtualpytest` (the repo default `~/virtualpytest` may not exist and the deploy then dies at Step 1) |
| `LEASE_ENV` default | the node's lease environment (the repo default is the lab's `node1-vpt`) |
| `LEASE_REGISTRY_HOST` default | the SSH alias of the lease registry; empty in the repo, so a node without `~/bin/vpt-lease` needs it |

Keep the old copy as `update_core.sh.bak-<date>`, run `bash -n` on the new one, then diff it against another node's copy: only these lines may differ.

## 2. Database migrations (not done by the deploy)

`update_core.sh` never runs SQL. Pending = a file in `setup/db/migrations` (no `*_rollback.sql`) with no row in `public.applied_migrations`.

1. **Find where the database stands.** No `applied_migrations` table means it predates `20261014a`. Compare columns with a database you trust (`select table_name||'.'||column_name from information_schema.columns where table_schema='public'`) and look for the newest migration whose objects exist. One node stopped at `20260930b` (it still had `device_models.controllers`, no `test_prompt_executions.run_mode`).
2. **Dry-run on a scratch copy.** Create a database, load `pg_dump -s` into it, run every candidate file in order with `ON_ERROR_STOP`. Failures that come from an empty schema-only copy (an unpopulated materialized view, empty seed tables) are expected; real ones are not.
3. **Run as `supabase_admin`, not `postgres`.** In the Supabase container some tables (28 on that node, e.g. `fleet_health`) belong to `supabase_admin`; as `postgres` the run stops with `must be owner of table`. Reach it over TCP with the container's own password:
   `docker exec -i supabase_db_supabase sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -U supabase_admin -d postgres -v owner_server=<SERVER_NAME> -v ON_ERROR_STOP=1 -q' < file.sql`
   `-v owner_server=<SERVER_NAME>` is needed by `20261004a_workspaces_server_name.sql` (it uses `:'owner_server'`); `SERVER_NAME` is in the server `.env`.
4. **Apply in filename order**, one file at a time, stop on the first real error.
5. **Record them.** Install the tracker (`20261014a`, applied by the loop), then insert a row per file: `method='baseline'` for files older than the first one you applied, `method='manual'` for the ones you ran. Without this the Platform update page lists everything as pending.
6. **Feature SQL is separate** (`features/*/db/`, not in `setup/db/migrations`): `features/mods` (without it Settings → Mods answers 500, BUG-0460), `features/ai-dataset`, `features/zammad` (support tickets), `setup/db/migrations/20260424_ai_userinterface_pack_5layer.sql` if `ai_userinterfaces.goto_home_actions` is missing. Apply those the install uses.
7. **Verify**: compare columns with the reference again. Expected leftovers: `device_models.controllers` and `workspaces.project_tags` still exist on a database that never ran the drop; `masterchief_audit` exists only where `20261009a` ran.

`20261015b` used to fail at its last statement (`data_migrations.id`; the column is `name`). Fixed on 2026-10-19; on an older checkout the `is_scope` column is still created and the error can be ignored.

## 3. Renamed services

The host deploy runs `setup/proxmox/node/migrate_monitor_units.sh`, which renames and keeps the old unit file as `*.bak-task90`:

| Old | New |
|---|---|
| `vpt-monitor` | `vpt-monitor-img` |
| `vpt-transcript` | `vpt-monitor-audio` |
| `vpt-subtitle` | `vpt-monitor-subtitle` |

`AUX_SERVICES` in the deploy script uses the new names, so `--restart` restarts them. Anything of yours that names the old units (monitoring, alerts, scripts) must be updated.

## 4. Server units (not installed by the deploy)

Units for the server VM live in `backend_server/config/services/linux/` and are copied by hand: `sudo cp <unit> /etc/systemd/system/ && sudo systemctl daemon-reload`.

| Unit | Install | Why |
|---|---|---|
| `vpt-match-runs-writer.service` | enable + start | writes the Redis match queue to `match_runs`; needs `REDIS_URL` in `.env` and migration `20261016a`. Without it the table stays empty |
| `auto-classify.service` + `.timer` | enable the timer (02:00) | classifies unknown screens through the AI route; needs a working AI route |
| `vpt-discard-incidents.service` | install, leave disabled in production | alert triage; enabling the unit is the switch (see `backend_server/config/services/README.md`) |
| `vpt-fleet-health*.service/.timer` | only where a fleet report is wanted | needs `FLEET_HEALTH_SERVERS` and an R2 upload target |

## 5. `.env`, packages, sudoers

- Server `.env`: `FRONTEND_DEPLOY_HOST` (frontend VM address, `local` or `none`; no default), `SERVER_NAME`, `SERVER_PUBLIC_URL`, `REDIS_URL`. Restart `vpt-server` after a change.
- Host `.env`: `TRANSCRIPT_AUTOCORRECT` (optional); `DEVICEn_MODEL=fire_tv` becomes `fire_tv_fireos`.
- Every host venv: `PyYAML>=6` and pydantic v2 (`/opt/virtualpytest/venv/bin/python -c "import yaml, pydantic"`). The deploy does not run pip.
- The **frontend VM** needs `python3-yaml` from apt: the docs build runs `scripts/generate_api_docs.py` with the system Python and only warns when it is missing.
- Sudoers, on the server VM and every host, once and again whenever `reconcile_feature_units.sh` changes: `sudo bash /opt/virtualpytest/setup/sudoers/install_vpt_update_sudoers.sh`.

## 6. Deploy and verify

1. `VPT_LEASE_AGENT=<agent> bash ~/update_core.sh main --server --frontend --host --restart`
2. **The deploy lease is capped at 10 minutes.** A deploy of one server, one frontend and five hosts ran past it and stopped with `DEPLOY LEASE EXPIRED` before host 3 (exit 6). Rerun for the rest: `bash ~/update_core.sh main --host --hosts <ip>,<ip> --restart`. Hosts already done stay deployed.
3. A host that is off is skipped with `SKIPPED (unreachable, no ssh)`; check it is off on purpose.
4. Verify: `cat VERSION.txt` on the server, `curl localhost:5109/server/health`, `systemctl is-active vpt-host vpt-monitor-img` on each host, `systemctl --failed 'vpt-*'` empty, `vpt-lease check` free.

## 7. AI routing and provider keys (not part of any migration)

The AI configuration is data (`ai_endpoints`, `ai_profiles`, `ai_routes`, `ai_budgets`), so a migration never brings it level, and the provider keys live outside the database in the server's secrets store (`~vpt_user/.config/virtualpytest/ai_secrets.json`, key `secrets`).

1. Compare with the reference install: `select usage_key, model ... from ai_routes r join ai_profiles p on p.id = r.profile_id`.
2. Copy the four tables with `pg_dump --data-only --column-inserts -t ai_endpoints -t ai_profiles -t ai_routes -t ai_budgets` from the reference, after saving the target's own dump. Load it as `supabase_admin` in one transaction with `SET session_replication_role = replica` (profiles reference each other through `fallback_profile_id`), after deleting routes, profiles, endpoints and budgets in that order. Team routes need the same team id on both sides.
3. Disable endpoints the target cannot reach (the LM Studio endpoint is a private tailnet address): `update ai_endpoints set enabled = false where name = ...`.
4. Restart `vpt-server` so the router drops its cache.
5. **Test every profile with the target's own keys** before calling it done: run `router.Hop(profile, endpoint).client()` with `connectivity_response` for each enabled profile (Settings → AI has a test button per profile). Never copy the secrets file between installs; the key is the customer's or the node's own. A route can look right and still fail: on the node this was written from, the OpenRouter key answered `401 User not found` and `claude-sonnet-4-20250514` answered 404 (retired model), so every OpenRouter route failed until the key is replaced in Settings → AI.

## 8. Report links, and checking that scheduled tests recover

- **Presigned report links** (screenshots, logs, videos) use `MINIO_PRESIGN_ENDPOINT` from each host and server `.env`. It must be the install's own public name, and that name's nginx must route `/virtualpytest/` to the install's MinIO (`http://<storage-vm>:9000/virtualpytest/`, `Host` passed through unchanged, so the signature stays valid). On the node this was written from, the hosts still pointed at another install's public name, so every report link answered `InvalidAccessKeyId`. Fix: set the variable on the server and every host, restart `vpt-host`, add the nginx `location /virtualpytest/` block, `nginx -t`, reload. Check with a fresh run, not an old link.
- **Code and database move together.** A scheduled suite that passed at about 78% went to 0% for three days after a host deploy brought newer code, while the database had not been migrated; every run failed in under 100 ms, before the browser started. It recovered in the first hour after the migrations and deploy. After an upgrade, read the next two hourly runs: `select date_trunc('hour', started_at), count(*), count(*) filter (where success) from script_results where started_at > now() - interval '6 hours' group by 1`.
- **Do not trust the pass rate until you know what the suite cannot pass.** A test that needs a login on a site that shows a captcha (hCaptcha on a Shopify store's customer login) fails every run and is not a regression. Keep such tests out of the schedule or give them a captcha-free target.

