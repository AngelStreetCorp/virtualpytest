# Install on a VM or a Proxmox fleet

This is a native install: every part runs as a system service on a Debian or Ubuntu machine, with no
containers. Choose one:

- **[One VM](#one-vm)**: everything on one machine. A script does all of it.
- **[Proxmox fleet](#proxmox-fleet)**: one VM per job. You create the VMs and copy values between them.

## One VM

Use this for a single machine, a lab box or a first setup. It takes most of an hour.

**The VM needs:** Debian 12 or Ubuntu 22.04 or newer, 4 CPU cores, 8 GB of RAM and 60 GB of disk, a user
with admin rights, and internet access. For each HDMI capture card, add 2 CPU cores and 4 GB of RAM.
For a physical machine and its capture hardware, see [hardware.md](hardware.md).

<div data-technical>

Minimum: Debian 12 or Ubuntu 22.04+, 4 vCPU, 8 GB RAM, 60 GB disk, a user with `sudo`. The installer
downloads Python packages, Node 22, Docker (for Supabase), Grafana, MinIO and Redis. Add 2 vCPU and
4 GB per HDMI capture card.

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
sudo -v && ./setup/local/linux/install_all.sh
```

Options for the installer:

- `--no-grafana`: skip Grafana.
- `--no-storage`: skip MinIO and Redis. File storage must then be Cloudflare R2, set in `.env`.
- `--no-host`: this is a server-only machine.
- `--public-host <ip-or-name>`: the address browsers use. The default is the first LAN address.
- `--open-mode false`: start with login turned on. See [supabase.md](supabase.md).

</div>

Run the installer from the repository, and wait. Re-running it later is safe. It installs the
database, writes the settings files, starts every service, and prints the web addresses.

<div data-technical>

Timings: the whole run takes 45 to 70 minutes on a fresh 4 vCPU VM, most of it downloads and the bluez build.

1. Copied to `/opt/virtualpytest`, owned by the `vpt_user` service account.
2. System packages, Python 3.11 and Node 22.
3. Supabase installed through the Supabase CLI (Postgres 17, auth, REST, Studio, as Docker containers managed by a `supabase` systemd unit). Schema applied.
4. `.env` files written by `setup/local/linux/shared/write_env.sh` (Supabase keys, generated `API_KEY`, LAN address).
5. MinIO and Redis, the server, the host, the frontend (built once) and Grafana installed as services.
6. URLs printed.

</div>

| What | URL | Service |
|---|---|---|
| Web app | `http://<PUBLIC_HOST>:5073` | `vpt-frontend-prod` |
| Server API | `http://<PUBLIC_HOST>:5109` | `vpt-server` |
| Device controller and its desktop | `http://<PUBLIC_HOST>:6109` and the desktop on the port `HOST_VNC_STREAM_PATH` names | `vpt-host`, `vpt-vnc`, `vpt-stream`, `vpt-monitor-img` |
| Grafana | `http://<PUBLIC_HOST>:3000` | `grafana-server` |
| Database (API and admin screens) | `http://<PUBLIC_HOST>:54321` and `:54323` | `supabase` |
| File storage console | `http://<PUBLIC_HOST>:9001` | `minio` |

<div data-technical>

Logins: Grafana is `admin` with `GRAFANA_ADMIN_PASSWORD` from `/opt/virtualpytest/.env`. The MinIO console
is `admin` with `MINIO_SECRET_KEY` from `.env`. The Supabase API is on `:54321` and Studio on `:54323`.

</div>

The stack starts with no login, and the installer says so. To turn login on, see [supabase.md](supabase.md#enforce-login).

After the script returns, the web app and Grafana still need 10 to 40 minutes before they show anything.

<div data-technical>

The frontend's first production build takes 10–20 min. Meanwhile `vpt-frontend-prod` shows `activating (start-pre)`.
Grafana's first start runs a few hundred SQLite migrations, 20–40 min on a slow disk. Watch them with
`sudo journalctl -u vpt-frontend-prod -f` and `curl http://<PUBLIC_HOST>:3000/api/health`.

</div>

### Devices

Add your devices in the device controller's settings file. A USB capture card works only if the hypervisor passes it through.

<div data-technical>

File: `/opt/virtualpytest/backend_host/src/.env` (documents every option: capture card, audio, IR /
Bluetooth / IRTrans, Tapo power plugs, Android over ADB). Then:

```bash
sudo systemctl restart vpt-host vpt-stream vpt-monitor-img
```

USB capture cards appear as `/dev/videoN` on the VM once passed through by the hypervisor (Proxmox:
*Hardware → Add → USB device*).

</div>

### Day two

Check the services, read the log, update, or move the machine to a new address. The database is backed up
every day. Copying the backups elsewhere is your job.

<div data-technical>

```bash
sudo systemctl status vpt-server vpt-host vpt-frontend-prod supabase grafana-server minio redis-server
sudo journalctl -u vpt-server -f
cd /opt/virtualpytest && git pull && ./setup/local/linux/install_all.sh   # update in place
setup/local/linux/shared/write_env.sh --public-host new.address        # after moving the machine
```

Daily database dumps: `/etc/cron.d/vpt-db-backup` → `/data/backups/`. Off-site copies are your job.

</div>

## Proxmox fleet

Use this when each job should have its own VM. Each VM has one role and its own installer.

| VM | Role | Size |
|---|---|---|
| storage | File sharing for the device machines, file storage, Redis | 2 vCPU / 4 GB / 200 GB+ |
| database | Supabase | 2 vCPU / 4 GB / 60 GB |
| server | Backend server | 2 vCPU / 4 GB / 32 GB |
| frontend | Web app | 2 vCPU / 2 GB / 32 GB |
| monitoring | Grafana | 2 vCPU / 4 GB / 32 GB |
| proxy | nginx with TLS. The only VM with a public address | 1 vCPU / 1 GB / 16 GB |
| host-N | Device controllers, one per machine with hardware | 4 vCPU / 8 GB / 32 GB + captures |

<div data-technical>

Installers:

| VM | Installer |
|---|---|
| storage | `setup/proxmox/vm/storage/*`, then `setup/local/linux/storage/install_storage.sh` |
| database | `setup/local/linux/database/install_db.sh` |
| server | `setup/local/linux/backend_server/install_server.sh` |
| frontend | `setup/local/linux/frontend/install_frontend.sh` |
| monitoring | `setup/local/linux/monitoring/install_grafana.sh` |
| proxy | `setup/local/linux/reverse_proxy/install_nginx.sh` + a config from `infra/proxy/nginx/config/` |
| host-N | `setup/local/linux/backend_host/install_host.sh` |

Sizes in this table are vCPU / RAM / disk, with extra capture space on host VMs.

</div>

Do the steps in this order:

1. **Create the VMs** in Proxmox, with fixed addresses. Pass capture cards and infrared devices to the device VMs.
2. **Install the database first.** Copy its keys to the server and device VMs.
3. **Set the addresses** on each VM, and install the proxy with its certificates.
4. **Check it works.** Open the web app and make sure each device machine shows up under *Devices*.

<div data-technical>

Step 3, the four database values in `/opt/virtualpytest/config/database/local.env` on the database VM:
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`. Copy them into
`/opt/virtualpytest/.env` on the server VM, and into `backend_host/src/.env` on every host VM, with
`SUPABASE_URL=http://<database-vm>:54321`.

Step 4, on each VM run `setup/local/linux/shared/write_env.sh --public-host <that VM's address>`. Then set
the values that cross VMs by hand:

- on hosts: `SERVER_URL=http://<server-vm>:5109` and the server's `API_KEY`;
- on the server: `GRAFANA_URL=http://<monitoring-vm>:3000` and `MINIO_ENDPOINT=http://<storage-vm>:9000`;
- on the frontend: `VITE_SERVER_URL` and `VITE_GRAFANA_URL`, set to the **public** addresses the proxy exposes.
  Then rebuild with `install_frontend.sh`.

Step 5, the proxy: copy `infra/proxy/nginx/config/proxmox.local.conf` (HTTP) or
`proxmox.local.https.conf` (TLS) to the proxy VM. Replace the upstream addresses with your VMs and run
`install_nginx.sh <config>`. Issue certificates with `certbot --nginx` for your domain. Every browser-facing
URL (`VITE_*`, `HOST_URL`, `MINIO_PUBLIC_URL`) must be the public one.

Step 6, smoke test: `curl http://<server-vm>:5109/server/health`.

</div>

