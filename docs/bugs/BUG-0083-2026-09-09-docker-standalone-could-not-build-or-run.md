# BUG-0083 — Docker standalone stack could neither build nor run: `.env` copy in the Dockerfiles, wrong supervisord user, unused Postgres, no auth wiring

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0083                                                                    |
| Reported  | 2026-09-09 (TASK-15 audit of the self-service install paths)                |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (the documented "5-minute" Docker install cannot produce a running platform) |
| Area      | backend_server/Dockerfile · backend_host/Dockerfile · backend_host/docker/supervisord.conf · frontend/Dockerfile · setup/docker/ |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

`docs/get-started/quickstart.md` sends an evaluator to `setup/docker/standalone_server_host/launch.sh`.
Nothing past `docker compose up` ever worked, for four independent reasons:

1. **Both backend images fail to build.** `backend_server/Dockerfile:46` and
   `backend_host/Dockerfile:64` ran `cp .env.example .env`, but the root `.dockerignore`
   excludes `.env.*` from the build context, so the file is never there:
   ```
   cp: cannot stat '.env.example': No such file or directory
   ```
2. **The host container cannot start even with a built image.** The Dockerfile creates the
   service account `vpt_user`; `backend_host/docker/supervisord.conf` referenced `vptuser`
   on 16 program blocks (plus `generate_env.sh` and the host launcher), so supervisord aborts
   on an unknown user.
3. **The bundled `postgres:15-alpine` was not the platform's database.** The application
   talks to Supabase over REST (`SUPABASE_URL` + service-role key,
   `shared/src/lib/utils/supabase_utils.py`); the `DATABASE_URL` / `POSTGRES_*` variables
   the compose file injected have one reader (`shared/src/lib/config/settings.py`) and zero
   consumers. The schema mounted into initdb would have failed on `002_*.sql` anyway
   (`auth.uid()` does not exist on plain Postgres).
4. **No auth wiring.** Nothing in `setup/docker/` set `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_JWT_SECRET` or `SERVER_OPEN_MODE`; since TASK-10 the server is closed by default,
   so a fresh install answered 401 on every API call.

Found by the `docker-build` CI job once the stack came up: `setup/db/schema/002_ui_navigation_tables.sql`
failed on a **fresh** database at its first statement, `DROP TRIGGER IF EXISTS … ON userinterfaces`
— Postgres errors when the table is missing (`IF EXISTS` only covers the trigger). The VM
installer never noticed because it applies the files without `ON_ERROR_STOP` and only prints
the error. The four table-dependent `DROP TRIGGER` lines are removed (`DROP TABLE … CASCADE`
drops the triggers anyway); a static check confirms every remaining `DROP TRIGGER … ON` targets
a table created earlier in the sequence.

Found on the first acceptance run: `setup/docker/install_docker.sh` never installed anything —
it read `detect_platform.sh`'s coloured human-readable banner as the platform name and hit its
own "Unsupported platform" branch.

Smaller defects in the same tree: `setup/docker/.env.docker` used `NEXT_PUBLIC_SUPABASE_*`
names nothing reads and carried an internal `192.168.1.103`; the Grafana compose set an
entrypoint it never mounted; the frontend port was mapped to a container port with no listener
(`5073:80` / `5073:8080`, image serves 5073); `frontend/Dockerfile` had no `ARG VITE_*` and no
`.dockerignore` (copied `node_modules`, `dist`, `.env`); no CI job built any image.

Found on the acceptance runs (fresh Ubuntu 24.04 VM and the `docker-build` CI job):
- the frontend image: `adduser -u 1000` collides with the `node` user of `node:22-alpine`; the
  npm prebuild hook is a bash script and Alpine has no bash;
- the vendored Supabase healthchecks (db 50 s, auth/rest 15 s) are shorter than a first start
  on a small VM, so `depends_on: service_healthy` reported "dependency failed to start";
- the host entrypoint parsed `HOST_VIDEO_CAPTURE_PATH=… # comment` verbatim and created a
  directory named `capture    # Capture output directory`, leaving the real capture directory
  root-owned (capture monitor: `Permission denied … /thumbnails`);
- the host app bound to the hostname taken from `HOST_API_URL`, so the container's own
  healthcheck on `localhost` never passed (new `HOST_BIND_IP` override, `0.0.0.0` in compose);
- `setup/db/schema/002_*.sql` fails on a fresh database (`DROP TRIGGER … ON` a missing table);
- the Docker init scripts re-granted `anon` on every start, undoing the TASK-10 lockdown, which
  a fresh install did not apply at all (`apply_schema.sh` now applies it last);
- a VM that resolves IPv6 for Docker Hub but has no IPv6 route hangs on every pull (documented);
- the host image healthcheck probed `/host/health`, which needs the API key (401) — the exempt
  route is `/host/system/health`.

## Root cause

The Docker tree was written before the platform moved to Supabase-only data access and before
the auth lockdown, and was never exercised afterwards: the compose files were generated by
heredocs in launch scripts, so nothing could be linted or built in CI.

## Fix

- `backend_server/Dockerfile`, `backend_host/Dockerfile`: no `.env` is baked into the image;
  configuration arrives at runtime (`env_file:` / mounts). Healthchecks use the real routes
  (`/server/health`, `/host/health`). Server image also ships `backend_host/src` (shared
  executors import from it). Supervisord in the server image runs as `vpt_user` with its pid
  and socket under `/tmp`.
- `backend_host/docker/supervisord.conf`, `generate_env.sh`: `vptuser` → `vpt_user`.
- `frontend/Dockerfile`: Node 22, `ARG VITE_*` build args, `serve` on 5073; new
  `frontend/.dockerignore`.
- `setup/docker/` rewritten around **committed** compose files (`docker-compose.yml` +
  `docker-compose.{linux,macos,host}.yml`) that include a **vendored, pinned subset of the
  official self-hosted Supabase compose** (`setup/docker/supabase/`), a `db-init` one-shot that
  applies `setup/db/schema` through `setup/db/apply_schema.sh`, MinIO + Redis, Grafana with a
  read-only DB role, and a 150-line `launch.sh` that generates every secret (including the
  Supabase ANON / SERVICE_ROLE JWTs) into a git-ignored `.env`. Old generators, `.env.docker`
  and `test_platform.sh` deleted.
- `setup/docker/install_docker.sh`: platform from `uname -s`; `detect_platform.sh` removed.
- Fresh installs start in **open mode** (`SERVER_OPEN_MODE=true`, TASK-15 decision §7.2) with a
  printed warning and a documented three-line switch to enforced login.

## Verification

- `docker compose config` valid for all four file combinations (full/host × linux/macos).
- CI `docker-build` (GitHub-hosted, 2026-09-11, run 34633728612): images build, `launch.sh`
  brings the stack up, server / UI / host / Supabase REST / Grafana answer — **pass**.
- Fresh Ubuntu 24.04 VM (proxmox3 VMID 390, 4 vCPU / 8 GB, slow NAT egress):
  `./setup/docker/install_docker.sh` + `./setup/docker/launch.sh` → launcher completes, server
  and UI answer, host registers with one device through the service-role key — **pass** (this
  run is what surfaced the healthcheck, entrypoint and bind defects listed above).
