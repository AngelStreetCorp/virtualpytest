#!/usr/bin/env bash
# mm-sweep.sh — mm-manager's per-wake sweep across every active task session.
#
# Usage: mm-sweep.sh [--json]
#
# Output (default): a plain-text report grouped by state.
# Output (--json):  one JSON object per session with state + last line.
#
# States:
#   waiting-on-owner  : AskUserQuestion dialog visible (mm-manager can act under Jev-down)
#   waiting-on-mm     : empty input, no AskUserQuestion, no recent work — fully idle
#   interrupted       : "What should Claude do instead?" / error toast — needs nudge
#   working           : "Crunching / Loading / esc to interrupt" — leave alone
#   done-parked       : STATUS: done … + idle prompt — owner-direct needed (merge/deploy)
#   model-error       : 50001 / connection ended — retry the pending prompt
#
# mm-manager runs this on each wake event from manager-events.jsonl.

set -u

TASK_PREFIX_REGEX='^(TASK[0-9]+(-[a-z0-9-]+)?|codebox-quickfix-migrated)$'
JSON=0
[ "${1:-}" = "--json" ] && JSON=1

list_sessions() {
  tmux ls 2>/dev/null \
    | awk -F: '{print $1}' \
    | grep -E "$TASK_PREFIX_REGEX" \
    | grep -v '^mm-manager$' \
    | grep -v '^manager$' \
    | grep -v '^ghosty$' \
    | sort
}

classify() {
  local s="$1" cap; cap=$(tmux capture-pane -p -t "$s" -S -200 2>/dev/null)
  local last; last=$(printf '%s\n' "$cap" | tail -25)
  local recent; recent=$(printf '%s\n' "$cap" | tail -120)

  if printf '%s' "$last" | grep -qE 'Ask ─|╭─ Ask'; then
    echo "waiting-on-owner"
  elif printf '%s' "$recent" | grep -qE 'Couldn.t switch models|model connection ended|Error  50001'; then
    echo "model-error"
  elif printf '%s' "$last" | grep -qE 'Interrupted|What should Claude do instead'; then
    echo "interrupted"
  elif printf '%s' "$last" | grep -qE 'Crunching|Loading [0-9]|esc to interrupt|⚡ [0-9]+ tok'; then
    echo "working"
  elif printf '%s' "$last" | grep -qE 'STATUS: done|✻ [A-Z][a-z]+ed for .*done [0-9]'; then
    echo "done-parked"
  elif printf '%s' "$last" | grep -qE '^\s*›\s*$|^\s*❯\s*$'; then
    # empty prompt and no recent work detected — idle
    if printf '%s' "$recent" | grep -qE 'STATUS:|Completed in [0-9]'; then
      echo "done-parked"
    else
      echo "waiting-on-mm"
    fi
  else
    echo "waiting-on-mm"
  fi
}

snippet() {
  local s="$1" cap; cap=$(tmux capture-pane -p -t "$s" -S -8 2>/dev/null)
  printf '%s' "$cap" | tr '\n' ' ' | sed 's/  */ /g' | head -c 180
}

if [ "$JSON" = "1" ]; then
  echo "{"
  first=1
  for s in $(list_sessions); do
    st=$(classify "$s")
    sn=$(snippet "$s" | sed 's/"/\\"/g')
    [ "$first" -eq 1 ] && first=0 || echo ","
    printf '  "%s": {"state":"%s","snippet":"%s"}' "$s" "$st" "$sn"
  done
  echo
  echo "}"
  exit 0
fi

echo "=== mm-manager sweep at $(date -u +%FT%TZ) ==="
for s in $(list_sessions); do
  st=$(classify "$s")
  sn=$(snippet "$s")
  printf '%-40s  %-20s  %s\n' "$s" "$st" "$sn"
done