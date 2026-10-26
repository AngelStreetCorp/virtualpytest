# Install VirtualPyTest

Everything runs in Docker on one machine. You need no account, no cloud service and no hardware to start.

<div data-technical>

```bash
curl -L https://github.com/AngelStreetCorp/virtualpytest/releases/latest/download/vpt-docker.tar.gz | tar xz
cd vpt-docker-*
./setup/docker/launch.sh
```

</div>

The launcher sets up the whole platform on this machine: the web app, the server, a device controller and dashboards. There is **nothing to edit first.**

<div data-technical>

The launcher starts 14 containers and connects them. It downloads the ready-made parts, creates every password, finds this machine's address and prints the web addresses. Nothing is built on your machine. The database has login and an API; a message queue and Grafana are included.

</div>

| | |
|---|---|
| You need | Linux or macOS · 4 CPU · 8 GB RAM · 30 GB free disk · Docker |
| Takes | about 3 minutes |
| Windows | run the same commands inside WSL2 |

Step by step, with the web addresses and the first test: **[Install with Docker](docker.md)**.

## Adding your own devices

Devices are set up in one settings file. Switch on the lines for a device, enter its address and run the launcher again.

<div data-technical>

The file is `backend_host/src/.env`. The device lines start with `x`, which switches them off. Drop the `x`:

```bash
xDEVICE1_NAME=AppleTv
xDEVICE1_MODEL=apple_tv
xDEVICE1_IP=192.168.1.27
```

Then re-run `./setup/docker/launch.sh`.

</div>

TVs, set-top boxes, phones and websites are all set up in that file. See [Hardware](hardware.md) for what to plug in, and [Emulators](emulators.md) to use an Android emulator.

## Which install do I want?

Most people want the first option.

| Your situation | Install | Page |
|---|---|---|
| Trying it out, a demo, a lab box, or one site on a trusted network | **Docker, one machine** | [docker.md](docker.md) |
| You have devices in a second location, or devices at the office and the platform on a server | **Docker here, host there** | [add-a-host.md](add-a-host.md) |
| You want native services (systemd) rather than containers, on one machine or one VM per role | **Linux installers** | [proxmox.md](proxmox.md) |
| You are changing VirtualPyTest's own code | **Developer setup** | [local-dev.md](local-dev.md) |

## Running it on a server you rent

A rented server is a Linux machine, and the same Docker install works on it. Once it is on the internet, do these first:

1. **Encrypt the connection.** Put Caddy or nginx in front of the app, serving HTTPS.
2. **Turn off open mode.** A fresh install lets anyone use the API without logging in. See [Supabase and authentication](supabase.md#enforce-login).
3. **Work through the [production checklist](production-checklist.md)** before it holds anything you care about.
4. **Open only the ports you need.** Keep the database screens, file storage and device controller private. [Network setup](network.md) lists the rules.

<div data-technical>

Providers that use the same install: Hetzner, AWS EC2, Azure, DigitalOcean, OVH and Scaleway. Choose on price and location.

Sizing: the 4 CPU, 8 GB and 30 GB above run the whole stack. A machine that also runs a device controller needs about 2 more CPU cores and 4 GB more RAM for each capture card.

Ports: the browser needs 5073 and 5109. Grafana 3000 is optional. Supabase Studio 54321, MinIO 9000/9001 and the host's 6109/6080 should stay private.

</div>

## What about Render, Vercel, Fly or App Runner?

These services can host **part** of VirtualPyTest, not the whole thing. The device controller needs direct access to your hardware, and a managed platform cannot give it that.

So run the server and web app on the managed platform, and keep the device controller on your own machine. That is the [Docker here, host there](add-a-host.md) setup. Start with a rented Linux server (a VPS) unless you already know you want managed services.

<div data-technical>

A managed platform runs one container with one port per service. The device controller needs two ports and direct access to your hardware. The [Cloud frontend + server](cloud-setup.md) page describes this split. It has more parts and more monthly bills than one Docker machine.

</div>

## After it is running

- **[User guide](../user-guide/README.md)**: your first test.
- **[Configuration reference](configuration.md)**: every setting and port.
- **[Branding](branding.md)**: name, logo, title and footer.
- **[Production checklist](production-checklist.md)**: everything to change before going online.
