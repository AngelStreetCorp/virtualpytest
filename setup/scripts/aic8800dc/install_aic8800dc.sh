#!/usr/bin/env bash
# Install the AIC8800DC USB Wi-Fi driver (TP-Link AX300 / Archer TX1U Nano and other
# AIC8800DC/DW sticks, USB IDs 3625:0110, 2357:0147, ...) with the RX defragmentation
# fix VirtualPyTest needs for Tello drones.
#
# Upstream: https://github.com/Kiborgik/aic8800dc-linux-patched (DKMS, 6.4.3.0 vendor base).
# That tree hands every 802.11 fragment to the network stack as its own frame, so any peer
# that fragments (a Tello AP fragments everything above ~520 bytes) delivers truncated
# packets: pings above ~500 bytes fail and the 1460-byte video datagrams never arrive.
# aic8800dc-rx-defrag.patch (next to this script) adds the defragmentation the vendor's
# newer driver has. Details: docs/agent/devices/TELLO_USB_WIFI.md, BUG-0839.
#
# Usage (as root, on the host that has the dongles):
#   sudo bash install_aic8800dc.sh            # clone, patch, DKMS build + install
#   sudo bash install_aic8800dc.sh --no-clone # reuse an existing $SRC checkout
#
# The script never unloads a running aic8800 module: an rmmod of this driver has hung a
# Raspberry Pi 5 (power cycle needed). Reboot the host afterwards to load the new module.
set -euo pipefail

UPSTREAM_REPO="${AIC8800_REPO:-https://github.com/Kiborgik/aic8800dc-linux-patched.git}"
UPSTREAM_REF="${AIC8800_REF:-7745043}"          # cut 6.4.3.0-patched.17 (2026)
UPSTREAM_VERSION="6.4.3.0-patched.17"
VPT_SUFFIX="+vpt.1"                              # bump when the patch changes
SRC="${AIC8800_SRC:-/usr/local/src/aic8800dc-vpt}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="${HERE}/aic8800dc-rx-defrag.patch"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo)" >&2
    exit 1
fi
[ -f "$PATCH" ] || { echo "missing $PATCH" >&2; exit 1; }

for cmd in git patch dkms make eject; do
    command -v "$cmd" >/dev/null || { echo "missing '$cmd' (apt install git patch dkms build-essential linux-headers-\$(uname -r) eject)" >&2; exit 1; }
done

if [ "${1:-}" != "--no-clone" ]; then
    rm -rf "$SRC"
    git clone -q "$UPSTREAM_REPO" "$SRC"
    git -C "$SRC" checkout -q "$UPSTREAM_REF"
fi
cd "$SRC"

if grep -q "defrag_ctrl_info" drivers/aic8800/aic8800_fdrv/rwnx_defs.h; then
    echo "source already carries the defrag patch"
else
    patch -p1 --no-backup-if-mismatch < "$PATCH"
fi

# One DKMS version per patch level, so `dkms status` says which driver a host runs.
NEW_VERSION="${UPSTREAM_VERSION}${VPT_SUFFIX}"
sed -i "s/${UPSTREAM_VERSION}\(+vpt\.[0-9]*\)\?\"/${NEW_VERSION}\"/" dkms.conf install.sh uninstall.sh
grep -q "PACKAGE_VERSION=\"${NEW_VERSION}\"" dkms.conf

# Upstream install.sh: firmware + udev eject rule, removes older DKMS versions,
# dkms add/build/install, modules-load.d. Its final modprobe is a no-op when the
# old module is loaded; the new one takes over at the next boot.
./install.sh

echo
echo "Installed aic8800dc/${NEW_VERSION}. Reboot to load it, then check:"
echo "  dkms status | grep aic8800dc"
echo "  ping -I <dongle address> -s 1400 <tello ip>     # 0% loss against a Tello"
