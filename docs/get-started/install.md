# Install VirtualPyTest

Everything runs in Docker on one machine. Download the bundle, run one command, open the
web UI — no account, no cloud service, no hardware needed to start.

```bash
curl -L https://github.com/AngelStreetCorp/virtualpytest/releases/latest/download/vpt-docker.tar.gz | tar xz
cd vpt-docker-*
./setup/docker/launch.sh
```

That gives you the whole platform on this machine: the web UI, the server API, a device
controller with a browser and a VNC desktop, a database (Postgres with auth and a REST
API), object storage, a queue, and Grafana dashboards — 14 containers, started and wired
together for you. `launch.sh` generates every password, finds this machine's address,
pulls the prebuilt images and prints the URLs. Nothing is compiled on your machine and
there is **nothing to edit first.**

| | |
|---|---|
| You need | Linux or macOS · 4 CPU · 8 GB RAM · 30 GB free disk · Docker |
| Takes | about 3 minutes |
| Windows | run the same commands inside WSL2 |

Step by step, with the URLs and the first test: **[Install with Docker](docker.md)**.

## Adding your own devices

`backend_host/src/.env` is **the only file you ever edit.**

It ships with the browser and VNC desktop switched on and physical devices switched off —
every device line is prefixed with `x`, which disables it:

```bash
xDEVICE1_NAME=AppleTv
xDEVICE1_MODEL=apple_tv
xDEVICE1_IP=192.168.1.27
```

Drop the `x`, set your device's address, re-run `./setup/docker/launch.sh`, and it appears
in the UI. TVs, set-top boxes, phones and websites are all configured in that one file —
see [Hardware](hardware.md) for what to plug in, and [Emulators](emulators.md) to use an
Android emulator instead of a physical device.

## Which install do I want?

Most people want the first row. The others exist for a reason, not for completeness.

| Your situation | Install | Page |
|---|---|---|
| Trying it out, a demo, a lab box, or one site on a trusted network | **Docker, one machine** | [docker.md](docker.md) |
| You have devices in a second location, or devices at the office and the platform on a server | **Docker here, host there** | [add-a-host.md](add-a-host.md) |
| You want native services (systemd) rather than containers, on one machine or one VM per role | **Linux installers** | [proxmox.md](proxmox.md) |
| You are changing VirtualPyTest's own code | **Developer setup** | [local-dev.md](local-dev.md) |

## Running it on a server you rent

A rented server is just a Linux box, so **Hetzner, AWS EC2, Azure, DigitalOcean, OVH and
Scaleway are all the same install** — the Docker path above, unchanged. Pick any of them
on price and location; nothing in VirtualPyTest is provider-specific.

What changes is not the install but what you add around it, because the machine is now
reachable from the internet:

1. **Put TLS in front of it.** Caddy or nginx terminating HTTPS for ports 5073 and 5109.
2. **Close open mode.** A fresh install accepts every API call with no login — fine on a
   trusted LAN, not on a public address. See [Supabase and authentication](supabase.md#enforce-login).
3. **Walk the [production checklist](production-checklist.md)** before it holds anything
   you care about.
4. **Only open the ports you need.** The browser needs 5073 and 5109; Grafana 3000 is
   optional; Supabase Studio 54321, MinIO 9000/9001 and the host's 6109/6080 should stay
   on your own network or behind a VPN. [Network setup](network.md) has the rules.

Sizing: the 4 CPU / 8 GB / 30 GB above runs the whole stack. Add ~2 CPU and ~4 GB per
capture card on a machine that also runs a host.

## What about Render, Vercel, Fly or App Runner?

They can host **part** of it, not the whole thing, and it is worth knowing why before you
try: a managed platform gives one container and one port per service, and the device
controller needs two ports plus direct access to your hardware. So on a managed platform
you would run the server and the frontend there, use hosted Postgres and object storage,
and **keep the device controller on your own machine** — which is the
[Docker here, host there](add-a-host.md) shape with the platform half rented.

That is a real deployment and [Cloud frontend + server](cloud-setup.md) describes it, but
it is more moving parts, more monthly bills and more ways to be misconfigured than one
Docker host on a VPS. Start with a VPS unless you already know you want managed services.

## After it is running

- **[User guide](../user-guide/README.md)** — your first test.
- **[Configuration reference](configuration.md)** — every variable and port.
- **[Branding](branding.md)** — name, logo, title, footer.
- **[Production checklist](production-checklist.md)** — everything to change before going online.
