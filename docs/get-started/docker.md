# Install with Docker (one machine)

This page describes the **full Docker Compose stack**: server, host, frontend, Supabase, Redis,
object storage, and Grafana. The VirtualPyTest application itself is three images
(`virtualpytest-server`, `virtualpytest-host`, and `virtualpytest-frontend`), pulled or built by
Compose; there is no single monolithic VirtualPyTest image. If this machine only owns devices and
the platform runs elsewhere, use [host-only mode](add-a-host.md) instead.

The whole platform on one Linux or macOS machine, in one command. Good for a first look,
a demo, a lab box, or a single-site deployment on a trusted network.

**You need:** Linux (Ubuntu 22.04+/Debian 12+ recommended) or macOS with Docker Desktop ·
4 CPU / 8 GB RAM / 30 GB free disk · internet access for the first build. Windows: run the
same commands inside WSL2, or install only a device controller on Windows (see
[Windows host](local-dev.md#windows)).

**What you get:** the web UI, the server API, one device controller ("host") with a
VNC desktop, a self-hosted Supabase (Postgres + auth + REST + Studio), MinIO object
storage, Redis and Grafana — all as containers on this machine.

## 1. Install

Download the standalone bundle — about half a megabyte, everything the stack needs:

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

Both are the same stack and the same commands from here on. The bundle carries the compose
files, the database schema, the Grafana dashboards and the shipped test scripts — the
paths the containers mount — and pulls everything else from the registry.

If `install_docker.sh` just added your user to the `docker` group, log out and back in
(or run `newgrp docker`) before `launch.sh`.

`launch.sh` does, in order:

1. creates `setup/docker/.env` from `.env.example` — every secret generated, `PUBLIC_HOST`
   set to this machine's LAN address;
2. creates `backend_host/src/.env` from its example (VNC desktop capture on, physical
   devices off);
3. pulls the images and builds the three VirtualPyTest images (first run: 5–15 minutes
   depending on bandwidth and CPU; later runs: seconds);
4. applies the database schema once, then waits until the server API answers;
5. prints the URLs.

### Skip the build (prebuilt images)

Step 3 is the slow part. Prebuilt backend images are published to GHCR so you can pull them
instead of building them. Before the first `launch.sh`, or any time afterwards, set the tag in
`setup/docker/.env`:

```bash
VPT_IMAGE_TAG=latest                  # the most recently published images
VPT_IMAGE_TAG=main-2026.09.17-9151    # or a specific release, to freeze it
# default is `local` = build from this checkout
```

**Images are published on purpose, not on every release.** They are big and slow to build, and
nothing depends on them — the default builds from your checkout, and a pull that finds no such
tag falls back to building. So a given release may not have an image, and `latest` is the last
one that was published rather than the newest release. If you need the images to match a
specific release exactly, build it: `VPT_IMAGE_TAG=local`.

`launch.sh` then pulls all three images — `virtualpytest-server`, `-host` and
`-frontend` from `ghcr.io/angelstreetcorp` — and **nothing compiles on your machine**: a
first run in about two minutes instead of fifteen. If the pull fails (no network, or a tag
that was never published) it falls back to building, so the command always works.

**A prebuilt image is the code of *its* build, not of your working tree.** If you edit anything under `backend_server/`, `backend_host/` or `frontend/`,
set `VPT_IMAGE_TAG=local` (or run `./setup/docker/launch.sh --rebuild`) or your change will
not be in the running container.

The frontend image takes its configuration at **run** time, not build time: its entrypoint
writes `dist/config.js` from the container's environment on every start, so changing
`PUBLIC_HOST` needs a restart rather than a rebuild, and one image serves any address.

Images are `linux/amd64` only. On arm64 (Apple Silicon, a Raspberry Pi) leave
`VPT_IMAGE_TAG=local` and build.

## 2. Open it

| What | URL |
|---|---|
| Web UI | `http://<PUBLIC_HOST>:5073` |
| Server API | `http://<PUBLIC_HOST>:5109` (`/server/health`) |
| Host API / host desktop (noVNC) | `http://<PUBLIC_HOST>:6109` / `http://<PUBLIC_HOST>:6080/vnc_lite.html` |
| Grafana | `http://<PUBLIC_HOST>:3000` — `admin` / `GRAFANA_ADMIN_PASSWORD` from `setup/docker/.env` |
| Supabase Studio | `http://<PUBLIC_HOST>:54321` — `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` from `.env` |
| MinIO console | `http://<PUBLIC_HOST>:9001` — `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env` |

`PUBLIC_HOST` is printed by `launch.sh` and stored in `setup/docker/.env`. Every URL the
platform hands to a browser is built from it, so if you later reach the machine by another
address (a DNS name, a VPN address), change `PUBLIC_HOST` and run `./setup/docker/launch.sh`
— a restart is enough, the frontend reads it at startup rather than baking it in.

The stack starts in **open mode**: no login, every API call accepted. `launch.sh` prints a
warning while that is the case. Keep the machine on a trusted network, or enable login —
see [Supabase and authentication](supabase.md#enforce-login).

## 3. First test

1. In the web UI, the host `docker-host` is already registered (it appears under
   *Devices* with its VNC desktop as the capture source).
2. Go to *Run Tests*, pick the host, pick `web/dailymotion_video_check` (or any `web/…`
   script) and run it. The host opens Chromium on its VNC desktop; you can watch it live on
   the noVNC URL above.
3. The result appears in *Test Results*, with the captures stored in MinIO and the KPIs in
   Grafana.

## 4. Add a real device

`backend_host/src/.env` is **the only file you edit.** Everything else — secrets,
addresses, the database — `launch.sh` handles.

It ships with the browser and VNC desktop on and physical devices off. "Off" means each
device line carries an `x` prefix, which is how this file disables a setting:

```bash
xDEVICE1_NAME=AppleTv          # ← drop the x on the lines you want
xDEVICE1_MODEL=apple_tv
xDEVICE1_IP=192.168.1.27
xDEVICE1_VIDEO=/dev/video0
```

So enabling a device is: remove the `x`, set its address and capture paths, restart.

```bash
nano backend_host/src/.env          # drop the x, set DEVICE1_* for your hardware
./setup/docker/launch.sh            # restarts the host container with the new config
```

The file carries commented examples for a TV/STB with HDMI capture and IR, an Android
device over the network, and a smart plug.

On Linux the host container sees the machine's `/dev` (USB capture cards, IR transmitters,
serial). Each capture path also needs a RAM-backed hot directory: add one `tmpfs` line per
`DEVICEn_VIDEO_CAPTURE_PATH` in `setup/docker/docker-compose.linux.yml` (the file shows the
default one). On macOS there is no `/dev` passthrough — use network-controlled devices
(Android over ADB, web) or run the host part on a Linux machine with
[`--host-only`](#more-than-one-machine).

## 5. Everyday commands

```bash
./setup/docker/launch.sh --logs      # follow all logs
./setup/docker/launch.sh --down      # stop (data kept)
./setup/docker/launch.sh             # start again
./setup/docker/launch.sh --rebuild   # after a git pull (PUBLIC_HOST / VITE_* now take effect on restart)
./setup/docker/launch.sh --reset     # stop AND delete all data volumes (asks for confirmation)
```

Data lives in Docker volumes: `virtualpytest_supabase-db-data` (database),
`virtualpytest_minio-data` (files), `virtualpytest_stream-data` (captures),
`virtualpytest_grafana-data`. Back up the database with
`docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql`.

## More than one machine

Run the stack on one machine and a device controller on each machine that has the
hardware — `./setup/docker/launch.sh --host-only`.

Full instructions, including the one thing that catches everyone (the browser connects to
the host directly, so a host behind NAT needs a tunnel): **[Add a machine with
devices](add-a-host.md)**.

## Before exposing it beyond the LAN

The stack publishes plain HTTP on several ports and starts in open mode. Before anything
but a trusted LAN can reach the machine:

1. enforce login — [supabase.md](supabase.md#enforce-login);
2. put a reverse proxy with TLS in front (an nginx example: `infra/proxy/nginx/config/docker.conf`)
   and set `PUBLIC_HOST` to the public name, then `./setup/docker/launch.sh --rebuild`;
3. firewall everything else:
   ```bash
   sudo ufw default deny incoming && sudo ufw default allow outgoing
   sudo ufw allow from <your-lan>/24 to any port 22
   sudo ufw allow 80/tcp && sudo ufw allow 443/tcp        # the proxy
   sudo ufw enable
   ```
   Studio (54321), Postgres (54322), MinIO (9000/9001) and Grafana (3000) must never be
   reachable from the internet; change the `DASHBOARD_PASSWORD` / `MINIO_SECRET_KEY` /
   `GRAFANA_ADMIN_PASSWORD` defaults if the machine is shared.

## Troubleshooting

- **`launch.sh` stops at "waiting for http://localhost:5109/server/health"** — run
  `./setup/docker/launch.sh --logs` and look at `vpt-server`. The usual cause on a first run
  is `vpt-db-init` failing on a schema file; its log names the file.
- **Web UI loads but every action fails** — the browser cannot reach `PUBLIC_HOST:5109`.
  Check that `PUBLIC_HOST` in `setup/docker/.env` is the address your browser uses and that
  the firewall allows 5109, 6109, 6080, 3000, 9000.
- **`permission denied while trying to connect to the Docker daemon`** — your user is not in
  the `docker` group yet: `newgrp docker` or log out and back in.
- **Host container restarts in a loop** — `docker logs vpt-host`. It refuses to start when
  `backend_host/src/.env` has no capture path (`HOST_VIDEO_CAPTURE_PATH` must be set) and on
  macOS when a `DEVICEn_VIDEO=/dev/videoX` is enabled.
- **Image pulls hang at "Downloading" with no traffic** while `curl` from the same machine is
  fast — the machine resolves IPv6 addresses for Docker Hub but has no IPv6 route (typical
  behind a NAT-only hypervisor). `sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1`, restart
  Docker, run `launch.sh` again (make it permanent in `/etc/sysctl.d/`).
- **Grafana answers nothing for the first 10–20 minutes on a slow disk** — its first start runs
  a few hundred SQLite migrations, each an fsync; the launcher does not wait for it. It is
  fine once `http://<PUBLIC_HOST>:3000/api/health` returns `ok`.
- **Ports already in use** — another service on 5073/5109/3000/54321/9000. Stop it, or edit
  the `ports:` lines in `setup/docker/docker-compose.yml`.

Variable reference: [configuration.md](configuration.md).
