#!/usr/bin/env bash
# Two (or more) plain Tellos on one host, WITHOUT network namespaces.
#
# Every plain Tello is an access point at 192.168.10.1, so two of them on one host collide: the
# same destination IP and the same UDP ports (state 8890, video 11111). The original answer to
# that was tello_netns.sh, which moves each adapter into its own namespace. That does not work
# on every Wi-Fi driver - notably not on the AIC8800DC vendor driver, whose wiphy cannot be moved
# into a namespace at all (`iw phy <phy> set netns` returns -EOPNOTSUPP, and the driver contains
# no netns code). So this script keeps both radios in the host namespace and separates the two
# links by SOURCE address instead:
#
#   drone 1  radio wlan1  host 192.168.10.2   rule "from 192.168.10.2" -> table 100 -> wlan1
#   drone 2  radio wlan2  host 192.168.10.4   rule "from 192.168.10.4" -> table 200 -> wlan2
#
# Everything aimed at one drone binds its source to that drone's host address, so the kernel
# always resolves the route through the right radio. Concretely, in the host .env:
#
#   DEVICE<i>_TELLO_LOCAL_IP=192.168.10.<n>            commands + state sockets
#   DEVICE<i>_VIDEO=udp://192.168.10.<n>:11111         ffmpeg's video input socket
#
# Both drones still answer on 192.168.10.1 and still use the stock 8890 / 11111; only the source
# address differs. Tellos are told apart by source IP, never by destination.
#
# Usage (root):
#   tello_prio.sh up <i> <wifi-iface> <tello-ssid> [<host-ip>]   # host-ip defaults to 192.168.10.<2*i>
#   tello_prio.sh route <i> <wifi-iface> [<host-ip>]           # addressing + tables only, no association
#   tello_prio.sh status [<i>]
#   tello_prio.sh down [<i>]
#
# Association uses `iw connect`, not wpa_supplicant: a Tello AP is open (key_mgmt=NONE) and needs
# no key exchange. NetworkManager must release each interface first: its wpa_supplicant otherwise
# deauthenticates a successful `iw connect` immediately ("No network configuration found for the
# current AP", reason 3, locally generated). The previous managed setting is restored on `down`.
#
# Static addressing, not DHCP: policy routing needs a known source address per radio, and DHCP
# lease order is not one. The Tello AP is open and hands out 192.168.10.0/24, so this is safe.
set -euo pipefail

usage() { sed -n '2,42p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -ge 1 ] || usage
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

ACTION=$1
I=${2:-}
STATE_DIR=/run/tello
DRONE_IP=192.168.10.1
TABLE_BASE=100          # drone i -> table TABLE_BASE + (i-1)*100; same value as the rule priority

for cmd in ip iw; do
    command -v "$cmd" >/dev/null || { echo "$cmd not found (apt install iw)" >&2; exit 1; }
done

table_for() { echo $((TABLE_BASE + ($1 - 1) * 100)); }
sd_for()    { echo "$STATE_DIR/$1"; }
# `status` and a bare `down` work on every configured drone, so I is only mandatory per drone.
case "$ACTION" in
    up|route) [ -n "$I" ] || { echo "drone index required" >&2; usage; } ;;
esac
TBL=$(table_for "${I:-1}")

# The addressing + policy-routing half. Deliberately separate from association so the routing can
# be inspected (and applied) without a drone in range.
apply_route() {
    local iface=$1 host_ip=$2
    # noprefixroute keeps 192.168.10.0/24 out of the MAIN table. Without it the second radio adds
    # a second identical connected route and the kernel silently picks one of them.
    ip addr replace "$host_ip/24" dev "$iface" noprefixroute
    ip link set "$iface" up
    ip route replace table "$TBL" "$DRONE_IP/32" dev "$iface" src "$host_ip"
    ip rule del priority "$TBL" 2>/dev/null || true
    ip rule add priority "$TBL" from "$host_ip" lookup "$TBL"
}

release_nm() {
    local iface=$1 sd=$2
    command -v nmcli >/dev/null || return 0
    if [ "$(nmcli -g GENERAL.NM-MANAGED device show "$iface" 2>/dev/null)" = yes ]; then
        nmcli device set "$iface" managed no
        echo "$iface" > "$sd/nm_managed_before"
    fi
}

restore_nm() {
    local sd=$1
    if [ -f "$sd/nm_managed_before" ] && command -v nmcli >/dev/null; then
        nmcli device set "$(cat "$sd/nm_managed_before")" managed yes || \
            echo "warning: could not restore NetworkManager control of $(cat "$sd/nm_managed_before")" >&2
    fi
}

associate() {
    local iface=$1 ssid=$2
    ip link set "$iface" up

    # A powered-on but idle Tello stops broadcasting entirely, so a join can fail right after a
    # successful scan. Poll for the SSID instead of trusting one scan, but only for a few seconds:
    # pairing runs behind a button, and a drone that is off or hot should be reported quickly.
    local t seen=0
    for t in $(seq 1 3); do
        if iw dev "$iface" scan 2>/dev/null | grep -q "SSID: $ssid$"; then seen=1; break; fi
        sleep 1
    done
    [ "$seen" -eq 1 ] || { echo "$iface: '$ssid' not in range - is the drone powered on, awake and cool?" >&2; return 1; }

    iw dev "$iface" connect "$ssid" || true

    t=0
    while [ $t -lt 8 ]; do
        iw dev "$iface" link 2>/dev/null | grep -q "^[[:space:]]*SSID: $ssid$" && return 0
        t=$((t + 1)); sleep 1
    done
    echo "$iface: association to '$ssid' did not stay connected" >&2
    return 1
}

up() {
    local iface=$1 ssid=$2 host_ip=${3:-}
    host_ip=${host_ip:-192.168.10.$((I * 2))}
    local sd; sd=$(sd_for "$I")

    ip link show "$iface" >/dev/null 2>&1 || { echo "no interface $iface" >&2; exit 1; }
    mkdir -p "$sd"
    release_nm "$iface" "$sd"

    if ! associate "$iface" "$ssid"; then
        restore_nm "$sd"
        rm -rf "$sd"
        exit 1
    fi
    apply_route "$iface" "$host_ip"

    echo "$iface"  > "$sd/iface"
    echo "$ssid"   > "$sd/ssid"
    echo "$host_ip"> "$sd/host_ip"
    echo "$TBL"    > "$sd/table"
    echo "drone $I: $iface -> $ssid, host $host_ip, rule from $host_ip lookup $TBL"
}

route() {
    local iface=$1 host_ip=${2:-}
    host_ip=${host_ip:-192.168.10.$((I * 2))}
    local sd; sd=$(sd_for "$I")
    ip link show "$iface" >/dev/null 2>&1 || { echo "no interface $iface" >&2; exit 1; }
    mkdir -p "$sd"
    release_nm "$iface" "$sd"
    apply_route "$iface" "$host_ip"
    echo "$iface"  > "$sd/iface"
    echo "$host_ip"> "$sd/host_ip"
    echo "$TBL"    > "$sd/table"
    echo "drone $I: routed $host_ip via $iface (table $TBL); not associated"
}

down() {
    local d sd iface host_ip
    for d in $(ls -1 "$STATE_DIR" 2>/dev/null || true); do
        [ -n "$I" ] && [ "$d" != "$I" ] && continue
        sd="$STATE_DIR/$d"
        iface=$(cat "$sd/iface" 2>/dev/null || true)
        host_ip=$(cat "$sd/host_ip" 2>/dev/null || true)
        local t; t=$(table_for "$d")
        ip rule del priority "$t" 2>/dev/null || true
        ip route flush table "$t" 2>/dev/null || true
        [ -n "$host_ip" ] && [ -n "$iface" ] && ip addr del "$host_ip/24" dev "$iface" 2>/dev/null || true
        [ -n "$iface" ] && iw dev "$iface" disconnect 2>/dev/null || true
        restore_nm "$sd"
        rm -rf "$sd"
        echo "drone $d: torn down ($iface, table $t)"
    done
}

status() {
    for d in $(ls -1 "$STATE_DIR" 2>/dev/null || true); do
        [ -n "$I" ] && [ "$d" != "$I" ] && continue
        local sd="$STATE_DIR/$d" iface
        iface=$(cat "$sd/iface" 2>/dev/null || true)
        echo "== drone $d  iface=$iface  ssid=$(cat "$sd/ssid" 2>/dev/null)  host_ip=$(cat "$sd/host_ip" 2>/dev/null)  table=$(table_for "$d")"
        [ -n "$iface" ] && iw dev "$iface" link 2>/dev/null | head -2 | sed 's/^/   /'
    done
    echo "== rules"; ip rule show | grep -E "lookup (100|200|300)" | sed 's/^/   /'
    echo "== tables"; for t in 100 200 300; do
        ip route show table $t 2>/dev/null | grep -q . && { echo "   table $t:"; ip route show table $t | sed 's/^/     /'; }
    done
    echo "== which radio would each source use?"
    for a in 192.168.10.2 192.168.10.4; do
        echo "   from $a -> $(ip route get "$DRONE_IP" from "$a" 2>/dev/null | head -1)"
    done
}

case "$ACTION" in
    up)     [ $# -ge 4 ] || usage; up "$3" "$4" "${5:-}" ;;
    route)  [ $# -ge 3 ] || usage; route "$3" "${4:-}" ;;
    down)   down "$I" ;;
    status) status ;;
    *)      usage ;;
esac
