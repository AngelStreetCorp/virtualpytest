#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
VERSION_FILE="${REPO_ROOT}/VERSION.txt"

if [[ ! -f "${VERSION_FILE}" ]]; then
  echo "[version] ${VERSION_FILE} not found" >&2
  exit 1
fi

current_line="$(grep -E '^current:' "${VERSION_FILE}" | head -n 1 || true)"

if [[ -z "${current_line}" ]]; then
  echo "[version] Missing current: line in ${VERSION_FILE}" >&2
  exit 1
fi

current_value="${current_line#current:}"
current_value="${current_value#"${current_value%%[![:space:]]*}"}"
current_value="${current_value%"${current_value##*[![:space:]]}"}"

if [[ ! "${current_value}" =~ ^([A-Za-z0-9._/-]+)-([0-9]{4}\.[0-9]{2}\.[0-9]{2})-([0-9]+)$ ]]; then
  echo "[version] Unsupported current: format: ${current_value}" >&2
  exit 1
fi

branch_name="${BASH_REMATCH[1]}"
build_number="${BASH_REMATCH[3]}"
next_build_number="$((build_number + 1))"
today="$(date '+%Y.%m.%d')"
head_hash="$(git rev-parse --short=7 HEAD 2>/dev/null || echo unknown)"
git_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -n "${git_branch}" && "${git_branch}" != "HEAD" ]]; then
  branch_name="${git_branch}"
fi
next_current="current:${branch_name}-${today}-${next_build_number}"
next_previous="previous:${current_value}-${head_hash}"

new_content="${next_current}"$'\n'"${next_previous}"$'\n'
existing_content="$(cat "${VERSION_FILE}")"
if [[ "${existing_content}" == "${new_content%$'\n'}" ]]; then
  exit 0
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  printf '%s' "${new_content}"
  exit 0
fi

printf '%s' "${new_content}" > "${VERSION_FILE}"

if [[ "${1:-}" == "--print" ]]; then
  printf '%s' "${new_content}"
fi
