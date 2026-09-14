#!/usr/bin/env bash
# feature_units.sh — shared logic for the feature systemd units
# (features/<name>/backend_host/services/<unit>.service -> /etc/systemd/system/vpt-<unit>.service).
#
# Sourced by:
#   setup/proxmox/node/deploy_customer.sh          (reconciles the units of every host target over ssh)
#   setup/proxmox/node/reconcile_feature_units.sh  (same reconcile, standalone ON the host — bundle /
#                                                   classic update_core.sh path)
# so both render the exact same bytes and share one core-unit rule. Pure bash 3.2, no ssh,
# no systemctl in here. See docs/technical/FEATURES.md and DEPLOY_CUSTOMER.md
# ("Feature systemd units").
#
# Caller-provided variables:
#   TARGET_DIR          absolute path the rendered units point at (%PROJECT_ROOT% substitution),
#                       e.g. /opt/virtualpytest
#   FEATURE_UNITS_TREE  tree whose backend_host/config/services/linux/<unit>.service templates
#                       define extra core units (the staged tree / the project root); may be empty

# First lines of every rendered unit. The marker is what makes an installed unit eligible
# for removal when its feature is disabled/removed; the second line is deliberately
# tool-neutral so a unit rendered by deploy_customer.sh and the same unit rendered by
# reconcile_feature_units.sh compare equal (no spurious "changed" -> restart).
FEATURE_UNIT_MARKER='# vpt-feature:'
FEATURE_UNIT_RENDER_NOTE='rendered by the VirtualPyTest deploy (setup/proxmox/node/lib/feature_units.sh) — do not edit on the host, the next deploy overwrites it'

# Unit names (without the vpt- prefix) that must never be installed or removed here.
CORE_UNIT_NAMES=(host server frontend-prod frontend-dev stream monitor subtitle transcript
                 archiver kpi vnc websockify ble-remote hid-agent hid-remote flask)

# trim <string>: strip leading/trailing whitespace.
trim() {
  local h="$1"
  h="${h#"${h%%[![:space:]]*}"}"
  h="${h%"${h##*[![:space:]]}"}"
  printf '%s' "$h"
}

# is_core_unit <unit>: a name the deploy must never install or remove (fixed list, any
# frontend* unit, or anything with a core template in
# ${FEATURE_UNITS_TREE}/backend_host/config/services/linux).
is_core_unit() {
  local u="$1" c
  for c in "${CORE_UNIT_NAMES[@]}"; do
    [[ "${u}" == "${c}" || "${u}" == "${c}@"* ]] && return 0
  done
  [[ "${u}" == frontend* ]] && return 0
  [[ -n "${FEATURE_UNITS_TREE:-}" && -f "${FEATURE_UNITS_TREE}/backend_host/config/services/linux/${u}.service" ]] && return 0
  return 1
}

# manifest_units <manifest.json>: names of an optional flat "units": ["a", "b"] key, one
# per line; empty when absent (then the template file names are used). No jq needed.
manifest_units() {
  tr -d '\n\r' < "$1" \
    | sed -n 's/.*"units"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
    | tr ',' '\n' | tr -d ' \t"' | sed '/^$/d'
}

# list_feature_units <root> [feature ...]: one "<feature>\t<unit>\t<template>" line per
# host unit of every feature under <root>/features (or only the named ones) that has a
# manifest.json. Unit = manifest "units" entry if declared, else the template file name
# (x.service -> x, x@.service -> x@).
list_feature_units() {
  local root="$1"; shift
  local names=("$@") d m name u tpl declared
  if [[ ${#names[@]} -eq 0 ]]; then
    for d in "${root}"/features/*/; do
      [[ -f "${d}manifest.json" ]] && names+=("$(basename "${d}")")
    done
  fi
  for name in ${names[@]+"${names[@]}"}; do
    m="${root}/features/${name}/manifest.json"
    [[ -f "${m}" ]] || continue
    declared="$(manifest_units "${m}")"
    if [[ -n "${declared}" ]]; then
      for u in ${declared}; do
        tpl="${root}/features/${name}/backend_host/services/${u}.service"
        if [[ -f "${tpl}" ]]; then
          printf '%s\t%s\t%s\n' "${name}" "${u}" "${tpl}"
        else
          echo "WARNING: features/${name}/manifest.json lists unit '${u}' but features/${name}/backend_host/services/${u}.service is missing" >&2
        fi
      done
    else
      for tpl in "${root}/features/${name}/backend_host/services/"*.service; do
        [[ -f "${tpl}" ]] || continue
        printf '%s\t%s\t%s\n' "${name}" "$(basename "${tpl}" .service)" "${tpl}"
      done
    fi
  done
}

# render_feature_unit <feature> <unit> <template> <out>: what lands in
# /etc/systemd/system/vpt-<unit>.service = marker header + template with
# %PROJECT_ROOT% -> TARGET_DIR (same substitution as install_service.sh). Pure, no ssh.
render_feature_unit() {
  local feature="$1" unit="$2" template="$3" out="$4"
  local root_escaped
  root_escaped="$(printf '%s' "${TARGET_DIR}" | sed 's/[&|\\]/\\&/g')"
  {
    printf '%s %s\n' "${FEATURE_UNIT_MARKER}" "${feature}"
    printf '# features/%s/backend_host/services/%s.service %s\n' "${feature}" "${unit}" "${FEATURE_UNIT_RENDER_NOTE}"
    sed "s|%PROJECT_ROOT%|${root_escaped}|g" "${template}"
  } > "${out}"
}

# marker_lines_to_units: stdin = `grep -H -m1 '^# vpt-feature: ' <dir>/vpt-*.service` output
# ("<path>:# vpt-feature: <name>"), stdout = "<unit>\t<feature>" per line.
marker_lines_to_units() {
  local line path feature unit
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    path="${line%%:*}"
    feature="$(trim "${line##*"${FEATURE_UNIT_MARKER}"}")"
    unit="$(basename "${path}" .service)"; unit="${unit#vpt-}"
    printf '%s\t%s\n' "${unit}" "${feature}"
  done
}

# units_has <"<feature>\t<unit>\t<template>" lines> <unit>: is vpt-<unit> in the list?
units_has() {
  printf '%s\n' "$1" | awk -F'\t' -v u="$2" '$2 == u { f = 1 } END { exit !f }'
}
