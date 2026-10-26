# Get Started

## What is VirtualPyTest?

VirtualPyTest tests and watches TVs, set-top boxes, phones, tablets and web applications. It is open source.

* Run the same test on TV, set-top box, mobile and web
* Check screens with image matching, text reading (OCR) and AI
* Control and watch real devices from your browser
* Keep screenshots, video and reports

![Fleet dashboard: hosts, devices and live screen](/screenshot/features/fleet-status.webp)

## Try VirtualPyTest

The quickest start is Docker. You need no device for a first look. The installer shows the web address when the platform is ready.

**[Install VirtualPyTest →](install.md)**

<div data-technical>

For a standard Docker installation:

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/docker/install_docker.sh
./setup/docker/launch.sh
```

Already have Docker? You can skip `install_docker.sh`.

</div>

## Choose your path

Not sure? Start with Docker.

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

Windows users can use WSL2.

The installer sets up the rest for you. You can explore without any device. For real hardware, see the [Hardware guide](hardware.md).

## How devices connect

VirtualPyTest has two parts: the platform, and the machines that touch your devices. Such a machine is a **host**. It controls your devices and records what they show. A bigger lab adds more hosts.

<div data-technical>

A host uses the connections that fit each device: HDMI capture, IR or Bluetooth remotes, ADB, Appium and browser automation.

</div>

![VirtualPyTest architecture: browser through frontend, backend\_server, backend\_host, to devices](/docs/get-started/images/architecture.svg)

You do not need this picture to start.

## After installation

Then follow the [User Guide](../user-guide/README.md). It shows you how to open the web interface, add a device, run your first test and review the results.

<div data-technical>

The User Guide steps, in order: open the web interface, add or choose a device, create or import navigation, run your first test, review screenshots, video and results.

</div>

## Running in production

The default installation is for trying things out. Before you open it to the internet, read:

* [Production checklist](production-checklist.md)
* [Security setup](security.md)
* [Network setup](network.md)
* [Supabase and authentication](supabase.md)

These guides cover logins, secure connections, firewalls and API keys.

<div data-technical>

They also cover CORS.

</div>

## More installation options

For bigger setups:

* [One VM](proxmox.md#one-vm): everything on one Debian or Ubuntu machine
* [Proxmox fleet](proxmox.md#proxmox-fleet): separate machines for each part
* [Managed cloud](cloud-setup.md): parts run in the cloud
* [Free cloud starter](../user-guide/free-cloud-starter.md): a low-cost showcase
* [Configuration reference](configuration.md): all settings

<div data-technical>

The free cloud starter uses Render, Supabase and a Linux host VM. The Proxmox fleet runs the database, server, web app, storage, monitoring, proxy and device hosts on separate machines.

</div>

## Where to go next

* Real devices: [Hardware](hardware.md)
* More machines: [Add a host](add-a-host.md) or the [Proxmox deployment guide](proxmox.md)
* Building or changing VirtualPyTest: the [Developer setup](local-dev.md), the [CI guide](ci_cd.md) and the [full documentation](../README.md)
* Container images: [Publishing container images](publishing-images.md)

<div data-technical>

That page covers `workflow_dispatch` on the public repo, what the `verify` job asserts, how users consume the published tags, and how to roll back a bad tag.

</div>
