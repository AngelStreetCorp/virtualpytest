# Get started

Pick the way you want to run VirtualPyTest. Every path ends with the web UI on port 5073.

Buying a machine first? See [Hardware](hardware.md) — Raspberry Pi 5 or mini PC, capture card, with links.

Going beyond a trusted LAN? [Network setup](network.md) has the firewall rules, TLS and
remote-access options; [Security setup](security.md) covers certificates, API keys, CORS; [Production checklist](production-checklist.md) lists every shipped default to change before going online
and per-service exposure.
Letting guests drive devices? [Content filtering](content-filtering.md) keeps lab browsers and
emulators off adult and malware sites with one DNS change.

| Path | Best for | Time | One command |
|---|---|---|---|
| **[Docker](docker.md)** | first look, demo, lab box, single-site on a trusted network | 15 min | `./setup/docker/launch.sh` |
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

## After the install

- **[Configuration reference](configuration.md)** — every variable, every port, the versions.
- **[Supabase and authentication](supabase.md)** — open mode vs login, cloud vs self-hosted.
- **[Branding](branding.md)** — name, logo, title, footer.
- **[Cloud frontend + server](cloud-setup.md)** — Vercel + Render variant with a local host.
- **[CI](ci_cd.md)** — what the regression workflow runs.
- Then the [User Guide](../user-guide/README.md) for the first test.

## Architecture in one picture

```
 browser ──► frontend :5073 ──► backend_server :5109 ──► Supabase :54321 (Postgres + auth + REST)
                                      │                     MinIO/R2 (files)   Redis (queues)
                                      ▼                     Grafana :3000 (dashboards)
                               backend_host :6109  ──► devices (HDMI capture, IR/BLE, ADB, web)
                               (one per machine with hardware; VNC desktop on :6080)
```
