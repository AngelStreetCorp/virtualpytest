# Configuration reference

Every variable the platform reads, where it lives, and which install path fills it for you.
Three files, one per component — the installers create all three:

| File | Read by | Docker stack | One-VM install |
|---|---|---|---|
| `.env` (repo root) | server, shared library, scripts | `setup/docker/.env` + compose `environment:` | `setup/local/linux/shared/write_env.sh` |
| `backend_host/src/.env` | device controller (host) | mounted as-is; URLs overridden by compose | `write_env.sh` |
| `frontend/.env` | web UI — **at build time** (Vite bakes `VITE_*` in; rebuild after a change) | compose `build.args` from `setup/docker/.env` | `write_env.sh`, before `install_frontend.sh` builds |

Templates: `.env.example`, `backend_host/src/.env.example`, `frontend/.env.example`,
`setup/docker/.env.example`. A value the installer generated is safe to change by hand;
re-run `write_env.sh` (VM) or `./setup/docker/launch.sh --rebuild` (Docker) afterwards.

## Ports

| Port | Service | Docker | One VM |
|---|---|---|---|
| 5073 | Web UI | ✓ | ✓ (`vpt-frontend-prod`) |
| 5109 | Server API (`/server/health`) | ✓ | ✓ (`vpt-server`) |
| 6109 | Host API (`/host/health`) | ✓ | ✓ (`vpt-host`) |
| 6080 | Host desktop, noVNC | ✓ | ✓ |
| 3000 | Grafana | ✓ | ✓ (`grafana-server`) |
| 54321 | Supabase API gateway (+ Studio on Docker) | ✓ | ✓ |
| 54322 | Postgres | ✓ | ✓ |
| 54323 | Supabase Studio | — (Studio is on 54321) | ✓ |
| 9000 / 9001 | MinIO S3 / console | ✓ | ✓ |
| 6379 | Redis | internal only | ✓ (`REDIS_PASSWORD`, generated per install) |

## Server — `.env`

| Variable | Meaning | Default / who sets it |
|---|---|---|
| `SERVER_NAME` | label shown in the UI and in host registrations | installer |
| `SERVER_URL` | address browsers and hosts use for the server API | `http://<PUBLIC_HOST>:5109`, installer |
| `SERVER_PORT` | listen port | `5109` |
| `API_KEY` | shared secret between the server and every host (`X-API-Key`). **Identical on all hosts.** | generated |
| `FLASK_SECRET_KEY` | Flask session secret | generated |
| `SERVER_OPEN_MODE` | `true` = no browser **login** on `/server/*` (default for fresh installs, trusted network only). Direct non-browser calls still send `X-API-Key` when `API_KEY` is set | `true`, installer |
| `SUPABASE_JWT_SECRET` | enables login: browser JWTs are verified with it. Ignored while `SERVER_OPEN_MODE=true` | from the Supabase install |
| `SERVER_PUBLIC_KEY` / `SERVER_PUBLIC_ROLE` | no-Supabase deployments: weak key the SPA sends as `X-Server-Key` (must differ from `API_KEY`) | unset |
| `CORS_ALLOWED_ORIGINS` | comma-separated browser origins allowed to call `/server/*` cross-origin; only needed when the frontend is on a different origin than this server. **No `*` fallback** (BUG-0092) | the vendor's own known frontend domains |
| `AUTO_SIGN_ENABLED` / `AUTO_SIGN_TOKEN` / `AUTO_SIGN_ROLE` | CI / agent-browser bypass of the login | `false` |
| `SUPABASE_URL` | Supabase API base (REST + auth) | `http://localhost:54321` (VM) · `http://api-gw:8000` (Docker, internal) |
| `SUPABASE_ANON_KEY` | public key (row-level security applies) | from the Supabase install |
| `SUPABASE_SERVICE_ROLE_KEY` | server-side key, bypasses RLS. Never in the frontend. | from the Supabase install |
| `SUPABASE_DB_URI` | direct Postgres URI — Grafana datasource and backups only | `postgresql://postgres:postgres@localhost:54322/postgres` |
| `CLOUDFLARE_R2_ENDPOINT` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` / `_BUCKET` / `_PUBLIC_URL` | Cloudflare R2 object storage. Takes precedence over MinIO when the three credentials are set. `_PUBLIC_URL` set = direct links, unset = presigned links | unset |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET` / `MINIO_PUBLIC_URL` | self-hosted S3 (MinIO). `MINIO_PUBLIC_URL` is what browsers use | `http://localhost:9000`, `admin` / generated per install, `virtualpytest` |
| `REDIS_URL` (+ `REDIS_TOKEN` for Upstash) | alert / script queues | `redis://:<REDIS_PASSWORD>@localhost:6379/0` (password generated per install) |
| `GRAFANA_URL` | internal Grafana base the server calls (with sub-path when behind nginx) | `http://localhost:3000` |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | Grafana admin the server uses | `admin` / generated |
| `AI_AGENT_PROVIDER` / `AI_AGENT_MODEL` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `MINIMAX_API_KEY` | AI features (optional) | empty = AI features off |
| `MCP_SECRET_KEY` | bearer token for the MCP endpoint | generated |
| `ENVIRONMENT` / `DEBUG` | `production` / `0` | |

## Host — `backend_host/src/.env`

| Variable | Meaning | Default / who sets it |
|---|---|---|
| `HOST_NAME` | how this host appears in the UI | machine hostname / `docker-host` |
| `HOST_PORT` | listen port | `6109` |
| `HOST_URL` | address **browsers** use for this host (streams, screenshots) | `http://<PUBLIC_HOST>:6109` |
| `HOST_API_URL` | address the **server** uses for this host | `http://localhost:6109` (VM) · `http://backend_host:6109` (Docker) |
| `SERVER_URL` | where this host registers | `http://localhost:5109` (VM) · `http://backend_server:5109` (Docker) |
| `API_KEY` | same value as the server's | copied by the installer |
| `HOST_TYPE` | `host_vnc` (full, default) or a `runner_*` type — see the template's comments | unset |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | hosts write results themselves | same as the server |
| `MINIO_*` / `CLOUDFLARE_R2_*` | hosts upload captures themselves | same as the server |
| `HOST_VIDEO_SOURCE` / `HOST_VIDEO_AUDIO` / `HOST_VIDEO_CAPTURE_PATH` / `HOST_VIDEO_FPS` | the host's own VNC desktop as a capture source | `:1` / `null` / `/var/www/html/stream/capture` / `10` |
| `HOST_VNC_STREAM_PATH` / `HOST_VIDEO_STREAM_PATH` / `HOST_VNC_PASSWORD` | browser paths for the desktop view and the stream | template values, address swapped by the installer |
| `DEVICEn_NAME` / `_MODEL` / `_IP` / `_PORT` / `_VIDEO` / `_VIDEO_AUDIO` / `_VIDEO_CAPTURE_PATH` / `_VIDEO_FPS` / `_VIDEO_STREAM_PATH` | device *n* (1–10): identity, network address, capture card, audio, output paths | template examples, disabled with the `x` prefix |
| `DEVICEn_IR_PATH` / `_IR_TYPE` or `_IR_IP` / `_IR_PORT` / `_IR_LED` / `_IR_REMOTE` | infrared control: local `lirc` transmitter or networked IRTrans box | |
| `DEVICEn_BLE_TYPE` / `_BLE_ADAPTER_HCI` | Bluetooth remote emulation | |
| `DEVICEn_POWER_NAME` / `_POWER_IP` / `_POWER_EMAIL` / `_POWER_PWD` or `_POWER_API_URL` / `_POWER_API_KEY` | power control: Tapo plug or a REST API | |
| `DEVICEn_USERINTERFACE` / `_VARIANT` | default navigation model for scripts run on this device | |
| `VPT_KEEP_BROWSER_OPEN` | keep Playwright's browser between web scripts | unset |

The template `backend_host/src/.env.example` documents every device option inline.

## Frontend — `frontend/.env` (build time)

| Variable | Meaning | Default / who sets it |
|---|---|---|
| `VITE_SERVER_URL` | server API as seen from the browser | `http://<PUBLIC_HOST>:5109` |
| `VITE_GRAFANA_URL` | Grafana as seen from the browser | `http://<PUBLIC_HOST>:3000` |
| `VITE_CLOUDFLARE_R2_PUBLIC_URL` | public base for stored files (set = direct links) | MinIO: `http://<PUBLIC_HOST>:9000/virtualpytest` |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | login page. Both empty = no login (open mode) | empty |
| `VITE_SERVER_PUBLIC_KEY` | pairs with `SERVER_PUBLIC_KEY` (no-Supabase deployments) | unset |
| `VITE_AUTO_SIGN_ENABLED` / `VITE_AUTO_SIGN_TOKEN` | pairs with `AUTO_SIGN_*` | off |
| `VITE_DISABLED_FEATURES` | comma-separated feature names hidden from this build | empty |
| `VITE_PROJECT_NAME` / `_TAGLINE` / `_LOGO_URL` / `_TITLE` / `VITE_SHOW_FOOTER` | branding — see [branding.md](branding.md) | |
| `VITE_FEATURE_DEPLOYMENTS` · `VITE_NAV_HIDDEN` / `_DISABLED` / `_COMING_SOON` | feature toggle and navbar overrides (full route paths) | |
| `VITE_DEV_MODE` | dev-only conveniences | `false` |

## Docker stack — `setup/docker/.env`

Same names, plus the values the compose files need: `PUBLIC_HOST`, `POSTGRES_PASSWORD`,
`JWT_SECRET`, `ANON_KEY`, `SERVICE_ROLE_KEY` (compose maps them to `SUPABASE_*` for the
server and host), `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` (Studio), `PG_META_CRYPTO_KEY`,
`SUPABASE_API_PORT` / `SUPABASE_DB_PORT`, `GRAFANA_DB_PASSWORD`. `setup/docker/.env.example`
lists them all; `launch.sh` fills every `CHANGE_ME`.

## Versions the installers use

| Component | Version | Where it is pinned |
|---|---|---|
| Python | 3.11 (VM: system Python via `install_requirements.sh`; Docker: `python:3.11-slim`) | `backend_*/Dockerfile` |
| Node.js | 22 | `setup/local/linux/frontend/install_frontend.sh`, `frontend/Dockerfile` |
| Postgres | 17 (Supabase image) | `setup/docker/supabase/docker-compose.yml`, Supabase CLI `config.toml` |
| Supabase services | pinned tags in `setup/docker/supabase/docker-compose.yml`; VM path = current Supabase CLI | |
| Grafana | 11.6 (Docker) / distro package (VM) | |
| Docker Engine | 24+ with the `docker compose` v2 plugin | `setup/docker/install_docker.sh` |
