# ☁️ Google Cloud — standalone install

> **Read [Install](install.md) first.** The Docker path there works
> on any rented Linux box — Hetzner, AWS, DigitalOcean, Scaleway, OVH, GCP,
> anywhere. This page adds only what is specific to a single GCP VM: project
> setup and OS Login / SSH access.
>
> **One VM, full platform.** This guide keeps the entire stack — Supabase,
> Redis, MinIO, Grafana, backend server, backend host, frontend — on a single
> Compute Engine instance. It does **not** cover splitting the stack across
> multiple GCP projects or across GCP + another cloud; for that, follow
> [Managed cloud (Vercel + Render)](cloud-setup.md).

A standalone GCP install is for: a long-running demo, a lab box you want to
reach from anywhere, a single-site deployment on a public cloud you already
have an account with. It is **not** a free path: GCP's Always Free `e2-micro`
(1 GB RAM) is too small for the full stack — see [Free cloud starter](../user-guide/free-cloud-starter.md)
for that tier.

## Recommended architecture

```text
┌──────────────────────────────────────────────────────────┐
│ GCP VM  e2-custom-4-8192  Debian 13  us/eu/asia           │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ Docker Compose (setup/docker/docker-compose.yml)     │ │
│ │  frontend · backend_server · backend_host            │ │
│ │  redis · db-init · supabase (7 services) · grafana   │ │
│ │  ── MinIO runs as a host systemd service (see §6) ──  │ │
│ └──────────────────────────────────────────────────────┘ │
│  systemd:  minio.service  (RELEASE.2025-07-23T15-54-02Z) │
│  gcloud CLI on the box for SSH + image pulls             │
└──────────────────────────────────────────────────────────┘
             ▲
             │ HTTPS through Identity-Aware Proxy (recommended)
             │ or SSH tunnel (zero firewall changes)
```

| | |
|---|---|
| OS | Debian 13 (trixie), x86_64 |
| Machine type | `e2-custom-4-8192` — 4 vCPU, 8 GB RAM |
| Boot disk | 30 GB `pd-balanced` (the 10 GB default is too small; see §3) |
| Region / zone | any — pick on latency and quota; `europe-west9` and `us-central1` are well-provisioned |
| Internal IP | static (optional but recommended for stable `PUBLIC_HOST`) |
| External IP | ephemeral is fine for a demo; reserve a static address if you want a stable URL |
| Takes | about 25 minutes (most of it pulling the 9 GB backend images) |

## What you need on the workstation

A machine with `gcloud` (Google Cloud CLI) installed and authenticated to the
GCP project that will own the VM. `gcloud` handles SSH key installation on
new VMs through OS Login, so you do not need to pre-authorize any keys.

```bash
# Install (macOS / Linux; on macOS brew is the simplest path)
curl -fsSL -o /tmp/gcloud.tgz \
  https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-x86_64.tar.gz
tar -xzf /tmp/gcloud.tgz -C ~               # extracts to ~/google-cloud-sdk
~/google-cloud-sdk/bin/gcloud --version      # 586.0.0 at time of writing

# Authenticate (browser opens once)
~/google-cloud-sdk/bin/gcloud auth login
~/google-cloud-sdk/bin/gcloud config set project <your-project-id>

# Confirm you can list instances
~/google-cloud-sdk/bin/gcloud compute instances list --project=<your-project-id>
```

## 1. Create the GCP project (one-time)

If you do not have a GCP project yet:

```bash
gcloud projects create <your-project-id> --name="VirtualPyTest standalone"
gcloud config set project <your-project-id>
# Enable the APIs the install touches
gcloud services enable compute.googleapis.com iam.googleapis.com oslogin.googleapis.com
# Link a billing account — required to create VMs
gcloud billing projects link <your-project-id> --billing-account=<BILLING_ACCOUNT_ID>
```

The user you authenticate with must have `roles/compute.instanceAdmin.v1`
on the project and `roles/iam.serviceAccountUser` on the default Compute
service account.

## 2. Create the VM

```bash
gcloud compute instances create vpt-standalone \
  --project=<your-project-id> \
  --zone=<zone> \
  --machine-type=e2-custom-4-8192 \
  --image-family=debian-13 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced
```

Three things to notice:

1. **Disk size = 30 GB.** The 10 GB default fills up while pulling the backend
   images (`backend_host` alone is 6.7 GB and the host's apt layer is another
   ~2 GB). Resizing later works but is more friction — start big.
2. **Debian 13 cloud-init image.** Cloud-init auto-grows the partition to the
   full disk on first boot; you do **not** need to run `resize2fs` or
   `growpart` by hand.
3. **OS Login is on by default.** `gcloud compute ssh` pushes an ephemeral
   SSH key into the VM's metadata on every call — you do not need to manage
   `~/.ssh/authorized_keys`.

Wait for SSH to be ready, then verify:

```bash
# Wait until the SSH key has propagated
for i in $(seq 1 24); do
  gcloud compute ssh virtualpytest@vpt-standalone --project=<your-project-id> --zone=<zone> \
    --command='echo OK' >/dev/null 2>&1 && break
  sleep 5
done

# Confirm from inside the VM
gcloud compute ssh virtualpytest@vpt-standalone --project=<your-project-id> --zone=<zone> \
  --command='cat /etc/os-release | head -3; uname -a; nproc; df -h / | tail -1'
```

You should see `Debian GNU/Linux 13 (trixie)`, kernel 6.12.x, `4` CPUs, and
`~30G` on `/`.

## 3. Install Docker Engine + Compose plugin

The repo has a script for this (`setup/docker/install_docker.sh`) that works
on macOS and most Debian-family distros; on a fresh Debian 13 image the
cleanest path is the official Docker apt repo:

```bash
gcloud compute ssh virtualpytest@vpt-standalone --project=<your-project-id> --zone=<zone>

sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian trixie stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                         docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker virtualpytest
# log out and back in (or run `newgrp docker`) so the group takes effect
```

Verify:

```bash
docker --version         # Docker version 29.8.1, build ...
docker compose version   # Docker Compose version v5.5.1
docker info              # Server Version: 29.8.1, Storage Driver: overlayfs, ...
```

## 4. Clone the repo at the release tag

The VM does not need write access — clone over HTTPS, anonymous:

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
git checkout main-2026.09.24-9321   # exact tag you are deploying
# Or, if you maintain a fork: git clone <your-fork-url>
```

Confirm the working tree matches the release:

```bash
git log -1 --oneline   # a2adff3 release: main-2026.09.24-9321
cat VERSION.txt        # current:main-2026.09.24-9321
```

> **Do not modify the public repo.** The steps below edit the local clone
> only; never `git push` from this VM unless you intend the change upstream.

## 5. Configure `.env` and pull the published images

```bash
cd setup/docker
cp .env.example .env

# Use the published release tag (skips ~10 min local build; pulls from GHCR)
sed -i 's|^VPT_IMAGE_TAG=.*|VPT_IMAGE_TAG=main-2026.09.24-9321|' .env
sed -i 's|^VPT_REGISTRY=.*|VPT_REGISTRY=ghcr.io/angelstreetcorp|' .env

# Public address for the browser URLs. Use the VM's external IP for now;
# switch to a hostname once you have one (see §7).
EXTERNAL_IP=$(curl -sH "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
sed -i "s|^PUBLIC_HOST=.*|PUBLIC_HOST=${EXTERNAL_IP}|" .env

# Identity tags so this server and host appear in the registry under
# recognisable names.
sed -i 's|^SERVER_NAME=.*|SERVER_NAME=vpt-gcloud|' .env
sed -i 's|^HOST_NAME=.*|HOST_NAME=vpt-gcloud-host|' .env
```

Launch populates the rest — every `CHANGE_ME` is replaced with a random
secret by `launch.sh` itself on first start, and the Supabase anon /
service-role JWTs are derived from `JWT_SECRET`.

```bash
cd setup/docker
docker compose -f docker-compose.yml -f docker-compose.linux.yml \
  pull --ignore-pull-failures
```

Expect ~9 GB of pulls. If any pull fails with `no space left on device`,
double-check `df -h /` — the 30 GB boot disk is the minimum for this image set.

## 6. The MinIO workaround (resolved)

`quay.io/minio/minio` and `quay.io/minio/mc` stopped accepting anonymous
pulls in late 2026 (`docker.io/minio/minio` does not exist on Docker Hub,
and `bitnami/minio` returns empty tag lists), which broke the `minio` /
`minio-init` services in `docker-compose.yml`. Fixed: those two services now
build from `setup/docker/images/minio/Dockerfile` and
`setup/docker/images/minio-mc/Dockerfile`, which vendor the same pinned
MinIO/mc versions from their GitHub release assets instead — the direct
GitHub download URLs still resolve even though the registries don't. Nothing
to do on a fresh install; `git pull` + `./launch.sh --rebuild` fixes an
existing one. `setup/local/linux/storage/install_minio.sh` (the native,
non-Docker install path) uses the same GitHub source.

## 7. Bring the stack up

```bash
docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d
sleep 30
curl -s http://localhost:5109/server/health
# {"db_key_role":"service_role","redis":"connected","status":"ok","supabase":"connected",...}
```

`docker compose ps` should show every service as `Up` / `healthy`:

```
vpt-frontend            Up   (healthy)   5073
vpt-server              Up   (healthy)   5109
vpt-host                Up   (healthy)   6109
vpt-supabase-db         Up   (healthy)   54322
vpt-supabase-auth       Up   (healthy)
vpt-supabase-rest       Up   (healthy)
vpt-supabase-meta       Up   (healthy)
vpt-supabase-studio     Up   (healthy)
vpt-supabase-gateway    Up   (healthy)   54321
vpt-redis               Up   (healthy)
vpt-grafana             Up               3000
# MinIO is on the host, not in docker — check it with systemctl
```

## 8. Reach the stack from the internet

GCP firewalls are closed by default — only `default-allow-ssh` (22), ICMP,
RDP, and the internal `10.128.0.0/9` rule are present. You have two options.

### A. SSH tunnel (zero firewall changes — what this guide uses by default)

```bash
gcloud compute ssh virtualpytest@vpt-standalone \
  --project=<your-project-id> --zone=<zone> \
  --ssh-flag="-L 15073:localhost:5073 -L 15109:localhost:5109 \
              -L 16109:localhost:6109 -L 13000:localhost:3000 \
              -L 15432:localhost:54321 -L 16080:localhost:6080 \
              -L 19000:localhost:9000 -L 19001:localhost:9001 -N"
```

Open on your Mac:

| URL | Service |
|---|---|
| `http://localhost:15073` | VPT web UI |
| `http://localhost:15109/server/health` | Backend server |
| `http://localhost:16109/host/health` | Backend host (X-API-Key required) |
| `http://localhost:13000` | Grafana (anonymous Viewer; admin in `.env`) |
| `http://localhost:15432` | Supabase API + Studio |
| `http://localhost:16080/vnc_lite.html` | noVNC desktop of the host |
| `http://localhost:19001` | MinIO console (creds in `.env`) |

### B. Open specific ports (only if you know what you are doing)

```bash
gcloud compute firewall-rules create vpt-public \
  --project=<your-project-id> \
  --allow tcp:5073,tcp:5109,tcp:6109,tcp:3000,tcp:54321,tcp:9000,tcp:9001,tcp:6080 \
  --source-ranges 0.0.0.0/0 \
  --direction INGRESS
```

> **Do not do this in OPEN MODE.** A fresh install accepts every API call
> with no login — fine on a trusted LAN, not on a public address. Walk
> [Production checklist](production-checklist.md) before
> opening any port.

## 9. Optional — Cloudflare in front of the showcase

For a public-facing showcase the stack needs TLS, a real hostname, and at
least a country gate and a content filter on the visitor side. Putting
Cloudflare in front handles all three without changing the GCP firewall.

```text
                                                          ┌────────────────────────────────────────────┐
                       visitor (browser)                  │ Cloudflare edge                              │
                              │                            │  DNS (proxied / orange cloud)                │
                              ▼                            │  TLS 1.3  ·  HTTP/3                          │
            ┌──────────────────────────────────┐            │  WAF                                         │
            │ vpt.example.com / api / grafana / │ ───────►   │   • Country allowlist (EU+US+CA+UK+AU)      │
            │ minio / studio                    │            │   • Managed ruleset: Adult + Malware only    │
            └──────────────────────────────────┘            │  Bot Fight Mode, Rate limits, Analytics      │
                                                          └────────────────────┬───────────────────────┘
                                                                               │ TLS (Cloudflare <-> origin over QUIC,
) Cloudflare Tunnel (cloudflared on the VM dials out over 7844 — no GCP firewall ports opened
                                                                               ▼
                                                          ┌────────────────────────────────────────────┐
                                                          │ GCP VM  e2-custom-4-8192  Debian 13         │
                                                          │ ┌────────────────────────────────────────┐ │
                                                          │ │ Docker Compose stack (setup/docker)     │ │
                                                          │ │  frontend · backend_server · backend_host│ │
                                                          │ │  redis · supabase (7) · grafana          │ │
                                                          │ └────────────────────────────────────────┘ │
                                                          │  systemd:  minio.service · cloudflared.service│ │
                                                          │  systemd-resolved → 1.1.1.3 (Families DNS)  │
                                                          └────────────────────────────────────────────┘
```

Cloudflare reaches the VM through **Cloudflare Tunnel** (`cloudflared`),
not through any GCP firewall port. The tunnel dials out from the VM to
Cloudflare's nearest edge over QUIC on port 7844 — the GCP firewall
stays closed, and the VM has no public IPs to attack. See
[Cloudflare Tunnels — quickstart](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
for the official primer.

> **Why Tunnel over opening 443.** Opening port 443 on the VM exposes it to
> every scanner on the internet even with a Cloudflare proxy in front, because
> Cloudflare origin-pull requests can be spoofed and the WAF does not inspect
> traffic that bypasses it. Tunnel inverts the flow — the VM dials out, and
> Cloudflare is the only path in.

### 9.1 Install `cloudflared` and create the systemd unit

The Debian 13 apt repo for `cloudflared` does not have a Release file today,
so install from the upstream `.deb` directly. As of `main-2026.09.24-9321`
this is already done on the reference VM (`/usr/local/bin/cloudflared`).

```bash
# latest .deb URL (always pin a version in production)
curl -fsSL -o /tmp/cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version

# systemd unit (the FIPS deb does not ship one)
sudo tee /etc/systemd/system/cloudflared.service > /dev/null <<'UNIT'
[Unit]
Description=cloudflared — Cloudflare Tunnel for VirtualPyTest showcase
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=notify
ExecStart=/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable cloudflared.service
```

### 9.2 Create the tunnel in the Cloudflare dashboard

The token lives in a separate file so `config.yml` is portable across boxes.
This is the part you do on the Cloudflare dashboard, not on the VM:

1. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**.
   Pick a name (e.g. `vpt-gcloud`); copy the one-line install command
   Cloudflare shows you — it prints a token like
   `eyJhIjoiNjM4...xMtR4In0` and a `<TUNNEL_ID>` UUID.
2. **Public hostname tab**: add `<your-showcase-domain>` →
   `http://localhost:5073` for the visitor UI. Repeat for the API, Grafana,
   MinIO console and Supabase Studio (one hostname per service).
3. Back on the VM, drop the token JSON you downloaded (or paste the JSON the
   dashboard shows under "Configure your tunnel") to
   `/etc/cloudflared/<TUNNEL_ID>.json` and put the matching UUID into
   `/etc/cloudflared/config.yml`:

   ```bash
   sudo tee /etc/cloudflared/config.yml > /dev/null <<'YAML'
   tunnel: <TUNNEL_ID>
   credentials-file: /etc/cloudflared/<TUNNEL_ID>.json

   ingress:
     - hostname: <your-showcase-domain>
       service: http://localhost:5073
       originRequest: { connectTimeout: 10s }
     - hostname: api.<your-showcase-domain>
       service: http://localhost:5109
     - hostname: grafana.<your-showcase-domain>
       service: http://localhost:3000
     - hostname: minio.<your-showcase-domain>
       service: http://localhost:9001
     - hostname: studio.<your-showcase-domain>
       service: http://localhost:54321
     - service: http_status:404   # catch-all is mandatory
   YAML

   sudo systemctl restart cloudflared.service
   sudo systemctl status cloudflared.service --no-pager
   ```

After this, `https://<your-showcase-domain>` on the open internet reaches
the frontend container on the VM — no GCP firewall changes required.

### 9.3 WAF — country allowlist (EU + US + CA + UK + AU)

Two ways to apply the country rule. The script on the VM
(`/home/virtualpytest/cloudflare/waf-rules.sh`, mode `0755`) takes a scoped
API token and pushes both the country allowlist and the managed-ruleset
categories in one go:

```bash
# On the Mac (or any host with curl + jq / python):
CLOUDFLARE_API_TOKEN=<token> CLOUDFLARE_ZONE_ID=<zone-id> \
  scp vpt-gcloud-standalone:/home/virtualpytest/cloudflare/waf-rules.sh ./
bash waf-rules.sh
```

The script ships with the agreed allowlist (DE FR IT ES NL BE SE NO DK FI
IE AT PT CH LU PL US CA GB AU NZ) and the categories you picked (Adult +
Malware only; everything else explicitly disabled). Edit the script if you
want to change either list.

If you prefer to click through the dashboard instead:
**Security → WAF → Custom Rules → Create rule**, name
`[VPT] Country allowlist`, expression
`(not ip.geoip.country in {DE FR IT ES NL BE SE NO DK FI IE AT PT CH LU PL US CA GB AU NZ})`,
action **Block**, priority `1`, deploy.

### 9.4 WAF — content categories (Adult + Malware only)

The script in §9.3 already applies this via the Cloudflare API. The same
result by hand:

1. **Security → WAF → Managed Rules → Cloudflare Managed Ruleset → Configure**
2. Search **"Adult and Sexually Explicit"** → enable.
3. Search **"Malware"** → enable.
4. Leave every other category (Drugs, Weapons, Gambling, Hacking, Crypto
   Mining, Piracy, Phishing) **disabled** — explicitly check the toggle is
   off if the dashboard defaults to "on".

### 9.5 Visitor filtering = cloud. Browser-side = DNS resolver.

Cloudflare WAF inspects the visitor URL only — it does **not** filter what
the host's noVNC browser fetches while running automation. For the
browser-side filter, point the VM's resolver at Cloudflare for Families.
Already done on the reference VM (`/etc/systemd/resolved.conf.d/family.conf`):

```ini
[Resolve]
DNS=1.1.1.3 1.0.0.3
FallbackDNS=
```

```bash
sudo systemctl restart systemd-resolved
dig +short @127.0.0.53 pornhub.com   # expect 0.0.0.0 (blocked)
dig +short @127.0.0.53 github.com   # expect a real A record
```

This covers every container that uses the host's resolver by default — the
whole docker stack — plus anything else on the VM (noVNC's Chromium, curl
from inside the host, etc.). For mobile emulators / real devices on a
separate network, point their DHCP-supplied DNS at `1.1.1.3 / 1.0.0.3`
or set Android's Private DNS to `family.cloudflare-dns.com`. The full
rationale and recipes are in [Content filtering](content-filtering.md).

### 9.6 Putting PUBLIC_HOST on the right name

Once the tunnel is up, the only change needed in `.env` is
`PUBLIC_HOST=<your-showcase-domain>` followed by a rebuild so the frontend
bakes `VITE_*` values at build time:

```bash
cd /home/virtualpytest/virtualpytest/setup/docker
sed -i 's|^PUBLIC_HOST=.*|PUBLIC_HOST=<your-showcase-domain>|' .env
./launch.sh --rebuild   # rebuilds the frontend image and recreates the container
```

## 10. Day-two

- **Logs**: `cd /home/virtualpytest/virtualpytest/setup/docker && ./launch.sh --logs`
- **Stop everything** (keeps data): `./launch.sh --down`
- **Wipe and restart** (deletes DB / captures / MinIO / Grafana): `./launch.sh --reset`
- **Rebuild after `.env` change**: `./launch.sh --rebuild`
- **Add a device**: edit `backend_host/src/.env`, drop the `x` from the
  device line, re-run `./launch.sh`. See [Add a host](add-a-host.md).
- **Rotate a secret**: edit `setup/docker/.env`, re-run `./launch.sh`.
  Existing services pick the new value up on container recreate. The shipped
  `.env` secrets are random per install; the production checklist covers
  rotation for shared deployments.

## What this guide does not cover

- **Multi-VM / multi-region deployments** — see [Managed cloud](cloud-setup.md)
  for the managed-service shape, or [Proxmox](proxmox.md) for
  the on-prem fleet shape.
- **Free-tier** — GCP Always Free `e2-micro` is too small; see [Free cloud starter](../user-guide/free-cloud-starter.md).
- **Production hardening** — auth, TLS, secrets rotation, firewall rules,
  backups. Walk [Production checklist](production-checklist.md)
  before this stack holds anything you care about.
- **Custom domains** — see §9.
- **The MinIO pin moving again** — `setup/docker/images/minio/Dockerfile` and
  `setup/docker/images/minio-mc/Dockerfile` pin exact upstream MinIO/mc
  versions. Bumping one means editing its `ARG` default and republishing
  (`.github/workflows/release-images.yml`, `workflow_dispatch`) — see §6.