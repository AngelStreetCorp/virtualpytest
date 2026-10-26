# Developer setup

For working on the code: the parts run in the foreground with one shared log, restart when you change a file, and a device controller can run on the laptop you have.

## Linux (full stack, foreground)

Install the core parts, then start them together. The start command shows all the logs in one place, and Ctrl+C stops everything.

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/local/linux/install_core.sh      # shared lib, server, host, frontend — no DB, no Grafana
./setup/local/linux/launch_core.sh       # server + host + frontend, colour-coded logs, Ctrl+C stops all
```

<div data-technical>

`install_core.sh` copies the repo to `/opt/virtualpytest` (owned by `vpt_user`) and installs
from there; work and launch from that copy. It writes the three `.env` files with generated
secrets and the LAN address, but has **no database**.

Ports: frontend 5073 (Vite dev server), server 5109, host 6109. Component installers and
launchers live one level down (`setup/local/linux/<component>/install_*.sh`, `launch_*.sh`)
when you want only one of them. `install_all.sh` is the production variant of the same
scripts (systemd services, Grafana, MinIO/Redis) — see [proxmox.md](proxmox.md#one-vm).

</div>

The install does not include a database. You must give it one, in one of three ways:

- **Use the Docker stack's database** on the same machine. Start the Docker setup first. Then copy its keys into the settings file.
- **Install a database on this machine.** The keys are picked up automatically.
- **Use a cloud project.** See [supabase.md](supabase.md#using-a-cloud-supabase-project).

<div data-technical>

- the Docker stack's Supabase — `./setup/docker/launch.sh` on the same machine, then in
  `/opt/virtualpytest/.env` set `SUPABASE_URL=http://localhost:54321` and copy `ANON_KEY`,
  `SERVICE_ROLE_KEY`, `JWT_SECRET` from `setup/docker/.env` into `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`;
- a self-hosted Supabase on this machine — `./setup/local/linux/database/install_db.sh`
  then `./setup/local/linux/shared/write_env.sh` picks the keys up;
- a cloud project — [supabase.md](supabase.md#using-a-cloud-supabase-project).

</div>

Tests run from the `tests/` folder for the backend, and from the frontend folder for the web app. The CI workflow is described in [ci_cd.md](ci_cd.md).

<div data-technical>

Tests: `tests/` (backend, `python -m pytest tests/backend_server`), `frontend` (`npm run
lint`, `npm run typecheck`, `npm run test`).

</div>

## macOS

There are two supported uses on a Mac. You can run the full platform in Docker Desktop. Or you can run only the device controller, which joins a server somewhere else.

- **Full stack:** use Docker Desktop, see [docker.md](docker.md). Inside Docker, the host can only reach network devices (Android over ADB, web) and its own VNC desktop. It cannot reach USB devices.
- **Device controller only** (joining a server elsewhere): install it as background services, then fill in the settings that point it at that server.

The server and the web app do not run natively on macOS. Use Docker Desktop for those.

<div data-technical>

Install the device controller:

```bash
./setup/local/macos/backend_host/install_host_macos.sh
```

Installs the host as launchd services (`com.virtualpytest.flask`, stream, monitor). Fill
`backend_host/src/.env` with `SERVER_URL`, `API_KEY` and the Supabase / storage values of
the server it joins (`backend_host/src/.env.example` documents them).

No `/dev` passthrough under Docker Desktop, so the host inside it drives network devices (Android over ADB, web) and its own VNC desktop only.

</div>

## Windows

Windows is supported only as a device controller. It captures its own desktop and joins a server that runs on Linux or in Docker. The server, web app and database are not offered on Windows. If you need everything on one machine, run the full stack in Docker Desktop with WSL2.

The installer does most of the work. You then fill in the settings with the server's address and the names of your capture devices.

<div data-technical>

```powershell
# PowerShell as Administrator
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
cd C:\path\to\virtualpytest
.\setup\local\windows\backend_host\install_host_windows.ps1
```

The installer copies the repo to `C:\virtualpytest\virtualpytest`, installs Python, FFmpeg,
TightVNC and NSSM, registers the `vpt-host`, `vpt-monitor-img`, `vpt-archiver`, `vpt-monitor-audio`,
`vpt-vnc`, `vpt-websockify` services and the `vpt-stream` scheduled task, and opens the
firewall for 6109 / 5900 / 6080. Then edit `C:\virtualpytest\virtualpytest\backend_host\src\.env`
(`SERVER_URL`, `API_KEY`, Supabase and storage values from the server, `HOST_NAME`,
`DEVICEn_*` with Windows DirectShow names — `ffmpeg -list_devices true -f dshow -i dummy`)
and restart the services. Details and troubleshooting: `setup/local/windows/README.md`.

</div>

For the exact steps and troubleshooting, see the Windows setup notes in the repo.
