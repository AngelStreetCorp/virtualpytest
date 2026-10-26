# VM agent

The infra VMs (database, storage, frontend, proxy, monitoring) run no VirtualPyTest
code, so nothing recorded their CPU / RAM / disk or whether their services were up.
The `/status` page showed some of it live, but kept nothing, so Grafana had no history.

`vpt_vm_agent.py` is a small HTTP agent (Python standard library only, no pip) that
answers `GET /status` with the VM's resources and the state of the services you list.
The backend server pulls it once a minute (`INFRA_VM_AGENTS`, see
`backend_server/src/lib/server/infra_status_collector.py`). To keep the database
small it stores the live status in `service_status_current` (overwritten), a row in
`service_status` only when a status changes, and the resources in `vm_metrics`
every 5 minutes. The **System Service Status** Grafana dashboard
(`infra/monitoring/grafana/dashboards/system-service-status.json`) reads them.

It is a pull: the VM holds no credentials and never writes to the database. `GET /status`
is read-only and stays that way. One **opt-in** action exists on top (below); an agent
installed without it behaves exactly as before.

## Install on a VM

Copy this folder to the VM, then run `install.sh` as root with the services that VM runs.
`--allow` limits who may read `/status` — list the backend server's IP (and `127.0.0.1` to
test locally). Below, `192.168.x.N` stands for your LAN.

| VM | Command |
|---|---|
| database | `sudo ./install.sh --containers supabase_db_supabase,supabase_rest_supabase,supabase_auth_supabase,supabase_kong_supabase,supabase_storage_supabase,supabase_studio_supabase,supabase_pg_meta_supabase --allow 192.168.x.103,127.0.0.1 --action db-backup --action-token-file /root/vm_agent_token` (the last two flags are optional: see *On-request database backup*) |
| storage | `sudo ./install.sh --units minio,redis-server,nginx --allow 192.168.x.103,127.0.0.1` |
| frontend | `sudo ./install.sh --units vpt-frontend-prod,vpt-frontend-demo --allow 192.168.x.103,127.0.0.1` |
| proxy | `sudo ./install.sh --units nginx --allow 192.168.x.103,127.0.0.1` |
| monitoring | `sudo ./install.sh --units grafana-server --allow 192.168.x.103,127.0.0.1` |

On the database VM, list the containers by name rather than `supabase_*`:
`supabase_analytics_supabase` and `supabase_realtime_supabase` are stopped on purpose
there, and a glob would report them as down forever.

`--containers` reads `/var/run/docker.sock`, which is why the unit runs as root. The
agent only reads from it.

Re-running `install.sh` rewrites `/etc/default/vpt-vm-agent` from its flags and
restarts the agent.

Check it on the VM:

```bash
curl -s http://127.0.0.1:9110/status | python3 -m json.tool
```

## On-request database backup (optional, database VM only)

The Platform update (step 1, Backup) asks the database VM for a fresh backup instead of
running `pg_dump` on the server, because only the database's own `pg_dump` matches its
PostgreSQL version. The agent starts the backup the VM already makes every night, as the systemd
one-shot unit `vpt-db-backup.service` (which runs `/usr/local/bin/vpt-db-backup.sh`).

Enable it with `--action db-backup --action-token-file <file>`. The file holds a shared
secret; create it once and put the same value in the server's `.env` as `VM_AGENT_ACTION_TOKEN`:

```bash
openssl rand -hex 32 > /root/vm_agent_token && chmod 600 /root/vm_agent_token
```

Security story, so the "read-only" claim above stays honest:

- **Off by default.** The action answers only when `VM_AGENT_ACTIONS` contains `db-backup`
  **and** `VM_AGENT_ACTION_TOKEN` is set (both written by `install.sh` to
  `/etc/default/vpt-vm-agent`, mode 0600, root only). Otherwise both routes return 404.
- **Two gates.** The client IP must be in `--allow`, and the request must carry the token in
  the `X-VM-Agent-Token` header (compared in constant time). Without the right token: 401.
- **One fixed unit.** It runs `systemctl start --no-block <unit>` with `VM_AGENT_DB_BACKUP_UNIT`
  (default `vpt-db-backup.service`, validated against a strict unit-name pattern) from the config file;
  nothing in a request (body, query, header) can change the unit. No shell is involved.
- **Why a unit and not a child process.** The agent itself is sandboxed (`ProtectSystem=strict`,
  `ProtectHome=yes`, `PrivateTmp=yes`) and a child inherits that: the backup could not write
  `/data/backups` (`read-only file system`). `systemctl start` asks PID 1 to run the unit with the
  unit's own settings (`vpt-db-backup.service` has no sandbox), so the agent stays sandboxed and gets
  no `ReadWritePaths`. `systemctl` and `journalctl` work from inside the sandbox: as root they talk to
  systemd over `/run/systemd/private` / D-Bus, which `ProtectSystem=strict` leaves reachable (it only
  makes the file tree read-only), and `NoNewPrivileges` does not affect a root process that only sends
  requests. The state (running, exit code, times) is read from `systemctl show`, the log from
  `journalctl -u`, so it also survives an agent restart.
- **Rate limited.** One run at a time (409 while the unit is active) and 5 minutes between successful
  runs (429 with `retry_after`; a failed run can be retried at once).
- The token lets a caller start that one script and read its last 40 log lines, nothing else.

| Request | Answer |
|---|---|
| `POST /actions/db-backup` | `202 {request_id, started_at}`; `409` already running; `429 {retry_after}` cooldown; `500` cannot start |
| `GET /actions/db-backup` | `200 {request_id, running, started_at, finished_at, exit_code, log_tail[<=40]}` |

Install: `install.sh --action db-backup ...` also copies `vpt-db-backup.service` to `/etc/systemd/system/` and
runs `systemctl daemon-reload`; it does not enable or start it (no timer: the nightly cron stays). The script
`/usr/local/bin/vpt-db-backup.sh` must already be installed; it reads `VPT_API_KEY` from `/etc/cron.d/vpt-db-backup`
itself. Option, not done by the installer: the cron line could call `systemctl start vpt-db-backup.service`
instead of the script, so the nightly run and the on-request run share one unit (and one journal).

Both need `X-VM-Agent-Token`. Check from the server:

```bash
curl -s -H "X-VM-Agent-Token: $VM_AGENT_ACTION_TOKEN" http://192.168.x.102:9110/actions/db-backup
```

## Tell the server to pull it

In the backend server's `.env`, on **one** server per database (each server that has it
pulls every agent):

```
INFRA_VM_AGENTS=database=192.168.x.102:9110,storage=192.168.x.101:9110,frontend=192.168.x.105:9110,proxy=192.168.x.107:9110,monitoring=192.168.x.106:9110
```

Then restart `vpt-server`. The name before `=` is the VM label the dashboard shows.

## What each status means

| Status | Meaning | Unit | Container |
|---|---|---|---|
| ok | running | `active` | running (and `healthy`, if it has a health check) |
| stopped | not running — switched off | `inactive` | exited with code 0, created, paused |
| down | failing | `failed` | exited with a non-zero code, dead, restarting; or no container with that name |
| degraded | starting / unhealthy | `activating` / `reloading` / `deactivating` | `unhealthy` or `health: starting` |
| unknown | can't tell | unit not installed | docker socket unreachable |

The collector adds one row per VM itself: component `agent`, `ok` when the agent
answered and `down` when it did not (the VM is off, unreachable, or the agent is stopped).
