#!/usr/bin/env bash
set -euo pipefail

# host_postclone_configure.sh — give a freshly-cloned backend_host box its own
# identity back after it was imaged from a sysprepped golden SSD
# (see scripts/host_golden_sysprep.sh).
#
# Run this LOCALLY (SSH in, or on console) as root, ONCE, the first time the
# clone boots in its new physical machine.
#
# What it does:
#   - regenerates /etc/machine-id
#   - regenerates SSH host keys
#   - sets hostname (+ /etc/hosts)
#   - restarts bluetooth + hid-remote/hid-agent/ble-remote units so they
#     start clean against the (empty, post-sysprep) /var/lib/bluetooth state
#   - prints the manual steps that CANNOT be scripted (BLE re-pairing is
#     physical — new dongles mean new bonds)
#
# Usage:
#   sudo bash host_postclone_configure.sh <new-hostname>
#
# Optional:
#   --rename-vg <new-vg-name>   Also rename the LVM VG and fix every reference
#                                to it in fstab/crypttab/grub, then rebuild the
#                                initramfs and grub config. Requires a reboot
#                                immediately after, at the console — do not run
#                                this over a connection you're relying on to
#                                fix things if the reboot fails.

log() { echo "[postclone] $*"; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[postclone] must run as root (sudo)" >&2
  exit 1
fi

NEW_HOSTNAME="${1:-}"
if [[ -z "$NEW_HOSTNAME" || "$NEW_HOSTNAME" == -* ]]; then
  echo "Usage: sudo bash $0 <new-hostname> [--rename-vg <new-vg-name>]" >&2
  exit 2
fi
shift

RENAME_VG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rename-vg) RENAME_VG="${2:-}"; shift 2 ;;
    *) echo "[postclone] unknown option: $1" >&2; exit 2 ;;
  esac
done

CURRENT_HOSTNAME="$(hostname)"
CURRENT_MACHINE_ID="$(cat /etc/machine-id 2>/dev/null || true)"
if [[ -n "$CURRENT_MACHINE_ID" && "$CURRENT_HOSTNAME" != "golden-template" ]]; then
  echo "[postclone] this host already has a machine-id and a hostname other than"
  echo "[postclone] 'golden-template' ($CURRENT_HOSTNAME) — it doesn't look like a"
  echo "[postclone] fresh clone off the sysprepped image. Continue anyway? [y/N]"
  read -r ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "[postclone] aborted."; exit 1; }
fi

log "regenerating machine-id"
rm -f /etc/machine-id
systemd-machine-id-setup

log "regenerating SSH host keys"
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
systemctl restart ssh.service 2>/dev/null || systemctl restart sshd.service 2>/dev/null || true

log "setting hostname to $NEW_HOSTNAME"
echo "$NEW_HOSTNAME" > /etc/hostname
hostnamectl set-hostname "$NEW_HOSTNAME"
sed -i '/^127\.0\.1\.1[[:space:]]/d' /etc/hosts
echo "127.0.1.1	$NEW_HOSTNAME" >> /etc/hosts

# backend_host's own identity — this is the actual point of "postclone configure":
# the box's OS hostname above is cosmetic, HOST_NAME/HOST_URL in .env is what the
# server and frontend actually address this host by.
ENV_FILE="/opt/virtualpytest/backend_host/src/.env"
if [[ -f "$ENV_FILE" ]]; then
  OLD_HOST_NAME="$(grep -m1 '^HOST_NAME=' "$ENV_FILE" | cut -d= -f2-)"
  if [[ -n "$OLD_HOST_NAME" && "$OLD_HOST_NAME" != "$NEW_HOSTNAME" ]]; then
    log "updating $ENV_FILE: HOST_NAME=$OLD_HOST_NAME -> $NEW_HOSTNAME (backup kept alongside)"
    cp -a "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
    sed -i "s|^HOST_NAME=.*|HOST_NAME=${NEW_HOSTNAME}|" "$ENV_FILE"
    # HOST_URL is a path keyed off the OLD name (e.g. /host/vpt-pi1), not the IP —
    # only rewrite it if it actually follows that /host/<name> convention, so we
    # don't clobber a value someone customized to something else.
    if grep -q "^HOST_URL=/host/${OLD_HOST_NAME}$" "$ENV_FILE"; then
      sed -i "s|^HOST_URL=/host/${OLD_HOST_NAME}\$|HOST_URL=/host/${NEW_HOSTNAME}|" "$ENV_FILE"
      log "  also updated HOST_URL to /host/${NEW_HOSTNAME}"
    else
      log "  HOST_URL doesn't match the /host/<name> convention — left as-is, check it manually"
    fi
  else
    log "$ENV_FILE HOST_NAME already '$NEW_HOSTNAME' or unreadable — not touching it"
  fi
  log "NOT auto-changed, needs manual/coordinated action:"
  log "  - HOST_API_URL (embeds this box's IP, not its name — verify it matches the"
  log "    clone's actual IP: $(hostname -I 2>/dev/null | awk '{print $1}')"
  log "  - API_KEY — this is the golden source's auth secret, copied verbatim onto"
  log "    this clone. Issue/register a NEW key for '${NEW_HOSTNAME}' against"
  log "    backend_server before relying on this host; don't just randomize it here,"
  log "    the server has to know the new value too."
else
  log "WARNING: $ENV_FILE not found — backend_host .env not updated, check install path"
fi

if [[ -n "$RENAME_VG" ]]; then
  OLD_VG="$(vgs --noheadings -o vg_name 2>/dev/null | awk '{$1=$1};1' | head -1)"
  if [[ -z "$OLD_VG" ]]; then
    log "no VG found via vgs — skipping --rename-vg"
  else
    log "renaming VG '$OLD_VG' -> '$RENAME_VG' and fixing references (fstab/crypttab/grub)"
    log "refusing to do this unattended — showing what references '$OLD_VG' first:"
    grep -rn "$OLD_VG" /etc/fstab /etc/crypttab /boot/grub/grub.cfg 2>/dev/null || log "  (no textual references found — still verify manually)"
    echo "[postclone] Proceed with vgrename + fixing the above + update-initramfs + update-grub? [y/N]"
    read -r ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
      vgrename "$OLD_VG" "$RENAME_VG"
      sed -i "s/${OLD_VG}/${RENAME_VG}/g" /etc/fstab /etc/crypttab 2>/dev/null || true
      update-initramfs -u -k all
      update-grub
      log "VG renamed. REBOOT NOW AT THE CONSOLE and confirm it comes up before doing anything else."
    else
      log "skipped VG rename."
    fi
  fi
fi

log "restarting bluetooth + hid-remote/hid-agent/ble-remote units (clean start against empty bond store)"
systemctl restart bluetooth.service 2>/dev/null || true
for unit in $(systemctl list-units --all --no-legend --plain 'hid-remote*' 'hid-agent*' 'ble-remote*' 2>/dev/null | awk '{print $1}'); do
  systemctl restart "$unit" 2>/dev/null || true
done

DIAG=""
for candidate in \
  /opt/virtualpytest/backend_host/src/controllers/remote/bluetooth/diagnose_ble.sh \
  /home/*/virtualpytest/backend_host/src/controllers/remote/bluetooth/diagnose_ble.sh
do
  [[ -e "$candidate" ]] && DIAG="$candidate" && break
done

cat <<EOF

[postclone] Identity reconfigured: hostname=$NEW_HOSTNAME, machine-id + SSH host keys
[postclone] regenerated, backend_host HOST_NAME/HOST_URL updated in .env.

[postclone] MANUAL / coordinated steps still required before this unit is ready
[postclone] (cannot be scripted — physical action, or need the server side too):
[postclone]   1. lsusb — confirm the expected number of Bluetooth dongles / IR
[postclone]      adapters are present and none are wedged on THIS physical unit.
[postclone]   2. Re-pair every STB from scratch. /var/lib/bluetooth was wiped by
[postclone]      sysprep and this clone's dongles have different adapter MACs —
[postclone]      there is no bond data to reuse, this is expected and correct.
[postclone]   3. Verify HOST_API_URL in .env matches this box's real IP, and issue
[postclone]      a new API_KEY registered against backend_server for '$NEW_HOSTNAME'
[postclone]      — it currently still has the golden source's key/IP, unchanged.
[postclone]
[postclone]   *** EASY TO FORGET — done on a DIFFERENT machine, not this one: ***
[postclone]   4. Add '$NEW_HOSTNAME' to the nginx reverse-proxy's host map so
[postclone]      /host/$NEW_HOSTNAME/ actually routes here — infra/proxy/nginx/config/*.conf,
[postclone]      the "map \$host_identifier \$backend_host_ip { ... }" block:
[postclone]          "$NEW_HOSTNAME"  "$(hostname -I 2>/dev/null | awk '{print $1}')";
[postclone]      Without this, HOST_URL=/host/$NEW_HOSTNAME above resolves to nothing —
[postclone]      .env can be perfectly correct and the host still unreachable via the proxy.
EOF
if [[ -n "$DIAG" ]]; then
  echo "[postclone]   5. Run: sudo bash $DIAG   and confirm it comes back clean."
else
  echo "[postclone]   5. Run diagnose_ble.sh (not found at the usual paths — locate it"
  echo "[postclone]      under backend_host/src/controllers/remote/bluetooth/) and confirm clean."
fi
cat <<'EOF'
[postclone]   6. Cold-reboot this box and re-verify BLE/IR come back automatically
[postclone]      with NO manual pairing step, before handing it to the client.
EOF
