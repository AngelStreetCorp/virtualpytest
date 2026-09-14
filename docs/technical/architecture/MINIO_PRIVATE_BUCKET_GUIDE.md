# MinIO Private Bucket with Pre-signed URLs

## Overview

This guide covers securing a self-hosted MinIO bucket so files are only accessible via **cryptographically signed, time-limited URLs**. It mirrors the R2 private bucket setup (see `R2_PRIVATE_BUCKET_GUIDE.md`) but addresses MinIO-specific concerns like nginx proxying and presigned URL endpoint separation.

**Auto-detected from environment variables** — same as R2, the system switches between public and private mode based on whether `MINIO_PUBLIC_URL` / `VITE_MINIO_PUBLIC_URL` env vars are set.

---

## Quick Start

### Public Mode (direct URLs, no auth)
```bash
# All VMs .env
MINIO_PUBLIC_URL=https://yourdomain.com/minio

# Frontend .env
VITE_MINIO_PUBLIC_URL=https://yourdomain.com/minio/virtualpytest/
```

### Private Mode (signed URLs)
```bash
# All VMs .env — comment out or remove MINIO_PUBLIC_URL
# MINIO_PUBLIC_URL=

# Add presign endpoint (public-facing URL for browser access)
MINIO_PRESIGN_ENDPOINT=https://yourdomain.com

# Frontend .env — comment out or remove
# VITE_MINIO_PUBLIC_URL=
```

---

## Architecture

### Public Mode (before)

```
Browser → https://domain.com/minio/bucket/file.jpg → nginx strips /minio/ → MinIO → file
                                                      (no auth needed)
```

### Private Mode (after)

```
1. Browser clicks "View Report"
2. Frontend calls POST /server/storage/signed-url { path: "script-reports/.../report.html" }
3. Backend generates signed URL using MINIO_PRESIGN_ENDPOINT
4. Browser opens: https://domain.com/virtualpytest/file.jpg?X-Amz-Signature=...
5. nginx proxies /virtualpytest/ → MinIO (no path stripping)
6. MinIO validates signature → returns file
```

### Why two S3 clients?

The backend needs two different endpoints:

| Client | Endpoint | Used for |
|--------|----------|----------|
| `s3_client` | `MINIO_ENDPOINT` (internal, e.g. `http://192.168.x.101:9000`) | Uploads, deletes, list operations |
| `presign_client` | `MINIO_PRESIGN_ENDPOINT` (public, e.g. `https://yourdomain.com`) | Generating presigned URLs for browsers |

Presigned URLs include the hostname in their cryptographic signature. If signed with the internal IP, browsers can't reach it. If signed with the public domain, the signature validates when the browser accesses it through nginx.

---

## Step-by-Step Setup

### 1. Make MinIO bucket private

```bash
ssh storage-vm
mc alias set local http://localhost:9000 <ACCESS_KEY> <SECRET_KEY>
mc anonymous set none local/virtualpytest
# Verify
mc anonymous get local/virtualpytest
# → Access permission for `local/virtualpytest` is `private`
```

### 2. Change MinIO root credentials

Edit `/etc/default/minio` (or docker env):
```bash
MINIO_ROOT_USER=<new-user>
MINIO_ROOT_PASSWORD=<strong-password>
```

Restart MinIO:
```bash
sudo systemctl restart minio
```

Update `mc` alias:
```bash
mc alias set local http://localhost:9000 <new-user> <new-password>
```

### 3. Add nginx location for presigned URLs

Presigned URLs include the path in their signature. The existing `/minio/` location strips the path prefix, which **breaks signatures**. Add a new location that preserves the full path:

```nginx
# Add BEFORE the existing /minio/ location block
location /virtualpytest/ {
    proxy_pass http://minio/virtualpytest/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
```

**Key point:** `proxy_set_header Host $host` forwards the original hostname to MinIO. The signature was computed with this hostname, so MinIO's validation succeeds.

### 4. Secure admin endpoints with basic auth

```bash
# Generate htpasswd file (on proxy VM)
openssl passwd -apr1 '<password>'
# Write to file: echo "username:<hash>" > /etc/nginx/.htpasswd_admin
```

Add `auth_basic` to `/minio/`, `/minio-console/`, and `/redis/` locations:
```nginx
location /minio/ {
    auth_basic "MinIO Admin";
    auth_basic_user_file /etc/nginx/.htpasswd_admin;
    proxy_pass http://minio/;
    # ... existing proxy headers
}

location /minio-console/ {
    auth_basic "MinIO Console";
    auth_basic_user_file /etc/nginx/.htpasswd_admin;
    # ... existing config
}

location /redis/ {
    auth_basic "Redis Admin";
    auth_basic_user_file /etc/nginx/.htpasswd_admin;
    # ... existing config
}
```

Test and reload:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Update environment variables

**All VMs** (backend server, frontend, all host VMs):

```bash
# New credentials
MINIO_ACCESS_KEY=<new-user>
MINIO_SECRET_KEY=<new-password>

# Comment out public URL to enable private mode
# MINIO_PUBLIC_URL=

# Add presign endpoint (backend + host VMs only)
MINIO_PRESIGN_ENDPOINT=https://yourdomain.com
```

**Frontend VM** (additional):
```bash
# Comment out to enable private mode
# VITE_MINIO_PUBLIC_URL=
```

**Backend VM** (additional — required for signed-url endpoint auth):
```bash
SUPABASE_JWT_SECRET=<your-supabase-jwt-secret>
```

### 6. Restart all services

```bash
# Backend server
sudo systemctl restart vpt-server

# Frontend (Vite dev reads env at startup)
sudo systemctl restart vpt-frontend

# All host VMs
sudo systemctl restart vpt-host
```

---

## VMs Updated (VirtualPyTest deployment)

| VM | IP | Role | Changes |
|----|-----|------|---------|
| storage | 192.168.x.101 | MinIO + Redis | New root creds, bucket set to private, Redis Commander creds |
| proxy | 192.168.x.107 | nginx | `/virtualpytest/` location, basic auth on `/minio/`, `/minio-console/`, `/redis/` |
| backend-server | 192.168.x.103 | API | Updated .env, added `MINIO_PRESIGN_ENDPOINT`, `SUPABASE_JWT_SECRET` |
| frontend | 192.168.x.105 | React UI | Removed `VITE_MINIO_PUBLIC_URL` |
| host-clone-1 | 192.168.x.109 | Script executor | Updated .env + cloudflare_utils.py |
| host-clone-2 | 192.168.x.110 | Script executor | Updated .env + cloudflare_utils.py |
| host-clone-3 | 192.168.x.136 | Script executor | Updated .env + cloudflare_utils.py |
| android-mobile | 192.168.x.180 | Android host | Updated .env + cloudflare_utils.py |
| android-tv | 192.168.x.181 | Android host | Updated .env + cloudflare_utils.py |
| android-tablet | 192.168.x.182 | Android host | Updated .env + cloudflare_utils.py |

---

## How It Works (Code)

### Backend (`shared/src/lib/utils/cloudflare_utils.py`)

**Mode detection:**
```python
def is_public_mode(self) -> bool:
    r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
    if r2_endpoint:
        return bool(os.environ.get('CLOUDFLARE_R2_PUBLIC_URL', '').strip())
    else:
        # MinIO: private if MINIO_PUBLIC_URL is not set
        return bool(os.environ.get('MINIO_PUBLIC_URL', '').strip())
```

**Presign client (separate from upload client):**
```python
def _init_presign_client(self):
    presign_endpoint = os.environ.get('MINIO_PRESIGN_ENDPOINT', '').strip()
    if not presign_endpoint:
        return None  # Falls back to s3_client
    return boto3.client('s3',
        endpoint_url=presign_endpoint,
        aws_access_key_id=os.environ.get('MINIO_ACCESS_KEY'),
        aws_secret_access_key=os.environ.get('MINIO_SECRET_KEY'),
        region_name='us-east-1',
        config=Config(signature_version='s3v4'))
```

**URL generation uses presign_client when available:**
```python
client = self.presign_client or self.s3_client
presigned_url = client.generate_presigned_url('get_object',
    Params={'Bucket': self.bucket_name, 'Key': path},
    ExpiresIn=expires_in)
```

### Frontend (`frontend/src/utils/infrastructure/cloudflareUtils.ts`)

**Mode detection (same as R2):**
- `VITE_MINIO_PUBLIC_URL` set → PUBLIC mode (direct URLs)
- `VITE_MINIO_PUBLIC_URL` not set → PRIVATE mode (calls `/server/storage/signed-url`)

**Old MinIO URLs in DB:** When in private mode, old URLs like `https://<origin-ip>/minio/virtualpytest/...` are automatically path-extracted and signed instead of being used directly (which would hit basic auth).

### API Endpoint

```
POST /server/storage/signed-url
Headers: X-Auto-Sign: <token>  OR  Authorization: Bearer <supabase-jwt>
Body: { "path": "script-reports/.../report.html", "expires_in": 3600 }

Response: {
  "success": true,
  "url": "https://domain.com/virtualpytest/...?X-Amz-Signature=...",
  "expires_at": "2026-03-18T15:30:00Z"
}
```

---

## Signature Duration

| Context | Duration | Configurable |
|---------|----------|-------------|
| On-demand (frontend clicks report) | 1 hour (3600s) | `expires_in` param in API call |
| Report assets (embedded in HTML) | ~7 days (604,799s) | `MAX_R2_PRESIGN_EXPIRY` constant |
| Batch URLs | 1 hour (3600s) | `expires_in` param |

MinIO doesn't have R2's 7-day maximum — it can go higher if needed.

---

## Verification Checklist

After setup, verify:

```bash
# 1. Direct bucket access without signature → 403
curl -sk -o /dev/null -w '%{http_code}' \
  'https://yourdomain.com/virtualpytest/script-reports/any-file.html'
# Expected: 403

# 2. /minio/ without basic auth → 401
curl -sk -o /dev/null -w '%{http_code}' 'https://yourdomain.com/minio/'
# Expected: 401

# 3. /redis/ without basic auth → 401
curl -sk -o /dev/null -w '%{http_code}' 'https://yourdomain.com/redis/'
# Expected: 401

# 4. Signed URL → 200
curl -sk -X POST 'https://yourdomain.com/server/storage/signed-url' \
  -H 'X-Auto-Sign: <token>' \
  -H 'Content-Type: application/json' \
  -d '{"path": "script-reports/.../report.html"}' | jq .url
# Then curl that URL → Expected: 200

# 5. Frontend shows private mode in browser console
# Expected: 🔐 PRIVATE mode - Using signed URLs

# 6. Execute a script and verify report URL is signed
# Expected: report_url contains X-Amz-Signature
```

---

## Rollback

To revert to public mode:

1. Set `MINIO_PUBLIC_URL` in all VM `.env` files
2. Set `VITE_MINIO_PUBLIC_URL` in frontend `.env`
3. Run `mc anonymous set download local/virtualpytest` on storage VM
4. Restart all services

No code changes needed — mode is env-var driven.

---

## Troubleshooting

### "Server configuration error" / "User authentication not configured"
**Cause:** `SUPABASE_JWT_SECRET` not set in backend `.env`
**Fix:** Add `SUPABASE_JWT_SECRET=<secret>` to backend server `.env`, restart `vpt-server`

### Presigned URL returns 403
**Cause:** Signature mismatch — usually wrong host header or path stripping
**Fix:** Ensure nginx `proxy_set_header Host $host` is set in the `/virtualpytest/` location, and the location does NOT strip the path

### Report uploads fail after credential change
**Cause:** Host VMs still have old MinIO credentials
**Fix:** Update `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` on ALL host VMs, restart `vpt-host`

### Old report URLs don't work
**Cause:** Old URLs point to `/minio/` path which now requires basic auth
**Fix:** The frontend automatically extracts paths from old MinIO URLs and generates signed URLs. If this doesn't work, check that the frontend code update (`normalizeStoragePath` in `cloudflareUtils.ts`) is deployed

### Frontend shows "PUBLIC mode" instead of "PRIVATE mode"
**Cause:** `VITE_MINIO_PUBLIC_URL` still set in frontend `.env`
**Fix:** Comment out or remove, restart `vpt-frontend`
