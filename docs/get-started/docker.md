# Install with Docker (one machine)

This page sets up the whole platform on one Linux or macOS machine, with one command. It suits a first
look, a demo or a lab box on a trusted network.

Everything runs in containers on this machine, including one device controller (the "host") with a
desktop you can watch.

If this machine only has devices and the platform runs somewhere else, use [host-only mode](add-a-host.md) instead.

**You need:** a Linux or macOS machine with about 4 CPU cores, 8 GB of RAM and 30 GB of free disk,
and internet access for the first install. On Windows, run the same commands inside WSL2, or install
only a device controller on Windows (see [Windows host](local-dev.md#windows)).

<div data-technical>

Supported Linux: Ubuntu 22.04 or newer, or Debian 12 or newer. macOS needs Docker Desktop.

The stack is three VirtualPyTest images: `virtualpytest-server`, `virtualpytest-host` and
`virtualpytest-frontend`. Docker Compose pulls or builds them with the database, Redis, MinIO and Grafana.
There is no single all-in-one image.

</div>

## 1. Install

Download the bundle, unpack it, and run the launcher. It installs what it needs and starts everything.

<div data-technical>

```bash
curl -L https://github.com/AngelStreetCorp/virtualpytest/releases/latest/download/vpt-docker.tar.gz | tar xz
cd vpt-docker-*
./setup/docker/install_docker.sh   # only if Docker is not installed yet
./setup/docker/launch.sh
```

Or clone the repo instead, if you also want the source (~330 MB of history):

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/docker/install_docker.sh
./setup/docker/launch.sh
```

The bundle carries the compose files, the database schema, the Grafana dashboards and the shipped test
scripts, which are the paths the containers mount. It pulls everything else from the registry.

</div>

Both ways give the same stack. If Docker rights were just granted, log out and back in first.

<div data-technical>

```bash
newgrp docker   # or log out and back in
```

</div>

The launcher generates the passwords and settings, fetches or builds the images (5 to 15 minutes on
the first run), sets up the database, and prints the web addresses.

<div data-technical>

Files it creates: `setup/docker/.env` (from `.env.example`, every secret generated, `PUBLIC_HOST` set to
this machine's LAN address) and `backend_host/src/.env` (from its example, VNC desktop capture on,
physical devices off).

</div>

### Skip the build (prebuilt images)

The build is the slow part. Ready-made images are published, so a first run takes about two minutes.
They only work on Intel and AMD Linux. If you change the code, build locally, or your changes will not
be in the running container.

<div data-technical>

Set the tag in `setup/docker/.env` before the first `launch.sh`, or any time afterwards:

```bash
VPT_IMAGE_TAG=latest                  # the most recently published images
VPT_IMAGE_TAG=main-2026.09.17-9151    # or a specific release, to freeze it
# default is `local` = build from this checkout
```

`launch.sh` pulls `virtualpytest-server`, `-host` and `-frontend` from `ghcr.io/angelstreetcorp`. If the
pull fails (no network, or a tag that was never published), it falls back to building. Nothing compiles
on your machine when the pull works.

A prebuilt image is the code of its build. If you edit anything under `backend_server/`,
`backend_host/` or `frontend/`, set `VPT_IMAGE_TAG=local` (or run `./setup/docker/launch.sh --rebuild`).

The frontend image writes `dist/config.js` from the container environment on every start. Changing
`PUBLIC_HOST` needs a restart, not a rebuild, and one image serves any address.

Images are `linux/amd64` only. On arm64 (Apple Silicon, a Raspberry Pi) leave `VPT_IMAGE_TAG=local` and build.

</div>

## 2. Open it

Open the web app in your browser. Each tool below has its own login.

- **Web app:** run tests and see devices.
- **Host desktop:** the device controller's desktop, which you can watch live.
- **Grafana:** charts and dashboards.
- **Supabase Studio:** the database admin screens.

<div data-technical>

| What | URL |
|---|---|
| Web UI | `http://<PUBLIC_HOST>:5073` |
| Server API | `http://<PUBLIC_HOST>:5109` (`/server/health`) |
| Host API / host desktop (noVNC) | `http://<PUBLIC_HOST>:6109` / `http://<PUBLIC_HOST>:6080/vnc_lite.html` |
| Grafana | `http://<PUBLIC_HOST>:3000` — `admin` / `GRAFANA_ADMIN_PASSWORD` from `setup/docker/.env` |
| Supabase Studio | `http://<PUBLIC_HOST>:54321` — `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` from `.env` |
| MinIO console | `http://<PUBLIC_HOST>:9001` — `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env` |

`PUBLIC_HOST` is printed by `launch.sh` and stored in `setup/docker/.env`. Every URL the platform hands
to a browser is built from it. If you reach the machine by another address later (a DNS name, a VPN
address), change `PUBLIC_HOST` and run `./setup/docker/launch.sh`. A restart is enough, because the
frontend reads it at startup.

</div>

Every link uses the address the launcher printed. If you reach the machine by another name later,
change the address and start the stack again.

The stack starts in **open mode**: no login, and every request is accepted. Keep the machine on a trusted
network, or turn on login. See [Supabase and authentication](supabase.md#enforce-login).

## 3. First test

1. The host `docker-host` is already registered under *Devices*.
2. In *Run Tests*, pick the host and a web test, and run it. You can watch the browser on the host's desktop.
3. The result appears in *Test Results*, and the measurements appear in Grafana.

<div data-technical>

The example script is `web/dailymotion_video_check`. Any script whose name starts with `web/…` works.
Chromium runs on the host's VNC desktop.

</div>

## 4. Add a real device

You edit one file: `backend_host/src/.env`. Turn a device on by removing the `x` from its lines, then
run the launcher again. The file ships with physical devices off.

<div data-technical>

```bash
nano backend_host/src/.env          # drop the x, set DEVICE1_* for your hardware
./setup/docker/launch.sh            # restarts the host container with the new config
```

```bash
xDEVICE1_NAME=AppleTv          # ← drop the x on the lines you want
xDEVICE1_MODEL=apple_tv
xDEVICE1_IP=192.168.1.27
xDEVICE1_VIDEO=/dev/video0
```

The file has commented examples for a TV or set-top box with HDMI capture and IR, an Android device
over the network, and a smart plug.

On Linux, the host container sees the machine's `/dev` (USB capture cards, IR transmitters, serial).
Each capture path also needs a RAM-backed hot directory: add one `tmpfs` line per
`DEVICEn_VIDEO_CAPTURE_PATH` in `setup/docker/docker-compose.linux.yml` (the file shows the default one).

</div>

On Linux, the host can use USB capture cards, IR transmitters and serial devices. On macOS there is no
device passthrough: use network-controlled devices, or run the host on a Linux machine with
[`--host-only`](#more-than-one-machine).

<div data-technical>

On macOS, a `DEVICEn_VIDEO=/dev/videoX` line stops the host from starting.

</div>

## 5. Everyday commands

Stopping keeps your data. Only the reset command deletes it, and it asks you first.

<div data-technical>

```bash
./setup/docker/launch.sh --logs      # follow all logs
./setup/docker/launch.sh --down      # stop (data kept)
./setup/docker/launch.sh             # start again
./setup/docker/launch.sh --rebuild   # after a git pull (PUBLIC_HOST / VITE_* now take effect on restart)
./setup/docker/launch.sh --reset     # stop AND delete all data volumes (asks for confirmation)
```

Data lives in Docker volumes: `virtualpytest_supabase-db-data` (database), `virtualpytest_minio-data`
(files), `virtualpytest_stream-data` (captures), `virtualpytest_grafana-data`. Back up the database with
`docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql`.

</div>

Back up the database regularly. The backup command is in the technical details.

## More than one machine

Run a device controller on each machine that has hardware. A host behind NAT needs a tunnel. See
[Add a machine with devices](add-a-host.md).

<div data-technical>

```bash
./setup/docker/launch.sh --host-only
```

</div>

## Before exposing it beyond the LAN

The stack serves plain HTTP and starts with no login. Before anyone outside your network can reach it:

1. Turn on login. See [supabase.md](supabase.md#enforce-login).
2. Put a reverse proxy with TLS in front of it, using the nginx example in `infra/proxy/nginx/config/docker.conf`.
3. Close every other port with a firewall. Keep the database, admin screens and file storage off the internet.

<div data-technical>

Step 2 in detail: set `PUBLIC_HOST` to the public name, then start the containers again with
`./setup/docker/launch.sh`. No rebuild is needed, because the frontend reads its `VITE_*` values when the
container starts. If the API, noVNC or Supabase end up on hostnames other than the UI's, set
`VITE_SERVER_URL`, `HOST_VNC_STREAM_PATH`, `HOST_URL`, `VITE_SUPABASE_URL` and `SUPABASE_PUBLIC_URL` /
`SITE_URL` to match. A worked example is in [Google Cloud standalone §9.6](gcp-standalone.md#96-wire-the-stack-to-the-hostnames).

Step 3, the firewall:

```bash
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow from <your-lan>/24 to any port 22
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp        # the proxy
sudo ufw enable
```

Studio (54321), Postgres (54322), MinIO (9000/9001) and Grafana (3000) must never be reachable from the
internet. If the machine is shared, change the `DASHBOARD_PASSWORD`, `MINIO_SECRET_KEY` and
`GRAFANA_ADMIN_PASSWORD` defaults.

</div>

## Troubleshooting

**The launcher stops at "waiting for http://localhost:5109/server/health".** Look at the server's log.
On a first run, the usual cause is a database setup file that failed. Its log names the file.

<div data-technical>

```bash
./setup/docker/launch.sh --logs   # look at vpt-server; vpt-db-init names the failing schema file
```

</div>

**The web app loads, but every action fails.** The browser cannot reach the server. Check that the address is the one your browser uses, and that the
firewall allows the ports listed below.

<div data-technical>

The browser must reach `PUBLIC_HOST:5109`. The setting is `PUBLIC_HOST` in `setup/docker/.env`. The firewall
must allow 5109, 6109, 6080, 3000 and 9000.

</div>

**"permission denied while trying to connect to the Docker daemon".** Your user is not in the Docker
group yet. Start a new login session.

<div data-technical>

```bash
newgrp docker   # or log out and back in
```

</div>

**The host container restarts in a loop.** Read its log. The host refuses to start when
`backend_host/src/.env` has no capture path, or, on macOS, when a `DEVICEn_VIDEO=/dev/videoX` line is enabled.

<div data-technical>

```bash
docker logs vpt-host
```

`HOST_VIDEO_CAPTURE_PATH` must be set in `backend_host/src/.env`.

</div>

**Image downloads hang at "Downloading" with no traffic,** while `curl` works fine on the same machine.
This happens on a machine that finds IPv6 addresses for Docker Hub but has no IPv6 route, which is typical
behind a NAT-only hypervisor. Turn IPv6 off, restart Docker and run the launcher again. Make the change permanent to keep it after a reboot.

<div data-technical>

```bash
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1
```

Make it permanent in `/etc/sysctl.d/`.

</div>

**Grafana answers nothing for the first 10 to 20 minutes on a slow disk.** Its first start runs a few
hundred database migrations, and the launcher does not wait for it. It is fine once Grafana reports healthy.

<div data-technical>

The first start runs a few hundred SQLite migrations, each an fsync. Check `http://<PUBLIC_HOST>:3000/api/health` until it returns `ok`.

</div>

**Another program already uses one of the ports** (5073, 5109, 3000, 54321 or 9000). Stop that program,
or change the ports in the Compose file.

<div data-technical>

The ports are the `ports:` lines in `setup/docker/docker-compose.yml`.

</div>

Variable reference: [configuration.md](configuration.md).
