# 🚀 VirtualPyTest Hetzner - Quick Start

## One-Command Setup for N Hosts

### Step 1: Configure How Many Hosts

```bash
cd setup/docker/hetzner_custom
nano config.env
```

Edit `HOST_MAX`:
```bash
HOST_MAX=2    # For 2 hosts
HOST_MAX=4    # For 4 hosts  
HOST_MAX=6    # For 6 hosts (max recommended for 4GB RAM)
```

### Step 2: Run Setup (Does Everything!)

```bash
./setup.sh
```

This automatically:
- ✅ Checks your RAM
- ✅ Generates nginx config for N hosts
- ✅ Generates docker-compose.yml for N hosts  
- ✅ Creates backend_host_1/.env through backend_host_N/.env
- ✅ **Deploys nginx config to /etc/nginx/**
- ✅ **Tests and reloads nginx**

### Step 3: Launch Services

```bash
./launch.sh
```

**Done!** 🎉

---

## Access Your Hosts

- **Host 1 VNC**: https://api.virtualpytest.com/host1/vnc/vnc_lite.html
- **Host 2 VNC**: https://api.virtualpytest.com/host2/vnc/vnc_lite.html
- **Host N VNC**: https://api.virtualpytest.com/hostN/vnc/vnc_lite.html

---

## 2-Command Deployment

```bash
# 1. Setup (generates + deploys nginx)
./setup.sh

# 2. Launch
./launch.sh
```

That's it! 🚀

## Scaling

### Add More Hosts

```bash
# Edit config
nano config.env   # Change HOST_MAX=2 to HOST_MAX=4

# Re-run setup (automatically redeploys nginx)
./setup.sh

# Restart services with new hosts
docker-compose -f docker-compose.yml down
./launch.sh
```

### Remove Hosts

```bash
# Edit config
nano config.env   # Change HOST_MAX=4 to HOST_MAX=2

# Re-run setup (automatically redeploys nginx)
./setup.sh

# Restart with fewer hosts
docker-compose -f docker-compose.yml down
./launch.sh
```

---

## RAM Calculator

| RAM | Max Hosts | Notes |
|-----|-----------|-------|
| 2GB | 3 hosts | Tight |
| 4GB | 6 hosts | Recommended |
| 8GB | 12 hosts | Comfortable |
| 16GB | 24 hosts | Plenty |

*Each host uses ~300-400MB RAM*

---

## Troubleshooting

### Check Services
```bash
docker ps
docker-compose -f docker-compose.yml logs -f
```

### Restart Single Host
```bash
docker restart virtualpytest-backend-host-2
```

### Full Restart
```bash
docker-compose -f docker-compose.yml down
./launch.sh
```

---

## Files Explained

- `config.env` - Your settings (HOST_MAX, ports, domain)
- `setup.sh` - Generates all configs based on config.env
- `launch.sh` - Starts Docker containers
- `host-nginx.conf` - Generated nginx config (deploy to server)
- `docker-compose.yml` - Generated Docker services
- `backend_host_N/.env` - Generated per-host configs

