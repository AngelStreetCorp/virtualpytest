#!/usr/bin/env bash
# Print rsync --exclude lines for every feature listed in DISABLED_FEATURES
# (comma-separated). Consumed by the deploy script so a disabled feature's folder
# never reaches a host. See docs/technical/FEATURES.md.
#
#   DISABLED_FEATURES=avq,quicktest bash scripts/disabled_features_excludes.sh
#   -> --exclude=/features/avq/
#      --exclude=/features/quicktest/
#
# Empty/unset list prints nothing (= everything is deployed).
set -euo pipefail
IFS=',' read -r -a _names <<< "${DISABLED_FEATURES:-}"
for _n in "${_names[@]:-}"; do
    _n="${_n//[[:space:]]/}"
    [ -n "$_n" ] || continue
    printf -- '--exclude=/features/%s/\n' "$_n"
done
