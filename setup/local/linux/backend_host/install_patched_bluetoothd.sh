#!/usr/bin/env bash
# Build and install the patched `bluetoothd` that persists external-app
# CCCD subscriptions. The BLE remote stack (backend_host/src/controllers/
# remote/bluetooth/) relies on this patch so STB reboots re-subscribe
# automatically instead of forcing a re-pair.
#
# Idempotent: skips the whole build if the patched binary is already in
# /opt/bluez-cccpatch-v2/ and the systemd override is pointing at it.
#
# Safe to run as part of install_host.sh. Stock /usr/libexec/bluetooth/
# bluetoothd is never overwritten — we build a parallel binary in /opt
# and flip bluetooth.service's ExecStart via a drop-in override.
#
# See docs/agent/devices/BLUETOOTH.md § 6.7.4 and § 6.8.x for context.

set -euo pipefail

# ---------- Paths ------------------------------------------------------------
PATCHED_PREFIX=/opt/bluez-cccpatch-v2
PATCHED_BIN="${PATCHED_PREFIX}/usr/libexec/bluetooth/bluetoothd"
OVERRIDE_DIR=/etc/systemd/system/bluetooth.service.d
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
OVERRIDE_STOCK_BACKUP="${OVERRIDE_DIR}/override.conf.stock"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
PATCH_APPLIER="${PROJECT_ROOT}/backend_host/src/controllers/remote/bluetooth/bluez-patches/apply_ccc_patch.py"

BUILD_ROOT="${BUILD_ROOT:-/tmp/bluez-cccpatch-build}"
FORCE_REBUILD="${FORCE_REBUILD:-0}"

log()  { printf '[install_patched_bluetoothd] %s\n' "$*"; }
warn() { printf '[install_patched_bluetoothd] WARN: %s\n' "$*" >&2; }
die()  { printf '[install_patched_bluetoothd] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------- Preconditions ----------------------------------------------------
[[ -f "${PATCH_APPLIER}" ]] || die "patch applier not found at ${PATCH_APPLIER}"

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo -E "${BASH_SOURCE[0]}" "$@"
fi

# ---------- Skip-if-already-installed ---------------------------------------
if [[ "${FORCE_REBUILD}" != "1" && -x "${PATCHED_BIN}" ]]; then
    if grep -Fq "${PATCHED_BIN}" "${OVERRIDE_FILE}" 2>/dev/null; then
        log "patched bluetoothd already installed at ${PATCHED_BIN}"
        log "override already points at it; nothing to do"
        log "(set FORCE_REBUILD=1 to rebuild anyway)"
        exit 0
    else
        warn "patched binary exists but override is missing/stale — will rewrite override only"
        install_override_only=1
    fi
else
    install_override_only=0
fi

# ---------- Detect BlueZ version --------------------------------------------
if ! command -v bluetoothd >/dev/null 2>&1; then
    # Try the usual path; some distros hide bluetoothd from $PATH.
    BLUETOOTHD_BIN=/usr/libexec/bluetooth/bluetoothd
    [[ -x "${BLUETOOTHD_BIN}" ]] || die "bluetoothd not installed (apt install bluez)"
else
    BLUETOOTHD_BIN=$(command -v bluetoothd)
fi

BLUEZ_VERSION=$("${BLUETOOTHD_BIN}" -v 2>&1 | head -1 | tr -d '[:space:]')
[[ -n "${BLUEZ_VERSION}" ]] || die "could not detect BlueZ version via ${BLUETOOTHD_BIN} -v"
log "system BlueZ version: ${BLUEZ_VERSION}"

# ---------- Override-only path ----------------------------------------------
install_override() {
    mkdir -p "${OVERRIDE_DIR}"
    if [[ -f "${OVERRIDE_FILE}" && ! -f "${OVERRIDE_STOCK_BACKUP}" ]]; then
        cp "${OVERRIDE_FILE}" "${OVERRIDE_STOCK_BACKUP}"
        log "backed up existing override to ${OVERRIDE_STOCK_BACKUP}"
    fi
    cat > "${OVERRIDE_FILE}" <<EOF
# Managed by setup/local/linux/backend_host/install_patched_bluetoothd.sh
# Points bluetooth.service at the patched bluetoothd built alongside the
# VirtualPyTest BLE remote stack. The patch persists external-app CCCD
# subscriptions in /var/lib/bluetooth/<adapter>/<peer>/info so STB reboots
# reconnect without re-pairing. See docs/agent/devices/BLUETOOTH.md § 6.7.4.
[Service]
ExecStart=
ExecStart=${PATCHED_BIN} --noplugin=policy,input -d
EOF
    log "wrote ${OVERRIDE_FILE}"
    systemctl daemon-reload
    systemctl restart bluetooth.service
    log "restarted bluetooth.service"
}

if [[ "${install_override_only}" == "1" ]]; then
    install_override
    log "done (override-only path)"
    exit 0
fi

# ---------- Build path ------------------------------------------------------
log "building patched bluetoothd (this takes a few minutes)"

# Ensure deb-src is available — apt source fails silently with no sources.
if ! apt-get source --print-uris bluez >/dev/null 2>&1; then
    log "apt source bluez unavailable — enabling deb-src entries"
    # Only the distribution's own repositories qualify (never a third-party list such as
    # packagecloud: on Ubuntu 24.04 the distro sources are deb822 files with no `deb ` line,
    # and copying whatever `deb … main` line exists produced a deb-src for a dead repo that
    # then broke every apt-get update on the machine).
    rm -f /etc/apt/sources.list.d/99-bluez-cccpatch-src.list /etc/apt/sources.list.d/99-bluez-cccpatch-src.sources
    # `|| true`: under set -e -o pipefail an empty grep would otherwise end the script here, silently.
    SRC_LIST=$({ grep -rshE "^deb (\[[^]]*\] )?https?://[^ ]*(debian\.org|ubuntu\.com|raspbian\.org|raspberrypi\.(org|com))[^ ]* .* main" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true; } | head -1 | sed 's/^deb /deb-src /')
    DEB822=$({ grep -lsE "^URIs: .*(debian\.org|ubuntu\.com|raspbian\.org)" /etc/apt/sources.list.d/*.sources 2>/dev/null || true; } | head -1)
    if [[ -n "${SRC_LIST}" ]]; then
        echo "${SRC_LIST}" | tee /etc/apt/sources.list.d/99-bluez-cccpatch-src.list
        apt-get update
    elif [[ -n "${DEB822}" ]]; then
        # deb822: same entries as the distro file, sources only
        sed -E 's/^Types: .*/Types: deb-src/' "${DEB822}" | tee /etc/apt/sources.list.d/99-bluez-cccpatch-src.sources >/dev/null
        apt-get update
    else
        die "could not derive deb-src line; enable deb-src in /etc/apt/sources.list manually and re-run"
    fi
fi

log "installing bluez build dependencies (apt build-dep bluez)"
apt-get install -y --no-install-recommends dpkg-dev
apt-get build-dep -y bluez
# libbluetooth-dev is NOT pulled in by `apt build-dep bluez` (it's BlueZ's own
# output, not a dep) but recent BlueZ source trees still expect the system
# `<bluetooth/*.h>` headers to exist for some include paths. Install it
# explicitly to avoid "fatal error: bluetooth/bluetooth.h: No such file" on
# trixie / 5.82+. Harmless on older distros where build-dep already covers it.
apt-get install -y --no-install-recommends libbluetooth-dev

mkdir -p "${BUILD_ROOT}"
cd "${BUILD_ROOT}"

# Remove any previous source tree so we always patch a clean tree.
rm -rf bluez-[0-9]*
log "fetching bluez source via apt"
apt-get source bluez

# The unpacked source dir is bluez-<version>/ — find it.
SRC_DIR=$(ls -d bluez-[0-9]*/ | head -1)
SRC_DIR="${SRC_DIR%/}"
[[ -n "${SRC_DIR}" ]] || die "apt source did not produce a bluez-*/ directory"
log "source tree: ${BUILD_ROOT}/${SRC_DIR}"

GATT_DB_C="${BUILD_ROOT}/${SRC_DIR}/src/gatt-database.c"
[[ -f "${GATT_DB_C}" ]] || die "source tree missing src/gatt-database.c"

# Keep a backup of the original for diff + rollback.
cp -n "${GATT_DB_C}" "${GATT_DB_C}.orig"

log "applying CCC-persistence patch"
python3 "${PATCH_APPLIER}" "${GATT_DB_C}"

cd "${BUILD_ROOT}/${SRC_DIR}"

# BlueZ source includes `<bluetooth/X.h>` resolved via `-I./lib`, expecting a
# `lib/bluetooth/` directory or symlink alongside `lib/X.h`. The Debian source
# tarball does not ship this symlink, so the build fails on
# "fatal error: bluetooth/bluetooth.h: No such file" without it. Create it.
[[ -e lib/bluetooth ]] || ln -sf . lib/bluetooth

log "./configure --prefix=/usr"
./configure --prefix=/usr --mandir=/usr/share/man \
            --sysconfdir=/etc --localstatedir=/var \
            --enable-experimental --disable-systemd

# We only need the bluetoothd binary, but `make src/bluetoothd` does NOT
# trigger automake's BUILT_SOURCES rule that generates `src/builtin.h` (the
# list of built-in plugins). Without it the build fails on
# "src/plugin.c:201:10: fatal error: src/builtin.h: No such file or directory".
# Build the generated header first, then the daemon.
log "building src/builtin.h (BUILT_SOURCES)"
make -j"$(nproc)" src/builtin.h
log "building src/bluetoothd"
make -j"$(nproc)" src/bluetoothd

[[ -x src/bluetoothd ]] || die "build did not produce src/bluetoothd"

log "installing to ${PATCHED_BIN}"
mkdir -p "$(dirname "${PATCHED_BIN}")"
install -o root -g root -m 0755 src/bluetoothd "${PATCHED_BIN}"

# Drop the override pointing at our new binary.
install_override

log "done — bluetoothd ($(${PATCHED_BIN} -v 2>&1 | head -1)) from ${PATCHED_BIN}"
log "verify: ps -ef | grep bluetoothd | grep -v grep"
log "verify: pair the STB with start.sh; bond /var/lib/bluetooth/.../<stb>/info should have a [Cccs] section"
