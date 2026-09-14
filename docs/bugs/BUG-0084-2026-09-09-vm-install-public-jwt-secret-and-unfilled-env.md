# BUG-0084 — One-VM install shipped the public Supabase CLI JWT secret and left every `.env` unfilled

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0084                                                                    |
| Reported  | 2026-09-09 (TASK-15 audit of the self-service install paths)                |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (security: forgeable service-role tokens on every CLI-installed database; usability: install ends with a non-working platform) |
| Area      | setup/local/linux/database/install_supabase.sh · setup/local/linux/install_all.sh · install_core.sh · .env.example files |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

> **The security half duplicates [BUG-0082](BUG-0082-2026-09-14-supabase-cli-default-jwt-secret-in-tree.md).**
> Same defect — `install_supabase.sh` writing the Supabase CLI's public default `jwt_secret` —
> found independently: BUG-0082 from the production side (signing a `service_role` token against
> the live REST API), this one from the TASK-15 audit of the self-service install paths. BUG-0082
> is the canonical report for the security issue and tracks rotation on existing installs; what is
> unique here is the second symptom, the install finishing with every `.env` unfilled.

## Symptom

1. **Security.** `install_supabase.sh` wrote `jwt_secret = "super-secret-jwt-token-with-at-least-32-characters-long"`
   into `supabase/config.toml` — the Supabase CLI's documented default. Anyone who can reach
   port 54321 of such an install can sign their own `service_role` JWT and read or write
   every table, whatever the RLS policies say. The value was then copied into
   `SUPABASE_JWT_SECRET`, so browser JWTs were forgeable too.
2. **Usability.** `install_all.sh` copied templates named `env.local.example` and
   `env.example` (no leading dot) under the root, `backend_host/src` and `frontend` — none of
   which exist (the files are `.env.example`) — so no
   `.env` was created; each role installer then created its own from the template and
   printed "please configure it". `install_supabase.sh` extracted the Supabase keys but the
   call that would have written them into `.env` was commented out ("users should manage
   manually"). Result: the platform came up with `API_KEY=your-api-key`,
   `SUPABASE_URL=https://your-project-id.supabase.co` and, since the auth lockdown, a 401 on
   every request. `install_all.md` promised a `--no-grafana` flag that did not exist.
3. The `.env.example` templates were out of date: no `SUPABASE_SERVICE_ROLE_KEY` /
   `SUPABASE_JWT_SECRET` / `SERVER_OPEN_MODE` in the root template, dead `UPSTASH_*` and
   `GRAFANA_DOMAIN` / `GRAFANA_SECRET_KEY` entries, a duplicated Supabase block, frontend
   template pointing at `192.168.1.x` and an `https://192.1.168.1.x/grafana` typo.

Found on the acceptance run (Ubuntu 24.04): `setup/local/linux/shared/install_requirements.sh` adds the Ookla
speedtest apt repository, which has no `noble` build; the step itself is non-fatal but the
repository file stays behind and the next `apt-get update` (first thing the installer does)
fails with "does not have a Release file", so a second run of `install_all.sh` died at step 0.
`database/install_supabase.sh` also installed Docker with bare `apt-get`/`systemctl`, which
only works as root — `install_all.sh` runs it as the installing user.

Further findings on the acceptance runs (fresh Ubuntu 24.04, 4 vCPU / 8 GB), all fixed:
`sudo -v` in the CLI install needs a tty and the fallback silently failed; the pre-flight probed
the Docker daemon as the installing user; `supabase status` now prints the new `sb_*` keys in
its table — the JWT keys the platform needs come from `supabase status -o env`; the lockdown
check tested `grep`'s exit code instead of `psql`'s; `config/database/local.env` and the
systemd unit temp file were written into the `vpt_user`-owned tree; the CLI `health_timeout`
of 3 min expired on the first database start (now 10 min) and `supabase.service` needed a
longer `TimeoutStartSec` than that; the existing-data check looked for a volume named after the
wrong project id, so a re-run wiped the database; the backup cron defaulted to a lab IP;
`storage/install_minio.sh` downloaded from dl.min.io, which answers **410 Gone** since 2025
(GitHub releases carry no assets either) — the binaries are now extracted from the pinned
`minio/minio` and `minio/mc` images the Docker stack uses.

## Fix

- `install_supabase.sh`: a random 32-byte `jwt_secret` per install, stored in
  `supabase/.jwt_secret` (mode 600) and written into `config.toml`; `extract_supabase_config`
  reads it back (falls back to `config.toml` for existing installs) so
  `config/database/local.env` carries the real secret.
- New `setup/local/linux/shared/write_env.sh`: writes the three `.env` files from
  `config/database/local.env`, the LAN address and generated secrets; idempotent, never
  overwrites a value a user set. `install_all.sh` runs it after the database install and
  before the frontend build; `install_core.sh` runs it too.
- `install_all.sh`: `--no-grafana`, `--no-storage`, `--no-host`, `--public-host`,
  `--open-mode`; correct template names; starts the services; prints the URL table and the
  open-mode warning.
- `setup/local/linux/shared/install_requirements.sh` removes the Ookla repository when the package is unavailable;
  `database/install_supabase.sh` runs its Docker/Compose installation through `sudo`.
- `.env.example`, `frontend/.env.example`, `backend_host/src/.env.example`: every key has a
  reader in the code (31/31 verified for the root template), auth posture documented inline.

Found on the scratch-VM runs (2026-09-11/12), all fixed:

- `install_supabase.sh` ran a leftover `create_config` *after* writing the extracted keys, so
  `config/database/local.env` ended with the template block (`${SUPABASE_ANON_KEY:-your_…}`)
  and `write_env.sh` left every `.env` on `CHANGE_ME` — the host then crash-looped on
  `Expected 3 parts in JWT`. The two template writers and the dead `update_main_env_file`
  are gone; the one remaining writer rewrites the whole file from the extracted values.
  `write_env.sh` also treats any `${…}` value as a placeholder.
- `install_supabase.sh`: root-only steps (apt, nodesource, CLI move, systemd unit, backup
  script) through `$SUDO`; keys read from `supabase status -o env` (the table view now shows
  `sb_*` keys); `sudo -v` needs a tty; pre-flight probed the Docker daemon as the wrong user;
  the CLI health timeout (3 min) and the unit `TimeoutStartSec` (300 s) were too short for a
  first start on a small VM (10 min / 900 s now); the lockdown migration is applied after the
  schema; the backup cron points at `SERVER_URL`, not a lab address.
- `install_frontend.sh` treated a slow first production build as fatal (`systemctl start`
  timed out at 360 s, installer returned 1, Grafana and the final service starts never ran).
  The unit allows 1800 s, the installer queues the start with `--no-block` and says so.
- `install_grafana.sh` wrote `launch_grafana.sh` into `/opt` and read `grafana.ini` without
  sudo; the csrf origins `sed` only matched the commented example while the template carried
  a lab IP. Writes go through `vpt_user`, the origins line is replaced whatever it was, and
  `install_all.sh` treats a Grafana failure as a warning, so the final starts always run.
- `install_minio.sh`: `dl.min.io` answers 410 and Docker Hub `minio/*` 401 — binaries are
  extracted from the pinned `quay.io/minio` images instead.
- `install_host.sh` / `install_patched_bluetoothd.sh`: the dead Ookla apt source broke every
  `apt-get update` on Ubuntu 24.04 (the bluez `deb-src` derivation copied it); removed before
  update, distro sources only.
- Lab addresses removed from installer output (`install_frontend.sh`, `patch_add_backup_cron.sh`,
  the Grafana template's csrf line).
- Grafana never came up on a fresh machine: the template `infra/monitoring/grafana/config/grafana.ini`
  configured the optional image renderer with the default `renderer_token = -`, which Grafana 11+
  rejects at start-up (`failed to start rendering service`), after 30–40 min of SQLite migrations
  on a small VM. The renderer keys are commented out by default; the renderer how-to now asks
  for a shared random token.
- The same template carried a lab hostname as `domain` and a `/grafana/` sub-path `root_url`,
  so the UI at `http://<ip>:3000` would redirect to the lab. `install_grafana.sh` sets
  `domain`, `root_url` and `serve_from_sub_path` from `SERVER_URL` in `.env`, through a
  section-scoped setter (a bare `sed` on `;?key` also uncommented the same key in other
  sections, e.g. `[cloud_migration]`).
- The host bound to `127.0.0.1` (it derives its bind address from `HOST_API_URL`, which
  `write_env.sh` sets to `localhost`), so the UI could not reach it at the advertised
  `HOST_URL`. `write_env.sh` sets `HOST_BIND_IP=0.0.0.0` (documented in
  `backend_host/src/.env.example`).
- `install_patched_bluetoothd.sh` exited silently right after "enabling deb-src entries" on
  Ubuntu 24.04: under `set -e -o pipefail` the empty `grep` in `SRC_LIST=$(…)` ended the
  script. The bluez build now completes (`/opt/bluez-cccpatch-v2`).
- `backend_host/scripts/patch_novnc_close_frame.sh` was tracked without the executable bit,
  so `install_host.sh` skipped it with "Missing patch script"; `patch_supabase_compose.sh`
  printed a warning on every CLI install although there is nothing to patch there.

**Existing CLI-installed databases** keep the public secret until re-installed or until
`jwt_secret` in `supabase/config.toml` is changed by hand and `supabase stop && supabase start`
is run (every issued token becomes invalid; update `SUPABASE_JWT_SECRET` on the server, and
`SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` everywhere from the new `supabase status`).

## Verification

2026-09-12, Ubuntu 24.04 scratch VM (`vpt-scratch-vm-install`, proxmox3 VMID 391, 4 vCPU,
8 GB, slow NAT egress), fresh copy of the branch tip (`1c9abfd023` + the bluetoothd and
Grafana-template fixes above), `./setup/local/linux/install_all.sh` with no options, run to
the end (66 min) and printing the URL table:

- `vpt-server`, `vpt-host`, `vpt-frontend-prod`, `supabase`, `grafana-server`, `minio`,
  `redis-server` all `active`; server, Web UI, host, Supabase REST, MinIO answer 200 on
  `localhost` **and** on the advertised LAN address; host listens on `0.0.0.0:6109`.
- Supabase keys in all three `.env` files are the instance's real keys (`eyJ…`, 153/164
  chars); `SERVER_OPEN_MODE=true` and the warning printed.
- Lockdown applied: anon on `teams` → 401, service_role → 200; 4 `USING (true)` policies
  left (profiles / team_members, by design).
- The host registered itself on the server (`MyHost`, 1 device).
- Grafana (13.2.1 from the apt repository) answers on `:3000` after its 53-minute first
  start, `/` redirects to `http://<ip>:3000/login`, the `.env` admin password logs in, the
  `supabase-postgres` datasource is provisioned; the renderer keys are commented out and the
  csrf origins carry the machine address.
- The patched bluetoothd build completed (`/opt/bluez-cccpatch-v2`); the noVNC patch ran.

Docker-standalone CI job `docker-build` green on the same tip (run 34680308948).
