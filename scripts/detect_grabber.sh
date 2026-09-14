#!/bin/bash
################################################################################
# detect_grabber.sh — list every peripheral that a backend_host might bind to
# (video grabber + paired ALSA audio, Bluetooth controllers, IR receivers) and
# show the USB topology port each one is plugged into.
#
# Kernel-assigned names (`/dev/videoN`, `plughw:N,0`, `hciN`, `/dev/lircN`)
# shuffle across reboots — only the USB topology port (e.g. `3-1`) is stable.
# This script surfaces the port for every device so you can write port-keyed
# udev rules (or pin entries in backend_host/src/.env after a USB replug).
#
# Usage:
#   scripts/detect_grabber.sh
################################################################################

set -u

# Each UVC device often exposes two /dev/video* nodes: one for video capture
# (V4L2_CAP_VIDEO_CAPTURE, bit 0 of Device Caps) and a sibling for metadata.
# Only the capture node is usable by the ffmpeg pipeline. Return success iff
# the node has the VIDEO_CAPTURE bit set.
is_capture_node() {
  local caps
  caps=$(v4l2-ctl -d "$1" --info 2>/dev/null | awk '/^[[:space:]]*Device Caps/ {print $NF; exit}')
  [ -n "$caps" ] || return 1
  (( (caps & 0x1) != 0 ))
}

# Walk up the sysfs tree from an interface symlink until we hit the USB device
# node (the one that has idVendor). That node is shared by all interfaces of a
# composite device (UVC video + UAC audio on an MS2109, for example).
get_usb_parent() {
  local p
  p=$(readlink -f "$1" 2>/dev/null)
  while [ -n "$p" ] && [ "$p" != "/" ] && [ ! -f "$p/idVendor" ]; do
    p=$(dirname "$p")
  done
  if [ -f "$p/idVendor" ]; then
    echo "$p"
  fi
}

# Build a map: USB device path -> ALSA card number.
declare -A CARD_USB
for c in /sys/class/sound/card[0-9]*; do
  usb=$(get_usb_parent "$c/device")
  if [ -n "$usb" ]; then
    CARD_USB["$usb"]="${c##*card}"
  fi
done

printf "%-14s  %-14s  %-11s  %s\n" "VIDEO" "AUDIO" "USB-ID" "USB-PATH"
printf "%-14s  %-14s  %-11s  %s\n" "-----" "-----" "------" "--------"

for v in /sys/class/video4linux/video*; do
  [ -e "$v" ] || continue
  dev="/dev/$(basename "$v")"
  # Skip metadata siblings — they can't be used as ffmpeg video sources.
  is_capture_node "$dev" || continue
  usb=$(get_usb_parent "$v/device")
  if [ -z "$usb" ]; then
    continue
  fi
  vendor=$(cat "$usb/idVendor" 2>/dev/null)
  product=$(cat "$usb/idProduct" 2>/dev/null)
  bus=$(basename "$usb")
  card=${CARD_USB[$usb]:-}
  if [ -n "$card" ]; then
    audio="plughw:${card},0"
  else
    audio="(none)"
  fi
  printf "%-14s  %-14s  %-11s  %s\n" \
    "$dev" "$audio" "${vendor}:${product}" "$bus"
done

# ---------------------------------------------------------------------------
# Bluetooth controllers (hciN).
# `hciN` is a netdev-style name (like eth0), not a /dev/ node. The MAC address
# is burned into the dongle and never changes — useful as a sanity check when
# writing systemd-networkd .link files keyed on USB port.
# ---------------------------------------------------------------------------
printf "\n"
printf "%-14s  %-19s  %-11s  %s\n" "BLUETOOTH" "MAC" "USB-ID" "USB-PATH"
printf "%-14s  %-19s  %-11s  %s\n" "---------" "---" "------" "--------"

found_bt=0
for h in /sys/class/bluetooth/hci*; do
  [ -e "$h" ] || continue
  found_bt=1
  name=$(basename "$h")
  # /sys/class/bluetooth/hciN/address is often empty until the controller is
  # powered up; hciconfig brings it up and reads the BD address directly.
  mac=$(cat "$h/address" 2>/dev/null)
  if [ -z "$mac" ] || [ "$mac" = "00:00:00:00:00:00" ]; then
    mac=$(hciconfig "$name" 2>/dev/null | awk '/BD Address:/ {print $3; exit}')
  fi
  mac="${mac:-(unknown)}"
  usb=$(get_usb_parent "$h/device")
  if [ -n "$usb" ]; then
    vendor=$(cat "$usb/idVendor" 2>/dev/null)
    product=$(cat "$usb/idProduct" 2>/dev/null)
    bus=$(basename "$usb")
    printf "%-14s  %-19s  %-11s  %s\n" "$name" "$mac" "${vendor}:${product}" "$bus"
  else
    printf "%-14s  %-19s  %-11s  %s\n" "$name" "$mac" "(non-USB)" "-"
  fi
done
[ "$found_bt" = "0" ] && echo "(none)"

# ---------------------------------------------------------------------------
# Infrared receivers/blasters (/dev/lircN).
# GPIO-backed IR (e.g. Raspberry Pi) has no USB parent and will report
# "(non-USB)" — those need a different pinning strategy (gpio-ir overlay).
# ---------------------------------------------------------------------------
printf "\n"
printf "%-14s  %-11s  %s\n" "INFRARED" "USB-ID" "USB-PATH"
printf "%-14s  %-11s  %s\n" "--------" "------" "--------"

found_ir=0
for l in /sys/class/lirc/lirc*; do
  [ -e "$l" ] || continue
  found_ir=1
  name="/dev/$(basename "$l")"
  usb=$(get_usb_parent "$l/device")
  if [ -n "$usb" ]; then
    vendor=$(cat "$usb/idVendor" 2>/dev/null)
    product=$(cat "$usb/idProduct" 2>/dev/null)
    bus=$(basename "$usb")
    printf "%-14s  %-11s  %s\n" "$name" "${vendor}:${product}" "$bus"
  else
    printf "%-14s  %-11s  %s\n" "$name" "(non-USB)" "-"
  fi
done
[ "$found_ir" = "0" ] && echo "(none)"
