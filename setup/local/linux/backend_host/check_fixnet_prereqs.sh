#!/bin/bash
################################################################################
# check_fixnet_prereqs.sh — audit what a PFR still needs before the first Fixnet
# call test. READ-ONLY: it installs nothing, writes nothing, changes no service.
# It answers one question per line: is this prerequisite already in place?
#
# Run it on the PFR (Debian 13), as the user that will drive the tests:
#
#   setup/local/linux/backend_host/check_fixnet_prereqs.sh                 # static audit
#   setup/local/linux/backend_host/check_fixnet_prereqs.sh --probe         # + talk AT to the modems
#   setup/local/linux/backend_host/check_fixnet_prereqs.sh --expected-modems 1   # single-line bench
#
# --probe is the only mode that touches hardware: it sends a bare `AT` to each
# modem and reads the reply. `AT` is a no-op query (no dial, no voice mode, no
# line state change), but it does open the serial port, so it is opt-in.
#
# Exit code: 0 = every required prerequisite is in place, 1 = at least one is
# missing. A non-zero exit is the signal that install-fixnet-prereqs.sh has
# work to do; this script deliberately does not install anything itself.
#
# Findings are tagged so the install script can act on them:
#   [ok]    present and correct
#   [MISS]  required and absent          -> must be installed
#   [WARN]  present but wrong/ambiguous   -> needs a decision, not a package
#   [info]  context, nothing to install
################################################################################

set -u

MODEM_VENDOR="0572"   # Conexant Systems (Rockwell) — the USB56KEMH2 voice modem
MODEM_PRODUCT="1349"  # CX9300x family
EXPECTED_MODEMS=4     # one USB modem per Fixnet line
PROBE=0
STABLE_DIR="/dev/fixnet"   # where port-keyed udev symlinks will live

usage() {
    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --probe)            PROBE=1 ;;
        --expected-modems)  shift; EXPECTED_MODEMS="${1:-4}" ;;
        --no-probe)         PROBE=0 ;;
        -h|--help)          usage ;;
        *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# --- output helpers ----------------------------------------------------------

if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_MISS=$'\033[31m'; C_WARN=$'\033[33m'
    C_HEAD=$'\033[1;36m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_MISS=""; C_WARN=""; C_HEAD=""; C_OFF=""
fi

N_OK=0; N_MISS=0; N_WARN=0

ok()   { N_OK=$((N_OK+1));   printf "  %s[ok]%s   %s\n"   "$C_OK"   "$C_OFF" "$1"; }
miss() { N_MISS=$((N_MISS+1)); printf "  %s[MISS]%s %s\n" "$C_MISS" "$C_OFF" "$1"; }
warn() { N_WARN=$((N_WARN+1)); printf "  %s[WARN]%s %s\n" "$C_WARN" "$C_OFF" "$1"; }
info() { printf "  [info] %s\n" "$1"; }
head_() { printf "\n%s== %s%s\n" "$C_HEAD" "$1" "$C_OFF"; }

have() { command -v "$1" >/dev/null 2>&1; }

# Send one AT command to a modem and echo whatever it replies.
#
# The port must be opened READ-WRITE: `printf AT | cat /dev/ttyACM0` writes
# nowhere, because cat reads the named file and ignores its stdin — the command
# would never reach the modem. File descriptor 3 is opened once, both ways, and
# used for the write and for the read.
#
# No pyserial needed: stty puts the line into raw 115200 and the reply is read
# with `read -t`, which keeps partial data when the timeout fires. A pipe into
# `head -c` would NOT do: head block-buffers, and the buffer is lost when
# timeout kills it, so the reply comes back empty.
at_send() {
    local tty="$1" cmd="$2" reply="" line i
    stty -F "$tty" raw -echo -echoe -echok speed 115200 2>/dev/null || return 1
    exec 3<>"$tty" || return 1
    printf '%s\r\n' "$cmd" >&3
    # A reply is a few lines ("", "OK"); stop at OK or after 5 lines / ~5 s.
    for i in 1 2 3 4 5; do
        line=""
        if IFS= read -r -t 1 line <&3; then
            line=$(printf '%s' "$line" | tr -d '\r')
            [ -z "$line" ] && continue
            reply="$reply$line "
            case "$line" in OK*|ERROR*) break ;; esac
        else
            # Timed out. `read` still leaves a partial line in $line — keep it
            # rather than throwing away a half-received answer.
            line=$(printf '%s' "$line" | tr -d '\r')
            [ -n "$line" ] && reply="$reply$line "
            break
        fi
    done
    exec 3<&- 2>/dev/null
    exec 3>&- 2>/dev/null
    printf '%s' "$reply"
}

# --- sysfs helpers (same walk as scripts/detect_grabber.sh) -------------------

# Resolve any sysfs path up to the USB device node that owns it (the node that
# has idVendor). A composite modem exposes several interfaces under one USB
# device, so this maps /dev/ttyACM* and the cdc_acm interface to one modem.
get_usb_parent() {
    local p
    p=$(readlink -f "$1" 2>/dev/null)
    while [ -n "$p" ] && [ "$p" != "/" ] && [ ! -f "$p/idVendor" ]; do
        p=$(dirname "$p")
    done
    [ -f "$p/idVendor" ] && echo "$p"
}

is_target_modem() {
    local d="$1"
    [ -f "$d/idVendor" ] || return 1
    [ "$(cat "$d/idVendor" 2>/dev/null)" = "$MODEM_VENDOR" ] || return 1
    [ "$(cat "$d/idProduct" 2>/dev/null)" = "$MODEM_PRODUCT" ]
}

# The kernel-assigned tty for a USB device path, empty when cdc_acm has not
# bound (no modem driver loaded / device not claimed yet).
# Both sides must be resolved: /sys/bus/usb/devices/<path> is a symlink into
# /sys/devices/..., so comparing it to get_usb_parent's resolved output would
# never match.
tty_for_usb() {
    local path="$1" target t d
    target=$(readlink -f "/sys/bus/usb/devices/$path" 2>/dev/null)
    for t in /sys/class/tty/ttyACM*; do
        [ -e "$t" ] || continue
        d=$(get_usb_parent "$t/device")
        [ -n "$d" ] || continue
        [ "$d" = "$target" ] && { echo "/dev/$(basename "$t")"; return 0; }
    done
    echo ""
}

# Which kernel driver is bound to a modem's first interface.
# No trailing slash on the glob: <path>:<cfg>.<intf> is a symlink, and a
# trailing slash through a symlink is not portable.
driver_for_usb() {
    local path="$1" i
    for i in /sys/bus/usb/devices/"$path":*; do
        [ -e "$i" ] || continue
        if [ -L "$i/driver" ]; then basename "$(readlink -f "$i/driver")"; return 0; fi
    done
    echo "(none)"
}

################################################################################
head_ "Host and OS"
################################################################################
info "kernel    $(uname -sr)"
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    info "os        $(. /etc/os-release && echo "$PRETTY_NAME")"
fi
info "arch      $(uname -m)"
info "user      $(id -un) (groups: $(id -Gn))"

if have python3; then
    info "python3   $(python3 --version 2>&1)"
else
    miss "python3 — the voice controller and every VPT host service need it"
fi

################################################################################
head_ "USB subsystem"
################################################################################
if have lsusb; then
    info "lsusb     $(lsusb --version 2>/dev/null | head -1)"
else
    miss "lsusb (package: usbutils) — needed to enumerate the modems"
fi

if [ -d /sys/bus/usb ]; then
    ok "USB bus present (/sys/bus/usb)"
else
    miss "no USB bus at /sys/bus/usb — this host cannot have the modems attached"
fi

# Enumerate through sysfs, not /proc/bus/usb/devices: usbfs was dropped from
# modern kernels, so that path is absent on a healthy Debian 13 and probing it
# produced a false warning.
USB_DEVICES=$(find /sys/bus/usb/devices -maxdepth 1 -name '*-*:*' 2>/dev/null | wc -l | tr -d ' ')
USB_NODES=0
for d in /sys/bus/usb/devices/*/; do
    [ -f "$d/idVendor" ] || continue
    [ "$(cat "$d/idVendor" 2>/dev/null)" = "1d6b" ] && continue   # skip root hubs
    USB_NODES=$((USB_NODES+1))
done
if [ "$USB_DEVICES" -gt 0 ]; then
    ok "USB device tree readable (/sys/bus/usb/devices: $USB_DEVICES entries)"
else
    warn "no USB device entries under /sys/bus/usb/devices"
fi
info "$USB_NODES non-root USB device(s) enumerated on this host"

# cdc_acm is the stock driver that must claim these modems. The authoritative
# signal is a modem actually bound to it, not the presence of the .ko file —
# `modinfo` needs kmod, which is often absent and produced a false warning.
if [ -d /sys/module/cdc_acm ]; then
    ok "cdc_acm module loaded"
elif [ -e /dev/ttyACM0 ]; then
    ok "cdc_acm is in use (a /dev/ttyACM* node exists, so the driver is loaded and bound)"
else
    warn "cdc_acm neither loaded nor bound — try 'sudo modprobe cdc_acm' after plugging a modem in"
fi

################################################################################
head_ "USB voice modems ($MODEM_VENDOR:$MODEM_PRODUCT)"
################################################################################
MODEM_PATHS=""
for d in /sys/bus/usb/devices/*/; do
    [ -e "$d" ] || continue
    is_target_modem "$d" || continue
    MODEM_PATHS="$MODEM_PATHS $(basename "$d")"
done
MODEM_COUNT=$(echo "$MODEM_PATHS" | wc -w | tr -d ' ')

if [ "$MODEM_COUNT" -eq 0 ]; then
    miss "no $MODEM_VENDOR:$MODEM_PRODUCT modem detected — plug the USB modems into the PFR and re-run"
else
    info "found $MODEM_COUNT modem(s); expecting $EXPECTED_MODEMS for a full Fixnet rack"
    if [ "$MODEM_COUNT" -lt "$EXPECTED_MODEMS" ]; then
        warn "$MODEM_COUNT of $EXPECTED_MODEMS modems attached — bench is partial, or use --expected-modems N"
    elif [ "$MODEM_COUNT" -gt "$EXPECTED_MODEMS" ]; then
        warn "$MODEM_COUNT modems attached but $EXPECTED_MODEMS expected — check for a spare or a dupliate"
    fi

    printf "\n  %-10s  %-11s  %-12s  %s\n" "USB-PORT" "USB-ID" "DRIVER" "TTY"
    printf "  %-10s  %-11s  %-12s  %s\n" "--------" "------" "------" "---"
    for p in $MODEM_PATHS; do
        drv=$(driver_for_usb "$p")
        tty=$(tty_for_usb "$p")
        printf "  %-10s  %-11s  %-12s  %s\n" "$p" "$MODEM_VENDOR:$MODEM_PRODUCT" "$drv" "${tty:-(none)}"
        if [ "$drv" != "cdc_acm" ]; then
            warn "  modem $p is bound to '$drv', not cdc_acm — no /dev node will appear"
        elif [ -z "$tty" ]; then
            warn "  modem $p is claimed by cdc_acm but exposes no /dev/ttyACM* node"
        fi
    done
    printf "\n  info: USB-PORT (e.g. 1-2) is the stable identity; the ttyACM number is not.\n"
fi

################################################################################
head_ "Serial device access"
################################################################################
TTY_NODES=$(ls /dev/ttyACM* 2>/dev/null | wc -l | tr -d ' ')
if [ "$TTY_NODES" -eq 0 ]; then
    warn "no /dev/ttyACM* nodes at all — nothing can talk to a modem yet"
else
    ok "$TTY_NODES /dev/ttyACM* node(s) present"
    for n in /dev/ttyACM*; do
        [ -e "$n" ] || continue
        info "$(stat -c '%A %U:%G' "$n")  $n"
    done
fi

# The serial dial-out group. Missing group membership is the single most common
# reason an AT session that works in picocom-as-root fails for the service user.
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
    ok "current user is in group dialout"
else
    if getent group dialout >/dev/null 2>&1; then
        warn "user '$(id -un)' is NOT in group dialout — add it and re-login before any AT access"
    else
        miss "group dialout does not exist (package: adduser) — create it, then add the service user"
    fi
fi

################################################################################
head_ "Serial tooling"
################################################################################
for t in picocom minicom screen stty; do
    if have "$t"; then
        ok "$t present"
    else
        case "$t" in
            picocom|minicom) warn "$t missing (apt: $t) — the bench terminal used for the DTMF spike" ;;
            stty)           miss "$t missing — the dependency-free AT probe needs it" ;;
            *)              info "$t missing (optional)" ;;
        esac
    fi
done

if have python3; then
    if python3 -c "import serial" >/dev/null 2>&1; then
        ok "pyserial importable ($(python3 -c 'import serial; print(serial.__version__)' 2>/dev/null))"
    else
        miss "python3 module 'serial' (pyserial) — required by the voice controller, not just the bench"
    fi
    # These are the standard-library modules the AT channel leans on. `serial`
    # is deliberately NOT here — it is pyserial, checked just above.
    for m in termios select fcntl struct; do
        python3 -c "import $m" >/dev/null 2>&1 \
            || miss "python3 module '$m' missing (standard library — broken python install?)"
    done
else
    miss "cannot check python modules — python3 missing"
fi

################################################################################
head_ "Stable device naming (TASK-71 goal 1)"
################################################################################
# Without this, /dev/ttyACM0..3 can be reassigned across reboots and a test
# result gets attributed to the wrong gateway. See docs/agent/devices/
# PERSISTENT_DEVICES.md for the udev rule recipe.
if have udevadm; then
    ok "udev present ($(udevadm --version 2>/dev/null | head -1))"
else
    miss "udevadm missing (apt: udev) — required to write the port-keyed rules"
fi

if [ -d "$STABLE_DIR" ]; then
    LINKS=$(find "$STABLE_DIR" -maxdepth 1 -name 'modem*' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$LINKS" -gt 0 ]; then
        ok "$STABLE_DIR holds $LINKS modem symlink(s): $(find "$STABLE_DIR" -maxdepth 1 -name 'modem*' -printf '%f ' 2>/dev/null)"
    else
        warn "$STABLE_DIR exists but has no modem* symlinks — nothing is pinned yet"
    fi
else
    miss "no $STABLE_DIR — the modems are still reachable only by enumeration-order tty name"
fi

# The device-facing names the `fx` remote controller reads (DEVICE{i}_FX_PORT).
# Same udev rule as the modemN links, so these existing means the rules were
# written by an installer new enough to emit both.
FX_LINKS=$(ls /dev/fx[0-9]* 2>/dev/null | wc -l | tr -d ' ')
if [ "$FX_LINKS" -gt 0 ]; then
    ok "/dev/fx* holds $FX_LINKS device-facing symlink(s): $(ls /dev/fx[0-9]* 2>/dev/null | tr '\n' ' ')"
    if [ "$FX_LINKS" -lt "$EXPECTED_MODEMS" ]; then
        warn "only $FX_LINKS of $EXPECTED_MODEMS /dev/fx* names exist — re-run install_fixnet_prereqs.sh"
    fi
else
    warn "no /dev/fx* names — the fx remote controller has no DEVICE{i}_FX_PORT to point at"
    warn "        run install_fixnet_prereqs.sh --apply (it emits both modemN and fxN)"
fi

if [ -d /etc/udev/rules.d ]; then
    if grep -rqi "fixnet" /etc/udev/rules.d/ 2>/dev/null; then
        ok "udev rule(s) mentioning 'fixnet' present in /etc/udev/rules.d"
        grep -rli "fixnet" /etc/udev/rules.d/ 2>/dev/null | sed 's/^/         /'
    else
        warn "no /etc/udev/rules.d rule references 'fixnet' — the stable names are unwritten"
    fi
else
    warn "/etc/udev/rules.d does not exist"
fi

# scripts/detect_grabber.sh is the tool that prints the port map to build the
# rule from. It only knows video/audio/BT/IR, so on a modem host it prints
# nothing useful — the modem walk above is the equivalent for ttyACM.
if [ -f "$(dirname "$0")/detect_grabber.sh" ]; then
    info "detect_grabber.sh present (video/audio/BT/IR only — not the modem ports)"
else
    info "port map for the udev rules is the USB-PORT column above"
    info "(scripts/detect_grabber.sh maps video/audio/BT/IR only — not these modems)"
fi

################################################################################
head_ "Voice audio"
################################################################################
if [ -d /dev/snd ]; then
    ok "/dev/snd present"
else
    warn "no /dev/snd — ALSA capture/playback for voice recording is unavailable"
fi
for t in aplay arecord; do
    if have "$t"; then ok "$t present"; else warn "$t missing (apt: alsa-utils) — voice capture/playback"; fi
done
for t in ffmpeg ffprobe; do
    if have "$t"; then ok "$t present"; else warn "$t missing (apt: ffmpeg) — 8 kHz PCM <-> playable file conversion"; fi
done

################################################################################
head_ "Matrix switch (1:12 cross-connect)"
################################################################################
# The switch is driven out-of-band, usually through a USB-serial cable, so it
# appears as an extra serial adapter — not as a 0572:1349 modem. Look for the
# adapters that such a cable usually is, and report any serial node that is NOT
# a modem so it can be identified by hand.
info "no automatic detection is possible: the switch answers on its own control port."
info "identify the control port by hand, then record it in the install script."
if have lsusb; then
    ADAPTERS=$(lsusb 2>/dev/null | grep -iE "0403:|1a86:|10c4:|067b:|0403" || true)
    if [ -n "$ADAPTERS" ]; then
        ok "USB-serial adapter(s) present (candidate switch control ports):"
        echo "$ADAPTERS" | sed 's/^/         /'
    else
        warn "no FTDI/CH340/CP210x/Prolific adapter seen — the switch control port is not enumerable"
    fi
fi

TTY_USB=$(ls /dev/ttyUSB* 2>/dev/null | wc -l | tr -d ' ')
info "serial nodes present: $TTY_NODES x /dev/ttyACM*, $TTY_USB x /dev/ttyUSB*"
info "Fixnet modems detected on USB: $MODEM_COUNT (expected $EXPECTED_MODEMS)"
if [ "$TTY_USB" -gt 0 ]; then
    warn "$TTY_USB /dev/ttyUSB* node(s) present — most likely the matrix-switch control adapter;"
    warn "        confirm by hand which port drives the 1:12 switch and record it here."
fi

################################################################################
head_ "VPT host integration"
################################################################################
# Optional: the PFR is a real backend_host, so a deployed VPT tree should be
# reachable. None of this blocks the bench work — it only blocks goal 8.
if have systemctl && systemctl list-unit-files 2>/dev/null | grep -q "vpt-host"; then
    ok "vpt-host unit found — this PFR is a deployed VPT host"
else
    info "no vpt-host unit detected — the PFR is not (yet) a deployed VPT host"
fi
if have systemctl && systemctl list-unit-files 2>/dev/null | grep -q "vpt-lease"; then
    info "vpt-lease present — claim this platform before any bench session"
else
    info "no vpt-lease unit detected — check with the other agents before using the PFR"
fi

################################################################################
head_ "AT reachability (--probe)"
################################################################################
if [ "$PROBE" -eq 0 ]; then
    info "skipped — re-run with --probe to send a bare AT to each modem"
elif ! have stty; then
    miss "cannot probe: stty is missing (needed for the dependency-free AT probe)"
elif [ "$MODEM_COUNT" -eq 0 ]; then
    miss "cannot probe: no modem detected"
else
    # `AT` is a no-op query. It does not dial, does not enter voice mode and
    # does not change line state, so it is safe on a live line — but it DOES
    # open the port, which is why it is opt-in.
    for p in $MODEM_PATHS; do
        tty=$(tty_for_usb "$p")
        [ -n "$tty" ] || { warn "modem $p: no tty node, skipped"; continue; }
        reply=$(at_send "$tty" "AT")
        if echo "$reply" | grep -q "OK"; then
            ok "modem $p ($tty): AT -> OK"
            fw=$(at_send "$tty" "ATI3")
            if [ -n "$fw" ]; then
                fwline=$(echo "$fw" | grep -iv "^OK" | grep -i "CX9\|V92\|EIS" | head -1)
                info "        firmware: ${fwline:-(no CX9/V92 string in reply)}"
            fi
        else
            warn "modem $p ($tty): no OK from AT — reply was: ${reply:-(empty)}"
            warn "        check dialout membership, another process holding the port, or baud rate"
        fi
    done
fi

################################################################################
head_ "Summary"
################################################################################
printf "  %d ok   %d missing   %d warning\n\n" "$N_OK" "$N_MISS" "$N_WARN"

if [ "$N_MISS" -gt 0 ]; then
    printf "  %d required prerequisite(s) missing — this host is not ready for the first call test.\n" "$N_MISS"
    printf "  Install them in a separate step; this script deliberately installs nothing.\n\n"
    exit 1
fi

printf "  No required prerequisite is missing.\n"
printf "  Warnings still need a human decision (see [WARN] lines) — install nothing for those.\n"
exit 0