#!/usr/bin/env bash
# Put a deployed lane clone back on the current main before the lane runs.
#
# The lanes of codebox (the game dispatcher, the Pokemon dispatcher, the stall watcher) run from
# their own clone: the shared checkout of ~/virtualpytest is the working copy of every Claude Code
# session on this host, and its branch is switched under them, so a lane that ran from it would
# run whatever branch the last session left behind.
#
# A clone that is never updated has the other fault: it runs the code it was deployed with, for
# ever. The stall watcher kept the code that read only the *latest* lock of the canonical store
# while main already read every lock, so the second Pokemon save stayed locked for two days and
# nobody was asked to fix it (BUG-0920). The same story with the game dispatcher, whose clone was
# several dozen commits behind main.
#
# So the clone is synced before every tick. A fetch that fails (no network, no key, a locked
# repository) must not stop the lane: it keeps the code it has and says so.
#
# Usage: sync_lane_clone.sh <clone> [ref]        (ref defaults to origin/main)
set -uo pipefail

CLONE="${1:-}"
REF="${2:-origin/main}"

if [[ -z "${CLONE}" || ! -d "${CLONE}/.git" ]]; then
  echo "sync_lane_clone: no clone at '${CLONE}'" >&2
  exit 0
fi

export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=20}"

if ! git -C "${CLONE}" fetch --quiet --prune origin 2>/dev/null; then
  echo "sync_lane_clone: the fetch of '${CLONE}' failed; the lane keeps the code it has" >&2
  exit 0
fi

# The clone is a deployed copy: it holds no work of its own, so it is put on main whatever it was
# on (a merge commit that cannot be fast-forwarded is what kept the stall watcher stale).
git -C "${CLONE}" checkout --quiet --force -B main "${REF}" 2>/dev/null \
  || git -C "${CLONE}" reset --hard --quiet "${REF}" 2>/dev/null || true
git -C "${CLONE}" clean -qfdf 2>/dev/null || true

head=$(git -C "${CLONE}" rev-parse --short HEAD 2>/dev/null || echo "?")
echo "sync_lane_clone: ${CLONE} is at ${head} (${REF})"
exit 0
