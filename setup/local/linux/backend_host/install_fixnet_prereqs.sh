#!/bin/bash
################################################################################
# install_fixnet_prereqs.sh — apply what check_fixnet_prereqs.sh reported missing.
#
# Companion to check_fixnet_prereqs.sh. Run the audit first; this script
# fixes the mechanical parts of what it found and prints the parts it will not
# touch.
#
#   setup/local/linux/backend_host/check_fixnet_prereqs.sh                 # see what is missing
#   setup/local/linux/backend_host/install_fixnet_prereqs.sh              # DRY RUN — prints every command
#   setup/local/linux/backend_host/install_fixnet_prereqs.sh --apply      # actually do it (needs sudo)
#
# WHY:
#   cdc_acm hands out /dev/ttyACM0, /dev/ttyACM1, ... in USB enumeration order
#   at boot. With several IDENTICAL Conexant CX9300x voice modems (0572:1349)
#   that ordering — and therefore which physical line is modem0 vs modem1 vs
#   ... — can flip on every reboot or replug, silently dialling one gateway and
#   attributing the result to another. The kernel does not promise the same
#   number twice. The only stable identity is the physical USB PORT PATH.
#
# CONVENTION (identical to install_bt_pinning.sh):
#   * modems are numbered in ASCENDING USB-port order, so the lowest USB port
#     gets the lowest number. Each rule emits TWO symlinks for one node:
#       /dev/fixnet/modemN  0-based, port-indexed — the audit + bench scripts
#       /dev/fxN            1-based, device-facing — .env (DEVICE{i}_FX_PORT)
#                           and the fx remote controller, which reads like the
#                           /dev/stb1 convention used for STB peripherals.
#   * Consequence: the numbering is POSITIONAL. Plug every modem into its final
#     port BEFORE running this once, and label the physical ports afterwards.
#     Re-running after adding a modem that sorts EARLIER renumbers the rest.
#     The rules are keyed on port, so modems that keep their port keep their
#     name — only the numbering shifts.
#
# Safe by default: with no --apply it prints the plan and changes nothing.
# Idempotent: packages already installed and rules already correct are skipped.
#
# It fixes:
#   1. missing apt packages (usbutils, picocom, minicom, alsa-utils, ffmpeg,
#      kmod, python3-serial, udev)
#   2. pyserial in BOTH the system python and the VPT service venv
#      (/opt/virtualpytest/venv) — apt alone leaves the service unable to
#      import serial, which is the mistake that costs an afternoon
#   3. dialout group membership for the calling user
#   4. stable /dev/fixnet/modemN names, pinned to USB topology ports, plus the
#      boot-time recreation of /dev/fixnet (/dev is tmpfs and is emptied)
#
# It will NOT fix — these need hardware or a decision, not a package:
#   * the 2 modems that are not plugged in yet
#   * the matrix-switch control port (nothing to enumerate until it is wired)
#
# Overridable at run time, same style as install_bt_pinning.sh:
#   MODEM_VENDOR=0572 MODEM_PRODUCT=1349 VENV=/opt/virtualpytest/venv \
#     bash setup/local/linux/backend_host/install_fixnet_prereqs.sh --apply
#
# Exit code: 0 = done (or dry run completed), 1 = a step failed or sudo is
# unavailable for a step that needs it.
################################################################################

set -u

APPLY=0
PORTS=""            # override the auto-detected port list, e.g. "5-1,5-2"
VENV="${VENV:-/opt/virtualpytest/venv}"
TARGET_USER="$(id -un)"
# Identical modems are the whole reason this script exists, so the IDs are
# overridable exactly like BELKIN_VID/BELKIN_PID in install_bt_pinning.sh.
MODEM_VENDOR="${MODEM_VENDOR:-0572}"
MODEM_PRODUCT="${MODEM_PRODUCT:-1349}"
RULES=/etc/udev/rules.d/99-fixnet-modems.rules
TMPFILES=/etc/tmpfiles.d/fixnet.conf

usage() { sed -n '3,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --apply)  APPLY=1 ;;
        --ports)  shift; PORTS="${1:-}" ;;
        --venv)   shift; VENV="${1:-}" ;;
        --user)   shift; TARGET_USER="${1:-}" ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

if [ "$APPLY" -eq 1 ]; then
    MODE="APPLY"
else
    MODE="DRY RUN — nothing will be changed (add --apply to execute)"
fi

N_DONE=0; N_SKIPPED=0; N_FAILED=0

run() {
    # run <description> <command...> — print, then execute when --apply.
    local desc="$1"; shift
    printf "  $ %s\n" "$*"
    printf "    -> %s\n" "$desc"
    if [ "$APPLY" -eq 1 ]; then
        if "$@" >/tmp/fixnet-install-step.log 2>&1; then
            printf "    [done]\n"; N_DONE=$((N_DONE+1)); return 0
        else
            printf "    [FAILED] last lines:\n"
            tail -5 /tmp/fixnet-install-step.log | sed 's/^/       /'
            N_FAILED=$((N_FAILED+1)); return 1
        fi
    else
        N_SKIPPED=$((N_SKIPPED+1))
    fi
    return 0
}

note() { printf "  [note] %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
need_sudo() {
    if [ "$APPLY" -eq 0 ]; then return 0; fi
    if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        printf "  [FAIL] this step needs root; run with sudo or as root\n"
        N_FAILED=$((N_FAILED+1)); return 1
    fi
    return 0
}

printf "\n== fixnet prerequisite install (%s)\n" "$MODE"

################################################################################
# 0. preflight
################################################################################
if [ ! -r /etc/os-release ]; then
    echo "  [FAIL] no /etc/os-release — this script targets Debian" >&2
    exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
    debian) printf "  [ok]   %s\n" "$PRETTY_NAME" ;;
    *)      warn "not Debian ($PRETTY_NAME) — apt package names below may differ" ;;
esac
if [ "$APPLY" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
    if sudo -n true 2>/dev/null; then
        printf "  [ok]   sudo available without a password prompt\n"
    else
        printf "  [FAIL] 'sudo -n true' failed — run this with sudo, or as root\n"
        exit 1
    fi
fi

################################################################################
# 1. apt packages
################################################################################
printf "\n== 1. packages\n"
MISSING=""
for p in usbutils picocom minicom alsa-utils ffmpeg kmod python3-serial udev; do
    if dpkg -s "$p" >/dev/null 2>&1; then
        printf "  [ok]   %s\n" "$p"
    else
        printf "  [MISS] %s\n" "$p"
        MISSING="$MISSING $p"
    fi
done

if [ -n "$MISSING" ]; then
    if [ "$APPLY" -eq 1 ]; then
        need_sudo || true
        run "refresh apt lists"                sudo apt-get update
        run "install$MISSING"                 sudo apt-get install -y $MISSING
    else
        printf "  $ sudo apt-get update\n"
        printf "  $ sudo apt-get install -y %s\n" "$MISSING"
        N_SKIPPED=$((N_SKIPPED+1))
    fi
else
    printf "  [ok]   all required packages already installed\n"
fi

################################################################################
# 2. pyserial in the service venv
################################################################################
# apt's python3-serial lands in the SYSTEM python. The VPT host service runs
# /opt/virtualpytest/venv/bin/python (see backend_host/config/services/linux/
# host.service), which does not see system site-packages. Without this the
# voice controller imports fine in your shell and fails in the service.
printf "\n== 2. pyserial in the VPT service venv\n"
if [ -x "$VENV/bin/python" ]; then
    if "$VENV/bin/python" -c "import serial" >/dev/null 2>&1; then
        printf "  [ok]   %s already has pyserial\n" "$VENV"
    else
        printf "  [MISS] %s cannot import serial\n" "$VENV"
        run "pip install pyserial into the service venv" \
            sudo "$VENV/bin/pip" install pyserial
        note "if the venv rejects system-wide installs: $VENV/bin/pip install --break-system-packages pyserial"
    fi
else
    warn "no interpreter at $VENV/bin/python — is this PFR a deployed VPT host?"
    note "skipping; pass --venv /path/to/venv if it lives elsewhere"
fi

################################################################################
# 3. dialout group
################################################################################
# cdc_acm hands out root:dialout 0660 nodes. Without group membership an AT
# session that works under sudo fails for the service user.
printf "\n== 3. dialout access\n"
# The platform runs the modems as vpt_user (vpt-host), not as whoever runs this installer,
# so both get the group.
DIALOUT_USERS="$TARGET_USER"
if [ "$TARGET_USER" != "vpt_user" ] && id vpt_user >/dev/null 2>&1; then
    DIALOUT_USERS="$DIALOUT_USERS vpt_user"
fi
if ! getent group dialout >/dev/null 2>&1; then
    run "create the dialout group" sudo groupadd dialout
fi
NEED_RESTART=0
for u in $DIALOUT_USERS; do
    if id -nG "$u" 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
        printf "  [ok]   %s is already in dialout\n" "$u"
    else
        printf "  [MISS] %s is not in dialout\n" "$u"
        run "add $u to dialout" sudo usermod -aG dialout "$u"
        NEED_RESTART=1
    fi
done
if [ "$NEED_RESTART" = 1 ]; then
    note "group membership only applies to NEW logins: log out and back in (or run 'newgrp dialout')"
    note "vpt-host keeps its old groups until restarted: sudo systemctl restart vpt-host"
fi

################################################################################
# 4. stable /dev/fixnet names
################################################################################
printf "\n== 4. stable device names\n"

detect_ports() {
    local d v p out=""
    for d in /sys/bus/usb/devices/*/; do
        [ -f "$d/idVendor" ] || continue
        v=$(cat "$d/idVendor" 2>/dev/null)
        [ "$v" = "$MODEM_VENDOR" ] || continue
        [ "$(cat "$d/idProduct" 2>/dev/null)" = "$MODEM_PRODUCT" ] || continue
        out="$out $(basename "$d")"
    done
    echo "$out" | tr ' ' '\n' | grep -v '^$' | sort -V | tr '\n' ' '
}

if [ -n "$PORTS" ]; then
    PORT_LIST=$(echo "$PORTS" | tr ',' ' ')
    printf "  [ok]   using the port list you gave: %s\n" "$PORT_LIST"
else
    PORT_LIST=$(detect_ports)
    if [ -z "$PORT_LIST" ]; then
        warn "no $MODEM_VENDOR:$MODEM_PRODUCT modem detected — plug the modems in, or pass --ports"
        note "example: --ports 5-1,5-2"
        PORT_LIST=""
    else
        printf "  [ok]   detected modem ports: %s\n" "$PORT_LIST"
    fi
fi

if [ -n "$PORT_LIST" ]; then
    NPORT=$(echo "$PORT_LIST" | wc -w | tr -d ' ')
    printf "  [info] numbering is positional in sorted port order:\n"
    i=0
    for p in $PORT_LIST; do
        printf "         fx%d  =  fixnet/modem%d  <->  USB port %s\n" "$((i+1))" "$i" "$p"
        i=$((i+1))
    done
    if [ "$NPORT" -lt 4 ]; then
        note "only $NPORT modem(s) present; re-run after plugging the rest — numbering may shift"
    fi

    # Build the rules file. KERNELS=="<port>" is the repo convention
    # (docs/agent/devices/PERSISTENT_DEVICES.md): the USB topology port is the
    # stable identity, the ttyACM number is not.
    RULES_BODY="# TASK-71 — stable names for the Fixnet USB voice modems (0572:1349)\n"
    RULES_BODY="$RULES_BODY# Generated by setup/local/linux/backend_host/install_fixnet_prereqs.sh.\n"
    RULES_BODY="$RULES_BODY# cdc_acm assigns /dev/ttyACM* in USB enumeration order, so the number in\n"
    RULES_BODY="$RULES_BODY# ttyACMN is NOT stable across reboots or replugs. The USB topology port is.\n"
    RULES_BODY="$RULES_BODY# To renumber: edit the KERNELS tokens here, or re-run the installer.\n"
    i=0
    for p in $PORT_LIST; do
        fx=$((i+1))
        RULES_BODY="$RULES_BODY# modem$i (device fx$fx) is physically in USB port $p\n"
        # Two symlinks, one rule, same node:
        #   fixnet/modemN  0-based, port-indexed — the audit, the bench scripts
        #   fxN            1-based, device-facing — .env and the fx remote controller
        # printf -v keeps the rule readable: no escaping gymnastics inside the
        # shell quoting, which is where the first version of this broke.
        printf -v RULE_LINE 'SUBSYSTEM=="tty", ATTRS{idVendor}=="%s", ATTRS{idProduct}=="%s", KERNELS=="%s", SYMLINK+="fixnet/modem%d", SYMLINK+="fx%d", MODE="0660", GROUP="dialout"\n' \
            "$MODEM_VENDOR" "$MODEM_PRODUCT" "$p" "$i" "$fx"
        RULES_BODY="$RULES_BODY$RULE_LINE"
        i=$((i+1))
    done

    printf '  $ write %s (%d rule(s))\n' "$RULES" "$NPORT"
    if [ "$APPLY" -eq 1 ]; then
        need_sudo || true
        printf '%b' "$RULES_BODY" > /tmp/fixnet-rules.body
        if sudo tee "$RULES" >/dev/null < /tmp/fixnet-rules.body; then
            printf "    [done] rules written\n"; N_DONE=$((N_DONE+1))
        else
            printf "    [FAILED] could not write %s\n" "$RULES"; N_FAILED=$((N_FAILED+1))
        fi
    else
        printf '%b' "$RULES_BODY" | sed 's/^/         /'
        N_SKIPPED=$((N_SKIPPED+1))
    fi

    # /dev is tmpfs: the directory holding the symlinks is wiped at boot, so it
    # has to be recreated by the system, not once by this script.
    printf "  $ write %s\n" "$TMPFILES"
    TF_BODY="# /dev is tmpfs and emptied on boot; /dev/fixnet must be recreated each time.\n# Type Path Mode UID GID Age Argument\nd /dev/fixnet 0755 root dialout -\n"
    if [ "$APPLY" -eq 1 ]; then
        need_sudo || true
        if printf '%b' "$TF_BODY" | sudo tee "$TMPFILES" >/dev/null; then
            printf "    [done] tmpfiles rule written\n"; N_DONE=$((N_DONE+1))
        else
            printf "    [FAILED] could not write %s\n" "$TMPFILES"; N_FAILED=$((N_FAILED+1))
        fi
        run "create /dev/fixnet now"  sudo systemd-tmpfiles --create fixnet.conf
    else
        printf '%b' "$TF_BODY" | sed 's/^/         /'
        N_SKIPPED=$((N_SKIPPED+1))
    fi

    printf "\n== 5. reload udev\n"
    run "reload udev rules"       sudo udevadm control --reload-rules
    run "apply to plugged modems" sudo udevadm trigger --subsystem-match=tty
    note "verify with: ls -l /dev/fixnet/ /dev/fx*"
else
    warn "skipping the udev rules — no modem ports known yet"
fi

################################################################################
printf "\n== summary\n"
if [ "$APPLY" -eq 0 ]; then
    printf "  DRY RUN. Nothing was changed. Re-run with --apply to execute the above.\n\n"
    exit 0
fi

printf "  %d step(s) done, %d skipped, %d failed\n" "$N_DONE" "$N_SKIPPED" "$N_FAILED"

printf "\n  Still yours to do — no script can do these:\n"
printf "   * plug the 2 remaining modems, then re-run both scripts (port numbering may shift)\n"
printf "   * identify the matrix-switch control port once it is wired, and record it here\n"
printf "   * label the physical USB ports once the rack layout is final\n"
printf "   * re-run setup/local/linux/backend_host/check_fixnet_prereqs.sh --probe to confirm AT on every line\n"

if [ "$N_FAILED" -gt 0 ]; then
    printf "\n  some steps failed — see [FAILED] above before running the audit again\n"
    exit 1
fi
printf "\n  Next: setup/local/linux/backend_host/check_fixnet_prereqs.sh --probe\n"
printf "  Then: ls -l /dev/fx*  (fx1 must be the lowest USB port)\n"
exit 0