#!/bin/bash

# Generic Linux Service Installation Script
# Installs a single systemd service from a template
# Equivalent to macOS's install_service.sh
#
# Usage: install_service.sh <service_name> [--force]
#   --force: Force reinstall (stop, disable, remove, regenerate cert, reinstall)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common variables (includes logging functions)
source "$SCRIPT_DIR/common_vars.sh"

# Global force flag
FORCE_REINSTALL=false

# Completely remove a service before reinstalling
uninstall_service() {
    local service_name="$1"
    local service_file="/etc/systemd/system/vpt-${service_name}.service"
    
    log_info "Removing existing $service_name service..."
    
    # Stop and disable service (ignore errors)
    sudo systemctl stop "vpt-${service_name}.service" 2>/dev/null || true
    sudo systemctl disable "vpt-${service_name}.service" 2>/dev/null || true
    
    # Kill any remaining processes
    pkill -f "websockify.*6080" 2>/dev/null || true
    
    # Remove service file
    if [[ -f "$service_file" ]]; then
        sudo rm -f "$service_file"
        log_info "Removed $service_file"
    fi
    
    # For websockify, also remove certificate if force reinstall
    if [[ "$service_name" == "websockify" && "$FORCE_REINSTALL" == true ]]; then
        if [[ -f "$WEBSOCKIFY_CERT" ]]; then
            sudo rm -f "$WEBSOCKIFY_CERT"
            log_info "Removed certificate: $WEBSOCKIFY_CERT"
        fi
    fi
    
    # Reload systemd
    sudo systemctl daemon-reload
    
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
        -subj "/CN=localhost/O=VNC Server/C=US" \
        2>/dev/null
    
    # Set appropriate permissions (readable by service user)
    sudo chmod 644 "$WEBSOCKIFY_CERT"
    
    log_success "Websockify SSL certificate generated: $WEBSOCKIFY_CERT"
}

# Install a service from template.
#
# Two source layouts are supported:
#   1. Plain unit:   <name>.service    → installed as vpt-<name>.service
#   2. Templated:    <name>@.service   → installed as vpt-<name>@.service
#                    (operator then enables vpt-<name>@<instance>.service per
#                     adapter / per instance, e.g. vpt-ble-remote@hci0)
#
# Templated units are detected by the @ suffix in the source filename.
# The installer does NOT auto-enable or start templated units because
# they have no implicit default instance — the caller (install_host.sh
# / a per-adapter setup script) is responsible for enabling the
# specific instances that exist on this host.
install_service() {
    local service_name="$1"
    local templated=0
    local template_file="$SERVICE_TEMPLATES_DIR/${service_name}.service"
    if [[ ! -f "$template_file" && -f "$SERVICE_TEMPLATES_DIR/${service_name}@.service" ]]; then
        template_file="$SERVICE_TEMPLATES_DIR/${service_name}@.service"
        templated=1
    fi
    # Optional feature units: features/<feature>/backend_host/services/<name>.service
    # (see docs/technical/FEATURES.md). Disabled features are not deployed, so the
    # unit file is simply absent; DISABLED_FEATURES is honoured too for local installs.
    if [[ ! -f "$template_file" ]]; then
        local feature_unit
        for feature_unit in "$PROJECT_ROOT"/features/*/backend_host/services/"${service_name}".service; do
            [[ -f "$feature_unit" ]] || continue
            local feature_name
            feature_name="$(basename "$(dirname "$(dirname "$(dirname "$feature_unit")")")")"
            if [[ ",${DISABLED_FEATURES:-}," == *",${feature_name},"* ]]; then
                log_info "Skipping $service_name: feature '$feature_name' is in DISABLED_FEATURES"
                return 0
            fi
            template_file="$feature_unit"
            break
        done
    fi
    local temp_service_file="/tmp/${service_name}.service"
    local service_file="/etc/systemd/system/vpt-${service_name}.service"
    if (( templated )); then
        service_file="/etc/systemd/system/vpt-${service_name}@.service"
    fi

    log_info "Installing $service_name service ($([[ $templated -eq 1 ]] && echo template || echo unit))..."

    # Check if template exists
    if [[ ! -f "$template_file" ]]; then
        log_error "Template file not found: $template_file"
        return 1
    fi

    # Generate certificate for websockify before substitution
    if [[ "$service_name" == "websockify" ]]; then
        generate_websockify_certificate
    fi

    # Substitute variables in template
    cp "$template_file" "$temp_service_file"

    # Perform variable substitutions
    sed -i "s|%PROJECT_ROOT%|$PROJECT_ROOT_ESCAPED|g" "$temp_service_file"
    sed -i "s|%WEBSOCKIFY_CERT%|$WEBSOCKIFY_CERT|g" "$temp_service_file"

    # Copy to systemd location
    sudo cp "$temp_service_file" "$service_file"
    rm "$temp_service_file"

    # Reload systemd daemon
    sudo systemctl daemon-reload

    if (( templated )); then
        # Template units cannot be enabled/started without an instance.
        # The caller is responsible for `systemctl enable vpt-<name>@<instance>.service`
        # for each adapter present on this host.
        log_success "$service_name template installed at $service_file (enable per-instance separately)"
        return 0
    fi

    # Enable and start the service
    sudo systemctl enable "vpt-${service_name}.service"

    if sudo systemctl start "vpt-${service_name}.service"; then
        log_success "$service_name service installed and started"
        return 0
    else
        log_error "Failed to start $service_name service"
        return 1
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
        log_error "Available services: flask, stream, monitor, archiver, transcript, kpi, vnc, websockify, ble-remote"
        log_error "Options:"
        log_error "  --force, -f  Force reinstall (stop, disable, remove, regenerate cert)"
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
