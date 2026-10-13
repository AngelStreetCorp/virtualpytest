#!/bin/bash

# VirtualPyTest - Install the dedicated MinIO instance for TASK-27 training data.
#
# This is a SECOND, SEPARATE MinIO instance (its own service, its own port, its own data
# disk) — not a bucket inside the default `minio` service. The default instance's disk
# had 12 GB free and already filled up once (XMinioStorageFull, 2026-09-14); training
# data must never share that failure mode.
#
# Bucket `vpt-training` gets NO lifecycle (ILM) rule, ever — it is the permanent AI
# training dataset, not a run artifact. See TASK-27 §5/§13 and CONTRACTS.md.
#
# This script is idempotent: safe to re-run.

set -e

echo "💾 VirtualPyTest - Installing dedicated MinIO for AI training data (vpt-training)"

DATA_MOUNT="/mnt/minio-training"
DATA_DIR="$DATA_MOUNT/data"
SERVICE_NAME="minio-training"
ENV_FILE="/etc/default/${SERVICE_NAME}"
API_PORT=9100
CONSOLE_PORT=9101
BUCKET="vpt-training"
ALIAS="training"
RW_POLICY_NAME="vpt-training-rw-policy"
RW_USER="vpt-training-rw"

SUDO=""; [ "$EUID" -ne 0 ] && SUDO="sudo"

# --- Guardrail: refuse to run unless the dedicated training disk is actually mounted ---
# This disk is separate from the default MinIO's data disk on purpose (see header). If
# it isn't mounted, writing to $DATA_DIR would silently land on the VM's root disk.
if ! mountpoint -q "$DATA_MOUNT"; then
    echo "❌ $DATA_MOUNT is not a mountpoint. Refusing to install."
    echo "   The dedicated training disk must be attached and mounted (fstab, nofail) first."
    exit 1
fi
echo "   ✅ $DATA_MOUNT is a mountpoint"

# --- Binaries: reuse the same minio/mc install as install_minio.sh, same versions ---
MINIO_VERSION="RELEASE.2025-07-23T15-54-02Z"
MC_VERSION="RELEASE.2025-04-16T18-13-26Z"
fetch_release_binary() {  # fetch_release_binary <repo> <version> <destination>
    curl -fsSL -o "$3" \
        "https://github.com/minio/$1/releases/download/$2/$1.linux-amd64.$2" || return 1
    $SUDO chmod +x "$3"
}
if ! command -v minio >/dev/null 2>&1; then
    echo "📦 Installing MinIO Server (binary from GitHub release $MINIO_VERSION)..."
    fetch_release_binary minio "$MINIO_VERSION" /tmp/minio
    $SUDO mv /tmp/minio /usr/local/bin/minio
else
    echo "   ℹ️  minio binary already present ($(minio --version | head -1))"
fi
if ! command -v mc >/dev/null 2>&1; then
    echo "📦 Installing MinIO Client (mc, from GitHub release $MC_VERSION)..."
    fetch_release_binary mc "$MC_VERSION" /tmp/mc
    $SUDO mv /tmp/mc /usr/local/bin/mc
else
    echo "   ℹ️  mc binary already present ($(mc --version | head -1))"
fi

# --- Data dir + user. Reuse minio-user (created by install_minio.sh) if present. ---
if ! id -u minio-user > /dev/null 2>&1; then
    $SUDO useradd -r minio-user -s /sbin/nologin
    echo "   ✅ Created minio-user"
else
    echo "   ℹ️  minio-user already exists, continuing..."
fi
$SUDO mkdir -p "$DATA_DIR"
$SUDO mkdir -p /etc/minio-training
$SUDO chown -R minio-user:minio-user "$DATA_MOUNT" /etc/minio-training

# --- Credentials: own root pair, independent of the default instance's. Generated once,
#     kept in $ENV_FILE (mode 600) and never re-generated on re-run. ---
if [ -f "$ENV_FILE" ] && grep -q '^MINIO_ROOT_USER=' "$ENV_FILE"; then
    echo "   ℹ️  $ENV_FILE already has root credentials, keeping them"
    TRAINING_ROOT_USER="$(grep -E '^MINIO_ROOT_USER=' "$ENV_FILE" | cut -d= -f2-)"
    TRAINING_ROOT_PASS="$(grep -E '^MINIO_ROOT_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
else
    TRAINING_ROOT_USER="vpt-training-root"
    TRAINING_ROOT_PASS="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
fi

echo "⚙️ Writing $ENV_FILE ..."
$SUDO tee "$ENV_FILE" > /dev/null << EOF
# Dedicated MinIO instance for TASK-27 AI training data. Independent of /etc/default/minio
# (the default instance) — different root credentials, different port, different disk.
# NEVER merge this with the default instance's config.
MINIO_ROOT_USER=$TRAINING_ROOT_USER
MINIO_ROOT_PASSWORD=$TRAINING_ROOT_PASS
MINIO_OPTS="--address :${API_PORT} --console-address :${CONSOLE_PORT}"
MINIO_CONFIG_DIR=/etc/minio-training
MINIO_CACHE_DRIVES=""
MINIO_DRIVES="$DATA_DIR"
EOF
$SUDO chmod 600 "$ENV_FILE"

# --- systemd unit. Same shape as setup/local/linux/config/services/minio.service, with
#     the new service/env-file names and no dependency on the default unit. ---
echo "🚀 Installing ${SERVICE_NAME} systemd service..."
$SUDO tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null << EOF
[Unit]
Description=MinIO (TASK-27 training data — separate from the default minio.service)
Documentation=https://docs.min.io
Wants=network-online.target
After=network-online.target
AssertFileIsExecutable=/usr/local/bin/minio

[Service]
Type=simple
User=minio-user
Group=minio-user
EnvironmentFile=${ENV_FILE}
ExecStartPre=/bin/bash -c "if [ -z \"\${MINIO_ROOT_USER}\" ]; then echo \"Variable MINIO_ROOT_USER not set in ${ENV_FILE}\"; exit 1; fi"
ExecStartPre=/bin/bash -c "if [ -z \"\${MINIO_ROOT_PASSWORD}\" ]; then echo \"Variable MINIO_ROOT_PASSWORD not set in ${ENV_FILE}\"; exit 1; fi"
ExecStart=/usr/local/bin/minio server \$MINIO_OPTS \$MINIO_DRIVES
Restart=always
RestartSec=5

LimitNOFILE=1048576
TimeoutStopSec=30

NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ReadWritePaths=${DATA_MOUNT} /etc/minio-training
ProtectSystem=full
ProtectProc=invisible

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable "${SERVICE_NAME}"

if $SUDO systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "   ℹ️  Restarting existing ${SERVICE_NAME}..."
    $SUDO systemctl restart "${SERVICE_NAME}"
else
    echo "   🚀 Starting ${SERVICE_NAME}..."
    $SUDO systemctl start "${SERVICE_NAME}"
fi

# Confirm the DEFAULT minio service is untouched and still active — this script must
# never affect it.
if $SUDO systemctl is-active --quiet minio; then
    echo "   ✅ Default 'minio' service still active (untouched)"
else
    echo "   ⚠️  Default 'minio' service is NOT active — this script did not touch it, but check separately."
fi

echo "⏳ Waiting for ${SERVICE_NAME} to listen on :${API_PORT}..."
RETRY_COUNT=0; MAX_RETRIES=30
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if $SUDO ss -tlnp 2>/dev/null | grep -q ":${API_PORT} "; then
        echo "   ✅ Listening on :${API_PORT}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ ${SERVICE_NAME} failed to start listening on :${API_PORT}"
        $SUDO systemctl status "${SERVICE_NAME}" --no-pager -l
        $SUDO journalctl -u "${SERVICE_NAME}" -n 50 --no-pager
        exit 1
    fi
    sleep 1
done
sleep 2

# --- mc alias + bucket, with retry (same pattern as install_minio.sh) ---
echo "⚙️ Configuring mc alias '${ALIAS}'..."
RETRY_COUNT=0; MAX_RETRIES=10
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if mc alias set "$ALIAS" "http://localhost:${API_PORT}" "$TRAINING_ROOT_USER" "$TRAINING_ROOT_PASS" 2>&1; then
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ Failed to configure mc alias after $MAX_RETRIES attempts"; exit 1
    fi
    sleep 3
done

if mc ls "${ALIAS}/" 2>/dev/null | grep -q "$BUCKET"; then
    echo "   ℹ️  Bucket '${BUCKET}' already exists"
else
    echo "   Creating bucket '${BUCKET}'..."
    mc mb "${ALIAS}/${BUCKET}"
    echo "   ✅ Bucket '${BUCKET}' created"
fi

# NEVER add an ILM rule here. TASK-27 §13. vpt-training is the permanent training
# dataset, not a run artifact — an expiry rule would silently delete unrecoverable data
# (source captures already expire after 14 days elsewhere).

echo "⚙️ Setting quota (50 GiB)..."
mc quota set "${ALIAS}/${BUCKET}" --size 50GiB

# --- Scoped IAM users: never hand out the root key to app code ---
gen_secret() { openssl rand -base64 24 | tr -d '/+=' | head -c 32; }

RW_POLICY_JSON=$(mktemp)
cat > "$RW_POLICY_JSON" << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::${BUCKET}", "arn:aws:s3:::${BUCKET}/*"]
    }
  ]
}
EOF
mc admin policy create "$ALIAS" "$RW_POLICY_NAME" "$RW_POLICY_JSON" 2>&1 | grep -v "already exists" || true
rm -f "$RW_POLICY_JSON"

if mc admin user info "$ALIAS" "$RW_USER" >/dev/null 2>&1; then
    echo "   ℹ️  IAM user '${RW_USER}' already exists, keeping its secret"
    RW_SECRET="(unchanged — see ${ENV_FILE})"
else
    RW_SECRET="$(gen_secret)"
    mc admin user add "$ALIAS" "$RW_USER" "$RW_SECRET"
    mc admin policy attach "$ALIAS" "$RW_POLICY_NAME" --user "$RW_USER"
    echo "MINIO_TRAINING_RW_ACCESS_KEY=$RW_USER" | $SUDO tee -a "$ENV_FILE" > /dev/null
    echo "MINIO_TRAINING_RW_SECRET_KEY=$RW_SECRET" | $SUDO tee -a "$ENV_FILE" > /dev/null
fi

$SUDO chmod 600 "$ENV_FILE"

echo ""
echo "🔍 Verifying..."
mc ls "${ALIAS}/${BUCKET}" || { echo "❌ Bucket not listable"; exit 1; }
mc ilm rule ls "${ALIAS}/${BUCKET}" 2>&1 || echo "   (no ILM rules — expected)"
mc quota info "${ALIAS}/${BUCKET}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ${SERVICE_NAME} installed"
echo "   API:      http://<this-host>:${API_PORT}"
echo "   Console:  http://<this-host>:${CONSOLE_PORT}"
echo "   Bucket:   ${BUCKET} (50 GiB quota, no ILM rule)"
echo "   Credentials (root + the scoped read-write user) are in ${ENV_FILE} (mode 600)."
echo "   Read-write key name for app .env (MINIO_TRAINING_ACCESS_KEY/SECRET_KEY): ${RW_USER}"
echo "   Key VALUES are never printed to logs beyond this run — read them from ${ENV_FILE}."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
