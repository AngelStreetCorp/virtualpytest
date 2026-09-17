#!/bin/bash
# =============================================================================
# VirtualPyTest - Android Emulator Runner Setup Script
# =============================================================================
# Sets up Android SDK + emulator on a Debian/Ubuntu VM so it can run as a
# runner_android_* host with ADB pointing to the local emulator.
#
# Run AFTER install_runner.sh (which installs vpt-host.service).
#
# Usage (on the VM, as <user> with sudo):
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

# avdmanager leaves hw.cpu.ncore at the device profile's default — 1 for pixel_6 and the
# tablet profiles — and vm.heapSize at 228M. A one-core guest boots in ~5 min on an idle
# node, but on a loaded node (45-70% steal seen 2026-09-16) it sat 90 min in the boot
# animation, zygote verifying bytecode at 25-44 bytecodes/s, and SystemUI ANRs on every
# start. 4 cores / 576M is the TV host's known-good (docs/agent/devices/EMULATOR.md,
# "Sizing"); the same AVDs then booted in 45 s (tablet) and 2 min (mobile).
AVD_HOME_DIR="$(getent passwd "$SERVICE_USER" | cut -d: -f6)/.android/avd"
AVD_CONFIG="$AVD_HOME_DIR/$AVD_NAME.avd/config.ini"
if [ -f "$AVD_CONFIG" ]; then
  for kv in "hw.cpu.ncore = 4" "vm.heapSize = 576M"; do
    key="${kv%% =*}"
    if grep -q "^$key = " "$AVD_CONFIG"; then
      sudo -u $SERVICE_USER sed -i "s|^$key = .*|$kv|" "$AVD_CONFIG"
    else
      echo "$kv" | sudo -u $SERVICE_USER tee -a "$AVD_CONFIG" > /dev/null
    fi
  done
  echo "   ✅ $AVD_CONFIG: $(grep -E '^(hw.cpu.ncore|vm.heapSize) = ' "$AVD_CONFIG" | tr '\n' ' ')"
else
  echo "   ⚠️  $AVD_CONFIG not found — set hw.cpu.ncore = 4 and vm.heapSize = 576M by hand"
fi

# --- Step 5: Install emulator systemd service ---
echo ""
echo "🔧 [Step 5] Installing vpt-emulator.service..."

sudo tee /etc/systemd/system/vpt-emulator.service > /dev/null <<EOF
[Unit]
Description=VirtualPyTest Android Emulator ($AVD_NAME)
# vpt-vnc owns X display :1 (the hidden Qt window needs an X server); vpt-pulse is the
# PulseAudio daemon the emulator plays into (installed by enable_emulator_audio.sh).
After=network.target vpt-host.service vpt-vnc.service vpt-pulse.service
Wants=network.target vpt-vnc.service vpt-pulse.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=ANDROID_HOME=$ANDROID_HOME
Environment=PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=DISPLAY=:1
Environment=XAUTHORITY=/var/lib/$SERVICE_USER/.Xauthority
Environment=PULSE_SERVER=unix:/run/vpt-pulse/native
ExecStartPre=$ANDROID_HOME/platform-tools/adb start-server
# Audio: the emulator's OWN sound reaches the host's PulseAudio, where run_ffmpeg.sh's
# imagefile grabber records it (DEVICEn_VIDEO_AUDIO=default). Two things make it work,
# both found on labox-mobile 2026-09-16 with emulator 36.4.10 after two failed attempts:
#   * `-qt-hide-window`, NOT `-no-window`. `-no-window` makes the launcher exec
#     qemu-system-x86_64-headless, and that build has no PulseAudio client at all (no
#     libpulse.so.0 and no pa_* symbol in `strings`): `-audio pa` prints "Failed to
#     initialize PA context" without ever loading libpulse, and `-audio alsa` is accepted
#     but opens no /dev/snd fd — the guest plays, the samples stop in QEMU. The Qt build
#     dlopens the system libpulse and works; -qt-hide-window keeps its window off-screen,
#     and DISPLAY/XAUTHORITY above point it at vpt-vnc's :1.
#   * PULSE_SERVER set explicitly. The launcher exports XDG_RUNTIME_DIR=/tmp, so libpulse
#     looks for /tmp/pulse/native and gives up ("XDG_RUNTIME_DIR (/tmp) is not owned by
#     us ... Connection refused"). The target is vpt-pulse.service's own socket: a daemon
#     we run (enable_emulator_audio.sh), not a per-login one — those come and go with
#     their sessions, depend on which HOME started them (vpt-vnc: /var/lib/vpt_user,
#     vpt-stream: /home/vpt_user) and race for TCP 4713. QEMU's pa backend never
#     reconnects, so vpt-emulator-audio.timer restarts the emulator if it drops off.
# Verified: a 1 kHz tinyplay tone in the guest measured -25 dB on the host's sink monitor
# (-91 dB baseline). Cold boot took ~8 min with this config on a loaded host, against
# ~5 min with -no-window -no-audio.
ExecStart=$ANDROID_HOME/emulator/emulator \
  -avd $AVD_NAME \
  -qt-hide-window \
  -audio pa \
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
# vpt-pulse.service + the audio watchdog timer; the unit above is already in its final
# shape, so the in-place patch inside is a no-op here.
sudo bash "$(dirname "$0")/enable_emulator_audio.sh" --no-restart
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
  # The emulator plays into the host's PulseAudio (-audio pa above); `default` makes the
  # imagefile grabber record it, so the device gets a real audio track and audio-loss
  # detection instead of N/A.
  if grep -q "^DEVICE1_VIDEO_AUDIO=" "$ENV_FILE"; then
    sudo -u $SERVICE_USER sed -i 's/^DEVICE1_VIDEO_AUDIO=.*/DEVICE1_VIDEO_AUDIO=default/' "$ENV_FILE"
  else
    echo "DEVICE1_VIDEO_AUDIO=default" | sudo -u $SERVICE_USER tee -a "$ENV_FILE" > /dev/null
  fi
  sudo systemctl restart vpt-host.service
  sudo systemctl try-restart vpt-stream.service 2>/dev/null || true
  echo "   ✅ .env updated (ADB + DEVICE1_VIDEO_AUDIO=default), vpt-host restarted"
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
