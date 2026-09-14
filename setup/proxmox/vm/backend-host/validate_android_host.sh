#!/bin/bash

# VirtualPyTest - Android Emulator Host Post-Clone Validator
# Run this INSIDE the VM after cloning a host or runner template.
# It checks and fixes all known issues that break emulator hosts.
#
# Usage: sudo bash validate_android_host.sh
# Docs:  docs/agent/devices/EMULATOR.md

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
ERRORS=0

pass() { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; ERRORS=$((ERRORS + 1)); }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  VirtualPyTest — Android Emulator Host Validator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. KVM ──────────────────────────────────────────────────────────
echo "── KVM (Nested Virtualization) ──"
if [ -e /dev/kvm ]; then
    pass "/dev/kvm exists"
else
    fail "/dev/kvm missing — VM CPU type must be 'host' in Proxmox"
    echo "     Fix on Proxmox: sudo qm stop <vmid> && sudo qm set <vmid> --cpu host && sudo qm start <vmid>"
fi

if grep -qE "vmx|svm" /proc/cpuinfo 2>/dev/null; then
    FLAG=$(grep -oE "vmx|svm" /proc/cpuinfo | head -1)
    pass "CPU virtualization flag present ($FLAG)"
else
    fail "No vmx/svm CPU flag — Proxmox VM CPU type is not 'host'"
fi
echo ""

# ── 2. Filesystem ──────────────────────────────────────────────────
echo "── Root Filesystem ──"
ROOT_MOUNT=$(mount | grep "on / " | head -1)
if echo "$ROOT_MOUNT" | grep -q "(rw"; then
    pass "Root filesystem is read-write"
else
    fail "Root filesystem is READ-ONLY"
    echo "     Immediate fix: sudo mount -o remount,rw /"
fi

if grep -q " / " /etc/fstab; then
    pass "Root partition is in /etc/fstab"
else
    fail "Root partition MISSING from /etc/fstab — will go read-only on reboot"
    ROOT_UUID=$(findmnt -no UUID / 2>/dev/null || blkid -s UUID -o value "$(findmnt -no SOURCE /)" 2>/dev/null || echo "UNKNOWN")
    echo "     Fix: echo 'UUID=$ROOT_UUID / ext4 errors=remount-ro 0 1' | sudo tee -a /etc/fstab"
fi

if touch /tmp/.validate_write_test 2>/dev/null; then
    rm -f /tmp/.validate_write_test
    pass "/tmp is writable (ADB needs this)"
else
    fail "/tmp is not writable — ADB will fail"
fi
echo ""

# ── 3. Android SDK & AVD ──────────────────────────────────────────
echo "── Android SDK & AVD ──"
SDK_PATH=""
for candidate in /home/jndoye/android-sdk /mnt/avd-storage/android-sdk; do
    if [ -x "$candidate/emulator/emulator" ]; then
        SDK_PATH="$candidate"
        break
    fi
done

if [ -n "$SDK_PATH" ]; then
    pass "Android SDK found at $SDK_PATH"
else
    fail "Android SDK not found at /home/jndoye/android-sdk or /mnt/avd-storage/android-sdk"
fi

AVD_HOME=""
for candidate in /home/jndoye/.android/avd /mnt/avd-storage/.android/avd; do
    if [ -f "$candidate/pixel6.ini" ]; then
        AVD_HOME="$candidate"
        break
    fi
done

if [ -n "$AVD_HOME" ]; then
    pass "AVD home found at $AVD_HOME (pixel6)"

    # Check AVD config for known issues
    AVD_DIR=$(grep "^path=" "$AVD_HOME/pixel6.ini" | cut -d= -f2)
    if [ -d "$AVD_DIR" ] && [ -f "$AVD_DIR/config.ini" ]; then
        ABI=$(grep "^abi.type" "$AVD_DIR/config.ini" | cut -d= -f2 | tr -d ' ')
        if [ "$ABI" = "x86_64" ]; then
            pass "AVD ABI is x86_64"
        else
            fail "AVD ABI is '$ABI' — should be x86_64 for KVM acceleration"
            echo "     Fix: sed -i 's/abi.type = .*/abi.type = x86_64/' $AVD_DIR/config.ini"
        fi

        CPU_ARCH=$(grep "^hw.cpu.arch" "$AVD_DIR/config.ini" | cut -d= -f2 | tr -d ' ')
        if [ "$CPU_ARCH" = "x86_64" ]; then
            pass "AVD CPU arch is x86_64"
        else
            fail "AVD CPU arch is '$CPU_ARCH' — should be x86_64"
            echo "     Fix: sed -i 's/hw.cpu.arch = .*/hw.cpu.arch = x86_64/' $AVD_DIR/config.ini"
        fi

        # Check for duplicate/conflicting image.sysdir.1
        SYSDIR_COUNT=$(grep -c "^image.sysdir.1" "$AVD_DIR/config.ini" 2>/dev/null || echo 0)
        if [ "$SYSDIR_COUNT" -gt 1 ]; then
            fail "AVD config has $SYSDIR_COUNT image.sysdir.1 entries — duplicates cause boot issues"
            echo "     Fix: remove stale entries, keep only: image.sysdir.1 = system-images/android-33/google_apis/x86_64"
        else
            pass "AVD config has no duplicate image.sysdir.1"
        fi
    else
        warn "AVD data dir not found at $AVD_DIR — emulator may need -wipe-data on first run"
    fi
else
    fail "No pixel6 AVD found"
fi
echo ""

# ── 4. ADB & Emulator ─────────────────────────────────────────────
echo "── ADB & Emulator ──"
if command -v adb &>/dev/null; then
    pass "ADB is installed"
    DEVICES=$(adb devices 2>/dev/null | grep -c "device$" || true)
    if [ "$DEVICES" -gt 0 ]; then
        pass "ADB sees $DEVICES device(s)"
    else
        warn "ADB sees no devices — emulator may not be running yet"
    fi
else
    fail "ADB not found in PATH"
fi

if pgrep -f "qemu-system.*x86_64" >/dev/null 2>&1; then
    pass "Emulator is running (qemu-system-x86_64)"
elif pgrep -f "qemu-system.*i386" >/dev/null 2>&1; then
    fail "Emulator is running as i386 (32-bit) — fix AVD ABI to x86_64"
else
    warn "Emulator is not running"
fi
echo ""

# ── 5. VPT .env (DEVICE1_VIDEO) ──────────────────────────────────
echo "── VPT Configuration ──"
ENV_FILE="/opt/virtualpytest/backend_host/src/.env"
if [ -f "$ENV_FILE" ]; then
    pass ".env exists at $ENV_FILE"

    DEVICE1_VIDEO=$(grep "^DEVICE1_VIDEO=" "$ENV_FILE" | cut -d= -f2 | head -1)
    if [ -n "$DEVICE1_VIDEO" ]; then
        if echo "$DEVICE1_VIDEO" | grep -q "emulator_frames/latest.png"; then
            pass "DEVICE1_VIDEO points to emulator frame source"
        else
            fail "DEVICE1_VIDEO=$DEVICE1_VIDEO — should be /var/www/html/stream/emulator_frames/latest.png"
            echo "     Fix: sed -i 's|^DEVICE1_VIDEO=.*|DEVICE1_VIDEO=/var/www/html/stream/emulator_frames/latest.png|' $ENV_FILE"
            echo "     Then: sudo systemctl restart vpt-stream.service"
        fi
    else
        warn "DEVICE1_VIDEO not set in .env"
    fi
else
    warn ".env not found at $ENV_FILE (may not be installed yet)"
fi
echo ""

# ── 6. Emulator frame directory ───────────────────────────────────
echo "── Emulator Frame Pipeline ──"
FRAME_DIR="/var/www/html/stream/emulator_frames"
if [ -d "$FRAME_DIR" ]; then
    pass "Frame directory exists: $FRAME_DIR"
    if [ -f "$FRAME_DIR/latest.png" ]; then
        AGE=$(( $(date +%s) - $(stat -c %Y "$FRAME_DIR/latest.png") ))
        if [ "$AGE" -lt 10 ]; then
            pass "latest.png is fresh (${AGE}s old)"
        else
            warn "latest.png is stale (${AGE}s old) — screencap loop may be broken"
        fi
    else
        warn "latest.png not found — vpt-emulator-fifo.service may not be running"
    fi
else
    warn "Frame directory missing — will be created by vpt-emulator-fifo.service"
fi

if systemctl is-active --quiet vpt-emulator-fifo.service 2>/dev/null; then
    pass "vpt-emulator-fifo.service is active"
else
    warn "vpt-emulator-fifo.service is not active"
fi
echo ""

# ── Summary ────────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
else
    echo -e "${RED}$ERRORS issue(s) found — fix them before starting the emulator.${NC}"
    echo ""
    echo "Quick reference: docs/agent/devices/EMULATOR.md"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit $ERRORS
