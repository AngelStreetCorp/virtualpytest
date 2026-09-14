# VirtualPyTest — Docker stack

One machine, one command, the whole platform. User guide: **docs/get-started/docker.md**.

```bash
./setup/docker/install_docker.sh   # only if Docker is missing (Linux / macOS)
./setup/docker/launch.sh           # full stack — Web UI on http://<this-machine>:5073
./setup/docker/launch.sh --host-only   # device controller joining an existing server
```

## What is in here

| Path | Role |
|---|---|
| `launch.sh` | Creates `.env` from `.env.example` with generated secrets, picks the platform override, `docker compose up`, waits for health, prints the URLs. `--rebuild`, `--down`, `--reset`, `--logs`. |
| `docker-compose.yml` | The stack: `db-init`, `redis`, `minio` (+`minio-init`), `backend_server`, `backend_host`, `frontend`, `grafana`. Includes `supabase/`. |
| `docker-compose.linux.yml` / `.macos.yml` | Platform override for the host container (`/dev` passthrough, tmpfs hot storage). |
| `docker-compose.host.yml` | Host-only variant (no server, no database). |
| `supabase/` | Vendored subset of the official self-hosted Supabase compose, image tags pinned. See the header of `supabase/docker-compose.yml` for what was kept and how to upgrade. |
| `scripts/db_init.sh` | Applies `setup/db/schema` once (via `setup/db/apply_schema.sh`) and creates Grafana's read-only role. |
| `grafana/grafana_entrypoint.sh` | Generates the Grafana datasource from `SUPABASE_DB_URI` at container start. |
| `.env.example` | Every variable the stack reads, with `CHANGE_ME` placeholders `launch.sh` fills. Copied to `.env` (git-ignored). |
| `installers/`, `install_docker.sh` | Docker Engine / Desktop installation per OS. |
| `hetzner_custom/` | Older multi-host production recipe with an external Supabase. Not the customer path; kept until it is folded into a `production/` variant. |

## Ports published on the machine

| Port | Service |
|---|---|
| 5073 | Web UI (frontend) |
| 5109 | Server API |
| 6109 / 6080 | Host API / noVNC desktop of the host |
| 3000 | Grafana |
| 54321 | Supabase API gateway + Studio (basic auth: `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`) |
| 54322 | Postgres |
| 9000 / 9001 | MinIO S3 / MinIO console |

## Auth posture

The stack starts in **open mode** (`SERVER_OPEN_MODE=true`, no login) for a fast first
contact on a trusted network. `launch.sh` prints a warning while that is the case. The
`.env.example` auth block describes the three-line switch to enforced login.

## Images

`backend_server/Dockerfile`, `backend_host/Dockerfile`, `frontend/Dockerfile` are built
from the repo root (`context: ../..`) — no `.env` is baked in, configuration is injected
by compose. The frontend bakes `VITE_*` values at build time: change them in `.env` and
run `./launch.sh --rebuild`.
