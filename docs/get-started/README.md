# Get started

## What is VirtualPyTest?

VirtualPyTest is an open-source test automation and monitoring platform for TVs, set-top boxes, mobile devices, and web applications.

It lets you control real devices, verify what is actually displayed on screen, reuse the same test logic across platforms, and monitor your device fleet from one web interface.

* Run the same test logic across TV, STB, mobile, and web
* Verify screens using visual matching, OCR, and AI
* Control and monitor real devices from your browser
* Keep screenshots, video, reports, and execution evidence
* Self-host everything, from one machine to a distributed device lab

![Fleet dashboard: hosts, devices and live screen](/screenshot/features/fleet-status.webp)

## Try VirtualPyTest

The fastest way to get started is with Docker.

You do not need physical hardware for your first look. The installer sets up the complete platform and prints the URL to open when it is ready.

**[Install VirtualPyTest →](install.md)**

For a standard Docker installation:

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/docker/install_docker.sh
./setup/docker/launch.sh
```

Already have Docker? You can skip `install_docker.sh`.

## Choose your path

Not sure which setup you need? Start with Docker. You can move to a larger deployment later without changing how VirtualPyTest works.

| I want to…                                    | Start here                       |
| --------------------------------------------- | -------------------------------- |
| **Try VirtualPyTest or run a small lab**      | [Docker quick start](docker.md)  |
| **Install VirtualPyTest on a server or VM**   | [Installation guide](install.md) |
| **Install VirtualPyTest on a Google Cloud VM**| [GCP standalone](gcp-standalone.md) |
| **Connect another machine that owns devices** | [Add a host](add-a-host.md)      |
| **Build a larger multi-machine lab**          | [Proxmox deployment](proxmox.md) |
| **Develop or modify VirtualPyTest**           | [Developer setup](local-dev.md)  |

## What you need

For the quickest start, use a machine with:

* Linux or macOS
* 4 CPU cores
* 8 GB RAM
* 30 GB free disk space
* Docker 24 or newer

Windows users can run the Docker setup through WSL2.

The installer sets up the database and supporting services automatically.

You can explore VirtualPyTest without connecting physical devices. When you are ready to add real hardware, see the [Hardware guide](hardware.md).

## How devices connect

VirtualPyTest separates the platform from the machines that control devices.

A **host** is a machine connected to your devices. Depending on the device, it can control and capture them using technologies such as:

* HDMI capture
* IR or Bluetooth remotes
* ADB
* Appium
* Browser automation

A small installation can run everything on one machine. Larger labs can add multiple hosts while keeping one central VirtualPyTest platform.

![VirtualPyTest architecture: browser through frontend, backend\_server, backend\_host, to devices](/docs/get-started/images/architecture.svg)

You do not need to understand this architecture to try VirtualPyTest. The standard Docker installation configures it for you.

## After installation

Once VirtualPyTest is running, continue with the [User Guide](../user-guide/README.md) to:

1. Open the web interface
2. Add or select a device
3. Create or import navigation
4. Run your first test
5. Review screenshots, video, and results

## Running in production

The default installation is designed to make local evaluation easy.

Before exposing VirtualPyTest outside a trusted network, review:

* [Production checklist](production-checklist.md)
* [Security setup](security.md)
* [Network setup](network.md)
* [Supabase and authentication](supabase.md)

These guides cover authentication, TLS, firewall rules, API keys, CORS, and other production settings.

## More installation options

VirtualPyTest can run on anything from a small lab machine to a distributed fleet.

For advanced deployments:

* [One VM](proxmox.md#one-vm) — run the platform as native services on one Debian or Ubuntu machine
* [Proxmox fleet](proxmox.md#proxmox-fleet) — separate database, server, frontend, storage, monitoring, proxy, and device hosts
* [Managed cloud](cloud-setup.md) — host parts of the platform remotely while keeping device controllers close to the hardware
* [Free cloud starter](../user-guide/free-cloud-starter.md) — a low-cost showcase using Render, Supabase, and a Linux host VM
* [Configuration reference](configuration.md) — environment variables, services, ports, and versions

## Where to go next

**Just trying VirtualPyTest?**
Start with the [Docker quick start](docker.md), then follow the [User Guide](../user-guide/README.md).

**Connecting real devices?**
See [Hardware](hardware.md) and the relevant device setup guide.

**Deploying beyond one machine?**
See [Add a host](add-a-host.md) or the [Proxmox deployment guide](proxmox.md).

**Building or extending VirtualPyTest?**
See the [Developer setup](local-dev.md), [CI guide](ci_cd.md), and [full documentation](../README.md).
