#!/bin/bash

# Shared device parsing functions for VirtualPyTest installation scripts
# Source this file to parse device configuration from .env files
#
# Usage:
#   source "$(dirname "$0")/../shared/parse_devices.sh"
#   parse_devices_from_env "/path/to/.env"
#   echo "Found devices: ${DEVICES[*]}"

# Global array to store parsed devices
DEVICES=()

# Parse devices from .env file
# Populates the global DEVICES array with capture folder names
# Arguments:
#   $1 - Path to .env file
parse_devices_from_env() {
    local env_file="${1:-$ENV_FILE}"
    
    # Source logging if available
    if type log_info &>/dev/null; then
        log_info "Parsing device configuration from .env file..."
    else
        echo "[INFO] Parsing device configuration from .env file..."
    fi
    
    # Reset DEVICES array
    DEVICES=()
    
    # Check if .env file exists
    if [[ ! -f "$env_file" ]]; then
        if type log_warning &>/dev/null; then
            log_warning ".env file not found at $env_file"
            log_warning "Using default devices (host only)"
        else
            echo "[WARNING] .env file not found at $env_file"
            echo "[WARNING] Using default devices (host only)"
        fi
        DEVICES=("host")
        return 0
    fi
    
    # Check for HOST device first
    local host_capture_path
    host_capture_path=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$env_file" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
    if [[ -n "$host_capture_path" ]]; then
        local capture_folder
        capture_folder=$(basename "$host_capture_path")
        DEVICES+=("$capture_folder")
        if type log_info &>/dev/null; then
            log_info "  ✓ Found host: HOST -> $capture_folder"
        fi
    fi
    
    # Check for regular devices (dynamically detect up to 14)
    local consecutive_empty=0
    for i in {1..14}; do
        local device_name
        local video_capture_path
        device_name=$(grep "^DEVICE${i}_NAME=" "$env_file" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
        video_capture_path=$(grep "^DEVICE${i}_VIDEO_CAPTURE_PATH=" "$env_file" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
        
        if [[ -n "$video_capture_path" ]]; then
            local capture_folder
            capture_folder=$(basename "$video_capture_path")
            DEVICES+=("$capture_folder")
            if type log_info &>/dev/null; then
                log_info "  ✓ Found device$i: ${device_name:-device$i} -> $capture_folder"
            fi
            consecutive_empty=0
        else
            ((consecutive_empty++))
            # Stop scanning after 5 consecutive empty slots
            if [[ $consecutive_empty -ge 5 && ${#DEVICES[@]} -gt 0 ]]; then
                break
            fi
        fi
    done
    
    if [[ ${#DEVICES[@]} -eq 0 ]]; then
        if type log_warning &>/dev/null; then
            log_warning "No devices found in .env file"
            log_warning "Using default device (host only)"
        fi
        DEVICES=("host")
    else
        if type log_success &>/dev/null; then
            log_success "Found ${#DEVICES[@]} device(s): ${DEVICES[*]}"
        fi
    fi
}
