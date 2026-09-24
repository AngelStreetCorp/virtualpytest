# ☁️ Google Cloud — standalone install

> **Read [Install](get-started/install.md) first.** The Docker path there works
> on any rented Linux box — Hetzner, AWS, DigitalOcean, Scaleway, OVH, GCP,
> anywhere. This page adds only what is specific to a single GCP VM: project
> setup, OS Login / SSH access, and the one Compose workaround (MinIO) that is
> needed today because `quay.io/minio/*` no longer accepts anonymous pulls.
>
> **One VM, full platform.** This guide keeps the entire stack — Supabase,
> Redis, MinIO, Grafana, backend server, backend host, frontend — on a single
> Compute Engine instance. It does **not** cover splitting the stack across
> multiple GCP projects or across GCP + another cloud; for that, follow
> [Managed cloud (Vercel + Render)](get-started/cloud-setup.md).

A standalone GCP install is for: a long-running demo, a lab box you want to
reach from anywhere, a single-site deployment on a public cloud you already
have an account with. It is **not** a free path: GCP's Always Free `e2-micro`
(1 GB RAM) is too small for the full stack — see [Free cloud starter](user-guide/free-cloud-starter.md)
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

## 6. The MinIO workaround (mandatory today)

The compose file pins `quay.io/minio/minio:RELEASE.2025-07-23T15-54-02Z` and
`quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z`. As of late 2026 these return
`HTTP 401` for anonymous pulls (the bearer token has `"actions":[]` for
`repository:minio/minio`), and the project has no alternative mirror wired
in — `docker.io/minio/minio` does not exist on Docker Hub, and `bitnami/minio`
returns empty tag lists. The fix is to install MinIO as a host systemd
service from the matching GitHub release assets (which **do** exist), then
point the docker stack at it.

```bash
# Download binaries matching the tags pinned in docker-compose.yml
MINIO_VER="RELEASE.2025-07-23T15-54-02Z"
MC_VER="RELEASE.2025-04-16T18-13-26Z"

curl -fsSL -o /tmp/minio \
  "https://github.com/minio/minio/releases/download/${MINIO_VER}/minio.linux-amd64.${MINIO_VER}"
curl -fsSL -o /tmp/mc \
  "https://github.com/minio/mc/releases/download/${MC_VER}/mc.linux-amd64.${MC_VER}"

sudo install -m 0755 /tmp/minio /usr/local/bin/minio
sudo install -m 0755 /tmp/mc    /usr/local/bin/mc
minio --version    # RELEASE.2025-07-23T15-54-02Z (go1.24.x linux/amd64)
mc    --version    # RELEASE.2025-04-16T18-13-26Z

# Credentials: pull from the .env that launch.sh generated
MINIO_USER="$(grep ^MINIO_ACCESS_KEY= setup/docker/.env | head -1 | cut -d= -f2-)"
MINIO_PASS="$(grep ^MINIO_SECRET_KEY= setup/docker/.env | head -1 | cut -d= -f2-)"
BUCKET="${MINIO_BUCKET:-virtualpytest}"
BUCKET="$(grep ^MINIO_BUCKET= setup/docker/.env | head -1 | cut -d= -f2-)"

# System user + dirs
sudo useradd -r -s /sbin/nologin -d /var/lib/minio minio
sudo mkdir -p /var/lib/minio && sudo chown minio:minio /var/lib/minio
sudo mkdir -p /etc/minio      && sudo chown minio:minio /etc/minio

# Env file (mode 0600, owned by minio)
sudo tee /etc/default/minio > /dev/null <<EOF
MINIO_ROOT_USER=${MINIO_USER}
MINIO_ROOT_PASSWORD=${MINIO_PASS}
EOF
sudo chmod 0600 /etc/default/minio && sudo chown minio:minio /etc/default/minio

# systemd unit
sudo tee /etc/systemd/system/minio.service > /dev/null <<'UNIT'
[Unit]
Description=MinIO object storage (standalone, VirtualPyTest)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=minio
Group=minio
EnvironmentFile=/etc/default/minio
ExecStart=/usr/local/bin/minio server /var/lib/minio --console-address ":9001"
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now minio.service

# Initialise the bucket
mc alias set local "http://localhost:9000" "$MINIO_USER" "$MINIO_PASS"
mc mb --ignore-existing "local/$BUCKET"
mc anonymous set download "local/$BUCKET"   # matches the project "public-URL mode"

# Health
curl -s http://localhost:9000/minio/health/live   # → 200
```

### Wire host MinIO into the docker stack

The local `docker-compose.yml` still references `quay.io/minio/...` images
that will not pull, and `backend_server` references `minio:9000` as a Docker
network alias. With MinIO running on the host, the alias needs to point at
the compose network bridge gateway (typically `172.18.0.1`):

```bash
cd /home/virtualpytest/virtualpytest/setup/docker

# Remove the two services that cannot pull
cp docker-compose.yml /tmp/docker-compose.yml.original
python3 - <<'PY'
import re
path = "docker-compose.yml"
with open(path) as f: text = f.read()
text = re.sub(r"^  minio:\n(?:    .+\n)+", "", text, flags=re.M)
text = re.sub(r"^  minio-init:\n(?:    .+\n)+", "", text, flags=re.M)
text = re.sub(r"\n    minio-init:\n      condition: service_completed_successfully\n", "\n", text)
with open(path, "w") as f: f.write(text)
PY

# Add an extra_hosts entry to backend_server and backend_host
NET_IP=$(docker network inspect virtualpytest_default \
  --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}" | head -1)
cat > /tmp/patch.py <<PY
import os, re
NET_IP = os.environ["NET_IP"]
path = "/home/virtualpytest/virtualpytest/setup/docker/docker-compose.yml"
with open(path) as f: text = f.read()
text = re.sub(r"\n    extra_hosts:\n      - \"minio:[0-9.]+\"\n", "\n", text)
def add(t, svc):
    pat = re.compile(r"^(  " + svc + r":\n(?:    .+\n)+)", re.M)
    def fix(m):
        b = m.group(1)
        a = "    extra_hosts:\n      - \"minio:" + NET_IP + "\"\n"
        return b.replace("    depends_on:\n", a + "    depends_on:\n", 1) \
               if "    depends_on:\n" in b else b + a
    return pat.sub(fix, t, count=1)
for svc in ("backend_server", "backend_host"):
    text = add(text, svc)
with open(path, "w") as f: f.write(text)
PY
NET_IP="$NET_IP" python3 /tmp/patch.py

docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d
```

Verify MinIO is reachable from inside the containers:

```bash
docker exec vpt-server sh -c \
  'getent hosts minio; \
   curl -s -o /dev/null -w "minio_live: %{http_code}\n" http://minio:9000/minio/health/live'
# expected: "172.18.0.1 minio" and "minio_live: 200"
```

> **Permanent fix.** A future release of `setup/docker/docker-compose.yml`
> should ship a `minio:` service that uses a local image (built from the
> MinIO binaries via `setup/docker/scripts/build_minio_image.sh` or similar)
> or a digest-pinned image from a private GHCR mirror. Until that lands,
> §6 is mandatory on every fresh install.

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
> [Production checklist](get-started/production-checklist.md) before
> opening any port.

## 9. Optional — put it on a hostname with HTTPS

The compose stack is designed to be fronted by a TLS-terminating reverse
proxy. Two common shapes:

- **Cloudflare in front of the VM**: Cloudflare Tunnel (cloudflared) on the
  VM, your domain pointed at the tunnel, no public inbound ports. See
  [Network setup](get-started/network.md#cloudflare-tunnel).
- **nginx + certbot on the VM**: open only 443, terminate TLS, proxy to the
  compose services. See [Security](get-started/security.md).

In either case the only change you need in `.env` is
`PUBLIC_HOST=your.domain.com` followed by `./launch.sh --rebuild` (the
frontend bakes `VITE_*` values at build time).

## 10. Day-two

- **Logs**: `cd /home/virtualpytest/virtualpytest/setup/docker && ./launch.sh --logs`
- **Stop everything** (keeps data): `./launch.sh --down`
- **Wipe and restart** (deletes DB / captures / MinIO / Grafana): `./launch.sh --reset`
- **Rebuild after `.env` change**: `./launch.sh --rebuild`
- **Add a device**: edit `backend_host/src/.env`, drop the `x` from the
  device line, re-run `./launch.sh`. See [Add a host](get-started/add-a-host.md).
- **Rotate a secret**: edit `setup/docker/.env`, re-run `./launch.sh`.
  Existing services pick the new value up on container recreate. The shipped
  `.env` secrets are random per install; the production checklist covers
  rotation for shared deployments.

## What this guide does not cover

- **Multi-VM / multi-region deployments** — see [Managed cloud](get-started/cloud-setup.md)
  for the managed-service shape, or [Proxmox](get-started/proxmox.md) for
  the on-prem fleet shape.
- **Free-tier** — GCP Always Free `e2-micro` is too small; see [Free cloud starter](user-guide/free-cloud-starter.md).
- **Production hardening** — auth, TLS, secrets rotation, firewall rules,
  backups. Walk [Production checklist](get-started/production-checklist.md)
  before this stack holds anything you care about.
- **Custom domains** — see §9.
- **The MinIO pin moving again** — the workaround in §6 pins the exact tag
  in `docker-compose.yml`. If you upgrade, update both the compose file
  **and** the systemd unit's `minio` binary, and re-initialise the bucket.