#!/bin/bash

# Generic macOS Service Installation Script
# Installs a single launchd service from a plist template
# Equivalent to Linux's install_service.sh
#
# Usage: install_service.sh <service_name> [--force]
#   --force: Force reinstall (unload, remove, regenerate cert, reinstall)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common variables (includes logging functions and load_launchd_service)
source "$SCRIPT_DIR/common_vars.sh"

# Global force flag
FORCE_REINSTALL=false

# Completely remove a service before reinstalling
uninstall_service() {
    local service_name="$1"
    local service_label="${SERVICE_DOMAIN}.${service_name}"
    
    log_info "Removing existing $service_name service..."
    
    # Determine plist location
    local plist_file
    if [[ "$service_name" == "vnc" ]]; then
        plist_file="$HOME/Library/LaunchAgents/${service_label}.plist"
    else
        plist_file="/Library/LaunchDaemons/${service_label}.plist"
    fi
    
    # Try to unload service (ignore errors)
    if [[ "$service_name" == "vnc" ]]; then
        launchctl bootout gui/$(id -u) "$plist_file" 2>/dev/null || true
        launchctl unload "$plist_file" 2>/dev/null || true
    else
        sudo launchctl bootout system "$plist_file" 2>/dev/null || true
        sudo launchctl unload "$plist_file" 2>/dev/null || true
    fi
    
    # Kill any remaining processes
    pkill -f "websockify.*6080" 2>/dev/null || true
    
    # Remove plist file
    if [[ -f "$plist_file" ]]; then
        if [[ "$service_name" == "vnc" ]]; then
            rm -f "$plist_file"
        else
            sudo rm -f "$plist_file"
        fi
        log_info "Removed $plist_file"
    fi
    
    # For websockify, also remove certificate if force reinstall
    if [[ "$service_name" == "websockify" && "$FORCE_REINSTALL" == true ]]; then
        if [[ -f "$WEBSOCKIFY_CERT" ]]; then
            sudo rm -f "$WEBSOCKIFY_CERT"
            log_info "Removed certificate: $WEBSOCKIFY_CERT"
        fi
    fi
    
    sleep 1
    log_success "Service $service_name removed"
}

# Generate self-signed certificate for websockify (HTTPS/WSS support)
generate_websockify_certificate() {
    log_info "Generating self-signed certificate for websockify..."
    
    # Create certificate directory if it doesn't exist
    sudo mkdir -p "$WEBSOCKIFY_CERT_DIR"
    
    # Generate certificate only if it doesn't exist, is expired, or force flag is set
    if [[ -f "$WEBSOCKIFY_CERT" && "$FORCE_REINSTALL" != true ]]; then
        # Check if certificate is still valid (not expired)
        if openssl x509 -checkend 86400 -noout -in "$WEBSOCKIFY_CERT" 2>/dev/null; then
            log_info "Websockify certificate already exists and is valid (use --force to regenerate)"
            return 0
        else
            log_info "Websockify certificate expired, regenerating..."
        fi
    fi
    
    # Generate combined certificate (key + cert in one file)
    # Using 365 days validity for development
    sudo openssl req -new -x509 -days 365 -nodes \
        -out "$WEBSOCKIFY_CERT" \
        -keyout "$WEBSOCKIFY_CERT" \
        -subj "/CN=localhost/O=VirtualPyTest/C=US" \
        2>/dev/null
    
    # Set appropriate permissions (readable by service user)
    sudo chmod 644 "$WEBSOCKIFY_CERT"
    
    log_success "Websockify SSL certificate generated: $WEBSOCKIFY_CERT"
}

# Install a service from template
install_service() {
    local service_name="$1"
    local template_file="$SERVICE_TEMPLATES_DIR/${service_name}.plist"
    local service_label="${SERVICE_DOMAIN}.${service_name}"
    
    # Determine plist location based on service type
    # VNC needs to run as user agent (GUI access required)
    local plist_file
    if [[ "$service_name" == "vnc" ]]; then
        plist_file="$HOME/Library/LaunchAgents/${service_label}.plist"
        mkdir -p "$HOME/Library/LaunchAgents"
    else
        plist_file="/Library/LaunchDaemons/${service_label}.plist"
    fi

    log_info "Installing $service_name service..."

    # Check if template exists
    if [[ ! -f "$template_file" ]]; then
        log_error "Template file not found: $template_file"
        return 1
    fi

    # Substitute variables in template
    local temp_plist="/tmp/${service_name}_temp.plist"
    cp "$template_file" "$temp_plist"

    # Generate certificate for websockify before substitution
    if [[ "$service_name" == "websockify" ]]; then
        generate_websockify_certificate
    fi

    # Perform variable substitutions
    sed -i '' "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" "$temp_plist"
    sed -i '' "s|@BACKEND_HOST_PATH@|$BACKEND_HOST_PATH|g" "$temp_plist"
    sed -i '' "s|@SHARED_PATH@|$SHARED_PATH|g" "$temp_plist"
    sed -i '' "s|@SCRIPTS_PATH@|$SCRIPTS_PATH|g" "$temp_plist"
    sed -i '' "s|@PYTHON_EXE@|$PYTHON_EXE|g" "$temp_plist"
    sed -i '' "s|@VENV_PATH@|$VENV_PATH|g" "$temp_plist"
    sed -i '' "s|@LOGS_PATH@|$LOGS_PATH|g" "$temp_plist"
    sed -i '' "s|@USER@|$USER|g" "$temp_plist"
    sed -i '' "s|@NOVNC_DIR@|$NOVNC_DIR|g" "$temp_plist"
    sed -i '' "s|@STREAM_SCRIPT@|$STREAM_SCRIPT|g" "$temp_plist"
    sed -i '' "s|@RAMDISK_SCRIPT@|$RAMDISK_SCRIPT|g" "$temp_plist"
    sed -i '' "s|@WEBSOCKIFY_CERT@|$WEBSOCKIFY_CERT|g" "$temp_plist"

    # Copy to final location
    if [[ "$service_name" == "vnc" ]]; then
        cp "$temp_plist" "$plist_file"
    else
        sudo cp "$temp_plist" "$plist_file"
    fi
    rm "$temp_plist"

    # Load the service (VNC uses user agent, others use system daemon)
    if [[ "$service_name" == "vnc" ]]; then
        if load_launchd_user_agent "$plist_file" "$service_label"; then
            log_success "$service_name service loaded (user agent)"
            return 0
        else
            log_warning "$service_name service may need manual setup - enable Screen Sharing in System Settings"
            return 0  # Don't fail since VNC is often a manual step on macOS
        fi
    else
        if load_launchd_service "$plist_file" "$service_label"; then
            log_success "$service_name service loaded"
            return 0
        else
            log_error "Failed to load $service_name service"
            return 1
        fi
    fi
}

# Main function
main() {
    local service_name=""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force|-f)
                FORCE_REINSTALL=true
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                log_error "Usage: $0 <service_name> [--force]"
                exit 1
                ;;
            *)
                service_name="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$service_name" ]]; then
        log_error "Usage: $0 <service_name> [--force]"
        log_error "Available services: ramdisk, flask, stream, monitor, archiver, transcript, kpi, vnc, websockify"
        log_error "Options:"
        log_error "  --force, -f  Force reinstall (unload, remove, regenerate cert)"
        exit 1
    fi
    
    # If force flag, uninstall first
    if [[ "$FORCE_REINSTALL" == true ]]; then
        log_info "Force reinstall requested"
        uninstall_service "$service_name"
    fi

    install_service "$service_name"
}

main "$@"
