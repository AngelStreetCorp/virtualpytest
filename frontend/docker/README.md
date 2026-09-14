# Frontend Docker Deployment

This directory contains Docker configurations for deploying the VirtualPyTest frontend.

## Dockerfile Overview

### `../Dockerfile` (Frontend Only)
**Clean, simple deployment serving static files directly.**

- Uses Node.js `serve` package to serve static files
- Single container solution without nginx
- Includes SPA routing support for React Router
- Runs on port 5073 (matches development server)
- Security-focused with non-root user

**Build and run:**
```bash
# Build the image
docker build -t vpt-frontend -f Dockerfile ..

# Run the container
docker run -d -p 5073:5073 --name vpt-frontend vpt-frontend

# Access at: http://localhost:5073
```

### Optional: Nginx Reverse Proxy
If you need advanced serving features (gzip compression, security headers, caching), you can add nginx through setup/compose configurations. The `nginx/` directory contains configurations that can be used when deploying with reverse proxy setups.

## Configuration Files

- `nginx.conf` - Optional nginx configuration for reverse proxy setups
  - SPA routing with `try_files $uri $uri/ /index.html`
  - Gzip compression and security headers
  - Static asset caching (1 year for JS/CSS/images)
  - Protection against accessing hidden files

## Deployment Options

### Direct Deployment (Recommended)
Use the main Dockerfile for simple, secure deployments:

- ✅ Single container solution
- ✅ Non-root user for security
- ✅ SPA routing support
- ✅ Health checks included
- ✅ Minimal dependencies

### With Reverse Proxy
For advanced features, deploy with nginx or other reverse proxies:

- ✅ Gzip compression
- ✅ Security headers
- ✅ Advanced caching
- ✅ Load balancing
- ✅ SSL termination

Use the configurations in `nginx/` directory when setting up reverse proxy deployments.

## Common Commands

### Building
```bash
# Build the image
docker build -t vpt-frontend -f Dockerfile ..
```

### Running
```bash
# Run the container
docker run -d -p 5073:5073 --name vpt-frontend vpt-frontend
```

### Management
```bash
# View running containers
docker ps

# View logs
docker logs vpt-frontend

# Stop container
docker stop vpt-frontend

# Remove container
docker rm vpt-frontend
```

### Health Checks
Both containers include health checks that verify the application is responding:
```bash
# Check container health
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## Troubleshooting

### Container Won't Start
```bash
# Check container logs
docker logs vpt-frontend

# Check if port is already in use
netstat -tlnp | grep :5073
```

### Application Not Loading
```bash
# Test connectivity
curl http://localhost:5073

# Check if container is healthy
docker inspect vpt-frontend | grep -A 10 "Health"
```

### Build Issues
```bash
# Clean build
docker build --no-cache -t vpt-frontend -f Dockerfile ..

# Check build logs
docker build -t vpt-frontend -f Dockerfile .. 2>&1 | tee build.log
```