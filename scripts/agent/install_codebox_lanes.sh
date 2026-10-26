#!/usr/bin/env bash
# Install the game lanes on codebox: the system units (game dispatcher, Pokemon dispatcher, stall
# watcher) and the user units (the CoC Flash lane, the second Pokemon save).
#
# The units live in scripts/agent/systemd/ of the repository: a unit that is only on the machine
# drifts from the one in the repository, and that is how the lanes kept running code that main had
# already replaced (BUG-0920). This script copies them, reloads systemd and starts what is not
# running.
#
# Usage: install_codebox_lanes.sh [--user-only|--system-only]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_DIR="/etc/systemd/system"
USER_DIR="${HOME}/.config/systemd/user"
CLONES=("${HOME}/.local/share/game-dispatch/repo" "${HOME}/.local/share/pokemon-dispatch/repo" "${HOME}/.local/share/vpt-stall-watch")

SYSTEM_UNITS=(game-dispatch.service game-dispatch.timer pokemon-dispatch.service pokemon-dispatch.timer
               pokemon-stall-watch.service pokemon-stall-watch.timer)
USER_UNITS=(vpt-flash-games.service vpt-pokemon-2.service vpt-pokemon-2.timer)

mode="all"
[[ "${1:-}" == "--user-only" ]] && mode="user"
[[ "${1:-}" == "--system-only" ]] && mode="system"

echo "== the lane clones"
for c in "${CLONES[@]}"; do
  if [[ -d "${c}/.git" ]]; then
    echo "   ${c} -> $(git -C "${c}" rev-parse --short HEAD 2>/dev/null || echo '?')"
  else
    echo "   ${c} is missing - cloning it"
    mkdir -p "$(dirname "${c}")"
    git clone --quiet git@github.com:AngelStreetCorp/virtualpytest-internal.git "${c}" || echo "   CLONE FAILED: ${c}"
  fi
done

if [[ "${mode}" != "user" ]]; then
  echo "== the system units"
  # The sync script lives in ~/.local/bin: the units call it before every tick, and that path must not
  # depend on the shared checkout (whose branch the other sessions switch under each other).
  install -m 0755 "${HERE}/sync_lane_clone.sh" "${HOME}/.local/bin/sync_lane_clone.sh" || echo "   FAILED: sync_lane_clone.sh"
  for u in "${SYSTEM_UNITS[@]}"; do
    sudo -n install -m 0644 "${HERE}/systemd/${u}" "${SYSTEM_DIR}/${u}" || echo "   FAILED: ${u}"
  done
  sudo -n systemctl daemon-reload
  for u in game-dispatch.timer pokemon-dispatch.timer pokemon-stall-watch.timer; do
    sudo -n systemctl enable --now "${u}" || echo "   FAILED to enable: ${u}"
  done
fi

if [[ "${mode}" != "system" ]]; then
  echo "== the user units"
  mkdir -p "${USER_DIR}"
  for u in "${USER_UNITS[@]}"; do
    install -m 0644 "${HERE}/systemd/${u}" "${USER_DIR}/${u}" || echo "   FAILED: ${u}"
  done
  install -m 0755 "${HERE}/vpt-flash-games.sh" "${HOME}/.local/bin/vpt-flash-games.sh" || echo "   FAILED: vpt-flash-games.sh"
  systemctl --user daemon-reload || true
  systemctl --user enable --now vpt-flash-games.service || echo "   FAILED to enable: vpt-flash-games.service"
  systemctl --user enable --now vpt-pokemon-2.timer || echo "   FAILED to enable: vpt-pokemon-2.timer"
fi

echo "== the lanes"
systemctl --user is-active vpt-flash-games.service 2>/dev/null | sed 's/^/   vpt-flash-games: /'
systemctl --user is-active vpt-pokemon-2.timer 2>/dev/null | sed 's/^/   vpt-pokemon-2.timer: /'
for u in game-dispatch.timer pokemon-dispatch.timer pokemon-stall-watch.timer; do
  systemctl is-active "${u}" 2>/dev/null | sed "s|^|   ${u}: |"
done
