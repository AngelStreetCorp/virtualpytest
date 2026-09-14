# Developer setup

For working on the code: services in the foreground with one interleaved log, restart on
change, and a device controller on the laptop you have.

## Linux (full stack, foreground)

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/local/linux/install_core.sh      # shared lib, server, host, frontend — no DB, no Grafana
./setup/local/linux/launch_core.sh       # server + host + frontend, colour-coded logs, Ctrl+C stops all
```

`install_core.sh` copies the repo to `/opt/virtualpytest` (owned by `vpt_user`) and installs
from there; work and launch from that copy. It writes the three `.env` files with generated
secrets and the LAN address, but has **no database**: give it one of

- the Docker stack's Supabase — `./setup/docker/launch.sh` on the same machine, then in
  `/opt/virtualpytest/.env` set `SUPABASE_URL=http://localhost:54321` and copy `ANON_KEY`,
  `SERVICE_ROLE_KEY`, `JWT_SECRET` from `setup/docker/.env` into `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`;
- a self-hosted Supabase on this machine — `./setup/local/linux/database/install_db.sh`
  then `./setup/local/linux/shared/write_env.sh` picks the keys up;
- a cloud project — [supabase.md](supabase.md#using-a-cloud-supabase-project).

Ports: frontend 5073 (Vite dev server), server 5109, host 6109. Component installers and
launchers live one level down (`setup/local/linux/<component>/install_*.sh`, `launch_*.sh`)
when you want only one of them. `install_all.sh` is the production variant of the same
scripts (systemd services, Grafana, MinIO/Redis) — see [proxmox.md](proxmox.md#one-vm).

Tests: `tests/` (backend, `python -m pytest tests/backend_server`), `frontend` (`npm run
lint`, `npm run typecheck`, `npm run test`). The CI workflow is described in [ci_cd.md](ci_cd.md).

## macOS

Two supported uses:

- **Full stack:** Docker Desktop → [docker.md](docker.md). No `/dev` passthrough, so the host
  inside it drives network devices (Android over ADB, web) and its own VNC desktop only.
- **Host role natively** (device controller joining a server elsewhere):
  ```bash
  ./setup/local/macos/backend_host/install_host_macos.sh
  ```
  Installs the host as launchd services (`com.virtualpytest.flask`, stream, monitor). Fill
  `backend_host/src/.env` with `SERVER_URL`, `API_KEY` and the Supabase / storage values of
  the server it joins (`backend_host/src/.env.example` documents them).

The server and frontend are not supported natively on macOS — use Docker Desktop.

## Windows

Windows is supported as a **host role only**: a device controller with its own desktop
capture, joining a server that runs on Linux or in Docker. Server, frontend and database on
Windows are not offered; run the full stack in Docker Desktop (WSL2) if it must be one box.

```powershell
# PowerShell as Administrator
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
cd C:\path\to\virtualpytest
.\setup\local\windows\backend_host\install_host_windows.ps1
```

The installer copies the repo to `C:\virtualpytest\virtualpytest`, installs Python, FFmpeg,
TightVNC and NSSM, registers the `vpt-host`, `vpt-monitor`, `vpt-archiver`, `vpt-transcript`,
`vpt-vnc`, `vpt-websockify` services and the `vpt-stream` scheduled task, and opens the
firewall for 6109 / 5900 / 6080. Then edit `C:\virtualpytest\virtualpytest\backend_host\src\.env`
(`SERVER_URL`, `API_KEY`, Supabase and storage values from the server, `HOST_NAME`,
`DEVICEn_*` with Windows DirectShow names — `ffmpeg -list_devices true -f dshow -i dummy`)
and restart the services. Details and troubleshooting: `setup/local/windows/README.md`.
