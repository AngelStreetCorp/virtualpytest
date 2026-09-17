# Get started

## What is VirtualPyTest?

VirtualPyTest is an open-source test automation platform for real devices — Android TV,
mobile, set-top boxes, smart TVs, and web. One navigation graph per app, driven by HDMI
capture, IR/Bluetooth, ADB, or a browser, with AI-assisted verification and Grafana analytics
on top. Every path below is self-hosted; nothing calls home. Every install ends with the web
UI on port 5073.

- One script drives every platform variant — mobile, Android TV, STB, web
- Visual + OCR + AI verification of what's actually on screen, not just a log line
- Built-in fleet dashboard, 24h screen rewind, and Grafana analytics
- Runs from a $100 Raspberry Pi to a full Proxmox fleet — same codebase either way

![Fleet dashboard: hosts, devices and live screen](/screenshot/features/fleet-status.webp)

## Architecture

![VirtualPyTest architecture: browser through frontend, backend_server, backend_host, to devices](/docs/get-started/images/architecture.svg)

`backend_host` runs once per machine that owns hardware; a host can run standalone and
register with a `backend_server` elsewhere (`--host-only` mode, or the host installers).

## Pick an install path

**In a hurry? → [Install VirtualPyTest](install.md)** — one download, one command, three
minutes, no hardware needed. That page also covers running it on a rented server
(Hetzner, AWS, Azure — all the same install) and what a managed platform can and cannot host.

| Path | Best for | Time | One command |
|---|---|---|---|
| **[Docker](docker.md)** | first look, demo, lab box, single-site on a trusted network | 3 min | `./setup/docker/launch.sh` |
| **[Add a host](add-a-host.md)** | a machine with devices joining a platform that runs elsewhere | 10 min | `./setup/docker/launch.sh --host-only` |
| **[One VM](proxmox.md#one-vm)** | a site install as native services (systemd) on one Debian/Ubuntu machine or VM | 30 min | `./setup/local/linux/install_all.sh` |
| **[Proxmox fleet](proxmox.md#proxmox-fleet)** | one VM per role (database, server, frontend, storage, monitoring, proxy, N hosts) | 2 h | per-role installers |
| **[Developer setup](local-dev.md)** | hacking on the code: foreground services with live logs, Windows/macOS device controllers | 30 min | `./setup/local/linux/install_core.sh` |

Every path installs a **Supabase** (Postgres + auth + REST) for you; you can point at a cloud
project instead — see [Supabase and authentication](supabase.md). Fresh installs start in
**open mode** (no login); the same page shows the three-line switch to enforced login.

## What you need

| | Docker | One VM / fleet | Developer |
|---|---|---|---|
| OS | Linux or macOS (Windows: WSL2) | Debian 12 / Ubuntu 22.04+ | Linux; macOS and Windows for the host role |
| CPU / RAM / disk | 4 / 8 GB / 30 GB | 4 / 8 GB / 60 GB per VM (host VMs: +2 CPU, +4 GB per capture card) | 4 / 8 GB / 30 GB |
| Software | Docker 24+ (installed by `setup/docker/install_docker.sh`) | nothing — the installer pulls Python 3.11, Node 22, Docker (for Supabase), Grafana, MinIO, Redis | same as One VM |
| Network | ports 5073, 5109, 6109, 6080, 3000, 54321 reachable by the browsers that use it | same | same |

Devices connect to the machine running the **host** role: HDMI capture cards, IR and
Bluetooth transmitters over USB, Android devices over the network, web targets over the
internet. A host can run on its own machine and join a server elsewhere
(`./setup/docker/launch.sh --host-only`, or the host installers).

What to buy for each role, with the models this project runs on: [Hardware](hardware.md).

## Where to go next

**Just want to try it?**
Run the [Docker](docker.md) quickstart, then the [User Guide](../user-guide/README.md) for
your first test.

**Configuring what you installed:**
- **[Configuration reference](configuration.md)** — every variable, every port, the versions.
- **[Supabase and authentication](supabase.md)** — open mode vs. login, cloud vs. self-hosted.
- **[Branding](branding.md)** — name, logo, title, footer.

**Going to production or beyond a trusted LAN?**
- **[Network setup](network.md)** — firewall rules, TLS, remote access.
- **[Security setup](security.md)** — certificates, API keys, CORS.
- **[Production checklist](production-checklist.md)** — every shipped default to change before going online.
- **[Content filtering](content-filtering.md)** — keep lab browsers and emulators off adult and malware sites.
- **[Managed cloud (Vercel + Render)](cloud-setup.md)** — the platform half hosted, the
  device controller still on your own machine. More moving parts than one Docker host —
  read [install.md](install.md#what-about-render-vercel-fly-or-app-runner) first.

**Building or extending:**
- **[CI](ci_cd.md)** — what the regression workflow runs.
- **[Hardware](hardware.md)** — capture cards, IR/BLE transmitters, machines this runs on.

**Want the full picture?**
[Browse all documentation](../README.md) — features, user guide, architecture, API reference, FAQ.
