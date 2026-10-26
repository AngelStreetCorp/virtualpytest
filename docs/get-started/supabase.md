# Supabase and authentication

VirtualPyTest stores its data in Supabase, which is the database and the login system. You never write SQL. This page covers where it runs and whether users must log in.

## Where Supabase runs

| Install path | Where the database runs | You do |
|---|---|---|
| [Docker stack](docker.md) | inside the stack, set up on first start | nothing |
| [One VM / Proxmox](proxmox.md) | on the same VM, set up by the installer | nothing |
| [Developer setup](local-dev.md) | either of the above, **or** a cloud project at [supabase.com](https://supabase.com) | see below |

<div data-technical>

Docker stack: `setup/docker/supabase/`, pinned official images, schema applied on first start. One VM:
the Supabase CLI via `setup/local/linux/database/install_supabase.sh`, schema applied by the installer.

</div>

### Using a cloud Supabase project

1. Create a project and note its keys and connection details.
2. Set up the tables once.
3. Put the values in your settings file.

<div data-technical>

Settings: *Settings → API* gives the URL, anon key, service-role key and JWT secret. *Settings → Database*
gives the direct connection string.

```bash
./setup/db/apply_schema.sh "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
./setup/db/apply_schema.sh --dry-run     # lists the files without applying
```

This applies every file in `setup/db/schema/` (the fresh-install path). Files in `setup/db/migrations/`
are for databases that already exist. Do not apply them to a new one.

In `.env`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`SUPABASE_DB_URI`. For a login page, in `frontend/.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.

</div>

## Authentication: open mode or login

- **Open mode (the default on a fresh install):** no login. Use it only on a trusted network.
- **Login enforced:** people sign in with a Supabase account.
- **Public key:** a shared key that only slows down bots. It is not real login.
- **Closed:** every anonymous call is refused.

<div data-technical>

| Posture | `.env` | Effect |
|---|---|---|
| **Open mode** (fresh-install default) | `SERVER_OPEN_MODE=true` | no login: the UI works with no account. A direct call (`curl`, a script) still needs `X-API-Key` when `API_KEY` is set, but that only stops casual scanning — trusted network only. The installers print a warning while this is on. |
| **Login enforced** | `SERVER_OPEN_MODE=false` + `SUPABASE_JWT_SECRET=<secret>` | browser users sign in with a Supabase account (JWT); hosts and scripts use `API_KEY`. |
| **Public key** (no Supabase login) | `SERVER_PUBLIC_KEY=<weak key>` | the SPA sends the key as `X-Server-Key`. A bot speed bump, not authentication. |
| Closed | none of the above | every anonymous call gets 401. |

The server reads these three variables in `.env` in this order of precedence, and treats calls to `/server/*` accordingly.

</div>

### Enforce login

To turn login on, switch off open mode, give the web app the public values, and restart.

<div data-technical>

**Docker stack**, in `setup/docker/.env`:

```bash
SERVER_OPEN_MODE=false
VITE_SUPABASE_URL=http://<PUBLIC_HOST>:54321
VITE_SUPABASE_ANON_KEY=<the ANON_KEY value from the same file>
```

Then recreate the server and frontend containers (`docker compose … up -d --force-recreate
--no-deps backend_server frontend`; the frontend reads `VITE_*` at container start).
`JWT_SECRET` is already generated and already passed to the server as `SUPABASE_JWT_SECRET`.
Behind an HTTPS proxy or tunnel, the Supabase gateway needs a public hostname of its own, and GoTrue must
know it (`SUPABASE_PUBLIC_URL`, `SITE_URL`). The worked example is
[Google Cloud standalone §9.6](gcp-standalone.md#96-wire-the-stack-to-the-hostnames).

**One VM**: in `/opt/virtualpytest/.env`, set `SERVER_OPEN_MODE=false` (`SUPABASE_JWT_SECRET` is already
there). In `/opt/virtualpytest/frontend/.env`, set `VITE_SUPABASE_URL=http://<PUBLIC_HOST>:54321` and
`VITE_SUPABASE_ANON_KEY=<SUPABASE_ANON_KEY from .env>`. Then:

```bash
sudo systemctl restart vpt-server
cd /opt/virtualpytest && sudo -u vpt_user ./setup/local/linux/frontend/launch_frontend_prod.sh --build   # or re-run install_frontend.sh
```

</div>

**Create the first user.** Add one in the admin screens, or let people sign up. New accounts start as viewers. Make the first admin by hand, once. After that, manage roles under *Users*.

<div data-technical>

Studio, for adding the first user: *Authentication* → *Add user*. Docker: `http://<PUBLIC_HOST>:54321`,
basic-auth `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`. One VM: `http://<PUBLIC_HOST>:54323`.

Without a mail relay, accounts work at once. With `SMTP_*` set and `ENABLE_EMAIL_AUTOCONFIRM=false`
(Docker stack), sign-up sends a confirmation link first. **Every new account is a `viewer`.**

Promote the first admin by SQL:

```sql
update public.profiles set role='admin' where email='…'
```

Run it on the database (Docker: `docker exec vpt-supabase-db psql -U postgres -c "…"`). Roles are admin,
tester or viewer.

</div>

### Row-level security

The public key cannot read the app's tables. A fresh install sets this up. An older install needs one manual step.

<div data-technical>

Since September 2026 the server and hosts write with the **service-role key**, and the anonymous key has no
access to application tables. `setup/db/apply_schema.sh` produces that state on a fresh database: it
applies `setup/db/schema/` (which still carries the historical open policies), then, as its last step, the
idempotent lockdown migration `setup/db/migrations/20260908b_close_app_tables_to_public_key.sql`.

An existing database installed earlier must apply that same migration by hand. Do it **after** every
server and host has `SUPABASE_SERVICE_ROLE_KEY` in its `.env`. The migration header says so.

</div>

## Operations

Everyday database tasks: admin screens, backup, restart and upgrade. The commands differ by install.

<div data-technical>

| Task | Docker | One VM |
|---|---|---|
| Studio | `http://<PUBLIC_HOST>:54321` | `http://<PUBLIC_HOST>:54323` |
| psql | `docker exec -it vpt-supabase-db psql -U postgres` | `psql postgresql://postgres:<password>@localhost:54322/postgres` |
| Backup | `docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql` | daily `pg_dump` via `/etc/cron.d/vpt-db-backup` (installed by `install_supabase.sh`) |
| Restart | `./setup/docker/launch.sh` | `sudo systemctl restart supabase` |
| Upgrade Supabase | bump the tags in `setup/docker/supabase/docker-compose.yml` | `supabase stop && supabase start` after updating the CLI |

</div>
