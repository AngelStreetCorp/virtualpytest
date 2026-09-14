#!/bin/bash
# Redirect /var/www/html/stream onto the large dedicated data disk (/data).
#
# Why: on some hosts the capture/stream tree was left on the small OS root
# (sda1, ~30G) while a large empty data disk sits unused at /data. This points
# the stream tree at /data via a symlink, then re-runs setup_ram_hot_storage.sh
# which is symlink-aware (resolves the real path with realpath) and rebuilds the
# tmpfs hot mounts + /etc/fstab against the new location.
#
# WARNING: this DESTROYS the current contents of /var/www/html/stream.
#          Stream/capture data is disposable runtime output, so this is safe,
#          but be aware nothing under it is preserved.
#
# Usage:  sudo ./redirect_stream_to_data.sh

set -euo pipefail

STREAM_LINK="/var/www/html/stream"
DATA_MOUNT="/data"
DATA_TARGET="$DATA_MOUNT/stream"
STORAGE_SCRIPT="/opt/virtualpytest/setup/local/linux/backend_host/setup_ram_hot_storage.sh"
STREAM_SERVICES=(vpt-stream vpt-monitor vpt-archiver vpt-transcript vpt-kpi)
# Optional feature services that read the stream tree (features/<name>/backend_host/services/*.service)
for _unit in /opt/virtualpytest/features/*/backend_host/services/*.service; do
    [ -f "$_unit" ] || continue
    _name="$(basename "$_unit" .service)"
    case "$_name" in *@) continue ;; esac
    STREAM_SERVICES+=("vpt-$_name")
done

if [ "$EUID" -ne 0 ]; then
    echo "❌ Run with sudo: sudo $0"
    exit 1
fi

# --- Sanity checks -----------------------------------------------------------
if ! mountpoint -q "$DATA_MOUNT"; then
    echo "❌ $DATA_MOUNT is not a mounted filesystem — aborting (nothing changed)"
    exit 1
fi

if [ -L "$STREAM_LINK" ] && [ "$(readlink -f "$STREAM_LINK")" = "$DATA_TARGET" ]; then
    echo "ℹ️  $STREAM_LINK already points at $DATA_TARGET — re-running storage setup only."
    SKIP_RELINK=1
else
    SKIP_RELINK=0
fi

if [ ! -x "$STORAGE_SCRIPT" ]; then
    echo "❌ Storage script not found/executable: $STORAGE_SCRIPT"
    exit 1
fi

echo "==> Stopping stream services..."
systemctl stop "${STREAM_SERVICES[@]}" 2>/dev/null || true

echo "==> Unmounting any tmpfs hot mounts under $STREAM_LINK..."
# Deepest paths first so nested mounts unmount cleanly.
while read -r m; do
    [ -z "$m" ] && continue
    echo "   umount $m"
    umount "$m" 2>/dev/null || umount -l "$m" 2>/dev/null || true
done < <(mount | awk '{print $3}' | grep -E "^${STREAM_LINK}/" | sort -r)

if [ "$SKIP_RELINK" -eq 0 ]; then
    echo "==> Removing old $STREAM_LINK (data loss accepted)..."
    rm -rf "$STREAM_LINK"

    echo "==> Creating $DATA_TARGET and symlinking $STREAM_LINK -> $DATA_TARGET..."
    mkdir -p "$DATA_TARGET"
    chown vpt_user:vpt_user "$DATA_TARGET"
    chmod 755 "$DATA_TARGET"
    ln -s "$DATA_TARGET" "$STREAM_LINK"
fi

echo "   $STREAM_LINK -> $(readlink -f "$STREAM_LINK")"

echo "==> Re-running storage setup (recreates dirs, remounts tmpfs, fixes fstab)..."
"$STORAGE_SCRIPT"

echo "==> Restarting stream services..."
systemctl start "${STREAM_SERVICES[@]}" 2>/dev/null || true

echo ""
echo "==> Verification:"
ls -ld "$STREAM_LINK"
echo "   stream backing device: $(findmnt -no SOURCE -T "$DATA_TARGET" 2>/dev/null || echo '?')"
df -h "$DATA_TARGET" | sed 's/^/   /'
echo ""
echo "✅ Done. /var/www/html/stream now lives on $DATA_MOUNT."
