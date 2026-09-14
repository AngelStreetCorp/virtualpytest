# install_all.sh — everything on one Linux machine

User guide: `docs/get-started/proxmox.md` §One VM. This file is the script reference.

```bash
sudo -v && ./setup/local/linux/install_all.sh [--no-grafana] [--no-storage] [--no-host]
                                               [--public-host <ip-or-name>] [--open-mode false]
```

| Step | Script | Result |
|---|---|---|
| copy to `/opt/virtualpytest`, `vpt_user` account, then re-exec from there | `shared/bootstrap.sh` (`setup_for_code_installer`) | the tree the services run from |
| 0 system requirements | `shared/install_requirements.sh` | packages, Python 3.11, build tools |
| service account + permissions | `shared/create_vpt_user.sh`, `backend_host/setup_permissions.sh` | |
| 1 database | `database/install_db.sh` → `install_supabase.sh` | Supabase CLI stack as `supabase.service`, schema applied, keys in `config/database/local.env`, per-install JWT secret |
| `.env` files | `shared/write_env.sh` | root `.env`, `backend_host/src/.env`, `frontend/.env` filled (keys, `API_KEY`, URLs from `--public-host` or the LAN address, `SERVER_OPEN_MODE`) |
| 2 storage (unless `--no-storage`) | `storage/install_storage.sh` | MinIO (`minio.service`, 9000/9001, `admin`/`admin1234`) + Redis (`redis-server`, 6379) |
| 3 shared library | `shared/install_shared.sh` | `venv/` |
| 4 server | `backend_server/install_server.sh` | `vpt-server.service` (5109), `vpt-heatmap.service` |
| 5 host (unless `--no-host`) | `backend_host/install_host.sh` | `vpt-host` (6109), `vpt-vnc`, `vpt-stream`, `vpt-monitor`, … |
| 6 frontend | `frontend/install_frontend.sh` | Node 22, production build, `vpt-frontend-prod.service` (5073) |
| 7 Grafana (unless `--no-grafana`) | `monitoring/install_grafana.sh` | `grafana-server` (3000), datasource from `SUPABASE_DB_URI` |
| start + summary | | `vpt-server`, `vpt-host`, `vpt-frontend-prod` started; URL table; open-mode warning |

Re-running is safe: every installer skips what exists and `write_env.sh` never overwrites a
value a user set. `--no-storage` means file storage must be Cloudflare R2 (set in `.env`)
and the queue features that need Redis are unavailable.

Disk: 60 GB is comfortable (Supabase images ≈ 3 GB, Node build, captures grow with use).
Ports: 5073, 5109, 6109, 6080, 3000, 54321–54323, 9000, 9001, 6379 (LAN), 5901 (VNC).

Related: `install_core.md` (developer subset, no database), `launch_core.md` (foreground
launcher for development), `shared/write_env.sh` (re-run after editing `.env` by hand).
