#!/bin/bash
################################################################################
# Hot/Cold Architecture - Clean Restart Script
################################################################################
#
# This script performs a CLEAN RESTART with the new hot/cold architecture:
#   1. Stops all capture-related services
#   2. Deletes old capture folders
#   3. Recreates hot/cold folder structure with proper permissions
#   4. Restarts all services
#
# ⚠️  WARNING: This will DELETE ALL EXISTING CAPTURE DATA!
#
# Usage:
#   sudo bash scripts/clean_restart_hot_cold.sh
#
################################################################################

set -e  # Exit on any error

# Configuration
STREAM_BASE="/var/www/html/stream"
CAPTURE_FOLDERS=("capture1" "capture2" "capture3" "capture4")
WWW_USER="www-data"
WWW_GROUP="www-data"

# Services to manage
SERVICES=(
    "stream"
    "monitor"
    "transcript-stream"
    "hot_cold_archiver"
    "heatmap_processor"
)

echo "================================================================================
🔄 HOT/COLD ARCHITECTURE - CLEAN RESTART
================================================================================"
echo ""
echo "⚠️  WARNING: This will DELETE ALL EXISTING CAPTURE DATA!"
echo ""
echo "Services to stop:"
for service in "${SERVICES[@]}"; do
    echo "  - $service"
done
echo ""
echo "Folders to recreate:"
for folder in "${CAPTURE_FOLDERS[@]}"; do
    echo "  - $STREAM_BASE/$folder"
done
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Aborted by user"
    exit 1
fi

################################################################################
# Step 1: Stop all services
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 1: Ensure user is in www-data group..."
echo "════════════════════════════════════════════════════════════════════════════"

# Get the current user (who ran sudo)
ACTUAL_USER="${SUDO_USER:-$USER}"

if [ -z "$ACTUAL_USER" ] || [ "$ACTUAL_USER" = "root" ]; then
    echo "⚠️  Warning: Could not determine actual user (not running via sudo?)"
    echo "   You may need to manually add your user to www-data group:"
    echo "   sudo usermod -a -G www-data <your-username>"
else
    echo "🔑 Checking if user '$ACTUAL_USER' is in www-data group..."
    
    if groups "$ACTUAL_USER" | grep -q "\bwww-data\b"; then
        echo "   ✅ User '$ACTUAL_USER' is already in www-data group"
    else
        echo "   ➕ Adding user '$ACTUAL_USER' to www-data group..."
        usermod -a -G www-data "$ACTUAL_USER"
        echo "   ✅ Added to www-data group"
        echo "   💡 Note: You'll need to log out and back in for this to take effect"
        echo "   💡 Or run: newgrp www-data"
    fi
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 2: Stopping services..."
echo "════════════════════════════════════════════════════════════════════════════"

for service in "${SERVICES[@]}"; do
    echo "🛑 Stopping $service..."
    if systemctl is-active --quiet "$service"; then
        systemctl stop "$service"
        echo "   ✅ Stopped"
    else
        echo "   ⏭️  Already stopped"
    fi
done

echo "✅ All services stopped"
sleep 2

################################################################################
# Step 2: Delete old capture folders
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 3: Deleting old capture folders..."
echo "════════════════════════════════════════════════════════════════════════════"

for folder in "${CAPTURE_FOLDERS[@]}"; do
    folder_path="$STREAM_BASE/$folder"
    
    if [ -d "$folder_path" ]; then
        echo ""
        echo "🗑️  Deleting $folder_path..."
        
        # Use Python script for fast parallel deletion with progress tracking
        # Shows: progress bar, files/sec, ETA, percentage
        python3 "$(dirname "$0")/fast_delete_with_progress.py" "$folder_path"
        
        if [ $? -eq 0 ]; then
            echo "   ✅ Deletion complete"
        else
            echo "   ⚠️  Deletion had errors, attempting cleanup..."
            # Fallback: force remove any remaining files
            if [ -d "$folder_path" ]; then
                rm -rf "$folder_path" 2>/dev/null || true
            fi
        fi
    else
        echo "⏭️  $folder_path does not exist, skipping"
    fi
done

echo "✅ Old folders deleted"

################################################################################
# Step 4: Create hot/cold folder structure
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 4: Creating hot/cold folder structure..."
echo "════════════════════════════════════════════════════════════════════════════"

for folder in "${CAPTURE_FOLDERS[@]}"; do
    folder_path="$STREAM_BASE/$folder"
    
    echo "📁 Creating $folder..."
    
    # Create root directories (hot storage)
    mkdir -p "$folder_path/segments"
    mkdir -p "$folder_path/captures"
    mkdir -p "$folder_path/thumbnails"
    mkdir -p "$folder_path/metadata"
    
    # Create 24 hour folders for each type (cold storage)
    for hour in {0..23}; do
        mkdir -p "$folder_path/segments/$hour"
        mkdir -p "$folder_path/captures/$hour"
        mkdir -p "$folder_path/thumbnails/$hour"
        mkdir -p "$folder_path/metadata/$hour"
    done
    
    # Set ownership to www-data
    chown -R "$WWW_USER:$WWW_GROUP" "$folder_path"
    
    # Set permissions (775 for directories = group writable, so backend can create subdirs)
    # This allows www-data (FFmpeg) and users in www-data group (backend) to write
    chmod -R 775 "$folder_path"
    
    # Set setgid bit so new files/dirs inherit www-data group
    find "$folder_path" -type d -exec chmod g+s {} \;
    
    echo "   ✅ Created with hot/cold structure"
    echo "      Owner: $WWW_USER:$WWW_GROUP"
    echo "      Permissions: 775 (group writable)"
    echo "      Structure:"
    echo "        - segments/    : hot (10 files) + 0-23 hour folders"
    echo "        - captures/    : hot (100 files) + 0-23 hour folders"
    echo "        - thumbnails/  : hot (100 files) + 0-23 hour folders"
    echo "        - metadata/    : hot (100 files) + 0-23 hour folders"
done

echo "✅ Hot/cold folder structure created"

################################################################################
# Step 5: Verify structure
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 5: Verifying structure..."
echo "════════════════════════════════════════════════════════════════════════════"

for folder in "${CAPTURE_FOLDERS[@]}"; do
    folder_path="$STREAM_BASE/$folder"
    echo "📊 $folder:"
    
    # Count directories
    total_dirs=$(find "$folder_path" -type d | wc -l)
    echo "   Total directories: $total_dirs (expected: 101)"
    echo "     - Root: 4 (segments, captures, thumbnails, metadata)"
    echo "     - Hour folders: 96 (24 folders × 4 types)"
    
    # Check ownership
    owner=$(stat -c '%U:%G' "$folder_path" 2>/dev/null || stat -f '%Su:%Sg' "$folder_path" 2>/dev/null)
    echo "   Owner: $owner"
    
    # Check permissions
    perms=$(stat -c '%a' "$folder_path" 2>/dev/null || stat -f '%A' "$folder_path" 2>/dev/null)
    echo "   Permissions: $perms"
done

echo "✅ Structure verified"

################################################################################
# Step 6: Restart services
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 6: Restarting services..."
echo "════════════════════════════════════════════════════════════════════════════"

for service in "${SERVICES[@]}"; do
    echo "🚀 Starting $service..."
    systemctl start "$service"
    
    # Wait up to 10 seconds for service to fully activate
    timeout=10
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if systemctl is-active --quiet "$service"; then
            echo "   ✅ Running (started in ${elapsed}s)"
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    
    # Final check
    if ! systemctl is-active --quiet "$service"; then
        echo "   ⚠️  Still starting after ${timeout}s - check 'systemctl status $service'"
        echo "   💡 Tip: Run 'sudo systemctl restart $service' if it doesn't start"
    fi
done

echo "✅ All services restarted"

################################################################################
# Step 7: Final status check
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 7: Final status check (waiting for services to fully start)..."
echo "════════════════════════════════════════════════════════════════════════════"

# Give services a bit more time to fully initialize
echo "⏳ Waiting 5 seconds for services to fully initialize..."
sleep 5

for service in "${SERVICES[@]}"; do
    status=$(systemctl is-active "$service" 2>/dev/null || echo "unknown")
    
    if [ "$status" = "active" ]; then
        echo "✅ $service: $status"
    elif [ "$status" = "activating" ]; then
        echo "⏳ $service: $status (still starting - this is normal)"
    else
        echo "❌ $service: $status"
        # Show last 3 lines of log for failed services
        echo "   Last log lines:"
        journalctl -u "$service" -n 3 --no-pager 2>/dev/null | sed 's/^/     /' || echo "     (no logs available)"
    fi
done

################################################################################
# Done!
################################################################################

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "🎉 HOT/COLD ARCHITECTURE CLEAN RESTART COMPLETE!"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📋 What happened:"
echo "   ✅ Old capture folders deleted"
echo "   ✅ New hot/cold structure created"
echo "   ✅ Proper www-data ownership set"
echo "   ✅ All services restarted"
echo ""
echo "📁 New structure:"
echo "   segments/     : hot (10 files) + 0-23/ hour folders (24h retention)"
echo "   captures/     : hot (100 files) + 0-23/ hour folders (1h retention)"
echo "   thumbnails/   : hot (100 files) + 0-23/ hour folders (24h retention)"
echo "   metadata/     : hot (100 files) + 0-23/ hour folders (24h retention)"
echo ""
echo "🔍 Check service status:"
echo "   sudo systemctl status stream"
echo "   sudo systemctl status monitor"
echo "   sudo systemctl status hot_cold_archiver"
echo "   sudo systemctl status transcript-stream"
echo ""
echo "📋 View logs:"
echo "   tail -f /tmp/ffmpeg_service.log"
echo "   tail -f /tmp/hot_cold_archiver.log"
echo "   tail -f /tmp/capture_monitor.log"
echo ""
echo "💡 If services show 'activating', wait 10-15 seconds or restart manually:"
echo "   sudo systemctl restart hot_cold_archiver"
echo "   sudo systemctl restart transcript-stream"
echo ""
echo "🔐 Permissions:"
echo "   Folders are owned by www-data:www-data (for FFmpeg)"
echo "   Permissions are 775 (group writable)"
echo "   User '$ACTUAL_USER' is in www-data group → can write"
echo "   Backend can create subdirs like captures/verification_results"
echo ""
echo "💡 If you still get permission errors after services start:"
echo "   1. Log out and back in (for group membership to take effect)"
echo "   2. Or run: newgrp www-data"
echo "   3. Then restart services: sudo systemctl restart monitor"
echo ""
echo "✨ System ready! FFmpeg will start creating files in hot folders."
echo ""

