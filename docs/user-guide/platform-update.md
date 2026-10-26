<!-- toc: h2 -->
<!-- compact -->
# Platform update

Update the install in 7 steps:

<a id="step-0"></a>
## 0 Prerequisites

Checks that the machines are ready.

**You do**
- Press **Run checks**.
- Open each KO row and follow its fix.
- Done when no required check is KO.

**If it fails**
- Fix the KO row, then press **Run checks** again.
- A host does not answer: restart its host service.
- A host cannot download: the row names the setting that differs (`SERVER_URL` or `API_KEY`) and the `.env` line to set on that host (the key value is never shown; copy it from the server's `.env`).
- Settings (frontend host, SSH user and key, database connection, GitHub token) are saved in the database for this server; GitLab is set in Plugins → GitLab.

<div data-technical>

On the host: `sudo systemctl start vpt-host`.

</div>

<details>
<summary>More details</summary>

The badge next to the page title shows each check, its log and its fix. A deploy is refused while a *required* check
is KO.

<div data-technical>

The server runs the update. It backs up and builds the bundle (steps 1 and 2). Each host downloads the bundle from the
server (step 3). The frontend VM gets it over SSH. The server updates itself last. The database is updated from the
server with a connection string (step 4).

Paths assume the standard install in `/opt/virtualpytest`, the service account `vpt_user` and `.env` at
`/opt/virtualpytest/.env`. After editing an `.env`, restart the service that reads it (`sudo systemctl restart vpt-server`
or `vpt-host`).

</div>

| Check | Required when | Where to set it up |
|---|---|---|
| [Server to frontend VM over SSH](#frontend-ssh) | always (`FRONTEND_DEPLOY_HOST` must be set; `none` makes it N/A) | server, frontend VM |
| [Server to every host API](#hosts-api) | there are hosts | server, hosts |
| [Hosts download from the server](#hosts-download) | there are hosts | hosts |
| [Server to database](#database) | migrations are pending | server |
| [Database backup on request](#db-backup) | always | database VM, server |
| [Tools](#tools) | always | server, hosts |
| [Disk space](#disk) | always | server, hosts |
| [Sudo rights](#host-sudo) | always | every host and the server |
| [Host version](#host-version) | there are hosts | each host, once |
| [GitHub](#source-github) | the core or the overlay comes from GitHub | server |
| [GitLab](#source-gitlab) | the overlay comes from GitLab | server |
| [No test run in progress](#no-test-running) | never (warning) | none |

Setup, one check at a time (the Prerequisites dialog links straight to each):

<details>
<summary><a id="frontend-ssh"></a>Server to frontend VM over SSH</summary>

**What.** The server deploys the frontend over SSH. You choose where the frontend lives. You must set it.

| Value | Meaning |
|---|---|
| a host name or IP | a separate frontend VM, updated over SSH |
| `local` | the frontend runs on the server VM itself |
| `none` | there is no frontend to update |
| not set | undecided: the check turns KO |

**Set up.** Press *Set up frontend VM* (on this check's row, or in **Settings → Frontend VM**). Type the frontend VM's address, an
admin account (`root`, or an account that can use `sudo` with its password) and its password once. The server logs in, creates
the deploy account, installs its key and the sudo rights, saves the settings and forgets the password; the check then runs again.

Without the button: open **Settings → Server key**, press *Create key*, copy the one command the page shows and run it as root
on the frontend VM (it does the same), then press *Re-check*.

<div data-technical>

The page does steps 1 to 3 below for you: **Settings → Server key** creates the key as the server's user (never over an existing
one) and shows the public key, the `authorized_keys` line with `from=` and the one root command for the frontend VM. A failing
row in the Prerequisites list shows the same command. Do the steps by hand only if you prefer.

**Why over SSH:** the frontend VM serves static files and has no host service to pull with. The bundle is copied to
`/var/tmp/vpt_bundle_incoming`. Then the code sync and the frontend build run as `vpt_user`, and `vpt-frontend` is
restarted. The older *Code deployment* buttons read the same setting.

1. On the frontend VM, create the deploy account and install the sync tool:

   ```bash
   sudo adduser --disabled-password --gecos '' deploy
   sudo apt-get install -y rsync
   ```

2. On the server, as `vpt_user`, create a key and allow it on the frontend VM. Reuse the key if it exists.
   `vpt_user` is a system account; its home is not under `/home` (on our installs `/var/lib/vpt_user`; check with
   `getent passwd vpt_user`). Reuse `~vpt_user/.ssh/id_ed25519` if it exists.

   ```bash
   H=$(getent passwd vpt_user | cut -d: -f6)
   sudo install -d -o vpt_user -g vpt_user -m 0700 "$H/.ssh"
   sudo test -f "$H/.ssh/id_ed25519" || sudo -u vpt_user ssh-keygen -t ed25519 -N '' -f "$H/.ssh/id_ed25519"
   sudo cat "$H/.ssh/id_ed25519.pub"   # then put it in /home/deploy/.ssh/authorized_keys on the frontend VM,
                                       # prefixed with from="<server address>",no-port-forwarding,no-agent-forwarding
   ```

3. On the frontend VM, give the deploy account its rights with the drop-in `setup/sudoers/vpt-update-frontend`. It allows
   only running as `vpt_user` and restarting the frontend. If your account is not called `deploy`, edit both `deploy`
   lines first.

   ```bash
   sudo install -o root -g root -m 0440 /opt/virtualpytest/setup/sudoers/vpt-update-frontend /etc/sudoers.d/vpt-update-frontend
   sudo visudo -cf /etc/sudoers.d/vpt-update-frontend
   ```

   The file allows `sudo -u vpt_user` for **any** command, on purpose. The sync runs `code-deploy.sh` from a staging folder
   this account writes, so a narrower rule could not constrain it. Treat the deploy account as `vpt_user`: a dedicated key
   used only by the server (prefix it with `from="<server address>"` in `authorized_keys`), no password login. It gets
   root only for the one restart.

4. On the server, open **Platform update → Settings** and fill *Frontend host* (the frontend VM address, `local` or `none`),
   *SSH user* and, if you do not use `vpt_user`'s default key, *SSH key path*. Save re-runs the checks. The values are
   stored on the server (not in a file in the project). Alternatively, the server's `.env` is read where nothing is saved
   in Settings:

   ```
   FRONTEND_DEPLOY_HOST=<frontend-vm address>
   FRONTEND_DEPLOY_SSH_USER=deploy
   # optional, with their defaults:
   # FRONTEND_DEPLOY_SSH_KEY=<vpt_user home>/.ssh/id_ed25519   (ssh's default key of vpt_user)
   # FRONTEND_DEPLOY_TARGET_DIR=/opt/virtualpytest
   # FRONTEND_DEPLOY_SERVICE_NAME=vpt-frontend
   # FRONTEND_DEPLOY_SERVICE_USER=vpt_user
   # FRONTEND_DEPLOY_BACKUP_ROOT=/var/tmp/virtualpytest_backups
   ```

   A password works instead of a key (what the older deploy button used): set `FRONTEND_DEPLOY_SSH_PASSWORD` and install
   `sshpass` on the server. A key is preferred, because with a password the remote `sudo -S` line carries it on the SSH
   command line.

The first connection records the frontend VM's host key (`StrictHostKeyChecking=accept-new`). To check it first:
`sudo -u vpt_user ssh deploy@<frontend-vm> true`.

</div>

**Verify.** From the server, the connection works without a password prompt. Then press *Re-check*.

<div data-technical>

```bash
sudo -u vpt_user ssh -o BatchMode=yes deploy@<frontend-vm> 'echo ok; command -v rsync; sudo -n -H -u vpt_user true; sudo -n -l systemctl restart vpt-frontend'
```

All four must succeed without a password prompt.

</div>

</details>

<details>
<summary><a id="hosts-api"></a>Server to every host API</summary>

**What.** The server reaches each host's API. Hosts that are registered but do not answer are listed.

**Set up.** Open the host's API port from the server, and use the same API key on both sides.

**Verify.** From the server, the host's health answers OK. If not, start the host service on the host: the KO row shows
the command for each host that does not answer (`sudo systemctl start vpt-host`) with a **Copy** button. Run it on that
host, then press **Re-check**. The page cannot start the service for you: a stopped host cannot receive the request, and
the server has no other way into the machine.

<div data-technical>

Why: the server starts the pull on each host and checks that it came back. It must reach `http(s)://<host>:6109`, and
`API_KEY` must be the same in the server's and the host's `.env`.

```bash
curl -s -H "X-API-Key: $API_KEY" http://<host>:6109/host/system/health   # answers {"status":"ok",...}
```

If it does not answer, run `sudo systemctl start vpt-host` on the host.

</div>

</details>

<details>
<summary><a id="hosts-download"></a>Hosts download from the server</summary>

**What.** Each host downloads a test file from the server. A blocking firewall is the usual cause.

**Set up.** On each host, the server address must be the one the host uses. The API key must match the server's.

**Verify.** Run the check from the host. A short JSON reply is good. `401` means a wrong key. A timeout means the network
path is closed.

<div data-technical>

Why: the hosts pull the update, so the host-to-server path must work. Hosts already use this path to register. Set
`SERVER_URL` and `API_KEY` in the host's `.env`. When they differ from this server's, the KO row says which one, per host ("host-x: SERVER_URL is http://a, this server is http://b" or "host-x: API_KEY differs from this server's") and shows the line to set. Allow outbound HTTPS (or HTTP on a LAN). The host downloads only from
`SERVER_URL`.

```bash
curl -s -H "X-API-Key: $(grep ^API_KEY= /opt/virtualpytest/.env | cut -d= -f2-)" "$(grep ^SERVER_URL= /opt/virtualpytest/.env | cut -d= -f2-)/server/platform-update/bundle/ping"
```

The answer is JSON with `"body":"vpt-update-ping"` and a `sha256`.

</div>

</details>

<details>
<summary><a id="database"></a>Server to database</summary>

**What.** Step 4 applies database changes from the server. It is required only when changes are pending.

**Set up.** Give the server a database connection string. The role must be allowed to create and change tables in
`public`. On an existing database, mark the already-applied files as described in [step 4](#step-4).

**Verify.** The check must get an answer from the server.

<div data-technical>

Why: the server is the one machine allowed to reach the database. Enter the string in **Platform update → Settings →
Database connection** (it is stored on the server and never shown again, only *set*). Where nothing is saved there, the
server's `.env` is read, first one found wins: `PLATFORM_UPDATE_DB_URI`, `SUPABASE_DB_URI`, `DATABASE_URL`:

```
PLATFORM_UPDATE_DB_URI=postgresql://postgres:<password>@<db-host>:5432/postgres
```

The migration tracker table is created the first time, in step 4 (*Create tracker*).

```bash
psql "$PLATFORM_UPDATE_DB_URI" -c "select to_regclass('public.applied_migrations')"   # empty until the tracker exists
```

</div>

</details>

<details>
<summary><a id="db-backup"></a>Database backup on request</summary>

**What.** Step 1 asks the database machine for a fresh backup, and waits up to 20 minutes. It is OK when the agent
answers, or when the last nightly backup is under 24 hours old.

**Set up** (once): in **Platform update → Settings**, press **Set up DB backup**. The page makes the token, keeps it on
the server and shows one command. Run that command as root on the database machine (keep your existing `--containers`
value), then press **Re-check**. The command is shown once; pressing the button again makes a new token and the
database machine must run the new command. The action stays off unless both sides have the token. The manual steps
below do the same by hand.

**Verify.** From the server. It only reads the state. `401` is a wrong token. `404` means the action is not enabled.

<div data-technical>

Why: the server does not run `pg_dump` itself, because its client can be older than the database. The database machine
makes the nightly backup at 02:00 (`/usr/local/bin/vpt-db-backup.sh`, `pg_dump` from inside the database container, copied
to `/data/backups` and the NFS share). The agent starts the same script as its own unit, `vpt-db-backup.service`, outside
the agent's sandbox so it can write `/data/backups`. Details are in `infra/vm_agent/README.md`.

1. The manual way. On the database VM, as root, create the token and install the agent. `192.168.x.103` is the server. Keep `127.0.0.1`
   for a local test:

   ```bash
   openssl rand -hex 32 > /root/vm_agent_token && chmod 600 /root/vm_agent_token
   sudo ./install.sh --containers supabase_db_supabase,supabase_rest_supabase,supabase_auth_supabase,supabase_kong_supabase,supabase_storage_supabase,supabase_studio_supabase,supabase_pg_meta_supabase --allow 192.168.x.103,127.0.0.1 --action db-backup --action-token-file /root/vm_agent_token
   ```

   Use the same `--containers` and `--allow` your agent already has. Re-running `install.sh` rewrites its settings. With
   `--action db-backup`, `install.sh` also installs `vpt-db-backup.service` (not enabled, not started: the agent starts it).
   Also copy the current `setup/local/linux/database/vpt-db-backup.sh` to `/usr/local/bin/vpt-db-backup.sh`. This version
   reads `VPT_API_KEY` from `/etc/cron.d/vpt-db-backup`, so it can report when the agent starts it.

2. Give the server the token: *Settings → Database agent* (`host:port`; the token is saved by *Set up DB backup*), or, as
   the `.env` fallback, add the token and list the database agent as `database`, then `sudo systemctl restart vpt-server`:

   ```
   VM_AGENT_ACTION_TOKEN=<the content of /root/vm_agent_token>
   INFRA_VM_AGENTS=database=192.168.x.102:9110,...
   ```

```bash
curl -s -H "X-VM-Agent-Token: $(grep ^VM_AGENT_ACTION_TOKEN= /opt/virtualpytest/.env | cut -d= -f2-)" http://192.168.x.102:9110/actions/db-backup
```

The answer is JSON with `running` and `exit_code`. To make a backup by hand, on the database VM:
`sudo systemctl start vpt-db-backup.service` (or `sudo bash /usr/local/bin/vpt-db-backup.sh`).

</div>

</details>

<details>
<summary><a id="tools"></a>Tools</summary>

**What.** The server and each host need a few standard tools. When one is missing, the row shows one ready line per
machine, built for that machine's own package manager (apt, dnf, apk or pacman). Installing needs root, so the page
only shows the line: copy it, run it on that machine, then press *Re-check*. macOS ships an old bash, so install a
newer one before you use it as a server.

**Verify.** Each tool prints its version.

<div data-technical>

Why: the bundle is built on the server and synced onto each machine with rsync. The server never runs `pg_dump`. The
server needs `git`, `tar`, `rsync`, `python3`, `bash` 4 or newer, and `zip` (for the default zip format). Each host needs
`rsync`, `tar`, `sudo` and `bash`.

`sudo apt-get install -y git rsync zip tar python3 bash` (server), `sudo apt-get install -y rsync tar sudo bash` (hosts).

There is no Install button on purpose: the update's sudoers file allows only the service restarts and the reconcile
helper, and the app never takes root. The line names only the tools that are missing, e.g. `sudo dnf install -y rsync zip`.
A host reports its package manager in `updatePrereqs`; if none of the four is found, the row names the missing tools
and no line is shown.

`git --version && rsync --version | head -1 && zip -v | head -2 && bash -c 'echo ${BASH_VERSINFO[0]}'`

</div>

</details>

<details>
<summary><a id="disk"></a>Disk space</summary>

**What.** The server needs 2 GB free where it builds bundles. Each host needs 1 GB free for the project, plus room for one
backup. Every update takes a backup first, and the last 5 are kept.

**Set up.** Press **Free space** on the KO row. The page first lists what would go (a dry run: saved `.env` sets, built
bundles and the previous trees `deploy_bundle.sh` keeps, beyond the newest five of each, with their sizes), and deletes
only after you confirm. It then shows the space freed and re-checks. This frees the **server** only; on a host, remove old
backups by hand or enlarge the disk.

**Verify.** Check the free space on each machine.

<div data-technical>

Why: each update backs up first. The server's build space is its integration state folder, `VPT_CONFIG_DIR` or the
default. A host's backup needs as much room as the project tree, at least 1 GB, in `/var/tmp/virtualpytest_backups`. Old
bundles are in the server's `platform-update/bundles` folder.

`ls /var/tmp/virtualpytest_backups` · `df -h /var/tmp /opt/virtualpytest`

</div>

</details>

<details>
<summary><a id="host-sudo"></a>Sudo rights on hosts and on the server</summary>

**What.** The update restarts services and system units, which needs root. It is allowed without a password, for the listed
commands only.

**Set up.** The failing row shows, for each machine, the exact command to run as root. Copy it, run it on that machine, then
press *Re-check*. Run it again after an update that changes the reconcile script (the row says "older than the tree").

**Verify.** As the service user, each command prints its allowed form, not "a password is required".

<div data-technical>

Why narrow: the rule allows exactly these commands. The reconcile step runs a **root-owned copy** of its script, so the
service user cannot edit it to get root. Keep the service user's write access to the project to what the product needs.
A frontend that runs on the server itself (`FRONTEND_DEPLOY_HOST=local`) needs the same rule.

```bash
sudo bash /opt/virtualpytest/setup/sudoers/install_vpt_update_sudoers.sh
# project not in /opt/virtualpytest: add --project-root <dir>
```

The helper copies the script `reconcile_feature_units.sh` to `/usr/local/sbin/vpt-reconcile-feature-units` and its
library `lib/feature_units.sh` to `/usr/local/lib/vpt-update/feature_units.sh`. It validates the drop-in with `visudo -cf` and installs it 0440. The rule
file is `setup/sudoers/vpt-update`:

```
Cmnd_Alias VPT_UPDATE = \
    /usr/bin/systemctl restart vpt-host, \
    /usr/bin/systemctl restart vpt-server, \
    /usr/bin/systemctl restart vpt-frontend, \
    /usr/local/sbin/vpt-reconcile-feature-units --project-root /opt/virtualpytest

vpt_user ALL=(root) NOPASSWD: VPT_UPDATE
```

The check turns KO with "installed reconcile helper is older than the tree" when the installed copy differs from the
project's copy (compared by sha256). `update_core.sh` on a deploy node runs the project's copy with its own sudo and is
not affected. The opt-in `run-command` drop-in also satisfies the restart check, but it is much broader.

```bash
sudo -u vpt_user sudo -n -l systemctl restart vpt-host
sudo -u vpt_user sudo -n -l /usr/local/sbin/vpt-reconcile-feature-units --project-root /opt/virtualpytest
ls -l /usr/local/sbin/vpt-reconcile-feature-units   # -rwxr-xr-x root root
```

</div>

</details>

<details>
<summary><a id="host-version"></a>Host version supports bundle pull</summary>

**What.** A host must be new enough to pull a bundle. This check stops the deploy before it starts, instead of failing
in the middle.

**Set up.** Update that host **once** to a version with this feature, then press *Re-check*. After that, the page
updates the host itself. A host with no `updatePrereqs` shows an **Update host once** button: it runs the host's
existing shared-source update (a dry run first, so a host that cannot reach the shared source stops with the reason),
keeps a backup, leaves `.env` alone and restarts the host service. Without the shared source, copy one of the two
commands shown (git checkout: pull; otherwise copy the new tree over it).

**Verify.** The host answers with JSON, not `404`.

<div data-technical>

For a git checkout: `cd /opt/virtualpytest && git pull --ff-only && sudo systemctl restart vpt-host`. Not a checkout: `rsync -a --exclude=.env --exclude=venv --exclude=node_modules <new tree>/ /opt/virtualpytest/`, then the same restart. The button calls `POST /server/system/updateHostCore` twice (`dry_run` true, then false). On installs with a deploy node,
`update_core.sh` there does the same for every host. The host answers `GET /host/system/updatePrereqs`.

`curl -s -H "X-API-Key: $API_KEY" http://<host>:6109/host/system/updatePrereqs`

</div>

</details>

<details>
<summary><a id="source-github"></a>Source: GitHub reachable</summary>

**What.** The server reads release tags and the core from GitHub. Required only when the core or the overlay comes from there.

**Set up.** Allow outbound HTTPS from the server to GitHub. A private repository needs a token.

**Verify.** The repository answers the request.

<div data-technical>

Mirror: set `VPT_CORE_REMOTE=<git url>`. Private repository: set `VPT_GITHUB_TOKEN` (or `GITHUB_TOKEN`) in the server's
`.env`. The token reaches git through a temporary askpass file, as user `x-access-token`, never on the command line.

`git ls-remote --heads https://github.com/AngelStreetCorp/virtualpytest.git HEAD` (or your mirror). A private repository
asks for the token: use `GIT_ASKPASS` with user `x-access-token`, or the page's check.

</div>

</details>

<details>
<summary><a id="source-gitlab"></a>Source: GitLab configured and reachable</summary>

**What.** The customer overlay comes from the GitLab instance set up on this server. Required only when the overlay
source is GitLab.

**Set up.** Add the instance and its access token in the app's GitLab settings. The server must reach the instance.

**Verify.** The instance answers with its version.

<div data-technical>

The token needs `read_api` and `read_repository`.

`curl -s -H "PRIVATE-TOKEN: <token>" <gitlab-url>/api/v4/version`

</div>

</details>

<details>
<summary><a id="no-test-running"></a>No test run in progress</summary>

**What.** Lists devices that a script, campaign or deployment is using now. It is a warning and never blocks a deploy.

**Set up.** Nothing. Wait for runs to end, or stop them, and pause queued runs in your scheduler.

<div data-technical>

The update restarts hosts under a running test, which is why this is shown. Manual take-control sessions are not counted.
The platform has no pause switch yet.

</div>

</details>

</details>

<a id="step-1"></a>
## 1 Backup

Saves the database and the settings files.

**You do**
- Press **Back up**.
- Snapshot the VMs in your hypervisor.
- Tick **I snapshotted the VMs**.

**If it fails**
- Each KO item has a one-line fix. Apply it, then press **Back up** again.
- A failed backup leaves no folder behind.

<details>
<summary>More details</summary>

The database machine makes a fresh full backup. It takes a few minutes. The server saves its own settings, and the settings
of every host and the frontend VM, in one folder. Only the service user can read it. Setup: [Database backup on request](#db-backup).

<a id="restore"></a>
**Restore.** In the step 1 result, each saved `.env` has a **Restore** button. It asks for a confirmation, writes the file
back (atomically, keeping its owner and mode) and keeps the current file next to it as `.bak-<timestamp>`. It never
restarts anything: the item then shows the exact command to run, and you run it when you are ready. The database dump has
no button (a dump replaces the whole database): the item shows the command for the database VM.

<div data-technical>

The backup folder is `<state dir>/platform-update/backups/<timestamp>/`. Why it is not a download: the folder holds
secrets. The database file stays on the database VM (`/data/backups`) and its NFS share. What each button does:

| Item | Writes | Then run |
|---|---|---|
| Server `.env` | on the server, `<project root>/.env` or `/opt/virtualpytest/backend_server/src/.env` | `sudo systemctl restart vpt-server` |
| A host `.env` | on that host, through the host API (`/host/system/restoreEnvFile`, only the two fixed names) | `sudo systemctl restart vpt-host` on the host |
| Frontend `.env` | on the frontend VM over the server's SSH key (not in the older password mode) | `sudo systemctl restart vpt-frontend` (`.env.production` is read at build: the next update rebuilds it) |
| Database | nothing | the command shown, as root on the database VM |

If a button reports that the host does not answer, start the host first (the Prerequisites row shows the command). A host
that predates the restore endpoint is refused with a message: update it once by hand, or copy the file there yourself.
**Free space** deletes backup folders beyond the newest five, so an old one may no longer be restorable.

Fallback, by hand on the server as the service user:

```
# the database: on the database VM, as root, from the command the backup item shows (pg_restore inside the container)
# the server .env
cp <backup>/server/env /opt/virtualpytest/.env && sudo systemctl restart vpt-server
# a host: copy <backup>/hosts/<host>/env to that host's /opt/virtualpytest/.env, then
sudo systemctl restart vpt-host
# the frontend VM: copy <backup>/frontend/env (and <backup>/frontend/frontend_env.production) back, then
sudo systemctl restart vpt-frontend
```

</div>

</details>

<a id="step-2"></a>
## 2 Bundle

Builds one zip from the chosen sources.

**You do**
- Core: pick a release tag or upload a ZIP.
- Overlay: GitLab, GitHub, ZIP or None.
- Press **Build zip**; check name, size and sha256.

**If it fails**
- Source unreachable: open *GitHub* or *GitLab* under step 0, More details.

<details>
<summary>More details</summary>

An overlay needs a customer config file. The page also opens the delivery note.

<div data-technical>

The file is `customer.conf`. *Advanced: prepared source* keeps the former way: prepare the source on the server, then
press *Source is ready*.

</div>

</details>

<a id="step-3"></a>
## 3 Deploy

Sends the zip to the frontend, the hosts, then this server. It will not start until step 1 (Backup) is done in this update.

**You do**
- Press **Deploy**. One card per machine shows progress.
- To stop for a moment, press **Pause**. The machine in progress is finished, then nothing else is updated until you press **Resume**.
- To stop for good, press **Abort**. It stops before the next machine. The page then shows, on each card, whether the machine is
  *on new version*, *rolled back* or *untouched*, and lists the database changes applied in this update.
- After an abort or a failed deploy, choose **Roll back** (every updated machine goes back to its previous copy, the server last),
  or **Leave partial** (you keep a mixed fleet on purpose; the page lists the versions and asks you to tick that you know).
- After the server restarts, press **Confirm restart** (or **Confirm roll back** after a roll back).

**If it fails**
- It stops at the failed machine. Click its card for the log.
- Fix the cause, then press **Deploy** again, or press **Roll back**.
- If a roll back stops on one machine, fix that machine and press **Roll back** again: machines already restored are skipped.

<details>
<summary>More details</summary>

The order is: the frontend VM, each host, then this server. Each host checks the zip, backs up, syncs and restarts.

Pause and Abort are taken only *between* machines, never in the middle of one. A request made during a machine waits for it to end.
An update that is waiting for the server restart can no longer be aborted: roll it back instead.

**Roll back order:** hosts (newest updated first), then the frontend VM, then this server last (it restarts itself, so you confirm
it afterwards). Each machine goes back to the copy it saved just before it was updated in this run; settings files (`.env`) and
local data stay as they are. The page never undoes data the new version wrote.

**Database changes** are undone separately: **Undo migrations** runs the matching `_rollback.sql` files, newest first, after you
tick a second confirmation listing the exact files. If a migration has no rollback file, it stops there and shows the command that
restores the database dump saved in step 1. The dump is never restored for you, because it replaces the whole database.

<div data-technical>

Each host checks the zip's sha256 before it installs, and updates its feature units. A host roll back is
`POST /host/system/rollbackBundle` with the backup id the host returned when it was updated; it restores with the same
exclusions as the update. *Advanced: deploy node* is our internal fast path. It ignores the prerequisites and cannot be paused,
aborted or rolled back from the page; it still needs the step 1 backup. Per-target rollbacks stay under *Advanced: per-target deploy*.

</div>

</details>

<a id="step-4"></a>
## 4 Migrations

Applies pending database changes. It runs only after you confirm.

**You do**
- Press **Apply n migrations**, check the list, then tick **I confirm**.
- Nothing pending: press **Mark step done**.

**If it fails**
- The first error stops the run. Fix it, then apply again.
- No connection string: set it up (see [Server to database](#database)), or apply by hand and press **Reload**.

<details>
<summary>More details</summary>

Files are never skipped. For a new tracker, press **Create tracker**, then **Mark as already applied** up to the last file
the database already has.

</details>

<a id="step-5"></a>
## 5 Testing

Proves the platform works.

**You do**
- Press **Check health**.
- Pick a host, a device and a script. Press **Run the smoke script**.

**If it fails**
- A host does not answer: restart its host service (see step 0).
- The smoke script fails: open its report, then close the update as *Failed* or *Rolled back*.

<a id="step-6"></a>
## 6 Close

Ends the update and tells users.

**You do**
- Choose *Succeeded*, *Failed* or *Rolled back*.
- Press **Close update**.

**If it fails**
- *Succeeded* is greyed out: finish steps 0 to 5 first.

<details>
<summary>More details</summary>

Closing switches the maintenance banner off. Users see a short notice for two hours. The log stays on the server and can
be downloaded at any time.

<a id="maintenance"></a>
**Maintenance windows.** A window tells users something is being worked on. Two sources create one:

- **A Platform update run** opens a platform window by itself (the banner).
- **Settings → Maintenance** (administrators only) creates a window with no update run. Give it a start, an end, a reason
  and a scope, then press *Start maintenance window*. You can edit or end it early from the list below the form. Ended
  windows stay listed for a week.

| Scope | Banner | Device markers |
|-------|--------|----------------|
| Full platform | on every page | none |
| Selected devices | on the Devices and Dashboard pages only, listing the covered devices | a wrench icon next to each covered device name |

A future window is listed as *Scheduled* and shows nothing yet. Users see changes within a minute.

A covered device shows a wrench icon, with the tooltip "Under maintenance until HH:MM - reason", in the device grid, the
control headers and the device pickers. Taking control of it, or starting a run on it, first asks "Device under
maintenance - continue?". It is a warning, not a lock. Scheduled jobs do not ask. The question comes when you create the
schedule.

</details>
