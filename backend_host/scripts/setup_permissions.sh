#!/bin/bash
# Fix all directory permissions on all capture devices
# ALL subdirectories need 777 for cross-service access
# Run this on each Raspberry Pi to fix permission issues

echo "============================================"
echo "Fixing All Storage Directory Permissions"
echo "============================================"
echo ""

FIXED_COUNT=0

for capture_dir in /var/www/html/stream/capture*; do
    if [ ! -d "$capture_dir" ]; then
        continue
    fi
    
    device=$(basename "$capture_dir")
    echo "Processing $device..."
    
    # Fix ALL hot storage directories (RAM storage) - archiver needs full access
    for subdir in captures thumbnails segments metadata audio; do
        if [ -d "$capture_dir/hot/$subdir" ]; then
            echo "  Fixing hot/$subdir permissions..."
            sudo chmod 777 "$capture_dir/hot/$subdir"
            echo "  ✓ $capture_dir/hot/$subdir → 777"
            FIXED_COUNT=$((FIXED_COUNT + 1))
        fi
    done
    
    # Fix ALL cold storage directories (SD card storage)
    for subdir in captures segments metadata audio; do
        if [ ! -d "$capture_dir/$subdir" ]; then
            echo "  Creating cold $subdir directory..."
            sudo mkdir -p "$capture_dir/$subdir"
            sudo chown vpt_user:vpt_user "$capture_dir/$subdir"
        fi
        sudo chmod 777 "$capture_dir/$subdir"
        echo "  ✓ $capture_dir/$subdir → 777"
        FIXED_COUNT=$((FIXED_COUNT + 1))
    done
    
    # Fix hour folders in segments (0-23)
    for hour in {0..23}; do
        hour_dir="$capture_dir/segments/$hour"
        if [ ! -d "$hour_dir" ]; then
            sudo mkdir -p "$hour_dir"
            sudo chown vpt_user:vpt_user "$hour_dir"
        fi
        sudo chmod 777 "$hour_dir"
    done
    echo "  ✓ Hour folders (0-23) → 777"
    FIXED_COUNT=$((FIXED_COUNT + 1))
    
    # Fix temp directory in segments (for MP4 merging)
    temp_dir="$capture_dir/segments/temp"
    if [ ! -d "$temp_dir" ]; then
        sudo mkdir -p "$temp_dir"
        sudo chown vpt_user:vpt_user "$temp_dir"
    fi
    sudo chmod 777 "$temp_dir"
    echo "  ✓ $temp_dir → 777"
    FIXED_COUNT=$((FIXED_COUNT + 1))
    
    echo ""
done

echo "============================================"
echo "✅ Fixed $FIXED_COUNT directories"
echo "============================================"
echo ""

# Fix active_captures.conf permissions in new location (needed by all services)
ACTIVE_CAPTURES_CONF="/var/www/html/stream/active_captures.conf"
if [ -f "$ACTIVE_CAPTURES_CONF" ]; then
    sudo chmod 666 "$ACTIVE_CAPTURES_CONF"
    echo "✓ Fixed $ACTIVE_CAPTURES_CONF → 666"
else
    echo "ℹ️  $ACTIVE_CAPTURES_CONF not found (will be created by stream.service)"
fi
echo ""

# Show current permissions
echo "Verification (hot storage):"
ls -ld /var/www/html/stream/capture*/hot/captures 2>/dev/null | awk '{print $1, $9}'
ls -ld /var/www/html/stream/capture*/hot/segments 2>/dev/null | awk '{print $1, $9}'
ls -ld /var/www/html/stream/capture*/hot/metadata 2>/dev/null | awk '{print $1, $9}'
echo ""
echo "Verification (cold storage):"
ls -ld /var/www/html/stream/capture*/captures 2>/dev/null | awk '{print $1, $9}'
ls -ld /var/www/html/stream/capture*/segments 2>/dev/null | awk '{print $1, $9}'
ls -ld /var/www/html/stream/capture*/metadata 2>/dev/null | grep -v "/hot/" | awk '{print $1, $9}'
echo ""
echo "✅ All directories should show 'drwxrwxrwx' (777)"
echo ""
echo "💡 Run this script on the Raspberry Pi to fix permissions immediately"
echo "   Then restart hot_cold_archiver service:"
echo "   sudo systemctl restart hot_cold_archiver.service"
echo ""
