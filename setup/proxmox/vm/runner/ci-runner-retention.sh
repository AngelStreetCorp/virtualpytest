#!/usr/bin/env bash
# =============================================================================
# VirtualPyTest - CI runner retention
# =============================================================================
# Reclaims disk space under the self-hosted GitHub Actions runner workspaces
# (<runners-root>/<runner>/_work) without ever deleting the workspace of a
# running job.
#
# Installed by setup/proxmox/vm/runner/install_runner.sh to
# /usr/local/bin/ci-runner-retention.sh and driven by the two timers shipped
# next to this script (as templates, rendered into /etc/systemd/system under
# their real unit names - see setup/proxmox/vm/runner/README.md):
#
#   ci-runner-retention.timer        daily full cleanup
#   ci-runner-retention-check.timer  every 15 min, cleans only above the check
#                                    threshold (a full disk is a red CI)
#
# Those two timers are two different systemd units, so systemd does not
# serialise them: the daily pass and the 15-minute check can walk the same
# workspaces at the same time. A lock file keeps them apart - see "the lock"
# below.
#
# The rules that keep a live job safe (BUG-0903):
#
#   1. A runner is busy when one of its worker processes is alive. The worker
#      binary is versioned (bin.<x.y.z>/Runner.Worker), so the guard matches the
#      runner directory and any bin.<version> directory under it. Matching the
#      fixed path bin/Runner.Worker matches nothing and made every runner look
#      idle.
#   2. The busy check is repeated immediately before every rm -rf: a runner
#      that takes a job between the first check and the delete is not touched.
#   3. A workspace is reclaimed on its JOB activity - the last checkout and the
#      last file the job wrote inside the tree - never on the mtime of the
#      top-level directory, which only says when the tree was created.
#   4. A tree a live process holds (its cwd, or an open file inside it) is
#      never deleted - not in the age-filtered pass and not in the hard-disk
#      pass.
#   5. Every runner gets a decision line, and the reclaimed bytes are reported
#      per runner, so a failure can be diagnosed from the VM alone.
#
# Usage:
#   ci-runner-retention.sh [--check] [--dry-run] [--runners-root DIR]
#                           [--keep-days N] [--check-threshold PCT]
#                           [--hard-threshold PCT]
#   ci-runner-retention.sh --check-busy <runner-dir>
#
# Environment:
#   CI_RETENTION_LOCK_FILE  the lock file that serialises the two units
#                           (default /run/ci-runner-retention.lock)
#
# Exit codes: 0 = done, 1 = usage error.
# =============================================================================

# --- Defaults (every one of them can be overridden from the command line) ---
RUNNERS_ROOT="${RUNNERS_ROOT:-$HOME/runners}"
KEEP_DAYS="${KEEP_DAYS:-3}"
CHECK_THRESHOLD="${CHECK_THRESHOLD:-80}"
HARD_THRESHOLD="${HARD_THRESHOLD:-85}"

# The lock that serialises the daily pass and the 15-minute check. It is not a
# command-line option: it is an environment variable, so the tests can point
# it at a temporary file instead of the real one under /run.
LOCK_FILE="${CI_RETENTION_LOCK_FILE:-/run/ci-runner-retention.lock}"

CHECK_MODE=0
DRY_RUN=0
CHECK_BUSY_DIR=""

# --- small helpers ----------------------------------------------------------

log() { printf 'ci-retention: %s\n' "$*"; }

usage() {
    cat <<'EOF'
Usage: ci-runner-retention.sh [options]

  --check               only clean when a disk is above the check threshold
  --dry-run             report what would be deleted, delete nothing
  --runners-root DIR    root holding the runner directories (default $HOME/runners)
  --keep-days N         keep a workspace that saw job activity in the last N days
  --check-threshold PCT  disk percentage that triggers a cleanup in --check mode
  --hard-threshold PCT  disk percentage that triggers the hard-disk pass
  --check-busy DIR      print "busy" or "idle" for one runner directory, then exit
EOF
}

# Escape the characters that would otherwise be read as a regex.
escape_re() {
    printf '%s' "$1" | sed 's/[][\.^$*+?(){}|]/\\&/g'
}

# A path without its trailing slashes: the guards compare paths, and a path
# that ends in "/" does not match the one a process reports.
norm_path() {
    local p="${1:-}"
    while [ "${#p}" -gt 1 ] && [ "${p: -1}" = "/" ]; do
        p="${p%/}"
    done
    printf '%s' "$p"
}

# Bytes -> a short human string (1.2G, 340M, 900B).
fmt_bytes() {
    local b="${1:-0}"
    if [ "$b" -ge 1073741824 ]; then
        awk -v b="$b" 'BEGIN { printf "%.1fG", b / 1073741824 }'
    elif [ "$b" -ge 1048576 ]; then
        awk -v b="$b" 'BEGIN { printf "%.1fM", b / 1048576 }'
    else
        printf '%dB' "$b"
    fi
}

# Free space of a filesystem, in KiB.
free_kib() {
    df -Pk "$1" 2>/dev/null | awk 'NR == 2 { print $4 }'
}

# Used percentage of the filesystem holding a path.
disk_pct() {
    df -P "$1" 2>/dev/null | awk 'NR == 2 { gsub(/%/, "", $5); print $5 }'
}

# --- liveness ---------------------------------------------------------------

# A runner is busy when one of its worker processes is alive.
#
# The worker binary is versioned: <runner>/bin.<x.y.z>/Runner.Worker. The old
# guard matched <runner>/bin/Runner.Worker, a path the listener does not use,
# so it never matched and every runner looked idle. Matching the runner
# directory followed by any bin.<version> directory covers every layout the
# runner ships, the versioned one included.
runner_busy() {
    local pattern
    pattern="$(escape_re "$(norm_path "$1")")/bin[^/]*/Runner\.Worker"
    pgrep -f "$pattern" >/dev/null 2>&1
}

# The pid of a live process that holds a path - its working directory, or an
# open file inside it - or nothing when no process does.
#
# This is the last-resort safety net: a workspace the runner is working in is
# held open by the step that runs in it, and deleting it breaks the job.
holder_pid() {
    local target pid link fd
    target="$(norm_path "$1")"
    for pid in /proc/[0-9]*; do
        pid="${pid#/proc/}"
        [ "$pid" = "$$" ] && continue
        link="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || link=""
        case "$link" in
            "$target"|"$target"/*) printf '%s\n' "$pid"; return 0 ;;
        esac
        for fd in "/proc/$pid/fd"/*; do
            link="$(readlink "$fd" 2>/dev/null)" || continue
            case "$link" in
                "$target"|"$target"/*) printf '%s\n' "$pid"; return 0 ;;
            esac
        done
    done
    return 1
}

# --- job activity -----------------------------------------------------------

# The newest mtime inside a workspace tree, in epoch seconds.
#
# This is the activity of the JOB, not the age of the directory: the checkout
# and the files the job wrote inside the tree. The top-level directory itself
# (depth 0) is deliberately left out - its mtime says when the tree was
# created, which is exactly the signal that made the cleanup delete a live
# workspace.
tree_activity_ts() {
    local tree="$1" newest
    newest="$(find "$tree" -mindepth 1 -maxdepth 4 -printf '%T@\n' 2>/dev/null | sort -rn | head -1)"
    newest="${newest%%.*}"
    [ -n "$newest" ] || newest=0
    printf '%s\n' "$newest"
}

# The newest worker log of a runner, in epoch seconds (diagnostics only).
runner_last_job_ts() {
    local runner="$1" newest
    newest="$(find "$runner/_diag" -maxdepth 1 -name 'Worker_*.log' -printf '%T@\n' 2>/dev/null | sort -rn | head -1)"
    newest="${newest%%.*}"
    [ -n "$newest" ] || newest=0
    printf '%s\n' "$newest"
}

# --- the lock ---------------------------------------------------------------

# Serialise the two units.
#
# The daily full cleanup and the 15-minute check are two different systemd
# units, so systemd does not serialise them: two passes can walk the same
# workspaces at the same time. The lock file is what keeps them apart. It is
# held for the whole run on fd 9, and a run that does not get it says so and
# deletes nothing.
#
# Returns 0 when this run holds the lock, 1 when another run holds it, and 2
# when the lock file cannot be used at all (not writable - the script then
# runs without it rather than refusing to clean).
acquire_lock() {
    local dir
    dir="$(dirname "$LOCK_FILE")"
    # The open is tried in a subshell first: a redirection that fails on exec
    # would take the whole script down with it.
    if [ ! -d "$dir" ] || ! ( exec 9>>"$LOCK_FILE" ) 2>/dev/null; then
        return 2
    fi
    exec 9>>"$LOCK_FILE"
    if flock -n 9; then
        return 0
    fi
    return 1
}

# --- the decision -----------------------------------------------------------

# Delete one workspace tree, or keep it, with the liveness re-checked right
# before the rm. Sets TREE_REASON to the reason it was kept and TREE_BYTES to
# the size the tree had.
TREE_REASON=""
TREE_BYTES=0
delete_tree() {
    local runner_dir="$1" tree="$2" name base pid size_kb bytes
    name="$(basename "$runner_dir")"
    base="$(basename "$tree")"

    # Re-check 1: the runner may have taken a job since the first check.
    if runner_busy "$runner_dir"; then
        TREE_REASON="job running"
        log "skip $name: job running"
        log "tree $name/$base: skip (the runner took a job since the first check)"
        return 1
    fi

    # Re-check 2: a live process may hold the tree, even though the runner
    # itself looks idle.
    if pid="$(holder_pid "$tree")"; then
        TREE_REASON="in use"
        log "skip $name: in use"
        log "tree $name/$base: skip (held by pid $pid)"
        return 1
    fi

    size_kb="$(du -sk "$tree" 2>/dev/null | cut -f1)"
    [ -n "$size_kb" ] || size_kb=0
    bytes=$((size_kb * 1024))
    TREE_BYTES="$bytes"

    if [ "$DRY_RUN" -eq 1 ]; then
        log "WOULD DELETE $tree ($(fmt_bytes "$bytes"))"
        TREE_REASON=""
        DELETED_TREES=$((DELETED_TREES + 1))
        DELETED_BYTES=$((DELETED_BYTES + bytes))
        return 0
    fi

    if rm -rf -- "$tree"; then
        TREE_REASON=""
        DELETED_TREES=$((DELETED_TREES + 1))
        DELETED_BYTES=$((DELETED_BYTES + bytes))
        log "deleted $name/$base ($(fmt_bytes "$bytes"))"
        return 0
    fi

    TREE_REASON="delete failed"
    log "tree $name/$base: skip (the delete failed)"
    return 1
}

# Walk one runner: every workspace tree under its _work directory.
DELETED_TREES=0
DELETED_BYTES=0
KEPT_TREES=0
HELD_TREES=0

process_runner() {
    local runner_dir="$1" name tree base activity age now="$NOW"
    name="$(basename "$runner_dir")"

    # A busy runner is never touched. This is the check that used to never
    # match, which is why the cleanup deleted live workspaces.
    if runner_busy "$runner_dir"; then
        log "skip $name: job running"
        return 0
    fi

    local deleted=0 kept=0 held=0 bytes=0

    for tree in "$runner_dir/_work"/*; do
        [ -d "$tree" ] || continue
        tree="$(norm_path "$tree")"
        base="$(basename "$tree")"
        # Runner internals (_actions, _tool, _diag, _temp, ...) are never
        # reclaimed.
        case "$base" in _*) continue ;; esac

        if [ "$HARD_MODE" -eq 0 ]; then
            # The age predicate asks about the job, not about the directory.
            activity="$(tree_activity_ts "$tree")"
            age=$(( (now - activity) / 86400 ))
            if [ "$activity" -gt 0 ] && [ "$age" -lt "$KEEP_DAYS" ]; then
                kept=$((kept + 1))
                log "tree $name/$base: skip (job activity ${age}d old, keep ${KEEP_DAYS}d)"
                continue
            fi
        fi

        if delete_tree "$runner_dir" "$tree"; then
            deleted=$((deleted + 1))
            bytes=$((bytes + TREE_BYTES))
        else
            kept=$((kept + 1))
            if [ "$TREE_REASON" = "in use" ]; then
                held=$((held + 1))
            fi
        fi
    done

    local last_job_ts last_job_age
    last_job_ts="$(runner_last_job_ts "$runner_dir")"
    if [ "$last_job_ts" -gt 0 ]; then
        last_job_age="$(( (now - last_job_ts) / 3600 ))h"
    else
        last_job_age="no"
    fi

    if [ "$deleted" -gt 0 ]; then
        log "$name: delete $deleted workspace(s), keep $kept, reclaimed $(fmt_bytes "$bytes"), last job ${last_job_age} ago"
    elif [ "$kept" -gt 0 ]; then
        log "$name: nothing to reclaim (kept $kept workspace(s)), last job ${last_job_age} ago"
    else
        log "$name: nothing to reclaim, last job ${last_job_age} ago"
    fi

    HELD_TREES=$((HELD_TREES + held))
    return 0
}

# --- main -------------------------------------------------------------------

HARD_MODE=0
NOW="$(date +%s)"

main() {
    set -uo pipefail

    while [ $# -gt 0 ]; do
        case "$1" in
            --check)           CHECK_MODE=1; shift ;;
            --dry-run)         DRY_RUN=1; shift ;;
            --runners-root)    RUNNERS_ROOT="${2:-}"; shift 2 ;;
            --keep-days)       KEEP_DAYS="${2:-}"; shift 2 ;;
            --check-threshold) CHECK_THRESHOLD="${2:-}"; shift 2 ;;
            --hard-threshold)  HARD_THRESHOLD="${2:-}"; shift 2 ;;
            --check-busy)      CHECK_BUSY_DIR="${2:-}"; shift 2 ;;
            --help|-h)         usage; exit 0 ;;
            *) echo "ci-retention: unknown argument: $1" >&2; usage >&2; exit 1 ;;
        esac
    done

    if [ -n "$CHECK_BUSY_DIR" ]; then
        if runner_busy "$CHECK_BUSY_DIR"; then
            echo "busy"
        else
            echo "idle"
        fi
        exit 0
    fi

    # The daily pass and the 15-minute check are two different units, so the
    # lock is what keeps them from walking the same workspaces at once. A run
    # that does not get it deletes nothing.
    acquire_lock
    case "$?" in
        0) ;;
        1)
            log "another run in progress, skipping"
            exit 0
            ;;
        *)
            log "lock $LOCK_FILE is not usable - running without it"
            ;;
    esac

    if [ ! -d "$RUNNERS_ROOT" ]; then
        log "no runners root at $RUNNERS_ROOT - nothing to do"
        exit 0
    fi

    local root_pct runners_pct free_root free_runners
    root_pct="$(disk_pct /)"
    runners_pct="$(disk_pct "$RUNNERS_ROOT")"
    free_root="$(fmt_bytes $(( $(free_kib /) * 1024 )))"
    free_runners="$(fmt_bytes $(( $(free_kib "$RUNNERS_ROOT") * 1024 )))"
    log "before root=${root_pct:-?}% runners=${runners_pct:-?}% (free root: $free_root, runners: $free_runners)"

    # In check mode nothing is reclaimed until a disk is really filling up.
    if [ "$CHECK_MODE" -eq 1 ]; then
        local worst=0
        [ "${root_pct:-0}" -ge "$CHECK_THRESHOLD" ] && worst=1
        [ "${runners_pct:-0}" -ge "$CHECK_THRESHOLD" ] && worst=1
        if [ "$worst" -eq 0 ]; then
            log "check: root=${root_pct:-?}% runners=${runners_pct:-?}% below ${CHECK_THRESHOLD}% - nothing to do"
            exit 0
        fi
    fi

    # Above the hard threshold the age filter is dropped, so the space comes
    # back fast. The safety rules do not change: a busy runner is skipped, and
    # a tree a live process holds is never deleted.
    if [ "${runners_pct:-0}" -ge "$HARD_THRESHOLD" ]; then
        HARD_MODE=1
        log "runners disk at ${runners_pct}% - hard pass, the age filter is off (the busy and the in-use rules stay on)"
    fi

    local runner
    for runner in "$RUNNERS_ROOT"/*; do
        [ -d "$runner" ] || continue
        runner="$(norm_path "$runner")"
        [ -d "$runner/_work" ] || continue
        process_runner "$runner"
    done

    root_pct="$(disk_pct /)"
    runners_pct="$(disk_pct "$RUNNERS_ROOT")"
    free_root="$(fmt_bytes $(( $(free_kib /) * 1024 )))"
    free_runners="$(fmt_bytes $(( $(free_kib "$RUNNERS_ROOT") * 1024 )))"
    log "after  root=${root_pct:-?}% runners=${runners_pct:-?}% (free root: $free_root, runners: $free_runners)"
    log "reclaimed $(fmt_bytes "$DELETED_BYTES") in $DELETED_TREES workspace(s)"
    exit 0
}

# Running the script executes main; sourcing it only defines the functions,
# which is how the tests exercise the guard.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
