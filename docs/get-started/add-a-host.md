# Add a machine with devices

A **host** is the piece that talks to your devices — HDMI capture cards, IR and Bluetooth
blasters, Android over the network, browsers. It runs next to the hardware, and it joins a
VirtualPyTest platform that already exists somewhere else.

Use this when your devices are not where the platform is: devices in a lab and the
platform on a server, devices at a customer site, or a second rack of set-top boxes added
to a platform you already run.

The device controller is the one piece that **cannot** be hosted for you: it needs physical
access to the hardware. Everything else can live anywhere.

## Install

On the machine with the devices:

**1. Get the bundle.**

```bash
curl -L https://github.com/AngelStreetCorp/virtualpytest/releases/latest/download/vpt-docker.tar.gz | tar xz
cd vpt-docker-*
```

**2. Tell it which platform to join** — do this *before* the first launch, or `launch.sh`
generates its own `API_KEY` and the server rejects the host. The file ships with a
"Host-only mode" block, commented out:

```bash
cp setup/docker/.env.example setup/docker/.env
$EDITOR setup/docker/.env        # uncomment and fill the "Host-only mode" block
```

Every value comes from the existing server's own `.env` and must match exactly:

| Variable | Where it comes from |
|---|---|
| `SERVER_URL` | the address of the existing server, e.g. `https://vpt.example.com` |
| `API_KEY` | the server's `API_KEY` — **identical on both sides** or the host is rejected |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | the platform's database |
| `MINIO_ENDPOINT` / `MINIO_PUBLIC_URL` (or `CLOUDFLARE_R2_*`) | the platform's storage, so captures land in the same bucket |
| `HOST_NAME` | a name unique to this machine, e.g. `lab-paris-1` |
| `PUBLIC_HOST` | this machine's address **as a browser reaches it** (see below) |

`HOST_NAME` and `PUBLIC_HOST` are near the top of the file rather than in the host-only
block. Anything you leave as `CHANGE_ME` gets a generated value, which is what you want
for everything except the shared values above.

**3. Configure the devices** in `backend_host/src/.env` — the same one file as any other
install. See [Install](install.md#adding-your-own-devices).

**4. Start it.**

```bash
./setup/docker/launch.sh --host-only
```

This pulls the prebuilt host image and starts one container: the device controller, its
browser and its VNC desktop. No database, no web UI, no Grafana — those are the
platform's, and it already has them.

## The part people get stuck on: the browser talks to the host directly

Streams and the VNC desktop are **not** proxied through the server. The browser connects
straight to this machine on ports 6109 and 6080, using the address in `PUBLIC_HOST`.

That is fine when the browser and the host are on the same network. It fails when the
platform is on a public server and the host sits in a lab behind NAT — the server can be
reached, the host cannot, and the UI shows a registered host whose video never loads.

Three ways to fix it, in the order I would try them:

**1. Tailscale (or any WireGuard mesh)** — simplest when the people using the UI are a
known team. Install Tailscale on the host and on the machines that open the UI, then set
`PUBLIC_HOST` to the host's Tailscale address. Nothing is exposed publicly.

**2. Cloudflare Tunnel** — best when the UI must work from anywhere, with no client
software. Run a tunnel on the host for ports 6109 and 6080, publish them as hostnames, and
set `PUBLIC_HOST` to the tunnel hostname. No inbound firewall rule at all.

**3. Port forwarding** — only on a network you control, and only with TLS and login
enabled. You are exposing a device controller and a remote desktop to the internet; read
the [production checklist](production-checklist.md) first.

Whichever you pick, `PUBLIC_HOST` must be the address **a browser** can reach — not the
host's LAN IP, and not `localhost`.

## Check it worked

```bash
curl -fsS http://localhost:6109/host/system/health
```

Then open the platform's web UI: the host appears under *Devices* with its name, and its
devices under it. If it registered but video does not load, it is the reachability problem
above, not the install.

## Notes

- One host can serve many devices; you do not need a machine per device.
- A host never stores test results itself — it writes captures to the platform's storage,
  which is why the `MINIO_*` / `CLOUDFLARE_R2_*` values must match the server's.
- Real hardware needs `/dev` access, which the Linux Docker override already grants. On
  macOS, USB capture cards and IR blasters are not passed into containers — use a browser
  or Android-over-network device there, or run the host on Linux.
- Native install instead of Docker: the per-role installers in [proxmox.md](proxmox.md).
