#!/bin/bash
# =============================================================================
# VirtualPyTest - Android Emulator Runner Setup Script
# =============================================================================
# Sets up Android SDK + emulator on a Debian/Ubuntu VM so it can run as a
# runner_android_* host with ADB pointing to the local emulator.
#
# Run AFTER install_runner.sh (which installs vpt-host.service).
#
# Usage (on the VM, as jndoye with sudo):
#   bash /opt/virtualpytest/setup/proxmox/vm/runner/install_android_emulator.sh \
#     --avd-type mobile
#
# AVD types:
#   mobile  — Pixel 6 (phone), 1080x2400, API 33
#   tablet  — Pixel Tablet, 2560x1600, API 33
#   tv      — Android TV 1080p, 1920x1080, API 36 (no x86_64 TV image exists below 36)
#
# The emulator runs with `-memory 3072`: that flag OVERRIDES hw.ramSize in the AVD's
# config.ini, and below 3 GB the guest ANRs on SystemUI constantly. `-no-snapshot` forces a
# cold boot — a restored snapshot is the top source of "the app is in a weird state" flakiness.
# Sizing and per-type AVD config: docs/get-started/emulators.md
#
# Requirements:
#   - VM must have nested virtualization / KVM enabled (CPU type = host on Proxmox)
#   - 12 GB RAM and a 40 GB disk. 8 GB RAM is NOT enough: the emulator process alone holds
#     7-8.5 GB resident, and one system image is 8.2 GB of the ~22 GB a working host uses.
#   - install_runner.sh already run for the appropriate runner_android_* type
# =============================================================================

set -e

AVD_TYPE="mobile"
PROJECT_DIR="/opt/virtualpytest"
SERVICE_USER="vpt_user"
ANDROID_HOME="/opt/android-sdk"
CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --avd-type) AVD_TYPE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "============================================================"
echo "📱 Android Emulator Setup"
echo "============================================================"
echo "   AVD Type:    $AVD_TYPE"
echo "   Android SDK: $ANDROID_HOME"
echo "   Service user: $SERVICE_USER"
echo "============================================================"

# Map AVD type to AVD config
case "$AVD_TYPE" in
  mobile)
    AVD_NAME="vpt_mobile"
    DEVICE_PROFILE="pixel_6"
    API_LEVEL="33"
    ABI="x86_64"
    SYSTEM_IMAGE="system-images;android-33;google_apis;x86_64"
    ;;
  tablet)
    AVD_NAME="vpt_tablet"
    DEVICE_PROFILE="pixel_tablet"
    API_LEVEL="33"
    ABI="x86_64"
    SYSTEM_IMAGE="system-images;android-33;google_apis;x86_64"
    ;;
  tv)
    # The TV UI comes from the `android-tv` tag — `google_apis_playstore` is a PHONE image and
    # yields a tv_1080p-shaped screen running the phone launcher. No x86_64 `android-tv` image
    # exists below API 36 (API <= 34 ships 32-bit x86 or arm64 only), hence 36 here.
    AVD_NAME="android_tv"
    DEVICE_PROFILE="tv_1080p"
    API_LEVEL="36"
    ABI="x86_64"
    SYSTEM_IMAGE="system-images;android-36;android-tv;x86_64"
    ;;
  *)
    echo "Unknown AVD type: $AVD_TYPE (use: mobile, tablet, tv)"
    exit 1
    ;;
esac

echo "   AVD Name:    $AVD_NAME"
echo "   Device:      $DEVICE_PROFILE  (API $API_LEVEL, $ABI)"

# --- Step 1: System dependencies ---
echo ""
echo "📦 [Step 1] Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y -q \
  openjdk-17-jdk \
  wget unzip \
  libgl1-mesa-glx libgles2-mesa \
  qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils \
  cpu-checker

echo "   → Checking KVM availability..."
if kvm-ok 2>/dev/null | grep -q "KVM acceleration can be used"; then
  echo "   ✅ KVM available — emulator will run with hardware acceleration"
else
  echo "   ⚠️  KVM not available — emulator will run slowly (software rendering)"
  echo "      On Proxmox: set CPU type to 'host' for this VM"
fi

# Add service user to kvm group (required for emulator KVM access)
if getent group kvm > /dev/null 2>&1; then
  sudo usermod -aG kvm $SERVICE_USER
  echo "   ✅ $SERVICE_USER added to kvm group"
fi
echo "   ✅ System dependencies installed"

# --- Step 2: Install Android SDK command-line tools ---
echo ""
echo "📱 [Step 2] Installing Android SDK..."

sudo mkdir -p "$ANDROID_HOME/cmdline-tools"
sudo chown -R $SERVICE_USER:$SERVICE_USER "$ANDROID_HOME"

if [ ! -f "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  echo "   → Downloading command-line tools..."
  sudo -u $SERVICE_USER wget -q "$CMDLINE_TOOLS_URL" -O /tmp/cmdline-tools.zip
  sudo -u $SERVICE_USER unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-extract
  sudo -u $SERVICE_USER mv /tmp/cmdline-tools-extract/cmdline-tools "$ANDROID_HOME/cmdline-tools/latest"
  sudo rm -f /tmp/cmdline-tools.zip
  sudo rm -rf /tmp/cmdline-tools-extract
  echo "   ✅ Command-line tools installed"
else
  echo "   ✅ Command-line tools already installed"
fi

# Set up environment for vpt_user
PROFILE_FILE="/home/$SERVICE_USER/.bashrc"
if ! grep -q "ANDROID_HOME" "$PROFILE_FILE" 2>/dev/null; then
  sudo -u $SERVICE_USER tee -a "$PROFILE_FILE" > /dev/null <<EOF

# Android SDK
export ANDROID_HOME=$ANDROID_HOME
export PATH=\$PATH:\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator
EOF
  echo "   ✅ Android SDK paths added to $PROFILE_FILE"
fi

export ANDROID_HOME
export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"

# --- Step 3: Install SDK packages ---
echo ""
echo "📦 [Step 3] Installing SDK packages (platform-tools, emulator, system image)..."
echo "   This may take several minutes..."

# Accept all licenses
yes | sudo -u $SERVICE_USER env ANDROID_HOME=$ANDROID_HOME \
  "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses > /dev/null 2>&1 || true

sudo -u $SERVICE_USER env ANDROID_HOME=$ANDROID_HOME \
  "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" \
  "platform-tools" \
  "emulator" \
  "$SYSTEM_IMAGE" \
  --verbose 2>&1 | grep -E "^(Downloading|Installing|done)" || true

echo "   ✅ SDK packages installed"

# --- Step 4: Create AVD ---
echo ""
echo "📱 [Step 4] Creating AVD: $AVD_NAME..."

if sudo -u $SERVICE_USER env ANDROID_HOME=$ANDROID_HOME \
    "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" list avd 2>/dev/null | grep -q "Name: $AVD_NAME"; then
  echo "   ✅ AVD '$AVD_NAME' already exists"
else
  echo "no" | sudo -u $SERVICE_USER env ANDROID_HOME=$ANDROID_HOME \
    "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd \
    --name "$AVD_NAME" \
    --package "$SYSTEM_IMAGE" \
    --device "$DEVICE_PROFILE" \
    --force 2>&1 | tail -5
  echo "   ✅ AVD '$AVD_NAME' created"
fi

# --- Step 5: Install emulator systemd service ---
echo ""
echo "🔧 [Step 5] Installing vpt-emulator.service..."

sudo tee /etc/systemd/system/vpt-emulator.service > /dev/null <<EOF
[Unit]
Description=VirtualPyTest Android Emulator ($AVD_NAME)
After=network.target vpt-host.service
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=ANDROID_HOME=$ANDROID_HOME
Environment=PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=DISPLAY=:0
ExecStartPre=$ANDROID_HOME/platform-tools/adb start-server
ExecStart=$ANDROID_HOME/emulator/emulator \
  -avd $AVD_NAME \
  -no-window \
  -no-audio \
  -no-boot-anim \
  -gpu swiftshader_indirect \
  -no-snapshot \
  -memory 3072 \
  -port 5554
ExecStartPost=/bin/sleep 30
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable vpt-emulator.service
sudo systemctl start vpt-emulator.service

echo "   ✅ vpt-emulator.service installed and started"

# --- Step 6: Wait for emulator + update .env ---
echo ""
echo "⏳ [Step 6] Waiting for emulator to boot (up to 120s)..."

BOOTED=false
for i in $(seq 1 24); do
  sleep 5
  STATUS=$(sudo -u $SERVICE_USER env ANDROID_HOME=$ANDROID_HOME \
    "$ANDROID_HOME/platform-tools/adb" -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  if [ "$STATUS" = "1" ]; then
    BOOTED=true
    echo "   ✅ Emulator booted! (took ~$((i * 5))s)"
    break
  fi
  echo "   → Waiting... ($((i * 5))s)"
done

if [ "$BOOTED" = false ]; then
  echo "   ⚠️  Emulator did not boot within 120s — check logs:"
  echo "      sudo journalctl -u vpt-emulator.service --no-pager -n 30"
fi

# Update .env to point ADB at the local emulator
ENV_FILE="$PROJECT_DIR/backend_host/src/.env"
if [ -f "$ENV_FILE" ]; then
  echo ""
  echo "⚙️  [Step 7] Updating .env to use local emulator (localhost:5554)..."
  if grep -q "DEVICE1_IP" "$ENV_FILE"; then
    sudo -u $SERVICE_USER sed -i 's/^DEVICE1_IP=.*/DEVICE1_IP=localhost/' "$ENV_FILE"
    sudo -u $SERVICE_USER sed -i 's/^DEVICE1_ADB_PORT=.*/DEVICE1_ADB_PORT=5554/' "$ENV_FILE"
  else
    sudo -u $SERVICE_USER tee -a "$ENV_FILE" > /dev/null <<EOF

# Android emulator ADB connection
DEVICE1_IP=localhost
DEVICE1_ADB_PORT=5554
EOF
  fi
  sudo systemctl restart vpt-host.service
  echo "   ✅ .env updated, vpt-host restarted"
fi

# --- Summary ---
echo ""
echo "============================================================"
echo "✅ Android emulator setup complete!"
echo "============================================================"
echo ""
echo "AVD Name:     $AVD_NAME"
echo "AVD Type:     $AVD_TYPE"
echo "ADB:          emulator-5554 (localhost:5554)"
echo ""
echo "Check emulator:"
echo "  sudo -u $SERVICE_USER $ANDROID_HOME/platform-tools/adb devices"
echo ""
echo "Service commands:"
echo "  sudo systemctl status vpt-emulator.service"
echo "  sudo journalctl -u vpt-emulator.service --no-pager -n 50"
echo "  sudo systemctl restart vpt-emulator.service"
echo "============================================================"
