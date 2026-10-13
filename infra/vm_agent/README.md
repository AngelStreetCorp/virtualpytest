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

It is a pull: the VM holds no credentials and never writes to the database.

## Install on a VM

Copy this folder to the VM, then run `install.sh` as root with the services that VM runs.
`--allow` limits who may read `/status` — list the backend server's IP (and `127.0.0.1` to
test locally). Below, `192.168.x.N` stands for your LAN.

| VM | Command |
|---|---|
| database | `sudo ./install.sh --containers supabase_db_supabase,supabase_rest_supabase,supabase_auth_supabase,supabase_kong_supabase,supabase_storage_supabase,supabase_studio_supabase,supabase_pg_meta_supabase --allow 192.168.x.103,127.0.0.1` |
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
