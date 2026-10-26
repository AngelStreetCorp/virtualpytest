# Add a machine with devices

A **host** talks to your devices: capture cards, remotes and Android devices. It runs next to the hardware and joins a platform that already exists elsewhere. Use this when your devices are not where the platform is.

<div data-technical>

Examples: devices in a lab and the platform on a server, devices at a customer site, or a second rack of set-top boxes added to a platform you already run. The device controller is the one part that cannot be hosted for you, because it needs physical access to the hardware. Everything else can live anywhere.

</div>

## Install

Do this on the machine that has the devices.

**1. Get the bundle.** It is the same as the one-machine install.

<div data-technical>

```bash
curl -L https://github.com/AngelStreetCorp/virtualpytest/releases/latest/download/vpt-docker.tar.gz | tar xz
cd vpt-docker-*
```

</div>

**2. Tell it which platform to join.** Do this before the first launch, or the server turns the host away. Copy the values from the existing server's settings exactly. You choose only the host name and this machine's address.

<div data-technical>

The settings file has a "Host-only mode" block that is switched off by default. Turn it on and fill it in. `HOST_NAME` and `PUBLIC_HOST` are near the top of the file, not in that block. Anything you leave as `CHANGE_ME` gets a generated value. That is what you want for everything except the shared values below.

```bash
cp setup/docker/.env.example setup/docker/.env
$EDITOR setup/docker/.env        # uncomment and fill the "Host-only mode" block
```

| Variable | Where it comes from |
|---|---|
| `SERVER_URL` | the address of the existing server, e.g. `https://vpt.example.com` |
| `API_KEY` | the server's `API_KEY` — **identical on both sides** or the host is rejected |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | the platform's database |
| `MINIO_ENDPOINT` / `MINIO_PUBLIC_URL` (or `CLOUDFLARE_R2_*`) | the platform's storage, so captures land in the same bucket |
| `HOST_NAME` | a name unique to this machine, e.g. `lab-paris-1` |
| `PUBLIC_HOST` | this machine's address **as a browser reaches it** (see below) |

</div>

**3. Set up the devices.** Follow [Install](install.md#adding-your-own-devices).

<div data-technical>

The device settings file is `backend_host/src/.env`.

</div>

**4. Start it.** Only the device part starts. The platform already has its database, web app and Grafana.

<div data-technical>

```bash
./setup/docker/launch.sh --host-only
```

This pulls the prebuilt host image and starts one container: the device controller, its browser and its VNC desktop. No database, no web UI, no Grafana.

</div>

## The part people get stuck on: the browser talks to the host directly

Video and the remote desktop go from the browser straight to this machine, not through the server. That works when both are on the same network. If the platform is public and the host sits behind a router, the host shows up in the web app but its video never loads.

There are three ways to fix this. Try them in this order.

1. **A private network such as Tailscale.** The simplest choice for a known team. Install it on the host and on the machines that open the app.
2. **A Cloudflare Tunnel.** Best when the app must work from anywhere, with no software on the client.
3. **Port forwarding.** Only on a network you control, with TLS and login turned on. You expose the device controller and remote desktop to the internet, so read the [production checklist](production-checklist.md) first.

<div data-technical>

For Tailscale, set `PUBLIC_HOST` to the host's address on that network. Nothing is exposed to the public internet.

For a Cloudflare Tunnel, run a tunnel on the host, publish its ports as names, and set `PUBLIC_HOST` to the tunnel name. No inbound firewall rule is needed.

Port forwarding exposes the host's ports directly. Ports to reach: 6109 (host API) and 6080 (VNC desktop, noVNC).

Whichever you pick, `PUBLIC_HOST` must be an address a **browser** can reach. It must not be the host's LAN address, and it must not be `localhost`.

</div>

## Check it worked

Open the web app. The host appears under *Devices*. If it shows up but video does not load, the cause is reachability, not the install.

<div data-technical>

```bash
curl -fsS http://localhost:6109/host/system/health
```

</div>

## Notes

- One host can serve many devices. You do not need one machine per device.
- A host stores no test results. Captures go to the platform's storage.
- USB capture cards and infrared remotes cannot be passed into Docker on macOS. Use a browser or an Android device over the network there, or run the host on Linux.
- To install without Docker, use the per-job installers in [proxmox.md](proxmox.md).

<div data-technical>

A host never stores test results. It writes captures to the platform's storage. That is why the file storage values must match the server's.

Real hardware needs access to the machine's device files. The Linux container setup already grants this. On macOS, USB capture cards and infrared remotes cannot be passed into containers.

File storage values: `MINIO_*` or `CLOUDFLARE_R2_*`, which must match the server's. Device access: `/dev`, granted by the Linux Docker override.

</div>
