#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="/opt/virtualpytest"

if [ -f "$SCRIPT_DIR/../shared/bootstrap.sh" ]; then
    source "$SCRIPT_DIR/../shared/bootstrap.sh"
else
    echo "❌ Bootstrap script not found"
    exit 1
fi

echo "🔧 Installing backend_host (Linux)..."

setup_for_code_installer "$SOURCE_ROOT"

source "$SCRIPT_DIR/common_vars.sh"

# Detect host type from .env (if already configured) for runner-aware installation
HOST_TYPE_FROM_ENV=""
if [ -f "$ENV_FILE" ]; then
    HOST_TYPE_FROM_ENV=$(grep -E '^HOST_TYPE=' "$ENV_FILE" | cut -d= -f2 | tr -d '[:space:]' || true)
fi
HOST_TYPE_FROM_ENV="${HOST_TYPE_FROM_ENV:-host_vnc}"

IS_RUNNER=0
if [[ "$HOST_TYPE_FROM_ENV" == runner_* ]]; then
    IS_RUNNER=1
    echo ""
    echo "🏃 Runner host detected (HOST_TYPE=$HOST_TYPE_FROM_ENV) — skipping VNC/stream services"
fi

cd "$PROJECT_ROOT"

if [ ! -f "README.md" ] || [ ! -d "backend_host" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Expected: $PROJECT_ROOT"
    exit 1
fi

ensure_executable() {
    local target="$1"

    if [ ! -e "$target" ]; then
        return 0
    fi

    if chmod +x "$target" 2>/dev/null; then
        return 0
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo chmod +x "$target" 2>/dev/null || true
    fi
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "👤 STEP 1: Service user ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ vpt_user service account exists and project is ready"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 STEP 2: Installing system dependencies..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "$PROJECT_ROOT/setup/local/linux/shared/install_requirements.sh" ]; then
    # Ensure the script is executable
    ensure_executable "$PROJECT_ROOT/setup/local/linux/shared/install_requirements.sh"
    "$PROJECT_ROOT/setup/local/linux/shared/install_requirements.sh"
else
    echo "❌ Shared requirements script not found at: $PROJECT_ROOT/setup/local/linux/shared/install_requirements.sh"
    exit 1
fi

# Ensure scripts are executable
ensure_executable "./setup/local/linux/backend_host/setup_ram_hot_storage.sh"
ensure_executable "./setup/local/linux/backend_host/install_service.sh"

echo "🎥 Installing host-specific packages..."

apt_noninteractive() {
    sudo DEBIAN_FRONTEND=noninteractive apt "$@"
}

apt_get_noninteractive() {
    sudo DEBIAN_FRONTEND=noninteractive apt-get "$@"
}

apt_noninteractive update -qq || { echo "❌ Failed to update package list"; exit 1; }

if [ $IS_RUNNER -eq 1 ]; then
    # Runner: minimal base packages only
    apt_noninteractive install -y --no-install-recommends \
        locales \
        nmap \
        dnsutils 2>&1 | grep -v "is already the newest" || true

    if [[ "$HOST_TYPE_FROM_ENV" == "runner_host" ]]; then
        echo "   → runner_host: installing Playwright + browser dependencies..."
        apt_noninteractive install -y --no-install-recommends \
            chromium chromium-driver \
            libnss3 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
            libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
            libasound2 libpango-1.0-0 libpangocairo-1.0-0 2>&1 | grep -v "is already the newest" || true
    elif [[ "$HOST_TYPE_FROM_ENV" == runner_android_* ]]; then
        echo "   → $HOST_TYPE_FROM_ENV: installing ADB..."
        apt_noninteractive install -y --no-install-recommends android-tools-adb 2>&1 | grep -v "is already the newest" || true
    fi
else
    # Full host: all packages
    apt_noninteractive install -y --no-install-recommends \
        ffmpeg                   \
        imagemagick              \
        tesseract-ocr            \
        tesseract-ocr-eng        \
        tesseract-ocr-fra        \
        tesseract-ocr-deu        \
        tesseract-ocr-ita        \
        xvfb                     \
        xfce4                    \
        xfce4-goodies            \
        bluez                    \
        dbus-x11                 \
        python3-dbus             \
        locales                  \
        novnc                    \
        websockify               \
        v4l-utils                \
        nmap                     \
        telnet                   \
        traceroute               \
        dnsutils                 \
        iperf3                   \
        network-manager          \
        wpasupplicant            \
        tigervnc-standalone-server \
        tigervnc-tools           \
        pulseaudio               \
        pulseaudio-utils         \
        alsa-utils               \
        pavucontrol              2>&1 | grep -v "is already the newest" || true

    if systemctl list-unit-files NetworkManager.service >/dev/null 2>&1; then
        sudo systemctl enable NetworkManager || true
        sudo systemctl restart NetworkManager || true
    fi

    # Generate en_US.UTF-8 locale for XFCE4 session
    sudo locale-gen en_US.UTF-8
    sudo update-locale LANG=en_US.UTF-8

    BROWSER_INSTALLED=0

    if apt_noninteractive install -y --no-install-recommends chromium 2>/dev/null; then
        echo "✅ Installed: chromium"
        BROWSER_INSTALLED=1
    fi

    if [ $BROWSER_INSTALLED -eq 0 ]; then
        if apt_noninteractive install -y --no-install-recommends chromium-browser 2>/dev/null; then
            echo "✅ Installed: chromium-browser"
            BROWSER_INSTALLED=1
        fi
    fi

    if apt_noninteractive install -y --no-install-recommends firefox-esr 2>/dev/null; then
        echo "✅ Installed: firefox-esr"
    else
        apt_noninteractive install -y --no-install-recommends firefox 2>/dev/null || true
        echo "Installed: firefox (fallback)"
    fi

    if [ $BROWSER_INSTALLED -eq 0 ]; then
        echo ""
        echo "⚠️  No Chromium-family browser installed"
        echo "    Playwright chromium target will have reduced functionality"
        echo ""
    fi

    apt_noninteractive install -y --no-install-recommends lirc 2>&1 | grep -v "is already the newest" || true
fi

# Install Ookla Speedtest CLI — NON-CRITICAL.
# Packagecloud builds lag behind Debian releases (e.g. no `trixie` build at
# the time of writing), so this step routinely fails on fresh OS versions.
# Network speed checks fall back gracefully when the CLI is missing, so
# every failure mode here is logged and ignored — never abort the install.
echo "🌐 Installing Ookla Speedtest CLI (non-critical)..."
if command -v speedtest &> /dev/null; then
    echo "✅ Ookla Speedtest CLI already installed"
else
    set +e
    echo "📥 Adding Ookla packagecloud repo (20s connect cap)..."
    # Hard caps so VMs with no egress to packagecloud.io don't stall for minutes:
    #   --connect-timeout 10  : give up per-IP after 10s (curl tries each A record)
    #   --max-time 20         : total curl budget 20s incl. body download
    #   timeout 30 …          : wraps curl+bash so the downloaded script can't
    #                           itself hang on its own apt-get update either
    timeout 30 bash -c "curl -fsSL --connect-timeout 10 --max-time 20 https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash" >/dev/null 2>&1
    REPO_RC=$?
    if [ $REPO_RC -ne 0 ]; then
        echo "⚠️  Packagecloud repo script failed (rc=$REPO_RC) — unreachable or no build for $(lsb_release -cs 2>/dev/null || echo this OS)"
    fi

    apt_get_noninteractive install -y speedtest >/dev/null 2>&1
    INSTALL_RC=$?
    set -e

    if command -v speedtest &> /dev/null; then
        echo "✅ Ookla Speedtest CLI installed"
    else
        # No build for this release: drop the repository the script added, or every later
        # `apt-get update` on this machine fails ("does not have a Release file").
        sudo rm -f /etc/apt/sources.list.d/ookla_speedtest-cli.list
        echo "⚠️  Skipping Ookla Speedtest CLI (apt rc=$INSTALL_RC) — continuing install"
        echo "    Network speed checks will use a fallback (this is non-critical)."
        echo "    To install manually later: https://www.speedtest.net/apps/cli"
    fi
fi

echo ""
echo "✅ System dependencies installation attempt finished"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🐍 STEP 3: Setting up Python environment..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "⚠️ Found incomplete venv directory, removing..."
        sudo rm -rf venv
    fi
    
    echo "Creating Python virtual environment as vpt_user..."
    sudo -u vpt_user python3 -m venv venv
    
    if [ ! -f "venv/bin/activate" ]; then
        echo "❌ Failed to create virtual environment"
        exit 1
    fi
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

echo "📦 Installing Python dependencies as vpt_user..."
sudo -u vpt_user bash -c "
    cd '$PROJECT_ROOT'
    source venv/bin/activate
    cd backend_host
    pip install --no-cache-dir -r requirements.txt || pip install -r requirements.txt
    cd ..
    "

if [ $IS_RUNNER -eq 0 ] || [[ "$HOST_TYPE_FROM_ENV" == "runner_host" ]]; then
    echo "📦 Installing Playwright system dependencies..."
    # Run playwright install-deps from within the activated virtual environment as root
    cd "$PROJECT_ROOT"
    source venv/bin/activate
    playwright install-deps || {
        echo "⚠️ playwright install-deps had non-zero exit — check if deps are really missing"
    }

    if [[ "$HOST_TYPE_FROM_ENV" == "runner_host" ]]; then
        echo "📦 Installing Playwright browsers..."
        sudo -u vpt_user "$PROJECT_ROOT/venv/bin/python" -m playwright install chromium 2>/dev/null || \
            sudo "$PROJECT_ROOT/venv/bin/python" -m playwright install-deps chromium
    fi
fi

echo "✅ Python dependencies and Playwright installed"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📡 STEP 4: Configuring LIRC for IR remote control..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    echo "   → Runner host — skipping LIRC configuration"
fi

LIRC_CONFIG="/etc/lirc/lirc_options.conf"

if [ -f "$LIRC_CONFIG" ]; then
    sudo cp "$LIRC_CONFIG" "$LIRC_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
fi

if [ $IS_RUNNER -eq 1 ]; then
    : # skip LIRC for runners
elif command -v lircd >/dev/null 2>&1; then
    PLUGIN_ARCH=$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || uname -m)
    sudo tee "$LIRC_CONFIG" > /dev/null << EOF
# LIRC configuration for VirtualPyTest IR remote control
[lircd]
nodaemon        = False
driver          = default
device          = auto
output          = /var/run/lirc/lircd
pidfile         = /var/run/lirc/lircd.pid
plugindir       = /usr/lib/${PLUGIN_ARCH}/lirc/plugins
permission      = 666
allow-simulate  = No
repeat-max      = 600

[lircmd]
uinput          = False
nodaemon        = False
EOF

    sudo systemctl enable lircd || true
    sudo systemctl restart lircd || true

    if sudo systemctl is-active --quiet lircd; then
        echo "✅ LIRC service is running"
    else
        echo "⚠️ LIRC service failed to start"
    fi
else
    echo "⚠️ lirc not installed — skipping IR configuration"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚙️  STEP 5: Setting up environment configuration..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -f "backend_host/src/.env" ]; then
    if [ -f "backend_host/src/.env.example" ]; then
        sudo -u vpt_user cp backend_host/src/.env.example backend_host/src/.env
        echo "✅ Created .env file from template"
    else
        echo "⚠️ No .env.example found — create .env manually"
    fi
else
    echo "✅ .env file already exists"
fi

# Load environment variables
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# Set default VNC password if not configured
HOST_VNC_PASSWORD="${HOST_VNC_PASSWORD:-admin1234}"
HOST_ACCOUNT_DISPLAY_NAME="${HOST_ACCOUNT_DISPLAY_NAME:-Host Service Account}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💾 STEP 6: Setting up storage directories..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    echo "   → Runner host — skipping stream storage setup"
else

# Auto-redirect /var/www/html/stream onto a dedicated /data partition when one
# exists. This is what makes install_host.sh portable across VMs/hosts with
# different disk layouts (sdb, nvme1n1, vdb, mmcblk1, ...). The rest of the
# stream pipeline (setup_permissions.sh, setup_ram_hot_storage.sh,
# ensure_hot_mounts.sh) is symlink-aware via realpath, so flipping this one
# symlink moves all cold capture I/O onto the data disk transparently.
STREAM_LINK="/var/www/html/stream"
DATA_MOUNT="/data"
if mountpoint -q "$DATA_MOUNT" 2>/dev/null; then
    DATA_TARGET="$DATA_MOUNT/stream"
    if [ -L "$STREAM_LINK" ] && [ "$(readlink -f "$STREAM_LINK")" = "$DATA_TARGET" ]; then
        echo "✅ $STREAM_LINK already symlinked to $DATA_TARGET"
    elif [ ! -e "$STREAM_LINK" ] || [ -L "$STREAM_LINK" ] || [ -z "$(sudo ls -A "$STREAM_LINK" 2>/dev/null)" ]; then
        echo "💽 Detected dedicated /data mount — redirecting stream tree to $DATA_TARGET"
        sudo mkdir -p "$DATA_TARGET"
        sudo chown vpt_user:vpt_user "$DATA_TARGET"
        sudo chmod 755 "$DATA_TARGET"
        sudo mkdir -p "$(dirname "$STREAM_LINK")"
        sudo rm -rf "$STREAM_LINK"
        sudo ln -s "$DATA_TARGET" "$STREAM_LINK"
        echo "✅ $STREAM_LINK → $DATA_TARGET"
    else
        echo "⚠️  $STREAM_LINK has data and isn't a symlink to $DATA_TARGET — leaving as-is"
        echo "    To move it onto $DATA_MOUNT, stop vpt-stream services and run:"
        echo "    sudo bash $PROJECT_ROOT/setup/local/linux/backend_host/redirect_stream_to_data.sh"
    fi
else
    echo "ℹ️  No separate /data mount detected — stream will live on root partition"
fi

ensure_executable "./setup/local/linux/backend_host/setup_permissions.sh"
ensure_executable "./setup/local/linux/backend_host/setup_ram_hot_storage.sh"
ensure_executable "$PROJECT_ROOT/backend_host/scripts/hot_cold_archiver.py"

# Set up directory structure and permissions (must run before storage setup)
if [ -f "./setup/local/linux/backend_host/setup_permissions.sh" ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo "./setup/local/linux/backend_host/setup_permissions.sh"
        echo "✅ Permissions setup completed"
    else
        echo "❌ setup_permissions.sh requires sudo access"
        exit 1
    fi
else
    echo "⚠️ setup_permissions.sh not found, skipping"
fi

if [ -f "./setup/local/linux/backend_host/setup_ram_hot_storage.sh" ]; then
    "./setup/local/linux/backend_host/setup_ram_hot_storage.sh"
    echo "✅ Storage setup completed"
else
    # Create directories in the specified data directory
    sudo mkdir -p "$HOST_DATA_DIR"
    for i in {1..4}; do
        for hour in {0..23}; do
            sudo mkdir -p "$HOST_DATA_DIR/capture$i/{captures,thumbnails,metadata,segments}/$hour"
        done
    done
    sudo chown -R vpt_user:vpt_user "$HOST_DATA_DIR"

    # Create symlink if custom directory is specified
    if [ "$HOST_DATA_DIR" != "/var/www/html/stream" ]; then
        echo "🔗 Creating symlink for custom data directory..."
        # Remove default directory if it exists
        sudo rm -rf /var/www/html/stream 2>/dev/null || true
        # Create symlink
        sudo ln -sf "$HOST_DATA_DIR" /var/www/html/stream
        echo "✅ Symlink created: /var/www/html/stream → $HOST_DATA_DIR"

        # Set environment variable for scripts that support it
        echo "VIRTUALPYTEST_INSTALL_PATH=\"$HOST_DATA_DIR\"" | sudo tee /etc/environment.d/virtualpytest.conf > /dev/null
        echo "✅ Environment variable set: VIRTUALPYTEST_INSTALL_PATH=$HOST_DATA_DIR"
    fi

    echo "✅ Storage directories created in $HOST_DATA_DIR"
fi

fi # end IS_RUNNER skip for storage

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🖥️  STEP 7: Installing systemd services..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    SERVICES=("host")
else
    ensure_executable "backend_host/scripts/run_ffmpeg.sh"
    ensure_executable "backend_host/scripts/capture_monitor.py"
    ensure_executable "backend_host/scripts/hot_cold_archiver.py"
    ensure_executable "backend_host/scripts/transcript_accumulator.py"
    ensure_executable "backend_host/scripts/kpi_executor.py"
    SERVICES=("host" "stream" "monitor" "archiver" "transcript" "kpi" "vnc" "websockify")
fi

# Optional feature services (features/<name>/backend_host/services/*.service, see
# docs/technical/FEATURES.md). Only folders present on disk are considered — a disabled
# feature is not deployed at all — and DISABLED_FEATURES is honoured for local installs.
if [ $IS_RUNNER -eq 0 ]; then
    for feature_unit in ./features/*/backend_host/services/*.service; do
        [ -f "$feature_unit" ] || continue
        feature_name="$(basename "$(dirname "$(dirname "$(dirname "$feature_unit")")")")"
        [ -f "./features/$feature_name/manifest.json" ] || continue
        case ",${DISABLED_FEATURES:-}," in *",${feature_name},"*) continue ;; esac
        unit_name="$(basename "$feature_unit" .service)"
        case "$unit_name" in *@) continue ;; esac   # templated units are enabled per-instance by hand
        SERVICES+=("$unit_name")
    done
fi

for service in "${SERVICES[@]}"; do
    echo "📦 Installing $service service..."
    if "./setup/local/linux/backend_host/install_service.sh" "$service"; then
        echo "✅ $service service installed"
    else
        echo "❌ Failed to install $service service"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🗒️  STEP 7b: Configuring journald (volatile / RAM)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    echo "   → Runner host — keeping default (persistent) journald"
else
    # Capture hosts: journal in RAM (/run/log/journal), NOT on the SD card.
    # Rationale (docs/agent/infra/HOST_SERVICE.md §8): on the RPi capture nodes the
    # journal lived on the SD card, so every log write contended with the live
    # 5fps capture I/O and wore the card. Volatile removes both. Trade-off:
    # logs do NOT survive reboot — accepted fleet-wide, incl. the WiFi-watchdog
    # Pis (watchdog has been stable since deploy). RuntimeMaxUse bounds the
    # in-RAM window predictably; combined with the trimmed log volume this
    # keeps a useful multi-hour/day per-boot window.
    # A drop-in is used so it overrides any hand-edited journald.conf (e.g. a
    # stale duplicate Storage= line) and survives package updates.
    sudo mkdir -p /etc/systemd/journald.conf.d
    sudo tee /etc/systemd/journald.conf.d/vpt.conf > /dev/null << 'EOF'
# Managed by setup/local/linux/backend_host/install_host.sh — do not hand-edit.
# See docs/agent/infra/HOST_SERVICE.md §8 (Logging & On-Demand Verbosity).
[Journal]
Storage=volatile
RuntimeMaxUse=300M
EOF
    if sudo systemctl restart systemd-journald; then
        echo "✅ journald set to volatile (RAM, RuntimeMaxUse=300M)"
    else
        echo "⚠️  journald restart failed; drop-in written, applies on next boot"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🖥️  STEP 8: Configuring VNC server..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    echo "   → Runner host — skipping VNC configuration"
else

set +e

# Keep the desktop session label neutral for XFCE/VNC surfaces.
if id "vpt_user" >/dev/null 2>&1; then
    sudo usermod -c "$HOST_ACCOUNT_DISPLAY_NAME" vpt_user 2>/dev/null || true
fi

pkill -f "Xvnc.*:1" 2>/dev/null || true
tigervncserver -kill :1 2>/dev/null || true
rm -f /tmp/.X1-lock 2>/dev/null || true
rm -f /tmp/.X11-unix/X1 2>/dev/null || true

VNC_HOME="/var/lib/vpt_user"
sudo mkdir -p "$VNC_HOME/.vnc"
sudo mkdir -p "$VNC_HOME/.config" "$VNC_HOME/.config/xfce4"
sudo chown -R vpt_user:vpt_user "$VNC_HOME/.config"

# Clear any stale VNC pid files to avoid startup warnings
sudo rm -f "$VNC_HOME/.vnc/"*.pid 2>/dev/null || true

# Create VNC password file (vncpasswd from tigervnc-tools)
echo "$HOST_VNC_PASSWORD" | vncpasswd -f | sudo tee "$VNC_HOME/.vnc/passwd" > /dev/null
sudo chmod 600 "$VNC_HOME/.vnc/passwd"
sudo chown -R vpt_user:vpt_user "$VNC_HOME/.vnc"
echo "✅ VNC password set to: $HOST_VNC_PASSWORD"

sudo mkdir -p /usr/share/xsessions
sudo tee /usr/share/xsessions/xfce4.desktop > /dev/null << 'EOF'
[Desktop Entry]
Name=Xfce Session
Comment=Use this session to run Xfce as your desktop environment
Exec=startxfce4
Icon=
Type=Application
DesktopNames=XFCE
EOF

sudo tee "$VNC_HOME/.vnc/xstartup" > /dev/null << 'EOF'
#!/bin/sh
export HOME=/var/lib/vpt_user
# Allow all local users to connect to X display (without this, x11grab depends
# entirely on .Xauthority cookie matching per-process and can fail with
# "Authorization required, but no authorization protocol specified" — see
# docs/agent/devices/STREAM.md)
xhost +local: 2>/dev/null || true
xrdb "$HOME/.Xresources" 2>/dev/null || true
xsetroot -solid grey
export XKL_XMODMAP_DISABLE=1
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export XDG_CONFIG_HOME="${HOME}/.config"
export PULSE_SERVER=tcp:127.0.0.1:4713
# Start PulseAudio for audio capture in FFmpeg
pulseaudio --start --log-target=syslog 2>/dev/null || true
exec /usr/bin/startxfce4
EOF
sudo chmod +x "$VNC_HOME/.vnc/xstartup"

sudo tee "$VNC_HOME/.vnc/config" > /dev/null << 'EOF'
session=xfce4
geometry=1280x720
localhost=no
alwaysshared
EOF

sudo chown -R vpt_user:vpt_user "$VNC_HOME/.vnc"

# Configure PulseAudio for VNC audio forwarding
echo "🔊 Configuring PulseAudio for VNC..."
# Configure PulseAudio to accept anonymous connections (idempotent: skip if already present).
# Only module-native-protocol-tcp is added here — module-native-protocol-unix is already
# loaded unconditionally by the stock /etc/pulse/default.pa, and loading it a second time
# (whether from a re-run of this script or, previously, unconditionally every run) crashes
# pulseaudio with a pa_strlist_remove assertion on the redundant module load.
if ! sudo grep -q "module-native-protocol-tcp auth-anonymous=1" /etc/pulse/default.pa; then
  echo 'load-module module-native-protocol-tcp auth-anonymous=1 listen=0.0.0.0' | sudo tee -a /etc/pulse/default.pa > /dev/null
fi

# Start PulseAudio
sudo pulseaudio --start --log-target=syslog 2>/dev/null || true

echo "✅ PulseAudio configured for VNC audio"

# Create TigerVNC config directory and copy xstartup (modern location)
sudo mkdir -p "$VNC_HOME/.config/tigervnc"
sudo cp "$VNC_HOME/.vnc/xstartup" "$VNC_HOME/.config/tigervnc/xstartup"
sudo chown vpt_user:vpt_user "$VNC_HOME/.config/tigervnc/xstartup"
sudo chmod +x "$VNC_HOME/.config/tigervnc/xstartup"

# Copy custom vnc_lite.html with auto-path detection
VNC_LITE_TEMPLATE="$PROJECT_ROOT/backend_host/config/services/linux/vnc.lite.example"
if [[ -f "$VNC_LITE_TEMPLATE" ]]; then
    sudo cp "$VNC_LITE_TEMPLATE" /usr/share/novnc/vnc_lite.html
    echo "✅ Installed custom vnc_lite.html with auto-path detection"
fi

NOVNC_FRAME_PATCH="$PROJECT_ROOT/backend_host/scripts/patch_novnc_close_frame.sh"
if [[ -f "$NOVNC_FRAME_PATCH" ]]; then
    echo "Patching noVNC VideoDecoder to close VideoFrames..."
    sudo bash "$NOVNC_FRAME_PATCH" "/usr/share/novnc" || true
else
    echo "⚠️  Missing patch script: $NOVNC_FRAME_PATCH"
fi

echo "✅ VNC server configured"
echo "ℹ️  VNC desktop terminal is disabled by default (vpt_user shell=/bin/false)."
echo "    To enable an interactive terminal in take-control: sudo usermod -s /bin/bash vpt_user"
set -e

fi # end IS_RUNNER skip for VNC

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 STEP 9: Configuring sudo permissions..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sudo tee /etc/sudoers.d/virtualpytest > /dev/null << EOF
vpt_user ALL=(root) NOPASSWD: /bin/systemctl show stream *, /usr/bin/systemctl show stream *
vpt_user ALL=(root) NOPASSWD: /bin/systemctl status stream*, /usr/bin/systemctl status stream*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl start stream*, /usr/bin/systemctl start stream*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl stop stream*, /usr/bin/systemctl stop stream*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart stream*, /usr/bin/systemctl restart stream*
# Dashboard per-service controls + autofix + restart-vpt-host-service:
# start/stop/restart any vpt-* unit
# (vpt-stream/monitor/archiver/kpi/vnc/websockify/transcript/subtitle/host/...).
vpt_user ALL=(root) NOPASSWD: /bin/systemctl start vpt-*, /usr/bin/systemctl start vpt-*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl stop vpt-*, /usr/bin/systemctl stop vpt-*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*
vpt_user ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot
vpt_user ALL=(root) NOPASSWD: /usr/bin/fuser
vpt_user ALL=(root) NOPASSWD: /usr/bin/pkill
vpt_user ALL=(root) NOPASSWD: /usr/bin/kill
# BLE remote control — start.sh/resume.sh need root for btmgmt, bluetoothctl,
# systemd-run, hciconfig, and UART driver unbind/rebind.
vpt_user ALL=(root) NOPASSWD: SETENV: $PROJECT_ROOT/backend_host/src/controllers/remote/bluetooth/start.sh
vpt_user ALL=(root) NOPASSWD: SETENV: $PROJECT_ROOT/backend_host/src/controllers/remote/bluetooth/resume.sh
vpt_user ALL=(root) NOPASSWD: /usr/bin/journalctl -u hid-remote-*.service *, /usr/bin/journalctl -u hid-agent-*.service *, /usr/bin/journalctl -u vpt-ble-remote@*.service *
vpt_user ALL=(root) NOPASSWD: /usr/bin/cat /var/lib/bluetooth/*/*/info
EOF
sudo chmod 440 /etc/sudoers.d/virtualpytest

# OPT-IN: "Run Command on Hosts" admin feature. Installing this drop-in makes
# vpt_user root-equivalent (NOPASSWD: ALL) so admin-authored maintenance
# scripts can sudo. OFF by default — set VPT_ENABLE_RUN_COMMAND=1 to enable.
# Disable later with: sudo rm /etc/sudoers.d/run-command
RUN_COMMAND_SUDOERS="$PROJECT_ROOT/setup/local/linux/backend_host/sudoers.d/run-command"
if [ "${VPT_ENABLE_RUN_COMMAND:-0}" = "1" ]; then
    if [ -f "$RUN_COMMAND_SUDOERS" ]; then
        sudo install -o root -g root -m 0440 "$RUN_COMMAND_SUDOERS" /etc/sudoers.d/run-command
        if sudo visudo -cf /etc/sudoers.d/run-command >/dev/null; then
            echo "🔓 VPT_ENABLE_RUN_COMMAND=1 — installed /etc/sudoers.d/run-command (vpt_user is now root-equivalent)"
        else
            sudo rm -f /etc/sudoers.d/run-command
            echo "❌ /etc/sudoers.d/run-command failed visudo validation — NOT installed"
        fi
    else
        echo "⚠️  VPT_ENABLE_RUN_COMMAND=1 but $RUN_COMMAND_SUDOERS is missing — skipped"
    fi
else
    echo "ℹ️  Run-Command admin feature sudoers NOT installed (set VPT_ENABLE_RUN_COMMAND=1 to enable)"
fi

# BLE remote: vpt_user needs bluetooth group for bluetoothctl D-Bus access
if getent group bluetooth >/dev/null 2>&1; then
    sudo usermod -aG bluetooth vpt_user 2>/dev/null || true
fi

# BLE remote: build + install the patched bluetoothd that persists external-app
# CCCD subscriptions. Idempotent — skips if /opt/bluez-cccpatch-v2/ is already
# populated and the systemd override points at it. Only runs when bluez is
# actually installed on this host (non-fatal if missing / build fails, so
# hosts that don't need the BLE stack don't block on this). See
# docs/agent/devices/BLUETOOTH.md § 6.7.4 and § 6.8.2.
if command -v bluetoothd >/dev/null 2>&1 || [ -x /usr/libexec/bluetooth/bluetoothd ]; then
    ensure_executable "./setup/local/linux/backend_host/install_patched_bluetoothd.sh"
    if sudo ./setup/local/linux/backend_host/install_patched_bluetoothd.sh; then
        echo "✅ Patched bluetoothd installed"
    else
        echo "⚠️  Patched bluetoothd install failed — BLE remote will still work for"
        echo "    fresh pairs, but STB reboots will require a re-pair until fixed."
        echo "    Run manually: sudo ./setup/local/linux/backend_host/install_patched_bluetoothd.sh"
    fi
else
    echo "ℹ️  bluez not installed — skipping patched-bluetoothd install (BLE remote disabled)"
fi

# BLE remote: install ble-remote.service so resume.sh auto-runs on boot,
# restoring the STB bond after a Pi reboot without requiring a re-pair.
# Idempotent — install_service.sh handles re-install. See § 6.7.11.
if command -v bluetoothd >/dev/null 2>&1 || [ -x /usr/libexec/bluetooth/bluetoothd ]; then
    # Narrow-scoped NOPASSWD for the two BLE scripts (start.sh / resume.sh) +
    # journalctl + bond-info reads. Without this drop-in, the frontend
    # "Start Pairing" button hits `sudo: a password is required`.
    BLE_REMOTE_SUDOERS="$PROJECT_ROOT/setup/local/linux/backend_host/sudoers.d/ble-remote"
    if [ -f "$BLE_REMOTE_SUDOERS" ]; then
        sudo install -o root -g root -m 0440 "$BLE_REMOTE_SUDOERS" /etc/sudoers.d/ble-remote
        if sudo visudo -cf /etc/sudoers.d/ble-remote >/dev/null; then
            echo "✅ /etc/sudoers.d/ble-remote installed (BLE pairing/resume sudo)"
        else
            sudo rm -f /etc/sudoers.d/ble-remote
            echo "❌ /etc/sudoers.d/ble-remote failed visudo validation — NOT installed"
        fi
    else
        echo "⚠️  $BLE_REMOTE_SUDOERS missing — BLE pairing will fail with sudo prompt"
    fi

    ensure_executable "./setup/local/linux/backend_host/install_service.sh"
    if sudo ./setup/local/linux/backend_host/install_service.sh ble-remote; then
        echo "✅ ble-remote.service installed (boot-time auto-resume)"
    else
        echo "⚠️  ble-remote.service install failed — BLE peripheral will NOT"
        echo "    auto-resume after Pi reboot. Run manually:"
        echo "    sudo ./setup/local/linux/backend_host/install_service.sh ble-remote"
    fi
fi

# Clean up legacy www-data sudoers if present
sudo rm -f /etc/sudoers.d/ffmpeg-www-data

echo "✅ Sudo permissions configured"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🖥️  STEP 10: Configuring XFCE4 startup..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $IS_RUNNER -eq 1 ]; then
    echo "   → Runner host — skipping XFCE4 configuration"
else

XINITRC_FILE="$HOME/.xinitrc"

if [ -f "$XINITRC_FILE" ]; then
    cp "$XINITRC_FILE" "$XINITRC_FILE.backup.$(date +%Y%m%d_%H%M%S)"
fi

cat > "$XINITRC_FILE" << 'EOF'
#!/bin/sh
xrdb "$HOME/.Xresources"
export XKL_XMODMAP_DISABLE=1
exec startxfce4
EOF

chmod +x "$XINITRC_FILE"
echo "✅ XFCE4 startup configured"

fi # end IS_RUNNER skip for XFCE4

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 INSTALLATION COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Service Status:"
printf "  %-25s %-40s\n" "Service" "Status"
printf "  %-25s %-40s\n" "─────────────────────────" "────────────────────────────────────────"

if [ $IS_RUNNER -eq 1 ]; then
    services_to_check=("vpt-host.service:Host API")
else
    services_to_check=(
        "vpt-host.service:Host API"
        "vpt-stream.service:FFmpeg Stream"
        "vpt-monitor.service:Capture Monitor"
        "vpt-archiver.service:Archiver"
        "vpt-transcript.service:Transcript"
        "vpt-kpi.service:KPI Executor"
        "vpt-vnc.service:VNC Server"
        "vpt-websockify.service:Websockify"
        "lircd.service:LIRC (IR Remote)"
    )
    # Optional feature services installed above (features/*/backend_host/services)
    for feature_unit in ./features/*/backend_host/services/*.service; do
        [ -f "$feature_unit" ] || continue
        unit_name="$(basename "$feature_unit" .service)"
        case "$unit_name" in *@) continue ;; esac
        feature_name="$(basename "$(dirname "$(dirname "$(dirname "$feature_unit")")")")"
        services_to_check+=("vpt-${unit_name}.service:${feature_name} (${unit_name})")
    done
fi

for service_entry in "${services_to_check[@]}"; do
    IFS=':' read -r service_name display_name <<< "$service_entry"
    
    if ! systemctl list-unit-files "$service_name" &>/dev/null 2>&1; then
        printf "  %-25s ⚪ Not installed\n" "$display_name"
        continue
    fi
    
    if systemctl is-active --quiet "$service_name" 2>/dev/null; then
        pid=$(systemctl show -p MainPID "$service_name" 2>/dev/null | cut -d= -f2)
        if [ "$pid" != "0" ] && [ -n "$pid" ]; then
            printf "  %-25s ✅ Running (PID $pid)\n" "$display_name"
        else
            printf "  %-25s ✅ Running\n" "$display_name"
        fi
    elif systemctl is-enabled --quiet "$service_name" 2>/dev/null; then
        printf "  %-25s ⚠️  Stopped (enabled)\n" "$display_name"
    else
        printf "  %-25s ⚪ Disabled\n" "$display_name"
    fi
done

echo ""
echo "📋 Configuration:"
echo "   Config File: $PROJECT_ROOT/backend_host/src/.env"
echo "   Host Type:   $HOST_TYPE_FROM_ENV"
if [ $IS_RUNNER -eq 0 ]; then
STORAGE_REAL=$(readlink -f /var/www/html/stream 2>/dev/null || echo "/var/www/html/stream")
if [ "$STORAGE_REAL" != "/var/www/html/stream" ]; then
    echo "   Storage: /var/www/html/stream → $STORAGE_REAL"
else
    echo "   Storage: /var/www/html/stream"
fi
echo "   Desktop Label: $HOST_ACCOUNT_DISPLAY_NAME"
fi
echo ""
echo "🌐 Access Points:"
echo "   API: http://localhost:6109"
if [ $IS_RUNNER -eq 0 ]; then
echo "   VNC: vnc://localhost:5901 (password: $HOST_VNC_PASSWORD)"
echo "   noVNC Web: http://localhost:6080/vnc_lite.html"
fi
echo ""
echo "📝 Next Steps:"
echo "   1. Edit backend_host/src/.env to configure your devices"
echo ""
