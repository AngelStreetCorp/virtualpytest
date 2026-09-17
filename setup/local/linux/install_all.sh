#!/bin/bash
# VirtualPyTest — full installation on ONE Linux machine (Debian 12 / Ubuntu 22.04+).
#
#   sudo -v && ./setup/local/linux/install_all.sh [--no-grafana] [--no-storage] [--no-host]
#                                                  [--public-host <ip-or-name>] [--open-mode false]
#
# Installs, in order: system requirements, the vpt_user service account, Supabase (Postgres +
# auth + REST + Studio, via the Supabase CLI), the shared library, backend_server,
# backend_host, frontend, Grafana, storage (MinIO + Redis) — each as a systemd service — and
# writes every .env from what the installers know (shared/write_env.sh), so the machine is
# usable at http://<this-machine>:5073 when the script ends.
#
#   --no-grafana      skip Grafana (dashboards)          --no-storage  skip MinIO + Redis
#   --no-host         skip the device controller (server-only machine)
#   --public-host X   address browsers use to reach this machine (default: first LAN IP)
#   --open-mode false start CLOSED: every /server/* call needs a login or key (default: open,
#                     no login, trusted network only — see docs/get-started/supabase.md)
#
# The repository is copied to /opt/virtualpytest (owned by vpt_user) and everything runs from
# there; re-running the script is safe (installers skip what is already done, .env values a
# user set by hand are kept).

set -e

ORIG_ARGS=("$@")
WITH_GRAFANA=true; WITH_STORAGE=true; WITH_HOST=true; PUBLIC_HOST=""; OPEN_MODE=true
while [ $# -gt 0 ]; do
    case "$1" in
        --no-grafana) WITH_GRAFANA=false; shift ;;
        --no-storage) WITH_STORAGE=false; shift ;;
        --no-host)    WITH_HOST=false; shift ;;
        --public-host) PUBLIC_HOST="$2"; shift 2 ;;
        --open-mode)  OPEN_MODE="$2"; shift 2 ;;
        -h|--help) sed -n 2,20p "$0"; exit 0 ;;
        *) echo "unknown option: $1"; sed -n 2,20p "$0"; exit 1 ;;
    esac
done

echo "🔥 VirtualPyTest Full Installation"
echo "   grafana=$WITH_GRAFANA storage=$WITH_STORAGE host=$WITH_HOST open-mode=$OPEN_MODE"
echo ""

# Get to project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STANDARD_ROOT="/opt/virtualpytest"

# Load shared bootstrap functions
if [ -f "$CURRENT_ROOT/setup/local/linux/shared/bootstrap.sh" ]; then
    source "$CURRENT_ROOT/setup/local/linux/shared/bootstrap.sh"
fi

# Bootstrap: copy the tree to /opt/virtualpytest (service account, permissions) and
# continue from there — the copy is what the systemd units run.
if [ "$CURRENT_ROOT" != "$STANDARD_ROOT" ]; then
    setup_for_code_installer "$CURRENT_ROOT"
    echo "🔄 Continuing from $STANDARD_ROOT ..."
    exec "$STANDARD_ROOT/setup/local/linux/install_all.sh" "${ORIG_ARGS[@]}"
fi

# We're now in the standard location
PROJECT_ROOT="$STANDARD_ROOT"
cd "$PROJECT_ROOT"

# Final verification
if [ ! -f "README.md" ] || [ ! -d "shared" ]; then
    echo "❌ Could not find virtualpytest project in standard location: $PROJECT_ROOT"
    exit 1
fi

echo "✅ Running from standard VirtualPyTest location: $PROJECT_ROOT"

# Linux installation setup
VPT_INSTALL_DB_SCRIPT="linux/database/install_db.sh"
VPT_INSTALL_SERVER_SCRIPT="linux/backend_server/install_server.sh"
VPT_INSTALL_HOST_SCRIPT="linux/backend_host/install_host.sh"
VPT_INSTALL_FRONTEND_SCRIPT="linux/frontend/install_frontend.sh"
VPT_INSTALL_GRAFANA_SCRIPT="linux/monitoring/install_grafana.sh"
VPT_INSTALL_STORAGE_SCRIPT="linux/storage/install_storage.sh"

# Make scripts executable (the /opt copy belongs to vpt_user; rsync already kept the bits)
sudo find ./setup/local/linux -type f -name "*.sh" -exec chmod +x {} + 2>/dev/null || true

# Install system requirements
echo "0️⃣ Installing system requirements..."
if [ -f "./setup/local/linux/shared/install_requirements.sh" ]; then
    ./setup/local/linux/shared/install_requirements.sh
else
    echo "⚠️ Warning: setup/local/linux/shared/install_requirements.sh not found"
fi

# Create service account
echo ""
echo "👤 Creating VirtualPyTest service account..."
if [ -f "./setup/local/linux/shared/create_vpt_user.sh" ]; then
    sudo ./setup/local/linux/shared/create_vpt_user.sh
fi

# Set up permissions
echo ""
echo "🔐 Setting up system permissions..."
if sudo -n true 2>/dev/null; then
    sudo ./setup/local/linux/backend_host/setup_permissions.sh --user "$(whoami)"
else
    echo "⚠️ Permission setup requires sudo. Run manually if needed."
fi

# Install all components
echo ""
echo "1️⃣ Installing database (Supabase)..."
./setup/local/"$VPT_INSTALL_DB_SCRIPT"

# Every installer after this point reads .env — write them now, from what the DB install
# produced (keys), the LAN address and generated secrets. The frontend bakes VITE_* in at
# build time, so this MUST run before install_frontend.sh.
echo ""
echo "📄 Writing .env files..."
WRITE_ENV_ARGS=(--open-mode "$OPEN_MODE")
[ -n "$PUBLIC_HOST" ] && WRITE_ENV_ARGS+=(--public-host "$PUBLIC_HOST")
[ "$WITH_STORAGE" = true ] && WRITE_ENV_ARGS+=(--with-storage)
[ "$WITH_GRAFANA" = true ] && WRITE_ENV_ARGS+=(--with-grafana)
./setup/local/linux/shared/write_env.sh "${WRITE_ENV_ARGS[@]}"

if [ "$WITH_STORAGE" = true ]; then
    echo ""
    echo "2️⃣ Installing storage (MinIO + Redis)..."
    ./setup/local/"$VPT_INSTALL_STORAGE_SCRIPT"
fi

echo ""
echo "3️⃣ Installing shared library..."
./setup/local/linux/shared/install_shared.sh

echo ""
echo "4️⃣ Installing backend_server..."
./setup/local/"$VPT_INSTALL_SERVER_SCRIPT"

if [ "$WITH_HOST" = true ]; then
    echo ""
    echo "5️⃣ Installing backend_host..."
    ./setup/local/"$VPT_INSTALL_HOST_SCRIPT"
fi

echo ""
echo "6️⃣ Installing frontend..."
./setup/local/"$VPT_INSTALL_FRONTEND_SCRIPT"

if [ "$WITH_GRAFANA" = true ]; then
    echo ""
    echo "7️⃣ Installing Grafana..."
    ./setup/local/"$VPT_INSTALL_GRAFANA_SCRIPT" || \
        echo "⚠️  Grafana install failed — everything else is unaffected; rerun setup/local/linux/monitoring/install_grafana.sh"
fi

# Start what the installers only enabled
echo ""
echo "🚀 Starting services..."
sudo systemctl start vpt-server 2>/dev/null || true
if [ "$WITH_HOST" = true ]; then
    sudo systemctl start vpt-host 2>/dev/null || true
fi
sudo systemctl start vpt-frontend-prod 2>/dev/null || true

PUBLIC_HOST_SET="$(grep -E '^SERVER_URL=' "$PROJECT_ROOT/.env" | head -1 | sed -E 's|.*://([^:/]+).*|\1|')"
PUBLIC_HOST_SET="${PUBLIC_HOST_SET:-localhost}"
echo ""
echo "🎉 VirtualPyTest full installation completed!"
echo ""
echo "🌐 Web UI        http://$PUBLIC_HOST_SET:5073"
echo "🖥️  Server API    http://$PUBLIC_HOST_SET:5109"
[ "$WITH_HOST" = true ]    && echo "🎮 Host API      http://$PUBLIC_HOST_SET:6109"
[ "$WITH_GRAFANA" = true ] && echo "📊 Grafana       http://$PUBLIC_HOST_SET:3000   (admin / GRAFANA_ADMIN_PASSWORD in .env)"
echo "🗄️  Supabase      http://$PUBLIC_HOST_SET:54321  Studio: http://$PUBLIC_HOST_SET:54323"
[ "$WITH_STORAGE" = true ] && echo "📦 MinIO console http://$PUBLIC_HOST_SET:9001   (admin / MINIO_SECRET_KEY in .env)"
echo ""
echo "🔧 Services: vpt-server · vpt-host · vpt-frontend-prod · supabase · grafana-server · minio · redis-server"
echo "   sudo systemctl status vpt-server   ·   sudo journalctl -u vpt-server -f"
echo "   Config: $PROJECT_ROOT/.env · $PROJECT_ROOT/backend_host/src/.env · $PROJECT_ROOT/frontend/.env"
echo "   (re-run setup/local/linux/shared/write_env.sh after editing, then restart the services)"
if [ "$OPEN_MODE" = true ]; then
    echo ""
    echo "🚨 OPEN MODE: no login, every API call is accepted. Do not expose this machine to the"
    echo "   internet as-is. To enforce login see docs/get-started/supabase.md#enforce-login."
fi
