# Managed cloud (Vercel + Render): platform hosted, host local

> **Read [Install](install.md) first.** One Docker host on a server is simpler, and it is the path we test on every push. This page is not covered by automated tests.
>
> The device controller must run on your own machine, next to your hardware. See [Add a machine with devices](add-a-host.md).

<div data-technical>

Reason: a managed platform gives one container and one port per service, and the controller needs two ports plus access to your hardware.

</div>

This guide splits the install:

- **Frontend** (web app) on Vercel
- **Backend Server** on Render
- **Backend Host** on your own machine
- **Database** on Supabase

<div data-technical>

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Frontend     │    │ Backend Server  │    │  Backend Host   │
│   (Vercel)      │◄──►│   (Render)      │◄──►│    (Local)      │
│                 │    │                 │    │                 │
│ • Global CDN    │    │ • Auto-scaling  │    │ • Hardware I/O  │
│ • Fast deploys  │    │ • SSL included  │    │ • Device control│
│ • Branch preview│    │ • Zero downtime │    │ • Local network │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────┐
                    │    Supabase     │
                    │   (PostgreSQL)  │
                    │                 │
                    │ • Managed DB    │
                    │ • Auto backups  │
                    │ • Global edge   │
                    └─────────────────┘
```

</div>

## Prerequisites

- A **Vercel account**, a **Render account** and a **Supabase project** ([setup guide](./supabase.md))
- A **local machine** for the Backend Host, with access to your hardware
- A **GitHub repository** with your VirtualPyTest code

## Step 1: Deploy Backend Server to Render

### 1.1 Deploy via the Render Blueprint

1. Go to the [Render Dashboard](https://dashboard.render.com), click **"New +"**, then **"Blueprint"**.
2. Connect your GitHub repository and point it at `backend_server/src/render.yaml`.
3. Do not change the port; Render sets it.

<div data-technical>

Service name: `virtualpytest-backend-server`. Environment: Docker.

The file `backend_server/src/render.yaml` is a **Docker** deployment (`env: docker`, `dockerfilePath: ./backend_server/Dockerfile`), not the Python buildpack.

Port detail: Render injects the runtime `PORT`. Do not set `SERVER_PORT=80` or hardcode `5109` in the container Supervisor configuration. The image binds to `PORT` on Render and falls back to `SERVER_PORT=5109` for local Docker/native installs.

</div>

> **Important: image-backed Render services.** If the service was made from an image, a GitHub push does not rebuild it. Publish the new image first, then point Render at it and redeploy.

<div data-technical>

Publish the image from the public repository first, then update the Render service to the new immutable tag and redeploy. A service can show `RUNNING` while still failing Render's port scan if the image binds only to `5109`.

</div>

### 1.2 Add the remaining environment variables

Add the other settings in the Render dashboard, under the **Environment** tab.

<div data-technical>

`render.yaml` only checks in `PYTHONPATH`, `DEBUG`, and `RENDER`. The rest is deliberately not in the committed file:

```bash
# Database Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_JWT_SECRET=your_jwt_secret
API_KEY=the_same_value_used_by_each_backend_host
SERVER_URL=https://virtualpytest-backend-server.onrender.com
SERVER_OPEN_MODE=false
CORS_ALLOWED_ORIGINS=https://your-frontend.onrender.com,https://your-frontend.vercel.app

# Managed dependencies (keep credentials in Render, never in Git)
REDIS_URL=rediss://...
S3_ENDPOINT_URL=https://...                 # or the provider-specific S3 variable
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET=virtualpytest

# Optional: GitHub integration
GITHUB_TOKEN=your_github_token_if_needed
```

</div>

### 1.3 Deploy

Click **"Apply"** on the Blueprint. Render builds the server, gives it an address with SSL, and redeploys on each push.

### 1.4 Release order for new server images

For maintainers publishing new server images. Follow the steps in order.

<div data-technical>

For the public repository and GHCR images, use this order:

1. Commit and push the fix to the internal repository.
2. Create the release tag and publish the sanitized snapshot with
   `scripts/release/publish_public.sh <tag>`.
3. From `AngelStreetCorp/virtualpytest`, run the `Release artifacts` workflow for that tag.
4. Wait for `virtualpytest-server` to be published in GHCR.
5. Change the image reference in Render and redeploy.
6. Verify `/server/health` before connecting a host.

Do not test an older tag: the self-test must use the exact tag and image being released.

</div>

## Step 2: Deploy the frontend to Vercel

### 2.1 Prepare the frontend

Tell the frontend where the server is.

<div data-technical>

Create `frontend/.env.production`:

```bash
# API Endpoints (use your actual backend server URL)
VITE_SERVER_URL=https://virtualpytest-backend-server.onrender.com
VITE_DEV_MODE=false
```

</div>

### 2.2 Create the Vercel project

1. Go to the [Vercel Dashboard](https://vercel.com/dashboard) and click **"New Project"**.
2. Import your GitHub repository, with the web app in the `frontend` folder.

<div data-technical>

- **Framework Preset**: `Vite`
- **Root Directory**: `frontend`
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Install Command**: `npm install`

</div>

### 2.3 Set the environment variables

In the Vercel project settings, add the server's address and the development-mode setting.

<div data-technical>

```bash
# API Endpoints
VITE_SERVER_URL=https://virtualpytest-backend-server.onrender.com
VITE_DEV_MODE=false
```

</div>

### 2.4 Deploy

Click **"Deploy"**. Vercel builds the app and gives it an address. Each pull request gets a preview.

## Step 3: Set up the Backend Host

The Backend Host runs on your own machine, where your devices are. Install it directly, or in Docker.

### 3.1 Option A: local installation (hardware access)

<div data-technical>

```bash
# Clone repository (if not already done)
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest

# Install only the host component
./setup/local/linux/backend_host/install_host.sh
```

</div>

### 3.2 Option B: Docker (local or cloud)

#### Local Docker deployment (host only, connects to your cloud backend server)

<div data-technical>

```bash
./setup/docker/install_docker.sh
# from the repo root
./launch.sh
```

See `setup/docker/docker-compose.host.yml` for `.env` setup — set `SERVER_URL` to your Render backend
server's URL, and note the `host.docker.internal` caveat there if the server ever runs on the
same machine. (`setup/docker/` is the *full* local stack — Postgres,
server, frontend, Grafana — not what you want here since the server's already on Render.)

</div>

#### Cloud runner Docker deployment

To run the host as a cloud service, create a Docker web service on Render.

1. Create a Docker web service on the Render dashboard.
2. Set up the host's settings before you build.

<div data-technical>

- **Environment**: Docker
- **Root directory**: leave it empty
- **Dockerfile path**: `backend_host/Dockerfile`
- **Port**: 6109

Example `.env` for cloud deployment:

```bash
# Host Configuration
HOST_NAME=render-host-1
HOST_PORT=6109
HOST_URL=https://your-host-service.onrender.com
SERVER_URL=https://your-backend-server.onrender.com
DEBUG=0

# Optional: Video devices (for full config)
# DEVICE1_VIDEO=/dev/video0
# DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
```

For AWS, GCP or Azure, build and run the container yourself:

```bash
# Build and deploy container
docker build -f backend_host/Dockerfile -t virtualpytest/backend_host .
docker run -d -p 6109:6109 -p 6080:6080 virtualpytest/backend_host
```

</div>

### 3.3 Configure the Backend Host

Create the host's settings file, `backend_host/src/.env`. Use the minimal setup for remote desktop only, or the full setup if you have cameras.

#### Minimal configuration (remote desktop only)

<div data-technical>

```bash
# Host Configuration
HOST_NAME=my-host
HOST_PORT=6109
DEBUG=0

# Database Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
```

</div>

#### Full configuration (remote desktop, video and monitor)

<div data-technical>

```bash
# Host Configuration
HOST_NAME=my-host
HOST_PORT=6109
DEBUG=0

# Database Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key

# Device 1 - Video capture configuration
DEVICE1_VIDEO=/dev/video0
DEVICE1_AUDIO=plughw:2,0
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
DEVICE1_FPS=10

# Device 2 - Additional video device (optional)
DEVICE2_VIDEO=/dev/video2
DEVICE2_AUDIO=plughw:3,0
DEVICE2_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture2
DEVICE2_FPS=10

# Optional: Cloud Storage
CLOUDFLARE_R2_ENDPOINT=your_r2_endpoint
CLOUDFLARE_R2_ACCESS_KEY_ID=your_access_key
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your_secret_key
# AI: no key on hosts. Hosts call models through the server (/server/ai/complete);
# models and API keys are set in the web app under Settings → AI.
```

</div>

The host starts the services your settings call for.

<div data-technical>

**Note**: Backend Host automatically detects which services to start based on your configuration:
- **No DEVICE variables**: Only VNC services (minimal)
- **With DEVICE variables**: VNC + Video capture + Monitor services

</div>

### 3.4 Launch the Backend Host

Start the host with the launch script.

<div data-technical>

Local launch:

```bash
# Launch only the host service
./setup/local/linux/backend_host/launch_host.sh

# Or run directly
source venv/bin/activate
python backend_host/src/app.py
```

Docker launch: `./launch.sh` from the repo root.

</div>

### 3.5 Check the host is running

<div data-technical>

- **API Endpoints**: `http://localhost:6109/host/*`
- **NoVNC Web Desktop**: `http://localhost:6080` (virtual desktop access)
- **Health Check**: `http://localhost:6109/host/health`

</div>

### 3.6 Reach the host from the internet (optional)

Do this only if you need to reach the host from outside your network.

#### Option A: ngrok (recommended for testing)

<div data-technical>

```bash
# Install ngrok
npm install -g ngrok

# Expose local host (API + NoVNC)
ngrok http 6109
ngrok http 6080  # In separate terminal for NoVNC
```

Update your frontend environment with the ngrok URL:
```bash
VITE_SERVER_URL=https://your-ngrok-url.ngrok.io
```

</div>

#### Option B: port forwarding

Forward the host's ports on your router, then point the frontend at your public address.

<div data-technical>

Configure your router to forward ports 6109 and 6080 to your local machine:
```bash
VITE_SERVER_URL=http://your-public-ip:6109
# NoVNC available at: http://your-public-ip:6080
```

</div>

#### Option C: cloud deployment (Render)

Run the host on Render with Docker, as described in step 3.2.

## Step 4: Connect the services to each other

### 4.0 Supabase, Redis and file storage

Supabase provides the database, login and file storage. Add Redis as a separate service.

<div data-technical>

For a managed starter deployment, Supabase supplies PostgreSQL, authentication, and Storage.
Use its S3-compatible Storage endpoint for artifacts, or substitute Cloudflare R2 or another
S3 provider. Redis is a separate managed dependency; use a Redis-compatible provider such as
Render Key Value or Upstash and set `REDIS_URL` in Render and on any service that needs it.

For a fresh Supabase project, apply only the canonical schema path:

```bash
./setup/db/apply_schema.sh \\
  "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
```

This applies `setup/db/schema/*.sql` in order and applies the final public-key lockdown. Do
not apply every file in `setup/db/migrations/` to a fresh database; those files are for an
already-created schema. Confirm RLS is enabled and the `anon` role has no direct application
table grants before putting the backend online.

</div>

Set up a new database with the schema script only. Check that row-level security is on before going online.

### 4.1 Point a local or Pi host at Render

The host stays on the machine with the devices. Point it at the online server with the same API key. Switch only after the server's health check answers.

<div data-technical>

The host must remain on the machine with the devices. Set its native or Docker host
environment to the public backend URL and the same API key used by the server:

```bash
SERVER_URL=https://virtualpytest-backend-server.onrender.com
API_KEY=<same-server-api-key>
```

Restart only the host service, then verify its local health and the server logs. If the host is
behind a private LAN, use an SSH/reverse tunnel for administration; the host itself only needs
outbound HTTPS access to Render.

For the Pi tunnel used by the project:

```bash
ssh proxmox 'ssh vpt-pi4 "hostname; systemctl is-active vpt-host.service"'
```

After changing the host environment:

```bash
ssh proxmox 'ssh vpt-pi4 "sudo systemctl restart vpt-host.service"'
```

Do not redirect the host until the Render backend health endpoint returns successfully.

</div>

### 4.2 CORS: only needed if the frontend calls Render directly

If the web app and the server have different addresses, the server must allow the web app's address.

<div data-technical>

`shared/src/lib/utils/app_utils.py` already calls `CORS(app, origins=..., supports_credentials=True)`
for you — you don't add the call, you set which origins are allowed. `CORS_ALLOWED_ORIGINS`
(comma-separated, in `.env`) is the allowlist; there is no `*` fallback (BUG-0092), so an origin
not listed here simply cannot call this API from a browser.

Whether you need to set it depends on how `VITE_SERVER_URL` is configured:
- `frontend/vercel.json` maps `/server/(.*)` to `/server/$1` on the **same** Vercel deployment —
  it is a routing rule for the SPA, not a proxy to the backend. So with the frontend on Vercel
  and the server on Render, the browser always makes a cross-origin request and the server
  needs your Vercel domain in its allowlist:

```bash
# .env, on the Render (or wherever backend_server runs) side
CORS_ALLOWED_ORIGINS=https://virtualpytest.vercel.app,http://localhost:5073
```

</div>

### 4.3 Frontend API endpoint

If requests go to the wrong address, check where the web app reads the server address.

<div data-technical>

`VITE_SERVER_URL` is read in `frontend/src/utils/buildUrlUtils.ts`, not a dedicated
`apiClient.ts` — that's where to look if a request is going to the wrong URL.

</div>

## Step 5: Set up continuous deployment

### 5.1 Automatic deployments

Vercel and Render redeploy when you push to the connected branch.

<div data-technical>

- The committed `backend_server/src/render.yaml` tracks `main` on
  `github.com/AngelStreetCorp/virtualpytest`. Point `repo` and `branch` at your own fork if
  you deploy from one
- **Pull requests** → Preview deployments (Vercel)

</div>

### 5.2 Settings per environment

Use one server address for production and another for testing.

<div data-technical>

Production branch (`main`):

```bash
VITE_SERVER_URL=https://your-production-server.com
VITE_DEV_MODE=false
```

Staging branch (`dev`):

```bash
VITE_SERVER_URL=https://your-staging-server.com
VITE_DEV_MODE=true
```

</div>

## Step 6: Monitoring and maintenance

Check each service in its own dashboard: Render, Vercel and Supabase.

<div data-technical>

- **Scaling**: Render scales up and down with traffic. Vercel edge functions scale on their own. Run more than one local host if you need a backup.

</div>

## Troubleshooting

### Common issues

#### CORS errors

- Check the allowed origins on the backend server.
- Use the same protocol for both addresses (both `https`, or both `http`).

#### Database connection problems

- Check the Supabase addresses and keys, and the IP allow lists in Supabase.

#### The local host is unreachable

- Make sure the Backend Host is running on your machine.
- Check your firewall, and your port forwarding if you use it.

### Health check addresses

Test each part once it is up:

<div data-technical>

```bash
# Backend Server (Render)
curl https://virtualpytest-backend-server.onrender.com/server/health

# Frontend (Vercel)
curl https://virtualpytest.vercel.app

# Backend Host (Local)
curl http://localhost:6109/host/health

# NoVNC Web Desktop (Local)
curl http://localhost:6080
```

</div>

## Production checklist

Before you go live:

- [ ] All environment variables are set
- [ ] CORS is set up
- [ ] Database schemas are applied
- [ ] SSL certificates are active (automatic)
- [ ] Health checks pass
- [ ] Monitoring is set up
- [ ] A backup plan is in place
- [ ] The local host runs reliably

## Next steps

Add a custom domain, monitoring, CI/CD, scaling and security reviews as needed.

<div data-technical>

1. **Custom domain**: set up a custom domain in Vercel or Render
2. **Monitoring**: add application monitoring (Sentry, LogRocket)
3. **CI/CD**: set up testing pipelines
4. **Scaling**: set up auto-scaling rules
5. **Security**: review security settings and access controls

</div>

## Related guides

- [Supabase and authentication](./supabase.md)
- [Developer setup](./local-dev.md)
