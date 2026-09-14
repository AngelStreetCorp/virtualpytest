# VirtualPyTest - Development Mode Guide

## Quick Start

### Initial Setup (One Time)
```bash
cd setup/docker/hetzner_custom
./setup.sh
```

This generates:
- `docker-compose.yml` - Production config (builds images)
- `docker-compose.dev.yml` - Dev config (mounts source code)
- Host `.env` files

### Development Mode (Recommended for coding)
```bash
cd setup/docker/hetzner_custom
./launch-dev.sh
```

**Benefits:**
- ✅ Edit code locally (VS Code, Cursor, etc.)
- ✅ Changes reflect immediately in containers
- ✅ Just restart container (2 seconds) instead of rebuild (minutes)
- ✅ No need to rebuild images

### Production Mode
```bash
cd setup/docker/hetzner_custom
./launch.sh
```

Builds immutable images (slower, for deployment)

---

## Development Workflow

### 1. Start Services
```bash
./launch-dev.sh
```

### 2. Edit Code Locally
Edit any file in:
- `shared/`
- `backend_server/src/`
- `backend_host/src/`

Changes are **immediately** visible in containers (because folders are mounted)

### 3. Restart Container to Pick Up Changes
```bash
# Restart specific service (fast - 2 seconds)
docker-compose -f docker-compose.yml restart backend_host_1

# Or restart all hosts
docker-compose -f docker-compose.yml restart backend_server backend_host_1 backend_host_2
```

### 4. View Logs
```bash
# All services
docker-compose -f docker-compose.yml logs -f

# Specific service
docker-compose -f docker-compose.yml logs -f backend_host_1
```

---

## Common Commands

### Quick Restart After Code Change
```bash
cd setup/docker/hetzner_custom

# Restart one host (picks up your code changes)
docker-compose -f docker-compose.yml restart backend_host_1

# Restart server
docker-compose -f docker-compose.yml restart backend_server
```

### View Container Logs
```bash
# Follow logs (live)
docker-compose -f docker-compose.yml logs -f backend_host_1

# Last 100 lines
docker-compose -f docker-compose.yml logs --tail=100 backend_host_1
```

### Execute Commands in Container
```bash
# Open shell in container
docker exec -it virtualpytest-backend-host-1 bash

# Run single command
docker exec virtualpytest-backend-host-1 python --version
```

### Stop Services
```bash
docker-compose -f docker-compose.yml down
```

---

## Comparison: Dev vs Production Mode

| Feature | Dev Mode (launch-dev.sh) | Production Mode (launch.sh) |
|---------|-------------------------|----------------------------|
| Code mounting | ✅ Source code mounted | ❌ Code baked into image |
| Edit speed | ⚡ Instant | 🐌 Must rebuild (minutes) |
| Restart time | ⚡ 2 seconds | 🐌 Minutes to rebuild |
| Use case | 🔨 Active development | 🚀 Deployment |
| Git needed | ❌ No (edit locally) | ❌ No (CI/CD builds) |

---

## Troubleshooting

### Changes Not Reflecting?
1. **Check if volumes are mounted:**
   ```bash
   docker inspect virtualpytest-backend-host-1 | grep -A 10 Mounts
   ```
   
2. **Restart the container:**
   ```bash
   docker-compose -f docker-compose.yml restart backend_host_1
   ```

### Need to Rebuild?
Only needed if you change:
- Dockerfile
- System dependencies (apt packages)
- Python requirements.txt

```bash
# Rebuild and restart
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

### Switch from Prod to Dev
```bash
# Stop prod containers
docker-compose -f docker-compose.yml down

# Start dev containers
./launch-dev.sh
```

---

## Best Practices

### ✅ DO
- Use **dev mode** for daily development
- Edit code in your **local editor**
- **Restart containers** after changes
- Use **logs** to debug
- **Commit** frequently

### ❌ DON'T
- Don't edit code inside containers
- Don't use `docker cp` in dev mode (volumes are mounted!)
- Don't rebuild unless Dockerfile changed
- Don't put git inside containers

---

## Performance Tips

### Faster Restarts
Restart only what you changed:
```bash
# Only restart host 1 (if you changed host code)
docker-compose -f docker-compose.yml restart backend_host_1

# Only restart server (if you changed server code)
docker-compose -f docker-compose.yml restart backend_server
```

### Watch Logs During Development
```bash
# Split terminal - watch logs while editing
docker-compose -f docker-compose.yml logs -f backend_host_1
```

### Test in Container Without Restart
```bash
# Execute Python file directly (for quick tests)
docker exec virtualpytest-backend-host-1 python /app/test_scripts/test.py
```

---

## Summary

**For Development**: Always use `./launch-dev.sh` 
- Edit locally → Restart container (2s) → Test
- No rebuilding needed!

**For Production**: Use `./launch.sh`
- Builds immutable images
- Deploy with confidence

