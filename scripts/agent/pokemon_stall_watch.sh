#!/usr/bin/env bash
# Start a review-and-fix agent within a minute of a Pokemon long-play stall (TASK-33).
#
# The stalled run fails with "STALLED: ... Report: <path>" and locks the save, so the dispatcher
# (scripts/agent/pokemon_dispatch.py) starts no run until the cause is fixed and the lock cleared. Run from a systemd
# timer every minute on codebox: when the latest STALLED game_pokemon run (on any host) names a report not handled yet,
# take the report from the canonical store (the dispatcher pulls it after the run) or, failing that, from the host that
# ran it, and start one agent session (cbsession) on `scripts/pokemon_stall_review.py --fix`, which diagnoses, fixes,
# deploys and clears the lock.
# Provider and model are env-configurable: POKEMON_STALL_PROVIDER (default minimax) and POKEMON_STALL_MODEL
# (default MiniMax-M3.1-Flash for minimax, opus for claude), passed to cbsession as -p/-m.
# One fixer at a time: a running pokestall-* tmux session holds the next stall back until it ends.
set -euo pipefail

PROVIDER="${POKEMON_STALL_PROVIDER:-minimax}"
if [[ -n "${POKEMON_STALL_MODEL:-}" ]]; then
  MODEL="${POKEMON_STALL_MODEL}"
elif [[ "${PROVIDER}" == "minimax" ]]; then
  MODEL="MiniMax-M3.1-Flash"
else
  MODEL="opus"
fi
FIXER_MAX_MIN=75    # a fixer still open after this is treated as done (its brief aims at 30 min)
# The tree the fixing session starts in. NOT the shared checkout: ~/virtualpytest is the working copy of
# every Claude Code session on this host, its branch is switched under them, and its HEAD is whatever the
# last session left behind (on 2026-10-26 it was a day old). A fixer that started there read a runner
# that main had already fixed, so it reproduced the recursion of BUG-0919 instead of the stall it was
# sent to fix (BUG-0923). The fixer gets a clone of its own, put on the current main right before it
# starts.
FIX_REPO="${HOME}/.local/share/vpt-stall-fix"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # the watcher's own clone (~/.local/share/vpt-stall-watch, not a worktree)
# The clone is brought back to main by the unit that runs this script
# (scripts/agent/systemd/pokemon-stall-watch.service -> sync_lane_clone.sh). The `git pull` that used to be
# here could not fast-forward (the clone sat on a merge commit) and its failure was swallowed, so the
# watcher kept running the code it was deployed with for ever: the one that read only the *latest* lock
# of the canonical store, while main already read every lock (BUG-0920).
STALLS_DIR="${HOME}/vpt-private/pokemon/stalls"
CANON="${POKEMON_CANON:-${HOME}/vpt-private/pokemon/canonical}"
STATE_DIR="${HOME}/.cache/pokemon-stall-watch"
HANDLED="${STATE_DIR}/handled"
mkdir -p "${STATE_DIR}" "${STALLS_DIR}" "${HOME}/handovers"
touch "${HANDLED}"

log() { echo "$(date -u +%FT%TZ) $*"; }

# Every command name running in a tmux pane's process tree. The agent is a child of the pane's shell, so
# pane_current_command alone reads "bash" for a MiniMax session and would make the watcher kill a live fixer.
pane_cmds() {
  local pid=$1 out="" kids="" p
  if command -v pstree >/dev/null 2>&1; then
    pstree -p "${pid}" 2>/dev/null || true
    return 0
  fi
  while [[ -n "${pid}" ]]; do            # fallback: walk --ppid down the tree
    kids=""
    for p in ${pid}; do
      out+="${p} "
      kids+=" $(ps -o pid= --ppid "${p}" 2>/dev/null)"
    done
    pid="${kids# }"
  done
  ps -o comm= -p ${out} 2>/dev/null || true
}

# The fixer's agent (claude, minimax-code, mcode, codex) is somewhere in that tree
agent_running() {
  grep -qE '(^|[^[:alnum:]/])(claude|minimax-code|mcode|codex)([^[:alnum:]-]|$)' <<<"$(pane_cmds "${1}")"
}

# The dispatcher that owns the lanes. The watcher clears a lock through it, so the clear lands with the
# lane that plays that save (BUG-0932). The path can be pointed elsewhere for a test.
DISPATCH="${POKEMON_DISPATCH:-${HERE}/scripts/agent/pokemon_dispatch.py}"

# The report a fixer worked on: the handled list holds one "<report>|<epoch>" line per fixer.
handled_report() {
  grep -F "${1}.json" "${HANDLED}" 2>/dev/null | tail -1 | cut -d'|' -f1 || true
}

# The save a report is about ("stall_second_20261026-084552.json" -> "second").
report_save() {
  local base
  base=$(basename "${1}" .json)
  if [[ "${base}" =~ ^stall_(.+)_[0-9]{8}-[0-9]{6}$ ]]; then echo "${BASH_REMATCH[1]}"; fi
}

# The report the lock of one save names (nothing when that save is not locked).
lock_report_of() {
  local lf="${CANON}/stall_$1.lock.json"
  [[ -f "${lf}" ]] || return 0
  grep -oE '"report"[[:space:]]*:[[:space:]]*"[^"]+"' "${lf}" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || true
}

# Clear the lock of the save a finished fixer worked on, so the lane plays on.
#
# This is the chain's missing last link (2026-10-26). The fixer is asked to clear the lock itself (step 6
# of its brief) and an agent that ends without doing it leaves the save locked for ever: the dispatcher
# starts no run and nobody is asked again - the second save was dark from 08:45 to 12:12, the first save
# from 11:17 to 12:11. The watcher does the clear itself when the fixer it started is over.
#
# Only when the lock still names that very report: a newer stall holds the lock then, and that one is
# not ours to clear (the watcher arms a fixer for it on its own).
# Returns 1 when the clear itself failed: the fixer session is then kept, so the next minute tries again.
clear_finished_save() {
  local sname="${1}" report save lock_report
  report=$(handled_report "${sname#pokestall-}")
  [[ -n "${report}" ]] || return 0
  save=$(report_save "${report}")
  [[ -n "${save}" ]] || return 0
  lock_report=$(lock_report_of "${save}")
  [[ -n "${lock_report}" ]] || return 0          # the save is not locked any more
  if [[ "${lock_report}" != "${report}" ]]; then
    log "the lock of ${save} names another stall (${lock_report}); it is not cleared"
    return 0
  fi
  if [[ " ${live_reports} " == *" ${lock_report} "* ]]; then
    log "the lock of ${save} is held by a fixer that is still working; it is not cleared"
    return 0
  fi
  log "the fixer of ${report} is over: clearing the lock of ${save} so the lane plays on"
  if POKEMON_CANON="${CANON}" timeout 90 python3 "${DISPATCH}" clear-stall --save "${save}" >/dev/null 2>&1; then
    log "the ${save} lane was asked to clear its stall lock"
    return 0
  fi
  log "the clear of ${save} failed: the fixer session stays open so the next minute tries again"
  return 1
}

# The stall to fix. The canonical lock is the authoritative signal ("this save is stuck") and it names
# the report that locked it. The DB query only looked 3 hours back, so a lock that outlived that window
# (the fixer died, the fix never shipped, the host was down) sat there for ever: the dispatcher started no
# run and nobody was ever asked to fix it (the save stayed locked for two and a half days). The lock is
# read first and has no age limit, so a save that is still locked always gets a fixer.
# Every lock of the canonical store: one per save ("latest" and the parallel saves of TASK-164). The newest one
# is the stall to fix.
lock_report=""
lock_file=""
lock_save=""
for f in "${CANON}"/stall_*.lock.json; do
  [[ -f "${f}" ]] || continue
  if [[ -z "${lock_file}" || "${f}" -nt "${lock_file}" ]]; then lock_file="${f}"; fi
done
if [[ -n "${lock_file}" ]]; then
  lock_report=$(grep -oE '"report"[[:space:]]*:[[:space:]]*"[^"]+"' "${lock_file}" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || true)
  # The save the lock belongs to ("stall_second.lock.json" -> "second"): the clear command in the brief has
  # to name it, or it clears the other lane's save (the second lane waited 5 h 30 for its lock, 2026-10-26).
  lock_save=$(basename "${lock_file}" .lock.json | sed -E 's/^stall_//')
fi

# Host and error of the latest STALLED game_pokemon run (the stall itself, or a run the lock refused), last 3 hours only
row=$(ssh database "sudo -n docker exec -e PGPASSWORD=postgres supabase_db_supabase psql -U supabase_admin -d postgres -At -c \"select r.host_name, r.error_msg from script_results r where r.script_name like '%game_pokemon%' and r.error_msg like 'STALLED:%' and r.started_at > now() - interval '3 hours' order by r.started_at desc limit 1;\"" 2>/dev/null || true)
HOST=${row%%|*}
msg=${row#*|}
db_report=$(grep -oE 'Report: [^ ]+\.json' <<<"${msg}" | head -1 | cut -d' ' -f2 || true)

if [[ -n "${lock_report}" ]]; then
  report="${lock_report}"
  # The lock names no host: take it from the run row of that very report (any age).
  if [[ "${db_report}" != "${report}" ]]; then
    base=$(basename "${report}")
    hrow=$(ssh database "sudo -n docker exec -e PGPASSWORD=postgres supabase_db_supabase psql -U supabase_admin -d postgres -At -c \"select r.host_name from script_results r where r.script_name like '%game_pokemon%' and r.error_msg like '%${base}%' order by r.started_at desc limit 1;\"" 2>/dev/null || true)
    [[ -n "${hrow}" ]] && HOST="${hrow}"
  fi
else
  report="${db_report}"
fi
[[ -z "${report}" ]] && exit 0

# One fixer at a time. A pokestall session whose agent has exited from its pane tree, or older than FIXER_MAX_MIN,
# is done: close it. Liveness comes from the pane's process tree, never from pane_current_command alone.
now=$(date +%s)
busy="" stale="" seen="" live_reports=""
while IFS='|' read -r sname created pid; do
  [[ "${sname}" == pokestall-* ]] || continue
  case " ${seen} " in *" ${sname} "*) continue ;; esac    # judge a session once, whatever its pane count
  seen="${seen} ${sname}"
  if ! agent_running "${pid}" || (( now - created > FIXER_MAX_MIN * 60 )); then
    stale="${stale} ${sname}"
  else
    busy="${busy} ${sname}"
    rep=$(handled_report "${sname#pokestall-}")
    if [[ -n "${rep}" ]]; then live_reports="${live_reports} ${rep}"; fi
  fi
done < <(tmux list-panes -a -F '#{session_name}|#{session_created}|#{pane_pid}' 2>/dev/null || true)
for sname in ${stale}; do
  # The clear comes first: a fixer that is over and did not clear its save leaves that save dark for
  # ever. When the clear fails the session is kept, so the next minute tries again.
  if clear_finished_save "${sname}"; then
    tmux kill-session -t "${sname}" 2>/dev/null && log "closed finished fixer ${sname}"
  else
    log "fixer ${sname} stays open until the lock of its save is cleared"
  fi
done
if [[ -n "${busy}" ]]; then
  log "stall ${report} waits: ${busy# } is still working"
  exit 0
fi

# A report is "handled" when a fixer worked on it. When the save is still locked the fixer did not
# manage to fix it, so the stall is armed again once the last attempt is RETRY_MIN old: a stuck save
# keeps getting a fixer instead of waiting for ever for a human. (An entry without a timestamp is an
# attempt from before the timestamps, and is re-armed at once.)
retry_min=360
last=0
line=$(grep -F "${report}" "${HANDLED}" | tail -1 || true)
if [[ "${line}" == *"|"* ]]; then
  last=$(cut -d'|' -f2 <<<"${line}")
  [[ -z "${last}" ]] && last=0
fi
now=$(date +%s)
if (( last > 0 && now - last <= retry_min * 60 )); then  log "stall ${report} was handled ${retry_min} min ago; waiting for the retry window"
  exit 0
fi

local_report="${STALLS_DIR}/$(basename "${report}")"
if [[ -f "${CANON}/$(basename "${report}")" ]]; then
  cp "${CANON}/$(basename "${report}")" "${local_report}.tmp"
elif ! ssh -o BatchMode=yes -o ConnectTimeout=10 "${HOST}" "sudo -n cat '${report}'" > "${local_report}.tmp" 2>/dev/null; then
  rm -f "${local_report}.tmp"
  log "cannot read ${report} in ${CANON} or on ${HOST}; retrying next minute"
  exit 0
fi
mv "${local_report}.tmp" "${local_report}"
chmod 600 "${local_report}"

run_id=$(basename "${report}" .json | grep -oE '[0-9]{8}-[0-9]{6}' || date -u +%Y%m%d-%H%M%S)
name="pokestall-${run_id}"
brief="${HOME}/handovers/${name}.md"

# The fixer's tree, on the current main. A dirty tree means the previous fixer is still at work in it:
# it is then left alone (a reset would throw its work away). A fetch that fails never stops the fixer:
# it keeps the code it has and says so.
if [[ ! -d "${FIX_REPO}/.git" ]]; then
  # A clone of a local path takes that path as its origin, so the origin URL is set right after: the
  # sync must fetch the real remote, not the shared checkout (whose main is the one that is stale).
  git clone --quiet "${HERE}" "${FIX_REPO}" 2>/dev/null || true
  url=$(git -C "${HERE}" remote get-url origin 2>/dev/null || true)
  [[ -n "${url}" ]] && git -C "${FIX_REPO}" remote set-url origin "${url}" 2>/dev/null || true
elif [[ -z "$(git -C "${FIX_REPO}" status --porcelain 2>/dev/null)" ]]; then
  SYNC="${HERE}/scripts/agent/sync_lane_clone.sh"
  [[ -x "${SYNC}" ]] || SYNC="${HOME}/.local/bin/sync_lane_clone.sh"
  "${SYNC}" "${FIX_REPO}" >/dev/null 2>&1 || true
fi

python3 "${HERE}/scripts/pokemon_stall_review.py" "${local_report}" --fix --host "${HOST}" --repo "${FIX_REPO}" --save "${lock_save}" --print > "${brief}"
"${HOME}/.local/bin/cbsession" -n "${name}" -d "${FIX_REPO}" -p "${PROVIDER}" -m "${MODEL}" -f "${brief}"
echo "${report}|$(date +%s)" >> "${HANDLED}"
log "started ${name} (${PROVIDER}/${MODEL}) on ${report}"
