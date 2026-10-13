#!/usr/bin/env bash
# host_deploy.sh -- put a branch's changed host files on ONE test host, with a backup, and take
# them off again. For short measurements like time_one_testcase.sh; never restarts anything.
#
#   pack <commit> [base]   (dev checkout) build ./host_deploy_set/{timing.tar,FILES,MD5_NEW} from
#                          the files <commit> changes under backend_host/src and shared/src vs
#                          [base] (default: merge-base with internal/main). Uses `git cat-file -p`, not
#                          `git archive`, so the bytes are the committed blobs (no autocrlf).
#   deploy                 (on the host) back up every file the set replaces to
#                          /var/tmp/vpt-timing-backup (files it adds are recorded as absent),
#                          install the set as vpt_user, md5-check, py_compile, import-check.
#   restore                (on the host) put the backup back, delete files that were absent,
#                          md5-check each against the backup manifest.
#   status                 (on the host) md5 of the set's paths, backup state.
#
# Recipe used for feat/testcase-step-timing on host-clone-3 (192.168.0.111, via proxmox3):
#   bash scripts/debug/host_deploy.sh pack HEAD
#   scp -r host_deploy_set scripts/debug/host_deploy.sh proxmox3:/tmp/  # then on to the host:
#   ssh proxmox3 'scp -r /tmp/host_deploy_set /tmp/host_deploy.sh 192.168.0.111:/tmp/'
#   ssh proxmox3 'ssh 192.168.0.111 "bash /tmp/host_deploy.sh deploy && sudo -n systemctl restart vpt-host"'
#   ssh proxmox3 'bash /tmp/time_one_testcase.sh'           # twice: run 1 after a restart differs
#   ssh proxmox3 'ssh 192.168.0.111 "bash /tmp/host_deploy.sh restore && sudo -n systemctl restart vpt-host"'
# Restart only when the host is idle (time_one_testcase.sh's host_busy check).
set -euo pipefail
ROOT="${ROOT:-/opt/virtualpytest}"
STAGE="${STAGE:-/tmp/host_deploy_set}"
BACKUP="${BACKUP:-/var/tmp/vpt-timing-backup}"

case "${1:-status}" in
  pack)
    commit="${2:?pack <commit> [base]}"
    base="${3:-$(git merge-base "$commit" internal/main 2>/dev/null || echo "${commit}^")}"
    echo "pack: files changed between $base and $commit"
    out="${PWD}/host_deploy_set"; rm -rf "$out"; mkdir -p "$out/tree"
    git diff --name-only --diff-filter=AM "$base" "$commit" -- backend_host/src shared/src > "$out/FILES"
    while read -r f; do
      mkdir -p "$out/tree/$(dirname "$f")"
      git cat-file -p "$commit:$f" > "$out/tree/$f"
    done < "$out/FILES"
    (cd "$out/tree" && md5sum $(cat ../FILES) | sed 's/ \*/  /' > ../MD5_NEW)
    tar --force-local -C "$out/tree" -cf "$out/timing.tar" $(cat "$out/FILES")
    rm -rf "$out/tree"
    echo "packed $(wc -l < "$out/FILES") file(s) from $commit into $out"; cat "$out/MD5_NEW"
    exit 0 ;;
esac

FILES=$(cat "$STAGE/FILES")
case "$1" in
  deploy)
    [[ -e "$BACKUP/MANIFEST" ]] && { echo "backup already exists at $BACKUP - restore first"; exit 1; }
    sudo -n mkdir -p "$BACKUP/tree"
    manifest=$(mktemp)
    for f in $FILES; do
      if [[ -e "$ROOT/$f" ]]; then
        sudo -n mkdir -p "$BACKUP/tree/$(dirname "$f")"
        sudo -n cp -a "$ROOT/$f" "$BACKUP/tree/$f"
        echo "present $f $(md5sum < "$ROOT/$f" | cut -c1-32)" >> "$manifest"
      else
        echo "absent $f -" >> "$manifest"
      fi
    done
    # World-readable: restore and status read it as the calling user.
    sudo -n install -m 644 "$manifest" "$BACKUP/MANIFEST"; rm -f "$manifest"
    rm -rf "$STAGE/tree" && mkdir -p "$STAGE/tree" && tar -C "$STAGE/tree" -xf "$STAGE/timing.tar"
    for f in $FILES; do
      sudo -n install -D -o vpt_user -g vpt_user -m 664 "$STAGE/tree/$f" "$ROOT/$f"
    done
    (cd "$ROOT" && md5sum -c "$STAGE/MD5_NEW")
    PY_FILES=$(printf '%s\n' $FILES | grep '\.py$' || true)  # a set can carry non-Python files
    (cd "$ROOT" && sudo -n -u vpt_user "$ROOT/venv/bin/python" -m py_compile $PY_FILES && echo "py_compile ok")
    (cd "$ROOT" && sudo -n -u vpt_user env PYTHONPATH="$ROOT" "$ROOT/venv/bin/python" -c \
       "import shared.src.lib.executors.script_executor; print('import ok')")
    echo "backup manifest:"; sudo -n cat "$BACKUP/MANIFEST"
    ;;
  restore)
    [[ -e "$BACKUP/MANIFEST" ]] || { echo "no backup at $BACKUP"; exit 1; }
    while read -r state f sum; do
      if [[ "$state" == present ]]; then
        sudo -n cp -a "$BACKUP/tree/$f" "$ROOT/$f"
        got=$(md5sum < "$ROOT/$f" | cut -c1-32)
        [[ "$got" == "$sum" ]] && echo "restored $got $f" || { echo "MD5 MISMATCH $f $got != $sum"; exit 1; }
      else
        sudo -n rm -f "$ROOT/$f" "$ROOT/$(dirname "$f")/__pycache__/$(basename "$f" .py)".*.pyc
        [[ -e "$ROOT/$f" ]] && { echo "could not remove $f"; exit 1; } || echo "removed (was absent) $f"
      fi
    done < <(sudo -n cat "$BACKUP/MANIFEST")  # a manifest written before it was made 644 is root 0600
    sudo -n mv "$BACKUP" "$BACKUP.restored.$(date +%Y%m%dT%H%M%S)"
    ;;
  status)
    (cd "$ROOT" && md5sum $FILES 2>&1 || true)
    ls -la "$BACKUP" 2>/dev/null || echo "no active backup"
    ;;
  *) echo "usage: $0 pack <commit> [base] | deploy | restore | status"; exit 2 ;;
esac
