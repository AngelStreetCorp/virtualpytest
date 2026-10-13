#!/usr/bin/env bash
# Two (or more) plain Tellos on one host (TASK-32 §B).
#
# Every plain Tello is an access point at 192.168.10.1 and sends state to UDP 8890 and video to
# UDP 11111 of whoever sent `command`. With two Wi-Fi adapters on one host, both links are
# 192.168.10.0/24 and the kernel can only route to one of them. This script moves each adapter into
# its own network namespace and presents drone <i> to the host as:
#
#   command   10.200.<i>.2:8889
#   state  -> host UDP 8889+<i>     (drone 1: 8890, drone 2: 8891)
#   video  -> host UDP 11110+<i>    (drone 1: 11111, drone 2: 11112)
#
# so the host .env lists DEVICE<n>_TELLO_IP=10.200.<i>.2 and the matching ports.
#
# Usage (root):
#   tello_netns.sh up <i> <wifi-iface> <tello-ssid>   # e.g. up 1 wlx00c0ca123456 TELLO-5A3F21
#   tello_netns.sh up <i> <iface> --no-wifi           # iface already wired to 192.168.10.1 (tests)
#   tello_netns.sh down <i>
#   tello_netns.sh status [<i>]
#
# The Wi-Fi adapter is gone from the host while its namespace exists; `down` gives it back.
set -euo pipefail

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -ge 1 ] || usage
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

ACTION=$1
I=${2:-}
DRONE_IP=192.168.10.1
NS_DRONE_SIDE_IP=192.168.10.2   # static when --no-wifi; DHCP from the Tello otherwise

ns() { echo "tello$1"; }

up() {
    local i=$1 iface=$2 ssid=$3
    local n; n=$(ns "$i")
    local host_ip=10.200.$i.1 ns_ip=10.200.$i.2
    local state_port=$((8889 + i)) video_port=$((11110 + i))

    ip netns add "$n"
    ip netns exec "$n" ip link set lo up

    if [ "$ssid" = "--no-wifi" ]; then
        ip link set "$iface" netns "$n"
        ip netns exec "$n" ip addr add "$NS_DRONE_SIDE_IP/24" dev "$iface"
        ip netns exec "$n" ip link set "$iface" up
    else
        # A Wi-Fi interface moves with its phy, not by itself.
        local phy; phy=$(cat "/sys/class/net/$iface/phy80211/name")
        iw phy "$phy" set netns name "$n"
        ip netns exec "$n" ip link set "$iface" up
        local conf=/run/tello$i-wpa.conf
        printf 'network={\n  ssid="%s"\n  key_mgmt=NONE\n}\n' "$ssid" > "$conf"
        ip netns exec "$n" wpa_supplicant -B -i "$iface" -c "$conf" -P "/run/tello$i-wpa.pid"
        ip netns exec "$n" dhclient -1 -pf "/run/tello$i-dhclient.pid" "$iface"
    fi

    # Host <-> namespace link.
    ip link add "vt$i" type veth peer name "vtn$i"
    ip link set "vtn$i" netns "$n"
    ip addr add "$host_ip/24" dev "vt$i"
    ip link set "vt$i" up
    ip netns exec "$n" ip addr add "$ns_ip/24" dev "vtn$i"
    ip netns exec "$n" ip link set "vtn$i" up

    ip netns exec "$n" sysctl -qw net.ipv4.ip_forward=1
    local ipt="ip netns exec $n iptables -t nat -A"
    # Host -> drone: commands to 10.200.i.2:8889 go to the Tello, from the namespace's own
    # address, so the Tello sends its replies, state and video back into the namespace.
    $ipt PREROUTING -i "vtn$i" -p udp --dport 8889 -j DNAT --to-destination "$DRONE_IP:8889"
    $ipt POSTROUTING -o "$iface" -j MASQUERADE
    # Drone -> host: state and video arrive on the namespace's fixed Tello ports and are
    # forwarded to this drone's own host ports.
    $ipt PREROUTING -i "$iface" -p udp --dport 8890 -j DNAT --to-destination "$host_ip:$state_port"
    $ipt PREROUTING -i "$iface" -p udp --dport 11111 -j DNAT --to-destination "$host_ip:$video_port"
    # Source becomes 10.200.i.2, so the host's reverse-path filter accepts it on vt<i>.
    $ipt POSTROUTING -o "vtn$i" -j MASQUERADE

    echo "drone $i: command $ns_ip:8889, state -> host :$state_port, video -> host :$video_port ($n)"
}

down() {
    local i=$1 n; n=$(ns "$i")
    for f in "/run/tello$i-wpa.pid" "/run/tello$i-dhclient.pid"; do
        [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
        rm -f "$f"
    done
    rm -f "/run/tello$i-wpa.conf"
    ip link del "vt$i" 2>/dev/null || true
    # Deleting the namespace returns physical interfaces (and Wi-Fi phys) to the host.
    ip netns del "$n" 2>/dev/null || true
    echo "drone $i: namespace $n removed"
}

status() {
    for n in $(ip netns list | awk '/^tello[0-9]+/{print $1}'); do
        [ -n "$I" ] && [ "$n" != "tello$I" ] && continue
        echo "== $n"
        ip netns exec "$n" ip -br addr
        ip netns exec "$n" iptables -t nat -S | grep -E 'DNAT|MASQ' || true
    done
}

case "$ACTION" in
    up)     [ $# -eq 4 ] || usage; up "$I" "$3" "$4" ;;
    down)   [ -n "$I" ] || usage; down "$I" ;;
    status) status ;;
    *)      usage ;;
esac
