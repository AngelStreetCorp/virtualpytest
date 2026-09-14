# Install on a VM or a Proxmox fleet

Native install: every component is a systemd service on Debian 12 / Ubuntu 22.04+. Two shapes:

- **[One VM](#one-vm)** — everything on one machine. Scripted end to end.
- **[Proxmox fleet](#proxmox-fleet)** — one VM per role. Each role is scripted; creating the
  VMs and copying a handful of values between them is done by hand (a provisioning script
  for the Proxmox node is planned, not shipped).

Both use the same per-role installers in `setup/local/linux/`. "Proxmox" is where we run it;
any hypervisor or bare machine that boots Debian works the same way.

## One VM

**VM:** Debian 12 or Ubuntu 22.04+ · 4 vCPU · 8 GB RAM · 60 GB disk (physical machines and
capture hardware: [hardware.md](hardware.md)) · a user with `sudo` ·
internet access (the installer downloads Python packages, Node 22, Docker for Supabase,
Grafana, MinIO, Redis). Add 2 vCPU and 4 GB per HDMI capture card you will attach.

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
sudo -v && ./setup/local/linux/install_all.sh
```

Options: `--no-grafana`, `--no-storage` (no MinIO/Redis: file storage must then be Cloudflare
R2, set in `.env`), `--no-host` (server-only machine), `--public-host <ip-or-name>` (the
address browsers use; default = first LAN address), `--open-mode false` (start with login
enforced — see [supabase.md](supabase.md)).

What happens (45–70 minutes on a fresh 4 vCPU VM, most of it downloads and the bluez build):

1. The repository is copied to `/opt/virtualpytest`, owned by the `vpt_user` service
   account; everything runs from there. Re-running the script later is safe.
2. System packages, Python 3.11 and Node 22 are installed.
3. Supabase is installed through the Supabase CLI (Postgres 17 + auth + REST + Studio, as
   Docker containers managed by a `supabase` systemd unit) and the schema is applied.
4. `.env` files are written from what the previous steps produced (Supabase keys, generated
   `API_KEY`, the LAN address) — `setup/local/linux/shared/write_env.sh`.
5. MinIO + Redis, the server, the host, the frontend (built once) and Grafana are installed
   as services and started.
6. The URLs are printed:

| What | URL | Service |
|---|---|---|
| Web UI | `http://<PUBLIC_HOST>:5073` | `vpt-frontend-prod` |
| Server API | `http://<PUBLIC_HOST>:5109` | `vpt-server` |
| Host API / desktop | `http://<PUBLIC_HOST>:6109` / noVNC on the port `HOST_VNC_STREAM_PATH` names | `vpt-host`, `vpt-vnc`, `vpt-stream`, `vpt-monitor` |
| Grafana | `http://<PUBLIC_HOST>:3000` — `admin` / `GRAFANA_ADMIN_PASSWORD` in `/opt/virtualpytest/.env` | `grafana-server` |
| Supabase API / Studio | `http://<PUBLIC_HOST>:54321` / `:54323` | `supabase` |
| MinIO console | `http://<PUBLIC_HOST>:9001` — `admin` / `admin1234` | `minio` |

The stack starts in **open mode** (no login) and the installer says so. To enforce login see
[supabase.md](supabase.md#enforce-login).

Two things finish **after** the script returns, so the Web UI and Grafana answer nothing for a
while: the frontend's first production build (10–20 min; `vpt-frontend-prod` shows
`activating (start-pre)` meanwhile) and Grafana's first start (a few hundred SQLite
migrations, 20–40 min on a slow disk). `sudo journalctl -u vpt-frontend-prod -f` and
`curl http://<PUBLIC_HOST>:3000/api/health` tell you when they are done.

### Devices

Declare them in `/opt/virtualpytest/backend_host/src/.env` (the file documents every
option: capture card, audio, IR / Bluetooth / IRTrans, Tapo power plugs, Android over ADB),
then `sudo systemctl restart vpt-host vpt-stream vpt-monitor`. USB capture cards appear as
`/dev/videoN` on the VM once passed through by the hypervisor (Proxmox: *Hardware → Add →
USB device*).

### Day two

```bash
sudo systemctl status vpt-server vpt-host vpt-frontend-prod supabase grafana-server minio redis-server
sudo journalctl -u vpt-server -f
cd /opt/virtualpytest && git pull && ./setup/local/linux/install_all.sh   # update in place
setup/local/linux/shared/write_env.sh --public-host new.address        # after moving the machine
```

Daily database dumps: `/etc/cron.d/vpt-db-backup` → `/data/backups/`. Off-site copies are
your job.

## Proxmox fleet

One VM per role. The reference layout (the one this project runs on):

| VM | Role | Installer | Size |
|---|---|---|---|
| storage | NFS share for the hosts, MinIO, Redis | `setup/proxmox/vm/storage/*` then `setup/local/linux/storage/install_storage.sh` | 2 vCPU / 4 GB / 200 GB+ |
| database | Supabase | `setup/local/linux/database/install_db.sh` | 2 / 4 GB / 60 GB |
| server | backend server | `setup/local/linux/backend_server/install_server.sh` | 2 / 4 GB / 32 GB |
| frontend | web UI | `setup/local/linux/frontend/install_frontend.sh` | 2 / 2 GB / 32 GB |
| monitoring | Grafana | `setup/local/linux/monitoring/install_grafana.sh` | 2 / 4 GB / 32 GB |
| proxy | nginx + TLS, the only VM with a public address | `setup/local/linux/reverse_proxy/install_nginx.sh` + a config from `infra/proxy/nginx/config/` | 1 / 1 GB / 16 GB |
| host-N | device controllers, one per machine with hardware | `setup/local/linux/backend_host/install_host.sh` | 4 / 8 GB / 32 GB + captures |

Procedure, in order:

1. **Create the VMs** in the Proxmox UI (Debian 12 cloud image or netinst, static IPs on one
   bridge, a `sudo` user with your SSH key). Pass USB capture / IR devices through to the
   host VMs.
2. **Clone the repo on each VM** and run its installer from the table. Each installer copies
   the repo to `/opt/virtualpytest` and registers its systemd unit.
3. **Database first.** When `install_db.sh` finishes, `/opt/virtualpytest/config/database/local.env`
   on the database VM holds `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_JWT_SECRET`. Copy those four values into `/opt/virtualpytest/.env` on the server VM
   and into `backend_host/src/.env` on every host VM, with `SUPABASE_URL=http://<database-vm>:54321`.
4. **Wire the addresses** on each VM with `setup/local/linux/shared/write_env.sh --public-host <that VM's address>`,
   then set by hand what crosses VMs: on hosts `SERVER_URL=http://<server-vm>:5109` and the
   server's `API_KEY`; on the server `GRAFANA_URL=http://<monitoring-vm>:3000` and
   `MINIO_ENDPOINT=http://<storage-vm>:9000`; on the frontend `VITE_SERVER_URL` /
   `VITE_GRAFANA_URL` to the **public** addresses the proxy exposes, then rebuild
   (`install_frontend.sh` again).
5. **Proxy.** Copy `infra/proxy/nginx/config/proxmox.local.conf` (HTTP) or
   `proxmox.local.https.conf` (TLS) to the proxy VM, replace the upstream addresses with your
   VMs, run `install_nginx.sh <config>`; issue certificates with `certbot --nginx` for your
   domain. Every browser-facing URL (`VITE_*`, `HOST_URL`, `MINIO_PUBLIC_URL`) must be the
   public one.
6. **Smoke:** `curl http://<server-vm>:5109/server/health`, open the web UI, check each host
   appears under *Devices*.

Rebuilding **this project's own** node from backups is a different, internal runbook that
is not part of the repository.
