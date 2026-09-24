# VirtualPyTest Docker Compose Setup

**One-command deployment of the complete VirtualPyTest stack with nginx reverse proxy.**

## 🚀 Quick Start (3 Steps)

### 1. Setup Environment
```bash
cd nginx/
cp docker-compose.env.example .env
nano .env  # Add your database credentials
```

### 2. Start Services
```bash
docker-compose up -d
```

### 3. Access VirtualPyTest
```
🌐 Frontend: http://localhost/
🔧 API: http://localhost/server/
🤖 Host: http://localhost/host/localhost/
```

**Done!** 🎉 Your complete VirtualPyTest environment is running.

## 🏗️ What's Included

### Services
- **nginx** (Port 80/443) - Reverse proxy and load balancer
- **frontend** (Port 5073) - React web interface
- **backend_server** (Port 5109) - Flask API server
- **backend_host** (Port 6109) - Hardware control & VNC

### Features
- ✅ **Automatic service discovery** (Docker networks)
- ✅ **Health checks** for all services
- ✅ **Persistent storage** for streams and captures
- ✅ **VNC access** for device control
- ✅ **HLS streaming** for video playback
- ✅ **Hot/Cold storage** for media files

## ⚙️ Configuration

### Required Environment Variables (.env)

```bash
# Database (Supabase)
DATABASE_URL=postgresql://postgres:<password>@db.your-project.supabase.co:5432/postgres
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key

# Security
FLASK_SECRET_KEY=your-secure-random-key

# Host Configuration
HOST_NAME=localhost
X11VNC_PASSWORD=admin123
```

### Optional Variables
```bash
# AI Features
OPENROUTER_API_KEY=your-openrouter-key

# Cloud Storage
CLOUDFLARE_R2_ENDPOINT=https://your-account.r2.cloudflarestorage.com
```

## 📊 Service Architecture

```
Internet
    ↓
┌─────────────┐
│   Nginx     │ ← Reverse Proxy (localhost:80)
│ (Port 80)   │
└─────────────┘
       ↓
┌──────┼──────┐
↓             ↓
Frontend    Backend Server
(Port 5073)  (Port 5109)
               ↓
          Backend Host
      (Port 6109, VNC 6080)
```

## 🔧 Management Commands

```bash
# Start all services
docker-compose up -d

# View service status
docker-compose ps

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend_host

# Stop all services
docker-compose down

# Update and restart
docker-compose pull && docker-compose up -d

# Clean restart (rebuild images)
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📁 Data Persistence

The setup creates persistent volumes for:

```
nginx/
├── logs/           # Service logs
│   ├── backend_server/
│   └── backend_host/
└── data/           # Media storage
    ├── stream/     # HLS streams, captures, metadata
    └── captures/   # Additional capture storage
```

## 🌐 Access URLs

Once running, access VirtualPyTest at:

| Service | URL | Purpose |
|---------|-----|---------|
| **Main App** | http://localhost/ | VirtualPyTest web interface |
| **API** | http://localhost/server/ | REST API endpoints |
| **Host Control** | http://localhost/host/localhost/ | Device control & VNC |
| **VNC Lite** | http://localhost/host/localhost/vnc_lite.html | Web-based VNC |
| **Streams** | http://localhost/host/localhost/stream/ | HLS video streams |

## 🚨 Troubleshooting

### Services Won't Start
```bash
# Check service status
docker-compose ps

# Check logs
docker-compose logs

# Check specific service
docker-compose logs backend_host
```

### Cannot Access Services
```bash
# Test nginx
curl http://localhost/

# Test backend server
curl http://localhost/server/health

# Test backend host
curl http://localhost/host/localhost/api/status
```

### Database Connection Issues
```bash
# Verify .env file
cat .env | grep DATABASE_URL

# Test database connection
docker-compose exec backend_server python3 -c "
import os
from shared.src.lib.config.supabase_config import get_supabase_client
print('Testing database...')
client = get_supabase_client()
print('✅ Database OK')
"
```

### VNC Not Working
```bash
# Check VNC service
docker-compose logs backend_host | grep x11vnc

# Test VNC access
curl http://localhost/host/localhost/vnc_lite.html
```

## 🔄 Updating

To update to the latest version:

```bash
# Pull latest images
docker-compose pull

# Restart services
docker-compose up -d

# Check everything is working
docker-compose ps
curl http://localhost/
```

## 🛑 Emergency Stop

To completely stop and clean up:

```bash
# Stop services
docker-compose down

# Remove volumes (WARNING: deletes all data)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## 📞 Support

- Check the main [VirtualPyTest README](../../README.md)
- Review nginx configurations in `config/`
- Check service-specific documentation in their directories

---

**Happy Testing!** 🧪🤖
