#!/usr/bin/env bash
# Install (or revert) the Nintendo Switch Bluetooth Pro Controller emulator
# (vpt-procon.service) on a Linux host. Opt-in: only for a host with a
# nintendo_switch device. The daemon OWNS the Bluetooth adapter.
#
#   install_procon.sh [--adapter hci0] [--adapter-mac AA:BB:..] [--desktop-user USER] [--lan]
#   install_procon.sh --revert [--adapter hci0]
#
# Install does:
#   1. /opt/nxbt-venv (python venv with system site packages + nxbt 0.1.4).
#   2. bluetoothd drop-in zz-vpt-procon.conf: `--compat --noplugin=*` (nxbt
#      needs the HID PSMs free and compat-mode SDP). Sorts after override.conf.
#   3. Disables the BLE STB remote units on this adapter (hid-remote@/hid-agent@,
#      and vpt-ble-remote unless another adapter still has a BLE STB remote in
#      .env): they reset the adapter and would kill the link.
#      STB bond dirs under /var/lib/bluetooth are left untouched.
#   4. Turns off the WirePlumber Bluetooth monitor for desktop users: its
#      Hands-Free SDP records stop the Switch from opening the HID channels.
#   5. /etc/default/vpt-procon pinning the adapter address the Switch pairs
#      with (default: the adapter's current address), then installs and
#      starts vpt-procon.service via install_service.sh.
#      --lan: listen on 0.0.0.0 with a generated PROCON_TOKEN (kept on re-run),
#      for a vpt-host on another host (the one with the Switch's HDMI grabber):
#      set DEVICE<n>_SWITCH_PROCON_URL=http://<this-host>:6190 and
#      DEVICE<n>_SWITCH_PROCON_TOKEN=<token> in that host's .env.
#
# NOT done here (host-specific, see docs/agent/devices/NINTENDO_SWITCH.md):
#   comment out DEVICE<n>_BLE_TYPE / DEVICE<n>_BLE_ADAPTER_HCI of a device on
#   the same adapter in backend_host/src/.env, otherwise vpt-host runs the BLE
#   resume.sh on every restart and takes the adapter back.
#
# --revert undoes 1-5 (keeps the venv) and re-enables vpt-ble-remote.service.
# It never runs the BLE start.sh (destructive: wipes STB bonds).

set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then exec sudo -E "${BASH_SOURCE[0]}" "$@"; fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER=hci0
ADAPTER_MAC=""
DESKTOP_USERS=""
REVERT=0
LAN=0
VENV=/opt/nxbt-venv
DROPIN_DIR=/etc/systemd/system/bluetooth.service.d
DROPIN="$DROPIN_DIR/zz-vpt-procon.conf"
DEFAULTS=/etc/default/vpt-procon
WP_LUA=".config/wireplumber/bluetooth.lua.d/80-vpt-procon-disable-bluez.lua"   # WirePlumber 0.4
WP_CONF=".config/wireplumber/wireplumber.conf.d/80-vpt-procon-disable-bluez.conf"  # WirePlumber 0.5

while [[ $# -gt 0 ]]; do
    case "$1" in
        --adapter) ADAPTER="$2"; shift 2 ;;
        --adapter-mac) ADAPTER_MAC="${2^^}"; shift 2 ;;
        --desktop-user) DESKTOP_USERS="$DESKTOP_USERS $2"; shift 2 ;;
        --revert) REVERT=1; shift ;;
        --lan) LAN=1; shift ;;
        *) echo "unknown option $1" >&2; exit 1 ;;
    esac
done

log() { printf '[install_procon] %s\n' "$*"; }
exec < <(:)   # btmgmt wedges when stdin is /dev/null

if [[ -z "$DESKTOP_USERS" ]]; then
    DESKTOP_USERS=$(awk -F: '$3 >= 1000 && $3 < 60000 && $6 ~ /^\/home\// {print $1}' /etc/passwd)
fi

user_systemctl() {  # user, args...
    local u="$1"; shift
    local uid; uid=$(id -u "$u")
    [[ -d "/run/user/$uid" ]] || return 0
    sudo -u "$u" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user "$@" 2>/dev/null || true
}

ENV_FILE="$(cd "$SCRIPT_DIR/../../../.." && pwd)/backend_host/src/.env"

other_ble_adapters() {  # adapters other than ours that still have a BLE STB remote in .env
    grep -oE "^DEVICE[0-9]+_BLE_ADAPTER_HCI=hci[0-9]+" "$ENV_FILE" 2>/dev/null \
        | cut -d= -f2 | grep -vx "$ADAPTER" | sort -u || true
}

ble_units() {
    echo "hid-remote@${ADAPTER}.service" "hid-agent@${ADAPTER}.service" \
        "vpt-ble-remote@${ADAPTER}.service" "ble-remote@${ADAPTER}.service"
    # vpt-ble-remote.service resumes EVERY BLE remote at boot: keep it when
    # another adapter still serves an STB (e.g. hci0 = STB remote, hci1 = Switch).
    [[ -n "$(other_ble_adapters)" ]] || echo vpt-ble-remote.service
}

if (( REVERT )); then
    log "stopping vpt-procon"
    systemctl disable --now vpt-procon.service 2>/dev/null || true
    rm -f /etc/systemd/system/vpt-procon.service "$DROPIN"
    for u in $DESKTOP_USERS; do
        home=$(getent passwd "$u" | cut -d: -f6)
        rm -f "$home/$WP_LUA" "$home/$WP_CONF"
        user_systemctl "$u" restart wireplumber
    done
    systemctl daemon-reload
    systemctl restart bluetooth
    if systemctl cat vpt-ble-remote.service >/dev/null 2>&1; then
        systemctl enable vpt-ble-remote.service
        log "vpt-ble-remote.service re-enabled (runs the non-destructive resume.sh at boot)"
    fi
    log "reverted. Next: restore DEVICE<n>_BLE_* in backend_host/src/.env and restart vpt-host"
    log "(it runs resume.sh, which keeps the STB bond). NEVER run start.sh to recover."
    exit 0
fi

# 1. nxbt venv
if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c 'import nxbt' 2>/dev/null; then
    log "creating $VENV with nxbt (needs libdbus-1-dev libglib2.0-dev python3-gi)"
    python3 -m venv --system-site-packages "$VENV"
    "$VENV/bin/pip" install --quiet nxbt==0.1.4
fi

# 2. bluetoothd flags
BLUETOOTHD=/usr/libexec/bluetooth/bluetoothd
[[ -x /opt/bluez-cccpatch-v2/usr/libexec/bluetooth/bluetoothd ]] && \
    BLUETOOTHD=/opt/bluez-cccpatch-v2/usr/libexec/bluetooth/bluetoothd
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
# vpt-procon (Nintendo Switch Pro Controller emulation). Sorts after
# override.conf so it wins. Revert: install_procon.sh --revert
[Service]
ExecStart=
ExecStart=$BLUETOOTHD --compat --noplugin=*
EOF
rm -f /run/systemd/system/bluetooth.service.d/zz-nxbt.conf /run/systemd/system/bluetooth.service.d/nxbt.conf
log "bluetoothd drop-in: $DROPIN ($BLUETOOTHD --compat --noplugin=*)"

# 3. BLE STB remote units off on this adapter
for unit in $(ble_units); do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl disable --now "$unit" 2>/dev/null || true
        log "disabled $unit"
    fi
done
if grep -qE "^DEVICE[0-9]+_BLE_ADAPTER_HCI=${ADAPTER}\b" "$ENV_FILE" 2>/dev/null; then
    log "WARNING: $ENV_FILE still has a BLE remote on $ADAPTER:"
    grep -nE "^DEVICE[0-9]+_BLE_(TYPE|ADAPTER_HCI)=" "$ENV_FILE" | sed 's/^/    /'
    log "comment those lines out, or vpt-host's resume.sh takes the adapter back"
fi
if [[ -n "$(other_ble_adapters)" ]]; then
    log "kept vpt-ble-remote.service: BLE STB remote still on $(other_ble_adapters | xargs)"
fi

# 4. WirePlumber Bluetooth monitor off (desktop audio keeps working)
for u in $DESKTOP_USERS; do
    home=$(getent passwd "$u" | cut -d: -f6)
    install -d -o "$u" -g "$u" "$home/$(dirname "$WP_LUA")" "$home/$(dirname "$WP_CONF")"
    printf -- '-- vpt-procon: keep PipeWire off the Bluetooth adapter (Switch HID needs it)\nbluez_monitor.enabled = false\n' \
        > "$home/$WP_LUA"
    printf '# vpt-procon: keep PipeWire off the Bluetooth adapter (Switch HID needs it)\nwireplumber.profiles = {\n  main = {\n    monitor.bluez = disabled\n  }\n}\n' \
        > "$home/$WP_CONF"
    chown "$u:$u" "$home/$WP_LUA" "$home/$WP_CONF"
    user_systemctl "$u" restart wireplumber
    log "WirePlumber Bluetooth monitor disabled for $u"
done

# 5. adapter address pin + service
systemctl daemon-reload
systemctl restart bluetooth
sleep 3
if [[ -z "$ADAPTER_MAC" ]]; then
    ADAPTER_MAC=$(hciconfig "$ADAPTER" | awk '/BD Address/ {print $3}')
fi
BIND=127.0.0.1
TOKEN=""
if (( LAN )); then
    BIND=0.0.0.0
    TOKEN=$(sed -n 's/^PROCON_TOKEN=//p' "$DEFAULTS" 2>/dev/null || true)
    [[ -n "$TOKEN" ]] || TOKEN=$(openssl rand -hex 24)
fi
umask 077
cat > "$DEFAULTS" <<EOF
# vpt-procon settings (read by vpt-procon.service)
PROCON_ADAPTER=$ADAPTER
# Address the Switch is bonded against; re-applied at start (a reboot resets it)
PROCON_ADAPTER_MAC=$ADAPTER_MAC
PROCON_PORT=6190
PROCON_BIND=$BIND
PROCON_TOKEN=$TOKEN
EOF
chmod 600 "$DEFAULTS"
log "$DEFAULTS: adapter $ADAPTER pinned to $ADAPTER_MAC, listening on $BIND:6190"
if (( LAN )); then
    log "token for the remote vpt-host's DEVICE<n>_SWITCH_PROCON_TOKEN: sudo grep PROCON_TOKEN $DEFAULTS"
fi
"$SCRIPT_DIR/install_service.sh" procon
log "done. Status: curl -s 127.0.0.1:6190/status ; logs: journalctl -u vpt-procon -f"
