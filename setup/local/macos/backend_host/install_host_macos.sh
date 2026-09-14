#!/bin/bash

# VirtualPyTest macOS Host Installation Script (Single Entry Point)
# Equivalent to setup/local/linux/backend_host/install_host.sh for macOS
# Creates native macOS services using launchd instead of systemd

set -e

# Script directory (must be set before sourcing common_vars.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common variables (includes logging, device parsing, launchd helpers)
source "$SCRIPT_DIR/common_vars.sh"

# Global variables
USER_INSTALL=false
INSTALL_ERROR=false

# Services to install (ramdisk first - other services depend on it)
SERVICES=(
    "ramdisk:VirtualPyTest RAM Disk Setup"
    "flask:VirtualPyTest Flask API Server"
    "stream:VirtualPyTest FFmpeg Stream Service"
    "monitor:VirtualPyTest Capture Monitor"
    "archiver:VirtualPyTest Hot/Cold Archiver"
    "transcript:VirtualPyTest Audio Transcript Service"
    "kpi:VirtualPyTest KPI Measurement Executor"
    "vnc:VirtualPyTest VNC Server"
    "websockify:VirtualPyTest WebSocket Proxy"
)

# Check if running on macOS
check_macos() {
    if [[ "$OSTYPE" != "darwin"* ]]; then
        log_error "This script is designed for macOS only"
        exit 1
    fi

    # Check macOS version (minimum 10.15 Catalina)
    MACOS_VERSION=$(sw_vers -productVersion | cut -d. -f1-2)
    if (( $(echo "$MACOS_VERSION < 10.15" | bc -l 2>/dev/null || echo "1") )); then
        log_error "macOS 10.15 (Catalina) or later required"
        exit 1
    fi

    log_info "Running on macOS $MACOS_VERSION"
}

# Installation requires sudo for system services and RAM disks
check_privileges() {
    log_info "VirtualPyTest macOS System Installation (requires sudo)"
}

# Create vpt_user service account if it doesn't exist
setup_vpt_user() {
    log_info "Checking for vpt_user service account..."
    
    # Check if vpt_user already exists
    if dscl . -read /Users/vpt_user &>/dev/null 2>&1; then
        log_success "vpt_user service account already exists"
        return 0
    fi
    
    # Create vpt_user using the dedicated script
    local create_user_script="$SCRIPT_DIR/../shared/create_vpt_user.sh"
    if [[ -f "$create_user_script" ]]; then
        log_info "Creating vpt_user service account..."
        chmod +x "$create_user_script"
        if sudo "$create_user_script"; then
            log_success "vpt_user service account created"
        else
            log_error "Failed to create vpt_user service account"
            return 1
        fi
    else
        log_warning "create_vpt_user.sh not found at $create_user_script"
        log_warning "Services will run as current user instead of vpt_user"
    fi
}

# Install Homebrew if not present
install_homebrew() {
    log_info "Checking Homebrew installation..."

    if ! command -v brew &> /dev/null; then
        log_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add Homebrew to PATH for this session
        if [[ -f ~/.zshrc ]]; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
        fi
        if [[ -f ~/.bashrc ]]; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.bashrc
        fi

        eval "$(/opt/homebrew/bin/brew shellenv)"
        log_success "Homebrew installed"
    else
        log_info "Homebrew already installed"
    fi

    # Update Homebrew as original user (Homebrew doesn't work as root)
    log_info "Updating Homebrew..."
    sudo -u "$SUDO_USER" brew update || log_warning "Homebrew update had warnings (non-critical)"
}

# Install macOS dependencies
install_dependencies() {
    log_info "Installing macOS dependencies..."

    # Function to check and install package
    check_and_install() {
        local package=$1
        local description=$2

        if sudo -u "$SUDO_USER" brew list "$package" &>/dev/null; then
            log_info "$description already installed"
        else
            log_info "Installing $description..."
            sudo -u "$SUDO_USER" brew install "$package"
        fi
    }

    # Check Python availability
    if command -v python3 &>/dev/null && python3 --version &>/dev/null; then
        local python_version=$(python3 --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        log_info "Python $python_version already available ($(which python3))"
    else
        log_info "Python not found, installing python@3.11..."
        brew install python@3.11
    fi

    # Install VNC and noVNC dependencies
    check_and_install "wget" "wget for downloading noVNC"
    check_and_install "ffmpeg" "FFmpeg"

    # Install Ookla Speedtest CLI
    log_info "Installing Ookla Speedtest CLI..."
    if ! command -v speedtest &> /dev/null; then
        log_info "Installing Ookla Speedtest CLI..."
        sudo -u "$SUDO_USER" brew tap teamookla/speedtest
        sudo -u "$SUDO_USER" brew install speedtest

        if command -v speedtest &> /dev/null; then
            log_success "Ookla Speedtest CLI installed"
        else
            log_warning "Failed to install Ookla Speedtest CLI"
        fi
    else
        log_info "Ookla Speedtest CLI already installed"
    fi

    log_success "Dependencies installed"
}

# Setup Python virtual environment
setup_python() {
    log_info "Setting up Python virtual environment..."

    # Check if virtual environment exists and is functional
    if [[ -d "$VENV_PATH" && -f "$VENV_PATH/bin/activate" && -f "$VENV_PATH/bin/python" ]]; then
        log_info "Virtual environment already exists and appears functional"

        # Quick check if key packages are installed
        if "$VENV_PATH/bin/python" -c "import flask, cv2, websockify" 2>/dev/null; then
            log_info "Key dependencies already installed, skipping Python setup"
            log_success "Python environment ready"
            return 0
        else
            log_info "Virtual environment exists but missing dependencies, updating..."
        fi
    else
        log_info "Creating Python virtual environment..."
        python3 -m venv "$VENV_PATH"
    fi

    # Activate virtual environment
    log_info "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"

    # Upgrade pip
    "$PIP_EXE" install --upgrade pip

    # Install Python dependencies
    log_info "Installing Python dependencies..."
    REQUIREMENTS_FILE="$BACKEND_HOST_PATH/requirements.txt"
    if [[ -f "$REQUIREMENTS_FILE" ]]; then
        "$PIP_EXE" install -r "$REQUIREMENTS_FILE"
    fi

    # Install additional macOS-specific packages
    "$PIP_EXE" install websockify pyobjc-framework-Quartz pyobjc-framework-ApplicationServices

    # Install Playwright
    log_info "Installing Playwright..."
    "$PIP_EXE" install playwright

    # Install Playwright browsers
    log_info "Installing Playwright browsers..."
    "$PYTHON_EXE" -m playwright install chromium firefox webkit
    "$PYTHON_EXE" -m playwright install-deps

    log_success "Python environment setup complete"
}

# Setup storage directories
setup_storage() {
    log_info "Setting up storage directories..."
    log_info "Installation path: $INSTALL_PATH"

    # Parse devices from .env
    parse_devices_from_env "$ENV_FILE"

    if [[ "$USER_INSTALL" == "true" ]]; then
        log_info "User installation - no administrator privileges required"
        MKDIR_CMD="mkdir -p"
    else
        log_info "System installation - administrator privileges required for system directories"
        MKDIR_CMD="sudo mkdir -p"
    fi

    # Create main directories
    $MKDIR_CMD "$INSTALL_PATH"
    $MKDIR_CMD "$LOGS_PATH"

    # Create device directories - ONLY for configured devices
    log_info "Creating storage for ${#DEVICES[@]} configured device(s): ${DEVICES[*]}"
    for device in "${DEVICES[@]}"; do
        DEVICE_PATH="$INSTALL_PATH/$device"
        $MKDIR_CMD "$DEVICE_PATH"

        # Create cold storage subdirectories
        SUBDIRS=("captures" "thumbnails" "segments" "metadata" "audio")
        for subdir in "${SUBDIRS[@]}"; do
            $MKDIR_CMD "$DEVICE_PATH/$subdir"

            # Create hour folders (0-23)
            for hour in {0..23}; do
                $MKDIR_CMD "$DEVICE_PATH/$subdir/$hour"
            done
        done
    done

    # Set permissions (only for system install)
    if [[ "$USER_INSTALL" == "false" ]]; then
        sudo chown -R $(whoami) "$INSTALL_PATH"
    fi

    # Setup RAM disk (macOS version) - only for system installs
    if [[ "$USER_INSTALL" == "false" ]]; then
        setup_ram_disk
    else
        log_info "User install - skipping RAM disk setup, using cold storage only"
        for device in "${DEVICES[@]}"; do
            mkdir -p "$INSTALL_PATH/$device"
        done
    fi

    log_success "Storage directories created"
}

# Setup RAM disk for hot storage (macOS)
setup_ram_disk() {
    log_info "Setting up RAM disk for hot storage..."

    # Calculate RAM usage
    local ram_per_device=128
    local total_ram=$((${#DEVICES[@]} * ram_per_device))
    log_info "RAM allocation: ${#DEVICES[@]} device(s) × ${ram_per_device}MB = ${total_ram}MB total"

    # Create device-specific hot storage in RAM
    for device in "${DEVICES[@]}"; do
        HOT_DIR="$INSTALL_PATH/$device/hot"
        MOUNT_POINT="/Volumes/VirtualPyTest_${device}_Hot"

        # Check if RAM disk is already properly set up and functional
        if [[ -L "$HOT_DIR" && -d "$(readlink "$HOT_DIR")" ]]; then
            LINK_TARGET=$(readlink "$HOT_DIR")
            if [[ "$LINK_TARGET" == "$MOUNT_POINT" ]]; then
                if mount | grep -q "$MOUNT_POINT"; then
                    MOUNT_INFO=$(mount | grep "$MOUNT_POINT")
                    if echo "$MOUNT_INFO" | grep -q "/dev/disk.*"; then
                        if [[ -d "$MOUNT_POINT/segments" && -d "$MOUNT_POINT/captures" && -d "$MOUNT_POINT/thumbnails" ]]; then
                            log_info "RAM disk already exists and is functional for $device, reusing..."
                            continue
                        else
                            log_info "RAM disk exists but missing directories for $device, recreating..."
                        fi
                    fi
                fi
            fi
        fi

        # Clean up any existing mount point if we're recreating
        if mount | grep -q "$MOUNT_POINT"; then
            log_info "Cleaning up existing RAM disk for $device..."
            sudo umount "$MOUNT_POINT" 2>/dev/null || sudo umount -f "$MOUNT_POINT" 2>/dev/null || true
            sudo rmdir "$MOUNT_POINT" 2>/dev/null || true
        fi

        # Clean up broken symlink if it exists
        if [[ -L "$HOT_DIR" && ! -d "$(readlink "$HOT_DIR")" ]]; then
            rm -f "$HOT_DIR"
        fi

        # Create RAM disk (128MB per device)
        RAM_DISK_SIZE_MB=128
        RAM_DISK_SECTORS=$((RAM_DISK_SIZE_MB * 1024 * 1024 / 512))

        # Create RAM disk device (requires sudo)
        log_info "Creating RAM disk device ($RAM_DISK_SIZE_MB MB)..."
        RAM_DISK_DEVICE_RAW=$(sudo hdiutil attach -nomount ram://$RAM_DISK_SECTORS 2>&1)
        if [[ $? -ne 0 || -z "$RAM_DISK_DEVICE_RAW" ]]; then
            log_error "Failed to create RAM disk device for $device"
            log_error "hdiutil output: $RAM_DISK_DEVICE_RAW"
            continue
        fi
        
        # CRITICAL: hdiutil outputs device path with trailing whitespace - must trim!
        RAM_DISK_DEVICE=$(echo "$RAM_DISK_DEVICE_RAW" | tr -d '[:space:]')
        
        if [[ ! -e "$RAM_DISK_DEVICE" ]]; then
            log_error "RAM disk device not found after creation: '$RAM_DISK_DEVICE'"
            continue
        fi

        log_info "RAM disk device created: $RAM_DISK_DEVICE"

        # Format as HFS+ (macOS native)
        log_info "Formatting RAM disk for $device..."
        if ! sudo diskutil eraseVolume HFS+ "VirtualPyTest_${device}_Hot" "$RAM_DISK_DEVICE" >/dev/null 2>&1; then
            log_warning "diskutil eraseVolume failed, trying newfs_hfs..."
            if ! sudo newfs_hfs -v "VirtualPyTest_${device}_Hot" "$RAM_DISK_DEVICE" >/dev/null 2>&1; then
                log_error "Failed to format RAM disk for $device"
                sudo hdiutil detach "$RAM_DISK_DEVICE" 2>/dev/null || true
                continue
            fi
        fi

        # diskutil eraseVolume auto-mounts the volume
        if mount | grep -q "VirtualPyTest_${device}_Hot"; then
            ACTUAL_MOUNT=$(mount | grep "VirtualPyTest_${device}_Hot" | awk '{print $3}')
            log_info "RAM disk auto-mounted at: $ACTUAL_MOUNT"
            MOUNT_POINT="$ACTUAL_MOUNT"
        else
            # Manual mount needed (newfs_hfs path)
            sudo mkdir -p "$MOUNT_POINT"
            if ! sudo mount -t hfs "$RAM_DISK_DEVICE" "$MOUNT_POINT"; then
                log_error "Failed to mount RAM disk for $device"
                sudo hdiutil detach "$RAM_DISK_DEVICE" 2>/dev/null || true
                sudo rmdir "$MOUNT_POINT" 2>/dev/null || true
                continue
            fi
        fi

        # Create hot storage structure
        sudo mkdir -p "$MOUNT_POINT/segments"
        sudo mkdir -p "$MOUNT_POINT/captures"
        sudo mkdir -p "$MOUNT_POINT/thumbnails"
        sudo mkdir -p "$MOUNT_POINT/metadata"
        sudo chmod -R 777 "$MOUNT_POINT"

        # Create symlink to device hot directory
        mkdir -p "$(dirname "$HOT_DIR")"
        rm -f "$HOT_DIR" 2>/dev/null || true
        ln -sf "$MOUNT_POINT" "$HOT_DIR"

        log_success "RAM disk created for $device at $HOT_DIR -> $MOUNT_POINT (128MB)"
    done

    # Clean up RAM disks for devices no longer configured
    cleanup_unused_ram_disks

    log_success "RAM disk setup complete"
}

# Clean up RAM disks for devices no longer in .env
cleanup_unused_ram_disks() {
    log_info "Checking for unused RAM disks..."
    
    local cleanup_count=0
    local mounted_volumes=$(mount | grep "VirtualPyTest_.*_Hot" | awk '{print $3}')
    
    for mount_point in $mounted_volumes; do
        local device_name=$(basename "$mount_point" | sed 's/VirtualPyTest_//' | sed 's/_Hot//')
        
        # Check if this device is in our active DEVICES list
        local found=false
        for active_device in "${DEVICES[@]}"; do
            if [[ "$active_device" == "$device_name" ]]; then
                found=true
                break
            fi
        done
        
        if [[ "$found" == "false" ]]; then
            log_info "Cleaning up unused RAM disk for $device_name..."
            
            local hot_dir="$INSTALL_PATH/$device_name/hot"
            if [[ -L "$hot_dir" ]]; then
                rm -f "$hot_dir" 2>/dev/null || true
            fi
            
            if sudo umount "$mount_point" 2>/dev/null || sudo umount -f "$mount_point" 2>/dev/null; then
                sudo hdiutil detach "$mount_point" 2>/dev/null || true
                log_success "  ✓ Unmounted $device_name RAM disk (freed 128MB)"
                ((cleanup_count++))
            else
                log_warning "  ⚠️  Could not unmount $mount_point"
            fi
        fi
    done
    
    if [[ $cleanup_count -eq 0 ]]; then
        log_info "No unused RAM disks found"
    else
        log_success "Cleaned up $cleanup_count unused RAM disk(s)"
    fi
}

# Setup environment configuration
setup_environment() {
    log_info "Setting up environment configuration..."

    # Create .env file if it doesn't exist
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$BACKEND_HOST_PATH/src/.env.example" ]]; then
            cp "$BACKEND_HOST_PATH/src/.env.example" "$ENV_FILE"
            log_info "Created .env file from .env.example"
        else
            log_error "No .env found and backend_host/src/.env.example not found"
            log_error "Please create backend_host/src/.env or backend_host/src/.env.example manually"
            exit 1
        fi
    else
        log_info ".env file already exists, preserving existing configuration"
    fi

    log_success "Environment configuration complete"
}

# Setup noVNC (called before websockify service)
setup_novnc() {
    log_info "Setting up noVNC..."

    if [[ ! -d "$NOVNC_DIR" ]]; then
        log_info "Downloading noVNC to $NOVNC_DIR..."
        git clone https://github.com/novnc/noVNC.git "$NOVNC_DIR" 2>/dev/null || {
            log_warning "Failed to clone noVNC, trying alternative location..."
            NOVNC_DIR="$PROJECT_ROOT/noVNC"
            [[ -d "$NOVNC_DIR" ]] || git clone https://github.com/novnc/noVNC.git "$NOVNC_DIR"
        }
    fi

    if [[ -d "$NOVNC_DIR" ]]; then
        # Copy custom vnc_lite.html with auto-path detection from template
        VNC_LITE_TEMPLATE="$PROJECT_ROOT/backend_host/config/services/mac/vnc.lite.example"
        if [[ -f "$VNC_LITE_TEMPLATE" ]]; then
            cp "$VNC_LITE_TEMPLATE" "$NOVNC_DIR/vnc_lite.html"
            log_info "Installed custom vnc_lite.html with auto-path detection"
        fi
        
        # Auto-set the username to current user (macOS uses username+password)
        sed -i '' "s/mac_user/$USER/g" "$NOVNC_DIR/vnc_lite.html" 2>/dev/null || true
        log_info "Set VNC username to: $USER"
        
        NOVNC_FRAME_PATCH="$PROJECT_ROOT/backend_host/scripts/patch_novnc_close_frame.sh"
        if [[ -x "$NOVNC_FRAME_PATCH" ]]; then
            log_info "Patching noVNC VideoDecoder to close VideoFrames..."
            bash "$NOVNC_FRAME_PATCH" "$NOVNC_DIR" || true
        else
            log_warning "Missing patch script: $NOVNC_FRAME_PATCH"
        fi

        log_success "noVNC setup complete"
    else
        log_error "noVNC setup failed"
        return 1
    fi
}

# Create macOS launchd services using generic install_service.sh
create_launchd_services() {
    log_info "Creating macOS launchd services..."

    # Make scripts executable
    chmod +x "$STREAM_SCRIPT" 2>/dev/null || true
    chmod +x "$RAMDISK_SCRIPT" 2>/dev/null || true

    # Install ramdisk service FIRST (other services depend on hot storage)
    log_info "Installing ramdisk service (boot-time RAM disk creation)..."
    if "$SCRIPT_DIR/install_service.sh" ramdisk; then
        log_success "ramdisk service installed - RAM disks will be created at boot"
    else
        log_warning "ramdisk service installation failed - RAM disks must be created manually"
    fi

    # Install all other services using the generic installer
    local services_to_install=("flask" "stream" "monitor" "archiver" "transcript" "kpi")
    
    for service in "${services_to_install[@]}"; do
        log_info "Installing $service service..."
        if "$SCRIPT_DIR/install_service.sh" "$service"; then
            log_success "$service service installed"
        else
            log_error "Failed to install $service service"
        fi
    done

    # Setup noVNC before websockify
    setup_novnc || log_warning "noVNC setup had issues"

    # Install VNC and websockify services
    log_info "Installing VNC service..."
    if "$SCRIPT_DIR/install_service.sh" vnc; then
        log_success "VNC service installed"
    fi

    log_info "Installing websockify service..."
    if "$SCRIPT_DIR/install_service.sh" websockify; then
        log_success "WebSockify service installed"
    fi

    log_success "launchd services created"
}

# Configure security permissions
setup_permissions() {
    log_info "Setting up security permissions..."

    log_warning "Screen Recording permission required for screen capture"
    log_warning "Please go to System Settings > Privacy & Security > Screen Recording"
    log_warning "And allow access for Terminal/iTerm or your preferred shell"

    log_info "Camera permissions will be requested when video capture starts"

    log_warning "Accessibility permission may be required for some desktop automation features"
    log_warning "Please go to System Settings > Privacy & Security > Accessibility"
}

# Test installation
test_installation() {
    log_info "Testing installation..."

    local tests_passed=0
    local total_tests=0

    # Test Python environment
    ((total_tests++))
    if [[ -f "$PYTHON_EXE" ]] && "$PYTHON_EXE" --version &>/dev/null; then
        log_success "✓ Python environment"
        ((tests_passed++))
    else
        log_error "✗ Python environment"
    fi

    # Test FFmpeg
    ((total_tests++))
    if command -v ffmpeg &>/dev/null; then
        log_success "✓ FFmpeg installed"
        ((tests_passed++))
    else
        log_error "✗ FFmpeg not found"
    fi

    # Test services
    for service_info in "${SERVICES[@]}"; do
        IFS=':' read -r service_name service_desc <<< "$service_info"
        ((total_tests++))

        if launchctl list "${SERVICE_DOMAIN}.${service_name}" &>/dev/null; then
            log_success "✓ $service_desc"
            ((tests_passed++))
        else
            log_error "✗ $service_desc"
        fi
    done

    # Test noVNC directory
    ((total_tests++))
    if [[ -d "$NOVNC_DIR" && -f "$NOVNC_DIR/vnc_lite.html" ]]; then
        log_success "✓ noVNC files"
        ((tests_passed++))
    else
        log_error "✗ noVNC files"
    fi

    # Test directories
    ((total_tests++))
    if [[ -d "$INSTALL_PATH" ]]; then
        log_success "✓ Installation directory"
        ((tests_passed++))
    else
        log_error "✗ Installation directory"
    fi

    # Summary
    echo
    log_info "Installation Test Results: $tests_passed/$total_tests tests passed"

    if [[ $tests_passed -eq $total_tests ]]; then
        log_success "Installation completed successfully!"
        return 0
    else
        log_warning "Some tests failed. Check the output above."
        return 1
    fi
}

# Show service status summary table
show_service_status() {
    echo
    log_info "📊 Service Status Summary:"
    echo
    printf "  %-15s %-40s\n" "Service" "Status"
    printf "  %-15s %-40s\n" "───────────────" "────────────────────────────────────────"
    
    local services_to_check=(
        "flask:Flask API"
        "stream:FFmpeg Stream"
        "monitor:Capture Monitor"
        "archiver:Hot/Cold Archiver"
        "transcript:Audio Transcript"
        "kpi:KPI Executor"
        "vnc:VNC Server"
        "websockify:WebSockify/noVNC"
    )
    
    for service_entry in "${services_to_check[@]}"; do
        IFS=':' read -r service_name display_name <<< "$service_entry"
        local full_name="${SERVICE_DOMAIN}.${service_name}"
        
        if launchctl list "$full_name" &>/dev/null; then
            local list_line
            list_line=$(launchctl list 2>/dev/null | grep "$full_name")
            
            if [[ -n "$list_line" ]]; then
                local pid=$(echo "$list_line" | awk '{print $1}')
                local exit_code=$(echo "$list_line" | awk '{print $2}')
                
                if [[ "$pid" == "-" ]]; then
                    if [[ "$exit_code" == "0" ]]; then
                        printf "  %-15s ${GREEN}✅ Completed${NC}\n" "$display_name"
                    else
                        printf "  %-15s ${RED}❌ Failed (exit code $exit_code)${NC}\n" "$display_name"
                    fi
                else
                    if [[ "$exit_code" == "0" || "$exit_code" == "-" ]]; then
                        printf "  %-15s ${GREEN}✅ Running (PID $pid)${NC}\n" "$display_name"
                    else
                        printf "  %-15s ${YELLOW}⚠️  Running/Restarting (PID $pid, last exit: $exit_code)${NC}\n" "$display_name"
                    fi
                fi
            else
                printf "  %-15s ${YELLOW}⚠️  Loaded but status unknown${NC}\n" "$display_name"
            fi
        else
            printf "  %-15s ${RED}❌ Not loaded${NC}\n" "$display_name"
        fi
    done
    echo
}

# Show usage information
show_usage() {
    echo
    log_success "VirtualPyTest macOS Installation Complete!"
    echo
    log_info "📋 Configuration:"
    log_info "   Config File: $ENV_FILE"
    log_info "   Logs: $LOGS_PATH"
    log_info "   Storage: $INSTALL_PATH"
    echo
    log_info "🔧 Service Management:"
    log_info "   List services: launchctl list | grep virtualpytest"
    log_info "   Start service: launchctl start ${SERVICE_DOMAIN}.<service>"
    log_info "   Stop service: launchctl stop ${SERVICE_DOMAIN}.<service>"
    log_info "   View logs: tail -f $LOGS_PATH/<service>.log"
    echo
    log_info "🌐 Access Points:"
    log_info "   API: http://localhost:6109"
    log_info "   VNC: vnc://localhost:5900 (uses macOS login)"
    log_info "   noVNC Web: http://localhost:6080/vnc_lite.html"
    echo
    log_warning "⚠️  REQUIRED: Configure noVNC password"
    log_warning "   Username auto-set to: $USER"
    log_warning "   Edit $NOVNC_DIR/vnc_lite.html line 85 with your macOS password"
    echo
    log_info "📝 Next Steps:"
    log_info "   1. Edit $ENV_FILE to configure devices"
    log_info "   2. Grant screen recording and camera permissions in System Settings"
    log_info "   3. Test services: launchctl list | grep virtualpytest"
    echo
    log_info "⚠️  Important: Grant permissions in System Settings > Privacy & Security"
    log_info "   - Screen Recording (for screen capture)"
    log_info "   - Camera (for camera access)"
    
    show_service_status
}

# Uninstall function
uninstall() {
    log_info "Uninstalling VirtualPyTest..."

    # Stop and unload services
    for service_info in "${SERVICES[@]}"; do
        IFS=':' read -r service_name service_desc <<< "$service_info"
        log_info "Unloading $service_desc..."

        launchctl unload "$HOME/Library/LaunchAgents/${SERVICE_DOMAIN}.${service_name}.plist" 2>/dev/null || true
        launchctl unload "/Library/LaunchDaemons/${SERVICE_DOMAIN}.${service_name}.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/${SERVICE_DOMAIN}.${service_name}.plist"
        sudo rm -f "/Library/LaunchDaemons/${SERVICE_DOMAIN}.${service_name}.plist"
    done

    # Remove RAM disks
    for device in "${DEVICES[@]}"; do
        mount_point="/Volumes/VirtualPyTest_${device}_Hot"
        if mount | grep -q "$mount_point"; then
            sudo umount "$mount_point" 2>/dev/null || true
            sudo rmdir "$mount_point" 2>/dev/null || true
        fi
    done

    # Remove installation directory
    sudo rm -rf "$INSTALL_PATH"

    log_success "VirtualPyTest uninstalled"
}

# Fix /tmp permissions
fix_tmp_permissions() {
    log_info "Fixing /tmp permissions..."
    
    sudo chmod 1777 /private/tmp
    sudo chmod -R a+rw /private/tmp 2>/dev/null || true
    
    local files_to_fix=("deployments.log" "speedtest_cache.json")
    for file in "${files_to_fix[@]}"; do
        if [[ -f "/tmp/$file" ]]; then
            sudo rm -f "/tmp/$file" 2>/dev/null || sudo chmod a+rw "/tmp/$file" 2>/dev/null || true
        fi
    done
    
    log_success "/tmp permissions configured"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user-install)
            USER_INSTALL=true
            INSTALL_PATH="$HOME/.virtualpytest"
            LOGS_PATH="$INSTALL_PATH/logs"
            log_info "Using user installation path: $INSTALL_PATH"
            shift
            ;;
        --uninstall)
            check_macos
            parse_devices_from_env "$ENV_FILE"
            uninstall
            exit 0
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --user-install Install to user directory (no sudo required)"
            echo "  --uninstall    Remove VirtualPyTest installation"
            echo "  --help         Show this help"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Main execution
main() {
    log_info "VirtualPyTest macOS Installation Script"
    log_section "Installation Starting"

    check_macos
    check_privileges

    # Fix /tmp permissions first
    fix_tmp_permissions

    # Create vpt_user service account
    setup_vpt_user || INSTALL_ERROR=true

    # Installation steps with error tracking
    install_homebrew || INSTALL_ERROR=true
    install_dependencies || INSTALL_ERROR=true
    setup_python || INSTALL_ERROR=true
    setup_storage || INSTALL_ERROR=true
    setup_environment || INSTALL_ERROR=true
    create_launchd_services || INSTALL_ERROR=true
    setup_permissions || INSTALL_ERROR=true
    
    # Run final tests
    if test_installation; then
        INSTALL_ERROR=false
    else
        INSTALL_ERROR=true
    fi

    # Final status message
    echo
    if [[ "$INSTALL_ERROR" == "true" ]]; then
        log_error "❌ INSTALLATION FAILED"
        log_error "   Some components may not work correctly"
        log_error "   Check the error messages above for details"
        exit 1
    else
        log_success "🎉 INSTALLATION SUCCESSFUL!"
        log_success "   VirtualPyTest is ready to use"
    fi

    show_usage
}

main "$@"
