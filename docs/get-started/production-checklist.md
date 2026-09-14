# Going to production — hardening checklist

The installers get you a working platform on a LAN in one command. They deliberately leave a
few things convenient rather than safe, and several services ship with **well-known default
passwords**. Before a deployment is reachable from the internet, or holds anything you care
about, walk this list top to bottom. Every item names the file or variable to change.

Companion pages: [Security setup](security.md) (TLS, firewall, VPN, CORS),
[Supabase](supabase.md) (auth modes, closed mode), [Configuration](configuration.md) (every
`.env` key), [Network](network.md).

## 0. Know what the installer already did for you

`setup/local/linux/shared/write_env.sh` **generates** a random `API_KEY`, `FLASK_SECRET_KEY`,
`MCP_SECRET_KEY` and Grafana admin password, and sets `AUTO_SIGN_ENABLED=false`.
`install_supabase.sh` generates a per-install Supabase JWT secret.

It **does not** change: the MinIO root credentials, the Redis password, the VNC password, the
Postgres superuser password, or the open-mode switch you passed at install time. Those are the
first section below.

## 1. Replace every default credential

| Service | Shipped default | Where to change | Also update |
|---|---|---|---|
| MinIO (object storage) | user `admin`, password `admin1234` | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` in `/etc/default/minio` (or the compose file), then `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `.env` and `backend_host/src/.env` | every host `.env`; restart `minio` and `vpt-server` |
| Redis | password `admin1234` | `REDIS_URL` in `.env`; `requirepass` in `redis.conf`; the `redis-commander` unit if installed | restart `redis`, `vpt-server` |
| VNC on every host | `admin1234` (`HOST_VNC_PASSWORD` in `install_host.sh`) | `HOST_VNC_PASSWORD` in `backend_host/src/.env`, then rewrite the password file: `echo "$HOST_VNC_PASSWORD" \| vncpasswd -f > ~vpt_user/.vnc/passwd` (what `install_host.sh` does) and restart the VNC unit | the `vnc_lite_*` pages read it from the host `.env`, nothing else to touch |
| Postgres superuser | `postgres` / `postgres` (`SUPABASE_DB_URI`) | `ALTER USER postgres PASSWORD '…'` and `ALTER USER supabase_admin PASSWORD '…'` in the DB, then `SUPABASE_DB_URI` in `.env`, Grafana's datasource, and `/etc/cron.d/vpt-db-backup` | restart `vpt-server`, `grafana-server` |
| Supabase JWT secret | per-install on new installs; **older installs may still carry the Supabase CLI default** (`super-secret-jwt-token-with-at-least-32-characters-long`) | `supabase/config.toml` → `jwt_secret`, then regenerate the anon and service-role keys, then `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` in `.env` and `VITE_SUPABASE_ANON_KEY` in `frontend/.env` | `supabase stop && supabase start`; every host `.env`; rebuild the frontend |
| Grafana | generated on install; `admin`/`admin` if you installed Grafana yourself | `GRAFANA_ADMIN_PASSWORD` in `.env` and `grafana.ini` `[security] admin_password`; set `secret_key` to a random value (the file ships Grafana's sample) | restart `grafana-server` |
| Server ↔ host key | generated | `API_KEY` must be identical on the server and every host; rotate if a host was ever cloned from another install (`host_postclone_configure.sh` copies it verbatim) | restart all `vpt-*` units |
| MCP | generated (`vpt_mcp_…`) | `MCP_SECRET_KEY` in `.env` | clients' bearer tokens |
| Windows hosts | TightVNC installed **without authentication** and a firewall rule opened for it (`install_host_windows.ps1`) | enable `UseVncAuthentication` and set a password, or keep the host on an isolated VLAN | — |

Generate values with `openssl rand -hex 24`. Never reuse a password across services: the server
holds all of them, a leak of one `.env` should not open everything.

## 1b. Rotation register — every secret the platform holds

Rotate all of these when a person with access leaves, when any `.env` or backup may have
been exposed, and on a schedule. Nothing here is generated twice: the value in `.env` is the
only copy, so rotating means "generate, write to `.env`, restart the unit(s)".

| Secret | Lives in | Used by | Rotate by | Then restart |
|---|---|---|---|---|
| `API_KEY` | `.env` + every host's `backend_host/src/.env` (identical) | server ↔ host calls, `X-API-Key` on admin routes, DB backup cron | `openssl rand -hex 32`, write to server and all hosts | `vpt-server`, every `vpt-host` |
| `MCP_SECRET_KEY` | `.env` | Bearer for `/server/mcp` (AI clients, IDE integrations) | new `vpt_mcp_<hex>`; update every MCP client config | `vpt-server` |
| `FLASK_SECRET_KEY` | `.env` | Flask session signing | new hex; all sessions log out | `vpt-server` |
| `SUPABASE_JWT_SECRET` + `SUPABASE_ANON_KEY` + `SUPABASE_SERVICE_ROLE_KEY` | `.env`, hosts' `.env`, `frontend/.env` (`VITE_SUPABASE_ANON_KEY`), `supabase/config.toml` | every login token, every DB call | see section 1 (JWT row); all three change together | Supabase stack, `vpt-server`, hosts, frontend rebuild |
| `AUTO_SIGN_TOKEN` | `.env`, `frontend/.env`, CI secrets | URL-based sign-in for CI/demos | new hex or disable; purge old CI reports that embedded the URL | `vpt-server`, frontend rebuild |
| `SERVER_PUBLIC_KEY` | `.env`, `frontend/.env` | no-login browser baseline | new value or unset; it is public by construction | `vpt-server`, frontend rebuild |
| MinIO root, Redis, VNC, Postgres, Grafana admin, `GRAFANA_SECRET_KEY` | see section 1 | — | see section 1 | see section 1 |
| `CLOUDFLARE_R2_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | `.env` (+ hosts if they upload) | object storage when R2 is used instead of MinIO | Cloudflare dashboard → R2 API tokens → create new, delete old | `vpt-server`, hosts |
| `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MINIMAX_API_KEY` | `.env` | AI agent, vision, text features | provider console; set spend limits | `vpt-server` |
| Langfuse public/secret keys (if tracing is on) | `.env` | agent tracing | Langfuse project settings | `vpt-server` |
| `GITHUB_TOKEN` (if the Run Command / CI features are enabled) | the `vpt-server` systemd unit `Environment=`, not `.env` | GitHub API from the server | GitHub → fine-grained token, minimal scopes, expiry set | `vpt-server` |
| CI secrets (`E2E_*`, role JWTs, `CICD_INGEST_TOKEN`, `CI_REPORTS_SSH_KEY`, `LEAK_TERMS`) | GitHub repository secrets (Actions **and** Dependabot stores) | workflows | `gh secret set …` for both stores | — |
| SSH keys: deploy user, CI reports key, jump host | `~/.ssh` on runners / operators | deploys, report upload | new keypair, replace `authorized_keys` entries | — |
| Host `.env` on Windows/Linux hosts | `backend_host/src/.env` | same as server copies | mirror the server rotation | `vpt-host` |

Quick inventory of what is set (never prints values):

```bash
grep -oE '^[A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|PASS)[A-Z_]*=' .env backend_host/src/.env frontend/.env | sort -u
```

## 2. Close the authentication switches

| Switch | Meaning | Production value |
|---|---|---|
| `SERVER_OPEN_MODE` | `true` = every `/server/*` call is accepted **without any credential** and runs as admin. The quick-start installers may set it to `true` so the UI works before Supabase Auth is configured. | `false` (or remove the key). Then configure Supabase Auth ([supabase.md](supabase.md), "Closed" mode) so users log in. |
| `SERVER_PUBLIC_KEY` / `SERVER_PUBLIC_ROLE` | a key baked into the frontend bundle that lets a browser call the server without a login; the role it grants defaults to `admin` | unset, or `SERVER_PUBLIC_ROLE=viewer` at most. Anyone who can load the UI can read the key. |
| `AUTO_SIGN_ENABLED` / `AUTO_SIGN_TOKEN` / `AUTO_SIGN_ROLE` | `?auto_signed=<token>` on any URL signs the visitor in with `AUTO_SIGN_ROLE`; meant for CI and demos | `false`. If you need it for CI, give it a random token, role `tester`, and rotate it after every exposure (it travels in URLs and logs). |
| `VITE_DEV_MODE` | dev conveniences in the UI | `false` |
| Supabase `anon` key | the public key the UI uses to log in; it must **not** be able to read application tables | run `setup/db/apply_schema.sh` on the current schema: RLS is on and only `service_role` is granted. Verify: `curl -H "apikey: <anon>" http://db:54321/rest/v1/device` must return an error, not rows. |

## 3. Expose only what has to be public

Put nginx in front of everything and let it be the only listener on 80/443
([security.md, Part C](security.md#part-c-network-security)). Then check each of these,
because some install docs and the LAN-oriented nginx templates open them:

| Surface | Default port | Production |
|---|---|---|
| Supabase Studio | 54323 | **never on the internet**. LAN only, or behind nginx basic auth. Studio has no login of its own and runs SQL as the DB owner. |
| Supabase REST / pooler | 54321 / 54322 | server and hosts only (firewall to their addresses) |
| MinIO console / Redis Commander | 9001 / 8081 | LAN or VPN only; remove the `/minio-console/` and `/redis/` locations from any public nginx file |
| MinIO API | 9000 | the UI needs to read stored files. Prefer a **private bucket + presigned URLs** ([R2_PRIVATE_BUCKET_GUIDE](../technical/architecture/R2_PRIVATE_BUCKET_GUIDE.md)); if you keep the bucket readable, make sure only `virtualpytest/` is, and nothing else on that MinIO |
| Grafana | 3000 | through `/grafana/` only; disable anonymous access and sign-up (`grafana.ini`), see [security.md](security.md#grafana) |
| `/ci-reports/` | nginx alias | reports can contain URLs with tokens (see auto-sign). Either drop the location or protect it with basic auth |
| Host API / VNC / noVNC / websockify | 6109 / 5901 / 6080 | reachable **only from the server** and via the nginx `/host/<name>/…` proxy; never bind VNC to a public interface |
| Postgres direct | 5432 | never public |
| Chrome DevTools ports on hosts (Windows: 9222/9223) | — | localhost only |
| SSH | 22 | keys only, `PasswordAuthentication no`, restrict to a management network or VPN |

Then run a scan from outside: `nmap -sT -p- <public-ip>` should show 22 (if at all), 80 and 443.

## 4. Least privilege on the hosts

- `setup/local/linux/backend_host/sudoers.d/run-command` ships a scoped NOPASSWD list; the
  optional `vpt_user ALL=(ALL) NOPASSWD: SETENV: ALL` line makes the service user root.
  Remove it unless you rely on Run Command for system administration.
- Do not add your own user to passwordless sudo on hosts to make deploys easier; use the
  deploy scripts' dedicated user.
- Stream and lock files are created world-writable by some scripts; keep hosts single-tenant.
- NFS exports for shared storage: no `no_root_squash` on a network you do not fully control.
- Disable `git pull` in service `ExecStartPre` lines (`vpt_server_host.service`) on
  production; deploy from a pinned release instead ([RELEASING](../release_note/README.md)).

## 5. Data, backups, retention

- Daily `pg_dump` is installed by `install_supabase.sh` (`/etc/cron.d/vpt-db-backup`); copy the
  dumps **off the machine** and test a restore once.
- Back up the MinIO bucket (reference images, reports, recordings) the same way.
- Recordings and screenshots can contain what is on the screen under test, and the gateway
  telemetry tables can contain subscriber identifiers. Set a retention and make sure the bucket
  is not public if that matters to you.
- Keep `.env` files at mode 600, owned by the service user. The frontend `.env` is read at
  build time only; do not leave it world-readable on the web root.

## 6. CI runners

- Self-hosted runners execute whatever a pull request contains. On a **public** repository, set
  *Require approval for all outside collaborators* (Settings → Actions) and keep PR-triggered
  jobs on GitHub-hosted runners; reserve self-hosted runners for `main` and manual dispatch.
- Runners should not hold SSH keys to production; give them a deploy user with a scoped key.

## 7. Keep it that way

- Rotate the credentials in section 1 on a schedule and whenever a person with access leaves.
- Subscribe to the [release notes](../release_note/README.md); security fixes are marked 🔒 in
  the [bug index](../bugs/README.md).
- Run `scripts/security/unauth_route_sweep.sh` against your own deployment after every
  upgrade: every `/server/*` route must answer 401 without a token.
- Grafana datasource: give it a **read-only** DB role, not `postgres`.
- fail2ban on SSH and nginx, unattended security upgrades on every VM.

## Quick self-check

```bash
# anything still on a default?
grep -nE 'admin1234|postgres:postgres|CHANGE_ME|SERVER_OPEN_MODE=true|AUTO_SIGN_ENABLED=true' \
  .env backend_host/src/.env frontend/.env
# anonymous REST must be closed
curl -s -o /dev/null -w '%{http_code}\n' -H "apikey: $SUPABASE_ANON_KEY" "$SUPABASE_URL/rest/v1/device?select=id&limit=1"   # expect 401/403
# server closed without a token
curl -s -o /dev/null -w '%{http_code}\n' "$SERVER_URL/server/health"   # expect 401 (health may be allow-listed: check another route)
```

If any line prints a match or a 200, you are not done.
