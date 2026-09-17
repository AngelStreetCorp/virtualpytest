# Supabase and authentication

VirtualPyTest stores everything in a Supabase project: Postgres for the data, Supabase Auth
for user accounts, PostgREST for the API the platform talks to. You never write SQL to use
the platform; this page is about **where that Supabase runs** and **whether users must log in**.

## Where Supabase runs

| Install path | Supabase | You do |
|---|---|---|
| [Docker stack](docker.md) | inside the stack (`setup/docker/supabase/`, pinned official images), schema applied on first start | nothing |
| [One VM / Proxmox](proxmox.md) | on the same VM via the Supabase CLI (`setup/local/linux/database/install_supabase.sh`), schema applied by the installer | nothing |
| [Developer setup](local-dev.md) | either of the above, **or** a cloud project at [supabase.com](https://supabase.com) | see below |

### Using a cloud Supabase project

1. Create a project; note its URL, anon key, service-role key and JWT secret
   (*Settings → API*), and the direct connection string (*Settings → Database*).
2. Apply the schema once, in order — the script stops on the first error:
   ```bash
   ./setup/db/apply_schema.sh "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
   ./setup/db/apply_schema.sh --dry-run     # lists the files without applying
   ```
   This applies every file in `setup/db/schema/` (the fresh-install path). Files in
   `setup/db/migrations/` are for databases that already exist — do not apply them to a new one.
3. Put the values in `.env` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_DB_URI`) and, if you want a
   login page, in `frontend/.env` (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`).

## Authentication: open mode or login

The server decides how to treat calls to `/server/*` from three variables in `.env`, in
this order of precedence:

| Posture | `.env` | Effect |
|---|---|---|
| **Open mode** (fresh-install default) | `SERVER_OPEN_MODE=true` | no login: the UI works with no account. A direct call (`curl`, a script) still needs `X-API-Key` when `API_KEY` is set, but that only stops casual scanning — trusted network only. The installers print a warning while this is on. |
| **Login enforced** | `SERVER_OPEN_MODE=false` + `SUPABASE_JWT_SECRET=<secret>` | browser users sign in with a Supabase account (JWT); hosts and scripts use `API_KEY`. |
| **Public key** (no Supabase login) | `SERVER_PUBLIC_KEY=<weak key>` | the SPA sends the key as `X-Server-Key`. A bot speed bump, not authentication. |
| Closed | none of the above | every anonymous call gets 401. |

### Enforce login

**Docker stack** — in `setup/docker/.env`:

```bash
SERVER_OPEN_MODE=false
VITE_SUPABASE_URL=http://<PUBLIC_HOST>:54321
VITE_SUPABASE_ANON_KEY=<the ANON_KEY value from the same file>
```
then `./setup/docker/launch.sh --rebuild` (the frontend bakes the two `VITE_*` values in).
`JWT_SECRET` is already generated and already passed to the server as `SUPABASE_JWT_SECRET`.

**One VM** — in `/opt/virtualpytest/.env` set `SERVER_OPEN_MODE=false` (`SUPABASE_JWT_SECRET`
is already there), in `/opt/virtualpytest/frontend/.env` set `VITE_SUPABASE_URL=http://<PUBLIC_HOST>:54321`
and `VITE_SUPABASE_ANON_KEY=<SUPABASE_ANON_KEY from .env>`, then:

```bash
sudo systemctl restart vpt-server
cd /opt/virtualpytest && sudo -u vpt_user ./setup/local/linux/frontend/launch_frontend_prod.sh --build   # or re-run install_frontend.sh
```

**Create the first user** in Supabase Studio → *Authentication* → *Add user* (Docker:
`http://<PUBLIC_HOST>:54321`, basic-auth `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`; VM:
`http://<PUBLIC_HOST>:54323`). Accounts are usable immediately — no confirmation mail is sent
by a self-hosted stack. The first user to sign in becomes the admin of the default team;
roles (admin / tester / viewer) are managed in the web UI under *Users*.

### Row-level security

Since September 2026 the server and hosts write with the **service-role key** and the
anonymous key has no access to application tables. `setup/db/apply_schema.sh` produces that
state on a fresh database: it applies `setup/db/schema/` (which still carries the historical
open policies) and then, as its last step, the idempotent lockdown migration
`setup/db/migrations/20260908b_close_app_tables_to_public_key.sql`. An existing database
that was installed earlier must apply that same migration by hand, **after** every server and
host has `SUPABASE_SERVICE_ROLE_KEY` in its `.env` — the migration header says so.

## Operations

| Task | Docker | One VM |
|---|---|---|
| Studio | `http://<PUBLIC_HOST>:54321` | `http://<PUBLIC_HOST>:54323` |
| psql | `docker exec -it vpt-supabase-db psql -U postgres` | `psql postgresql://postgres:postgres@localhost:54322/postgres` |
| Backup | `docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql` | daily `pg_dump` via `/etc/cron.d/vpt-db-backup` (installed by `install_supabase.sh`) |
| Restart | `./setup/docker/launch.sh` | `sudo systemctl restart supabase` |
| Upgrade Supabase | bump the tags in `setup/docker/supabase/docker-compose.yml` | `supabase stop && supabase start` after updating the CLI |
