#!/bin/bash

# VirtualPyTest macOS RAM Disk Setup Script
# Creates and mounts RAM disks for hot storage at boot
# Run as root via launchd at system startup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BACKEND_HOST_DIR/src/.env"

# Default install path (same as install script)
INSTALL_PATH="/var/www/html/stream"

# RAM disk size per device (MB)
RAM_DISK_SIZE_MB=128

# Logging
log_info() { echo "[INFO] $1"; }
log_success() { echo "[SUCCESS] $1"; }
log_error() { echo "[ERROR] $1" >&2; }
log_warning() { echo "[WARNING] $1"; }

# Parse devices from .env file (simplified version)
parse_devices() {
    local env_file="$1"
    DEVICES=()
    
    if [[ ! -f "$env_file" ]]; then
        log_warning ".env file not found at $env_file"
        return 1
    fi
    
    # Check for HOST device
    local host_path
    host_path=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$env_file" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'")
    if [[ -n "$host_path" ]]; then
        DEVICES+=("$(basename "$host_path")")
    fi
    
    # Check for DEVICE1-14
    for i in {1..30}; do
        local device_path
        device_path=$(grep "^DEVICE${i}_VIDEO_CAPTURE_PATH=" "$env_file" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'")
        if [[ -n "$device_path" ]]; then
            DEVICES+=("$(basename "$device_path")")
        fi
    done
    
    if [[ ${#DEVICES[@]} -eq 0 ]]; then
        log_warning "No devices found in .env"
        return 1
    fi
    
    log_info "Found ${#DEVICES[@]} device(s): ${DEVICES[*]}"
    return 0
}

# Create RAM disk for a device
create_ramdisk() {
    local device=$1
    local mount_point="/Volumes/VirtualPyTest_${device}_Hot"
    local hot_dir="$INSTALL_PATH/$device/hot"
    
    # Check if already mounted and functional
    if mount | grep -q "$mount_point"; then
        if [[ -d "$mount_point/segments" ]]; then
            log_info "RAM disk already mounted for $device"
            # Ensure symlink exists
            if [[ ! -L "$hot_dir" ]] || [[ "$(readlink "$hot_dir")" != "$mount_point" ]]; then
                rm -f "$hot_dir" 2>/dev/null || true
                ln -sf "$mount_point" "$hot_dir"
                log_info "Fixed symlink: $hot_dir -> $mount_point"
            fi
            return 0
        fi
    fi
    
    # Clean up broken symlink
    if [[ -L "$hot_dir" && ! -d "$(readlink "$hot_dir")" ]]; then
        rm -f "$hot_dir"
    fi
    
    # Calculate sectors (512 bytes per sector)
    local sectors=$((RAM_DISK_SIZE_MB * 1024 * 1024 / 512))
    
    log_info "Creating $RAM_DISK_SIZE_MB MB RAM disk for $device..."
    
    # Create RAM disk device
    local ram_device
    ram_device=$(hdiutil attach -nomount ram://$sectors 2>&1)
    if [[ $? -ne 0 ]]; then
        log_error "Failed to create RAM disk device: $ram_device"
        return 1
    fi
    
    # Trim whitespace
    ram_device=$(echo "$ram_device" | tr -d '[:space:]')
    
    if [[ ! -e "$ram_device" ]]; then
        log_error "RAM disk device not found: $ram_device"
        return 1
    fi
    
    # Format as HFS+
    log_info "Formatting RAM disk..."
    if ! diskutil eraseVolume HFS+ "VirtualPyTest_${device}_Hot" "$ram_device" >/dev/null 2>&1; then
        log_warning "diskutil failed, trying newfs_hfs..."
        if ! newfs_hfs -v "VirtualPyTest_${device}_Hot" "$ram_device" >/dev/null 2>&1; then
            log_error "Failed to format RAM disk"
            hdiutil detach "$ram_device" 2>/dev/null || true
            return 1
        fi
        # Manual mount
        mkdir -p "$mount_point"
        if ! mount -t hfs "$ram_device" "$mount_point"; then
            log_error "Failed to mount RAM disk"
            hdiutil detach "$ram_device" 2>/dev/null || true
            return 1
        fi
    fi
    
    # Get actual mount point (diskutil may use different path)
    if mount | grep -q "VirtualPyTest_${device}_Hot"; then
        mount_point=$(mount | grep "VirtualPyTest_${device}_Hot" | awk '{print $3}')
    fi
    
    # Create directory structure
    mkdir -p "$mount_point/segments"
    mkdir -p "$mount_point/captures"
    mkdir -p "$mount_point/thumbnails"
    mkdir -p "$mount_point/metadata"
    chmod -R 777 "$mount_point"
    
    # Create symlink
    mkdir -p "$(dirname "$hot_dir")"
    rm -f "$hot_dir" 2>/dev/null || true
    ln -sf "$mount_point" "$hot_dir"
    
    log_success "RAM disk ready: $hot_dir -> $mount_point ($RAM_DISK_SIZE_MB MB)"
    return 0
}

# Main
main() {
    log_info "VirtualPyTest RAM Disk Setup starting..."
    
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
    
    if ! parse_devices "$ENV_FILE"; then
        log_error "Failed to parse devices from $ENV_FILE"
        exit 1
    fi
    
    local success_count=0
    local fail_count=0
    
    for device in "${DEVICES[@]}"; do
        if create_ramdisk "$device"; then
            ((success_count++))
        else
            ((fail_count++))
        fi
    done
    
    echo ""
    if [[ $fail_count -eq 0 ]]; then
        log_success "All $success_count RAM disk(s) created successfully"
    else
        log_warning "$success_count succeeded, $fail_count failed"
    fi
}

main "$@"
