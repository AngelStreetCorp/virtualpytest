#!/bin/bash
# =============================================================================
# VirtualPyTest - Runner Host Install Script
# =============================================================================
# Installs a lightweight VPT runner host on a new Debian/Ubuntu VM.
# Only installs vpt-host.service — no stream, VNC, monitor, or capture services.
#
# Usage (on the new VM, as a sudo-capable user):
#   bash /opt/virtualpytest/setup/proxmox/vm/runner/install_runner.sh \
#     --host-name runner-01 \
#     --host-type runner_host \
#     --server-url https://<origin-ip> \
#     --api-key YOUR_API_KEY
#
# Runner types:
#   runner_host           — web + API (Playwright + HTTP)
#   runner_android_mobile — ADB only (Android phone)
#   runner_android_tablet — ADB only (Android tablet)
#   runner_android_tv     — ADB only (Android TV)
#
# After installation:
#   sudo systemctl status vpt-host.service
#   curl http://localhost:6109/health
# =============================================================================

set -e

# --- Defaults ---
HOST_NAME="runner-01"
HOST_TYPE="runner_host"
HOST_PORT="6109"
SERVER_URL="http://192.168.0.103:5109"
API_KEY=""
SUPABASE_URL="http://192.168.0.102:54321"
SUPABASE_ANON_KEY=""
SUPABASE_DB_URI="postgresql://postgres:postgres@192.168.0.102:54322/postgres"
# Storage credentials belong to the storage VM and are generated there per install; there
# is no default to fall back on. Pass them from that machine's .env.
MINIO_SECRET_KEY=""
REDIS_PASSWORD=""
PROJECT_DIR="/opt/virtualpytest"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_USER="vpt_user"

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host-name)   HOST_NAME="$2";   shift 2 ;;
    --host-type)   HOST_TYPE="$2";   shift 2 ;;
    --host-port)   HOST_PORT="$2";   shift 2 ;;
    --server-url)  SERVER_URL="$2";  shift 2 ;;
    --api-key)          API_KEY="$2";          shift 2 ;;
    --supabase-url)     SUPABASE_URL="$2";     shift 2 ;;
    --supabase-anon-key) SUPABASE_ANON_KEY="$2"; shift 2 ;;
    --supabase-db-uri)  SUPABASE_DB_URI="$2";  shift 2 ;;
    --minio-secret-key) MINIO_SECRET_KEY="$2"; shift 2 ;;
    --redis-password)   REDIS_PASSWORD="$2";   shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [ -z "$MINIO_SECRET_KEY" ]; then
  echo "⚠️  MINIO_SECRET_KEY not given (--minio-secret-key) — the runner will not reach MinIO."
  echo "   Take the value from the storage VM's .env."
fi
if [ -z "$REDIS_PASSWORD" ]; then
  echo "⚠️  REDIS_PASSWORD not given (--redis-password) — the runner will not reach Redis."
  echo "   Take the value from the storage VM's .env."
fi

echo "============================================================"
echo "🏃 VirtualPyTest Runner Host Setup"
echo "============================================================"
echo "   Host Name:  $HOST_NAME"
echo "   Host Type:  $HOST_TYPE"
echo "   Host Port:  $HOST_PORT"
echo "   Server URL: $SERVER_URL"
echo "   Project Dir: $PROJECT_DIR"
echo "============================================================"

# Derive HOST_URL from host IP
HOST_IP=$(hostname -I | awk '{print $1}')
HOST_URL="http://$HOST_IP:$HOST_PORT"
HOST_API_URL="http://$HOST_IP:$HOST_PORT"

echo "   Host IP:    $HOST_IP"
echo "   Host URL:   $HOST_URL"

# --- Step 1: System dependencies ---
echo ""
echo "📦 [Step 1] Installing system dependencies..."
sudo apt-get update -q

# Base tools always needed
sudo apt-get install -y -q \
  curl wget git python3 python3-pip python3-venv \
  net-tools dnsutils lsof rsync

# Runner-type-specific dependencies
if [[ "$HOST_TYPE" == "runner_host" ]]; then
  echo "   → runner_host: installing Playwright + browser dependencies..."
  sudo apt-get install -y -q \
    chromium chromium-driver \
    libnss3 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libpangocairo-1.0-0
elif [[ "$HOST_TYPE" == runner_android_* ]]; then
  echo "   → $HOST_TYPE: installing ADB..."
  sudo apt-get install -y -q android-tools-adb
fi

echo "   ✅ System dependencies installed"

# --- Step 2: vpt_user service account ---
echo ""
echo "👤 [Step 2] Ensuring vpt_user service account..."
if ! id vpt_user &>/dev/null; then
  sudo useradd -r -m -s /bin/bash -d /home/vpt_user vpt_user
  echo "   ✅ vpt_user created"
else
  echo "   ✅ vpt_user already exists"
fi

# --- Step 3: Python venv ---
echo ""
echo "🐍 [Step 3] Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  sudo -u $SERVICE_USER python3 -m venv "$VENV_DIR"
  echo "   ✅ venv created at $VENV_DIR"
else
  echo "   ✅ venv already exists"
fi

echo "   → Installing backend_host Python dependencies..."
sudo -u $SERVICE_USER "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u $SERVICE_USER "$VENV_DIR/bin/pip" install --quiet \
  -r "$PROJECT_DIR/backend_host/requirements.txt"

# Install Playwright browsers for runner_host
if [[ "$HOST_TYPE" == "runner_host" ]]; then
  echo "   → Installing Playwright browsers..."
  sudo -u $SERVICE_USER "$VENV_DIR/bin/python" -m playwright install chromium 2>/dev/null || \
    sudo "$VENV_DIR/bin/python" -m playwright install-deps chromium
  echo "   ✅ Playwright installed"
fi

echo "   ✅ Python environment ready"

# --- Step 4: Create .env files ---
echo ""
echo "⚙️  [Step 4] Creating .env configuration..."

# 4a: Project root .env (shared infra: Supabase, MinIO, Redis, AI keys)
ROOT_ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ROOT_ENV_FILE" ]; then
  echo "   ⚠️  Root .env already exists — skipping"
else
  sudo -u $SERVICE_USER tee "$ROOT_ENV_FILE" > /dev/null <<EOF
# VirtualPyTest Project — generated by install_runner.sh
SERVER_URL=$SERVER_URL
API_KEY=$API_KEY
SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
SUPABASE_DB_URI=$SUPABASE_DB_URI
MINIO_ENDPOINT=http://192.168.0.101:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=$MINIO_SECRET_KEY
MINIO_BUCKET=virtualpytest
MINIO_CONSOLE_URL=http://192.168.0.101:9001
MINIO_PUBLIC_URL=$SERVER_URL/minio
REDIS_URL=redis://:$REDIS_PASSWORD@192.168.0.101:6379/0
ENVIRONMENT=production
SKIP_SPEEDTEST=true
EOF
  echo "   ✅ Root .env created at $ROOT_ENV_FILE"
fi

# 4b: Service-specific .env (host identity + device config)
ENV_FILE="$PROJECT_DIR/backend_host/src/.env"

if [ -f "$ENV_FILE" ]; then
  echo "   ⚠️  .env already exists — skipping (edit manually if needed)"
  echo "   Location: $ENV_FILE"
else
  # Determine default DEVICE1 model from host type
  if [[ "$HOST_TYPE" == "runner_host" ]]; then
    DEVICE1_NAME="Runner"
    DEVICE1_MODEL="runner_host"
  elif [[ "$HOST_TYPE" == "runner_android_mobile" ]]; then
    DEVICE1_NAME="Android Mobile"
    DEVICE1_MODEL="runner_android_mobile"
  elif [[ "$HOST_TYPE" == "runner_android_tablet" ]]; then
    DEVICE1_NAME="Android Tablet"
    DEVICE1_MODEL="runner_android_tablet"
  elif [[ "$HOST_TYPE" == "runner_android_tv" ]]; then
    DEVICE1_NAME="Android TV"
    DEVICE1_MODEL="runner_android_tv"
  else
    DEVICE1_NAME="Runner"
    DEVICE1_MODEL="runner_host"
  fi

  # Android runners connect to local emulator via ADB
  DEVICE1_ADB_SECTION=""
  if [[ "$HOST_TYPE" == runner_android_* ]]; then
    DEVICE1_ADB_SECTION="DEVICE1_IP=localhost
DEVICE1_ADB_PORT=5554"
  fi

  sudo -u $SERVICE_USER tee "$ENV_FILE" > /dev/null <<EOF
# VirtualPyTest Runner Host — generated by install_runner.sh
HOST_NAME=$HOST_NAME
HOST_TYPE=$HOST_TYPE
HOST_PORT=$HOST_PORT
HOST_URL=$HOST_URL
HOST_API_URL=$HOST_API_URL
SERVER_URL=$SERVER_URL
API_KEY=$API_KEY

# Device (required for script execution)
DEVICE1_NAME=$DEVICE1_NAME
DEVICE1_MODEL=$DEVICE1_MODEL
$DEVICE1_ADB_SECTION
EOF
  echo "   ✅ .env created at $ENV_FILE"
fi

# --- Step 5: Install vpt-host.service ---
echo ""
echo "🔧 [Step 5] Installing vpt-host.service..."

sudo tee /etc/systemd/system/vpt-host.service > /dev/null <<EOF
[Unit]
Description=VirtualPyTest Runner Host (lightweight)
After=network.target
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR/backend_host/src
Environment=PYTHONPATH=$PROJECT_DIR/shared/src/lib:$PROJECT_DIR/backend_host/src
ExecStartPre=+/usr/bin/systemctl daemon-reload
ExecStart=$VENV_DIR/bin/python app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable vpt-host.service
sudo systemctl start vpt-host.service

echo "   ✅ vpt-host.service installed and started"

# --- Step 6: Set ownership ---
echo ""
echo "🔑 [Step 6] Setting file ownership..."
sudo chown -R $SERVICE_USER:$SERVICE_USER "$PROJECT_DIR" 2>/dev/null || true
echo "   ✅ Ownership set to $SERVICE_USER"

# --- Step 6b: Sudoers for vpt_user (matches install_host.sh) ---
sudo tee /etc/sudoers.d/virtualpytest > /dev/null <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl show vpt-*, /usr/bin/systemctl show vpt-*
$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl status vpt-*, /usr/bin/systemctl status vpt-*
$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl start vpt-*, /usr/bin/systemctl start vpt-*
$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl stop vpt-*, /usr/bin/systemctl stop vpt-*
$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*
$SERVICE_USER ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/fuser
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/pkill
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/kill
EOF
sudo chmod 440 /etc/sudoers.d/virtualpytest
echo "   ✅ Sudoers configured"

# --- Step 7: Health check ---
echo ""
echo "🩺 [Step 7] Health check (waiting 5s for service to start)..."
sleep 5

if curl -sf "http://localhost:$HOST_PORT/health" > /dev/null 2>&1; then
  echo "   ✅ Runner host is healthy!"
  curl -s "http://localhost:$HOST_PORT/health" | python3 -m json.tool 2>/dev/null || true
else
  echo "   ⚠️  Health check failed — check logs:"
  echo "      sudo journalctl -u vpt-host.service --no-pager -n 30"
fi

# --- Summary ---
echo ""
echo "============================================================"
echo "✅ Runner host setup complete!"
echo "============================================================"
echo ""
echo "Host Name:    $HOST_NAME"
echo "Host Type:    $HOST_TYPE"
echo "Host API:     http://localhost:$HOST_PORT"
echo "Server URL:   $SERVER_URL"
echo ""
echo "Service commands:"
echo "  sudo systemctl status vpt-host.service"
echo "  sudo journalctl -u vpt-host.service --no-pager -n 50"
echo "  sudo systemctl restart vpt-host.service"
echo ""
echo "The runner will register with the VPT server on startup."
echo "It should appear in the Devices page with a RUNNER badge."
echo "============================================================"
