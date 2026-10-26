#!/bin/bash

# VirtualPyTest - Proxmox VM Prerequisites Setup
# This script sets up Debian VMs with VirtualPyTest prerequisites
# Must be run as root on each VM
#
# Usage:
#   sudo bash install_prerequisites.sh                # the full prerequisites
#   sudo bash install_prerequisites.sh --journal-only # only the persistent journal
#
# --journal-only is the entry point the guest-image scripts call
# (setup/proxmox/vm/runner/install_android_emulator.sh): the persistent-journal
# logic lives here once, so both guest families (shared prerequisites and the
# Android emulator runner) get the same journal.
#
# It also repairs a guest that is ALREADY RUNNING: a guest that booted without
# /var/log/journal keeps a RAM-only journal for the life of that boot, and no
# restart flips it — journald adopts the directory only once a VALID journal
# file exists there, which is what `journalctl --flush` writes (measured on a
# live Proxmox guest, 2026-10-24).

set -e

# --- Arguments ---
JOURNAL_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --journal-only) JOURNAL_ONLY=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [ "$JOURNAL_ONLY" = true ]; then
    echo "🖥️ VirtualPyTest - Persistent journal setup"
else
    echo "🖥️ VirtualPyTest - Installing Proxmox VM Prerequisites"
    echo "   • System updates and base tools"
    echo "   • VirtualPyTest service account (vpt_user)"
    echo "   • Development tools"
    echo "   • Persistent system journal (survives a reboot)"
fi

# --- Persistent journal ------------------------------------------------------
# A guest that hangs (qemu at 100% of a core, network stack dead) is only
# diagnosable if its own journal survives the reboot: with the stock
# `#Storage=auto` and no /var/log/journal the journal lives in RAM
# (/run/log/journal) and dies with the boot, so the freeze leaves no trace.
# Storage=persistent writes it to disk; SystemMaxUse bounds it so a persistent
# journal cannot fill the guest disk.
JOURNAL_DIR="${VPT_JOURNAL_DIR:-/var/log/journal}"
JOURNAL_CONF="${VPT_JOURNAL_CONF:-/etc/systemd/journald.conf}"
JOURNAL_CONF_D="${VPT_JOURNAL_CONF_D:-/etc/systemd/journald.conf.d}"
JOURNAL_MAX_USE_OVERRIDE="$(printf '%s' "${VPT_JOURNAL_MAX_USE:-}" | tr -d '[:space:]')"

# ─── journald size cap (E61) ────────────────────────────────────────────────
# The size cap follows the host. A fixed 512 M is 19 % of the free space left
# on a disk that is 91 % full (measured on host-clone-1, 2026-10-24) — on the
# very filesystem the live capture writes to. So the cap is computed from the
# free space of the filesystem that holds the journal directory:
#     cap = min(512M, max(64M, 5 % of the free space))
# 64 M is the floor (a journald cap below that is not worth having) and 512 M
# the ceiling (the cap that shipped before). VPT_JOURNAL_MAX_USE overrides the
# computed value; when it is set, nothing is computed.
JOURNAL_CAP_DEFAULT_MB=512
JOURNAL_CAP_MIN_MB=64
JOURNAL_CAP_PERCENT=5

# Free space (KiB) of the filesystem that holds the journal directory. Empty
# when it cannot be read — the caller falls back to the default cap.
journal_free_kb() {
    local dir="${1:-/var/log/journal}" kb="" path
    command -v df >/dev/null 2>&1 || return 1
    for path in "$dir" "$(dirname "$dir")"; do
        kb="$(df -Pk "$path" 2>/dev/null | awk 'NR==2 {print $4}')"
        case "$kb" in
            ''|*[!0-9]*) continue ;;
        esac
        printf '%s\n' "$kb"
        return 0
    done
    return 1
}

# The cap in MiB (journald's "M" is 1024*1024) for a free space in KiB: 5 % of
# it, never below 64 M and never above 512 M.
journal_cap_mb() {
    local free_kb="${1:-0}" cap_mb
    cap_mb=$(( free_kb * JOURNAL_CAP_PERCENT / 100 / 1024 ))
    if [ "$cap_mb" -lt "$JOURNAL_CAP_MIN_MB" ]; then cap_mb="$JOURNAL_CAP_MIN_MB"; fi
    if [ "$cap_mb" -gt "$JOURNAL_CAP_DEFAULT_MB" ]; then cap_mb="$JOURNAL_CAP_DEFAULT_MB"; fi
    printf '%s\n' "$cap_mb"
}

# The cap to use: the explicit override wins and nothing is computed; without
# it the cap follows the free space of the filesystem holding the journal
# directory, and the default cap is used when that cannot be read.
journal_max_use() {
    local override="${1:-}" free_kb cap_mb
    override="$(printf '%s' "$override" | tr -d '[:space:]')"
    if [ -n "$override" ]; then
        printf '%s\n' "$override"
        return 0
    fi
    free_kb="$(journal_free_kb "${JOURNAL_DIR:-/var/log/journal}" || true)"
    if [ -z "$free_kb" ]; then
        printf '%s\n' "${JOURNAL_CAP_DEFAULT_MB}M"
        return 0
    fi
    cap_mb="$(journal_cap_mb "$free_kb")"
    printf '%s\n' "${cap_mb}M"
}

# Where the cap came from, for the script's output: the explicit override, the
# computed value, or the default because the free space could not be read.
journal_cap_reason() {
    local override="${1:-}"
    if [ -n "$override" ]; then
        printf 'VPT_JOURNAL_MAX_USE\n'
        return 0
    fi
    if journal_free_kb "${JOURNAL_DIR:-/var/log/journal}" >/dev/null 2>&1; then
        printf '5%% of the free space of the journal filesystem\n'
    else
        printf 'default - the free space of the journal filesystem could not be read\n'
    fi
}

# The cap drop-in both provisioning paths write, byte for byte: the same
# SystemMaxUse in the file the host installer writes and in the file the guest
# script writes, or the last writer wins with a different cap.
journal_cap_dropin_body() {
    local cap="${1:-${JOURNAL_CAP_DEFAULT_MB}M}"
    cat << EOF
# Managed by VirtualPyTest — do not hand-edit.
# Journal size cap: 5% of the free space of the filesystem holding the journal
# directory, clamped to [64M, 512M]; VPT_JOURNAL_MAX_USE overrides it. The
# installers write this drop-in with the cap computed for the host. An
# uncapped journal reached 3.0 G on a 31 G disk (TASK-156).
[Journal]
SystemMaxUse=${cap}
SystemMaxFileSize=64M
EOF
}
# ─── end journald size cap (E61) ────────────────────────────────────────────

# Run a command as root: directly when we already are root, through sudo
# otherwise (the guest-image scripts call this one with sudo).
run_root() {
    if [ "$EUID" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "❌ root privileges are required ($*) — run as root or install sudo" >&2
        return 1
    fi
}

# The journald drop-in both provisioning paths write. install_host.sh (STEP 7b)
# and this script manage the SAME file (/etc/systemd/journald.conf.d/vpt.conf)
# and the last writer wins, so both must produce byte-identical content —
# tests/backend_host/test_journald_persistence.py asserts that they agree.
journald_dropin_body() {
    case "${1:-persistent}" in
        persistent)
            cat << 'EOF'
# Managed by VirtualPyTest — do not hand-edit.
# Written by setup/local/linux/backend_host/install_host.sh (STEP 7b) and
# setup/proxmox/vm/shared/install_prerequisites.sh --journal-only.
# See docs/agent/infra/HOST_SERVICE.md §8.
[Journal]
Storage=persistent
EOF
            ;;
        volatile)
            cat << 'EOF'
# Managed by VirtualPyTest — do not hand-edit.
# Written by setup/local/linux/backend_host/install_host.sh (STEP 7b) and
# setup/proxmox/vm/shared/install_prerequisites.sh --journal-only.
# See docs/agent/infra/HOST_SERVICE.md §8.
[Journal]
Storage=volatile
RuntimeMaxUse=300M
EOF
            ;;
    esac
}

# Write a file only when its content differs from what is already there, so a
# second run changes nothing at all (not even the mtime).
write_file_if_changed() {
    local target="$1" tmp
    tmp="$(mktemp)"
    cat > "$tmp"
    if [ -f "$target" ] && cmp -s "$tmp" "$target"; then
        rm -f "$tmp"
        return 0
    fi
    run_root mkdir -p "$(dirname "$target")"
    run_root tee "$target" > /dev/null < "$tmp"
    rm -f "$tmp"
}

# Set one key in the [Journal] section of a journald config file. Idempotent:
# the key is replaced in place where it already is (the stock file ships it
# commented out) and added to the [Journal] section only when it is absent —
# so a second run finds the same line and changes nothing.
journald_conf_set() {
    local conf="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)"
    if [ -f "$conf" ]; then
        if grep -qE "^[[:space:]]*#?[[:space:]]*${key}=" "$conf"; then
            # The key is already there: replace its first mention in place and
            # drop the others.
            awk -v key="$key" -v value="$value" '
                BEGIN { done = 0 }
                {
                    if ($0 ~ ("^[[:space:]]*#?[[:space:]]*" key "=")) {
                        if (!done) { print key "=" value; done = 1 }
                        next
                    }
                    print
                }
            ' "$conf" > "$tmp"
        else
            # The key is absent: add it to the [Journal] section.
            awk -v key="$key" -v value="$value" '
                BEGIN { done = 0 }
                {
                    print
                    if (!done && $0 ~ "^[[:space:]]*\\[Journal\\]") { print key "=" value; done = 1 }
                }
                END {
                    if (!done) {
                        print "[Journal]"
                        print key "=" value
                    }
                }
            ' "$conf" > "$tmp"
        fi
    else
        printf '[Journal]\n%s=%s\n' "$key" "$value" > "$tmp"
    fi
    write_file_if_changed "$conf" < "$tmp"
    rm -f "$tmp"
}

# Name the file that sets the effective Storage=, so the next reader does not
# have to rediscover the drop-in precedence: a drop-in in journald.conf.d/
# overrides the main config file, whatever it says.
report_storage_sources() {
    local out
    out="$(run_root systemd-analyze cat-config systemd/journald.conf 2>/dev/null || true)"
    if [ -z "$out" ]; then
        echo "   (systemd-analyze cat-config is unavailable — cannot show the effective Storage=)" >&2
        return 0
    fi
    printf '%s\n' "$out" | awk '
        /^#[[:space:]]*(\/|[Cc]onfig file:)/ {
            file = $0
            sub(/^#[[:space:]]*/, "", file)
            sub(/^[Cc]onfig file:[[:space:]]*/, "", file)
            next
        }
        /^[[:space:]]*Storage=/ { printf "   → %s sets %s\n", (file == "" ? "journald.conf" : file), $0 }
    ' >&2
}

# journald adopts /var/log/journal only when a VALID journal file exists
# there. Measured on a live Proxmox guest (2026-10-24), with Storage=persistent
# in every config file and the directory present with the right ownership:
#   - `systemd-tmpfiles --create --prefix /var/log/journal` → exit 0, created
#     nothing; the same with every rule (no --prefix) → exit 0, created nothing;
#   - a planted 0-byte file → "Journal file ... is truncated, ignoring file";
#   - `journalctl --flush` → writes a valid <machine-id>/system.journal (and
#     <machine-id>/user-<uid>.journal) with the right ownership, and the next
#     restart of systemd-journald serves it.
# So the flush is the step that makes a RUNNING guest adopt the journal.
flush_journal_to_disk() {
    if run_root journalctl --flush; then
        return 0
    fi
    echo "❌ journalctl --flush failed — journald cannot write a journal file under $JOURNAL_DIR" >&2
    echo "   (a drop-in in $JOURNAL_CONF_D may set a different Storage=)" >&2
    report_storage_sources
    return 1
}

# Fail loudly when the journal is still RAM-only: a guest built with this
# script must never ship a journal that dies with the boot.
verify_persistent_journal() {
    local dir="$1" conf="$2" dropin="$3" usage paths file
    if [ ! -d "$dir" ]; then
        echo "❌ $dir does not exist — the journal is still RAM-only" >&2
        return 1
    fi
    if ! grep -qE "^[[:space:]]*Storage=persistent" "$conf" 2>/dev/null; then
        echo "❌ $conf does not set Storage=persistent" >&2
        return 1
    fi
    if ! grep -qE "^[[:space:]]*Storage=persistent" "$dropin" 2>/dev/null; then
        echo "❌ $dropin does not set Storage=persistent — a drop-in in $JOURNAL_CONF_D overrides $conf" >&2
        return 1
    fi
    # A journal FILE, not only the directory: an empty directory (or a 0-byte
    # file) is not enough for journald to adopt the persistent journal.
    file="$(find "$dir" -type f -name '*.journal' 2>/dev/null | head -n 1)"
    if [ -z "$file" ]; then
        echo "❌ no journal file under $dir — journald does not adopt an empty directory" >&2
        echo "   (journalctl --flush writes the valid <machine-id>/system.journal journald adopts)" >&2
        report_storage_sources
        return 1
    fi
    usage="$(run_root journalctl --disk-usage 2>/dev/null || true)"
    if [ -z "$usage" ]; then
        echo "❌ journalctl --disk-usage reported nothing — journald serves no journal" >&2
        return 1
    fi
    # The journal files journald serves must live under $dir. journalctl prints
    # one "File path:" line per file it opened.
    paths="$(run_root journalctl --header 2>/dev/null | sed -n 's/^[Ff]ile [Pp]ath: //p')"
    if [ -z "$paths" ]; then
        paths="$file"
    fi
    if printf '%s\n' "$paths" | grep -q "^${dir}/"; then
        echo "   ✅ persistent journal active under $dir"
        echo "      $usage"
    else
        echo "❌ the journal is not under $dir (found: ${paths:-nothing}) — it is still RAM-only" >&2
        echo "   (a drop-in in $JOURNAL_CONF_D may override Storage=)" >&2
        report_storage_sources
        return 1
    fi
}

# Make the journal persistent and bounded, then verify it took effect.
enable_persistent_journal() {
    echo "   → Journal directory: $JOURNAL_DIR"
    # journald refuses a journal directory it does not own (root:<journal
    # group>, mode 2755) and silently falls back to the RAM journal, so the
    # directory is created first and systemd-tmpfiles then applies the
    # distribution's own rule for it.
    run_root mkdir -p "$JOURNAL_DIR"
    run_root systemd-tmpfiles --create --prefix "$JOURNAL_DIR" || true
    # The size cap follows the host (E61): it is computed from the free space
    # of the filesystem that holds the journal directory, and the SAME number
    # goes into the drop-in and into the vacuum — the two must agree, or the
    # vacuum and the cap disagree and the drop-in silently loses.
    JOURNAL_CAP="$(journal_max_use "$JOURNAL_MAX_USE_OVERRIDE")"
    echo "   → journald size cap: $JOURNAL_CAP ($(journal_cap_reason "$JOURNAL_MAX_USE_OVERRIDE"))"
    journald_conf_set "$JOURNAL_CONF" "Storage" "persistent"
    journald_conf_set "$JOURNAL_CONF" "SystemMaxUse" "$JOURNAL_CAP"
    # The cap goes into the drop-in as well: a drop-in overrides the main
    # config file, so the value written there is the one that counts — and it
    # must be the same value the host installer writes (byte for byte), or the
    # last writer wins with a different cap.
    journal_cap_dropin_body "$JOURNAL_CAP" | write_file_if_changed "$JOURNAL_CONF_D/90-vpt-cap.conf" \
        || echo "⚠️  could not write the journald size cap ($JOURNAL_CONF_D/90-vpt-cap.conf)"
    # The setting has to live in the DROP-IN: a drop-in in journald.conf.d/
    # overrides the main config file, so Storage=persistent in journald.conf
    # alone loses against any drop-in — that is how the live guest stayed
    # RAM-only (the host installer's own vpt.conf said volatile).
    journald_dropin_body persistent | write_file_if_changed "$JOURNAL_CONF_D/vpt.conf"
    run_root journalctl --vacuum-size="$JOURNAL_CAP" >/dev/null 2>&1 || true
    if ! run_root systemctl restart systemd-journald; then
        echo "❌ systemd-journald failed to restart — the journal configuration is broken" >&2
        return 1
    fi
    # journald now runs in persistent mode; flush the runtime journal to disk
    # so a VALID journal file exists under $JOURNAL_DIR. Without this the
    # guest keeps serving the RAM journal (measured 2026-10-24).
    if ! flush_journal_to_disk; then
        return 1
    fi
    if ! run_root systemctl restart systemd-journald; then
        echo "❌ systemd-journald failed to restart after the flush" >&2
        return 1
    fi
    verify_persistent_journal "$JOURNAL_DIR" "$JOURNAL_CONF" "$JOURNAL_CONF_D/vpt.conf"
}

if [ "$JOURNAL_ONLY" = true ]; then
    enable_persistent_journal
    exit 0
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the VM"
   echo "Usage: sudo bash install_prerequisites.sh [--journal-only]"
   exit 1
fi

# Fix IPv6 issues by preferring IPv4 for apt
#echo "🔧 Configuring apt to prefer IPv4 over IPv6..."
#echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# System update (with IPv4 preference)
echo "📦 Updating system packages..."
apt update
if [ $? -ne 0 ]; then
    echo "⚠️ apt update failed, trying with IPv4-only..."
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
    apt update
fi
apt upgrade -y

# Install sudo if not present
echo "🔧 Installing sudo..."
apt install -y sudo

# Install base tools with error handling
echo "📦 Installing base tools..."
if ! apt install -y curl wget nano htop net-tools git dnsutils lsof nfs-common rsync; then
    echo "⚠️ First attempt failed, retrying with IPv4 preference..."
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
    apt update
    apt install -y curl wget nano htop net-tools git dnsutils lsof nfs-common rsync
fi

# Persistent journal: a guest that hangs must leave a readable trace
echo ""
echo "📓 Enabling a persistent journal (survives a reboot)..."
enable_persistent_journal

# Configure PATH
    export PATH=$PATH:/usr/sbin:/sbin

# Create VirtualPyTest service account (vpt_user)
echo "👤 Creating VirtualPyTest service account..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/create_vpt_user.sh" ]; then
    bash "$SCRIPT_DIR/create_vpt_user.sh"
else
    echo "❌ create_vpt_user.sh script not found in $SCRIPT_DIR"
    exit 1
fi

echo ""
echo "🎉 VM prerequisites setup complete!"
echo ""
echo "📋 Next Steps:"
echo "   1. Mount NFS share: ./setup/proxmox/vm/scripts/mount_nfs_shared.sh"
echo "   2. Install service-specific software (e.g., ./setup/local/install_server.sh)"
echo ""
echo "🔧 VM is ready for VirtualPyTest service installation!"