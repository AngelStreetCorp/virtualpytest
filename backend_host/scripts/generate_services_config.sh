#!/bin/bash

# VirtualPyTest - Service Configuration Generator
# Parses .env file and determines which services to start
# Generates dynamic GRABBERS config for ffmpeg script

set -e

# Configuration - Auto-detect environment
if [ -d "/app/backend_host/src" ]; then
    # Docker environment
    DEFAULT_ENV_FILE="/app/backend_host/src/.env"
else
    # Local environment
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    DEFAULT_ENV_FILE="$PROJECT_ROOT/backend_host/src/.env"
fi

ENV_FILE="${ENV_FILE:-$DEFAULT_ENV_FILE}"
GRABBERS_CONFIG_FILE="/tmp/grabbers_config.sh"
SERVICES_LIST_FILE="/tmp/services_list.txt"

# Default audio device mapping (can be overridden in .env)
DEFAULT_AUDIO_DEVICE="plughw:2,0"
DEFAULT_FPS="10"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] generate_services_config: $1" >&2
}

# Function to parse environment file
parse_env() {
    if [ ! -f "$ENV_FILE" ]; then
        log "Warning: .env file not found at $ENV_FILE"
        return 1
    fi
    
    # Source the environment file (override any existing env vars with .env values)
    while IFS= read -r line; do
        # Skip comments and empty lines
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
            continue
        fi
        
        # Extract variable name and value
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            var_name="${BASH_REMATCH[1]}"
            var_value="${BASH_REMATCH[2]}"
            
            # Always use .env file values (they take precedence)
            export "$var_name=$var_value"
        fi
    done < "$ENV_FILE"
    
    log "Parsed environment from $ENV_FILE"
}

# Function to detect video devices from environment
detect_video_devices() {
    local device_count=0
    local grabbers_config=""
    
    log "Detecting video devices from environment..."
    
    # Look for DEVICE*_VIDEO variables
    for var in $(env | grep -E '^DEVICE[0-9]+_VIDEO=' | sort); do
        # Extract device number and video path
        local device_num=$(echo "$var" | sed -E 's/^DEVICE([0-9]+)_VIDEO=.*/\1/')
        local video_device=$(echo "$var" | cut -d'=' -f2)
        
        # Get corresponding audio device (default if not specified)
        local audio_var="DEVICE${device_num}_AUDIO"
        local audio_device="${!audio_var:-$DEFAULT_AUDIO_DEVICE}"
        
        # Get capture path (strip carriage returns from Windows line endings)
        local capture_var="DEVICE${device_num}_VIDEO_CAPTURE_PATH"
        local capture_path="${!capture_var:-/var/www/html/stream/capture$((device_count+1))}"
        capture_path=$(echo "$capture_path" | tr -d '\r')
        
        # Get FPS (default if not specified)
        local fps_var="DEVICE${device_num}_FPS"
        local fps="${!fps_var:-$DEFAULT_FPS}"
        
        # Build grabber entry
        grabbers_config+="  [\"$device_count\"]=\"$video_device|$audio_device|$capture_path|$fps\"\n"
        
        log "Found device $device_count: video=$video_device, audio=$audio_device, capture=$capture_path, fps=$fps"
        device_count=$((device_count + 1))
    done
    
    # Generate GRABBERS config file
    if [ $device_count -gt 0 ]; then
        log "Generating GRABBERS config for $device_count devices"
        cat > "$GRABBERS_CONFIG_FILE" << EOF
#!/bin/bash
# Auto-generated GRABBERS configuration
# Generated on: $(date)

declare -A GRABBERS=(
$(echo -e "$grabbers_config")
)
EOF
        chmod +x "$GRABBERS_CONFIG_FILE"
        log "GRABBERS config written to $GRABBERS_CONFIG_FILE"
    else
        log "No video devices found in environment"
        # Remove any existing grabbers config
        rm -f "$GRABBERS_CONFIG_FILE"
    fi
    
    echo $device_count
}

# Function to determine required services
determine_services() {
    local video_device_count=$1
    local services=""
    
    log "Determining required services..."
    
    # VNC services are always required (minimal config)
    services="vnc"
    log "VNC services: required (minimal configuration)"
    
    # Video services only if devices are configured
    if [ "$video_device_count" -gt 0 ] 2>/dev/null; then
        services="$services video"
        log "Video services: required ($video_device_count devices detected)"
        
        # Monitor service only if video services are running
        services="$services monitor"
        log "Monitor services: required (video analysis needed)"
    else
        log "Video services: not required (no devices configured)"
        log "Monitor services: not required (no video to analyze)"
    fi
    
    # Write services list to file
    echo "$services" > "$SERVICES_LIST_FILE"
    log "Services list written to $SERVICES_LIST_FILE: $services"
    
    echo "$services"
}

# Function to validate device paths (optional check)
validate_device_paths() {
    local validation_errors=0
    
    log "Validating device paths..."
    
    # Check video devices
    for var in $(env | grep -E '^DEVICE[0-9]+_VIDEO='); do
        local video_device=$(echo "$var" | cut -d'=' -f2)
        if [ ! -e "$video_device" ]; then
            log "Warning: Video device $video_device does not exist"
            validation_errors=$((validation_errors + 1))
        else
            log "Video device $video_device: OK"
        fi
    done
    
    # Check capture directories
    for var in $(env | grep -E '^DEVICE[0-9]+_VIDEO_CAPTURE_PATH='); do
        local capture_path=$(echo "$var" | cut -d'=' -f2 | tr -d '\r')
        local capture_dir=$(dirname "$capture_path")
        if [ ! -d "$capture_dir" ]; then
            log "Creating capture directory: $capture_dir"
            mkdir -p "$capture_dir" || {
                log "Error: Failed to create capture directory $capture_dir"
                validation_errors=$((validation_errors + 1))
            }
        else
            log "Capture directory $capture_dir: OK"
        fi
    done
    
    if [ $validation_errors -gt 0 ]; then
        log "Warning: $validation_errors validation errors found"
    else
        log "All device paths validated successfully"
    fi
    
    return $validation_errors
}

# Main execution
main() {
    log "Starting service configuration generation"
    
    # Parse environment
    if ! parse_env; then
        log "Using minimal configuration (VNC only)"
        echo "vnc" > "$SERVICES_LIST_FILE"
        rm -f "$GRABBERS_CONFIG_FILE"
        echo "vnc"
        return 0
    fi
    
    # Detect video devices  
    local device_count=$(detect_video_devices 2>/dev/null)
    
    # Validate device paths (non-fatal)
    validate_device_paths || true
    
    # Determine required services
    local services=$(determine_services $device_count)
    
    log "Service configuration complete"
    log "Required services: $services"
    log "Video devices: $device_count"
    
    # Output services for caller
    echo "$services"
}

# Execute main function
main "$@" 