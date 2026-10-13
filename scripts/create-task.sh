#!/usr/bin/env bash
# create-task.sh — mm-manager's structured task-spawner.
#
# Goal: every new mm-spawned task session has:
#   - a unique TASK-NN (gap-checked across worktrees, tmux sessions, ghosty briefs)
#   - a worktree on the right repo with the right branch
#   - a TASK-NN-{slug}.md with the structured fields (Goals / Repo / Tests / Validate / Output / Rules / Reference / Manager)
#   - a tmux session with the right cwd
#   - an initial prompt that embeds the manager info + the reference index, not re-derived each time
#
# Usage:
#   create-task.sh --goal "..." --repo <abs-path> --slug <slug> [--task-num <N>] [--model <M>] [--pre-approve "..."] [--lease-host <host>] [--provider NAME]
#
# Required:
#   --goal        one-line goal (the "what's done when")
#   --repo        absolute path to the git repo (must be a git repo, must NOT be the parent worktree's dir)
#   --slug        short kebab-case (e.g. stream-latency, vpt-mobility)
#
# Optional:
#   --task-num    explicit TASK-NN (default: auto-grep the next free number)
#   --model       minimax/M3 (default) or minimax/M3.1-Flash-Preview
#   --pre-approve optional inline pre-approvals the owner wants the session to act on under Jev-down
#   --lease-host  if the task starts with a lease, the host name to claim
#   --provider    AI provider of the spawned task (default: minimax). Written into the lease claim command so
#                 `vpt-lease list/check` shows who is on the platform. Pass `claude` / `codex` etc. for other agents.
#   --dry-run     do everything except the actual spawn (validates + prints the plan)
#
# Reference index is auto-built from:
#   - MEMORY.md                       (CLAUDE.md-style hard rules from the owner's brief)
#   - ~/.local/state/ghosty/mm-manager-actions.jsonl (recent mm-manager actions, last 20)
#   - the repo's docs/agent/INDEX.md  (if present)
#   - the repo's docs/tasks/TASK-NN-*.md (siblings, last 5)
#
# Owner-only carve-outs are pulled from MEMORY.md. Edit MEMORY.md, never re-list here.

set -euo pipefail

# ---- args ----
GOAL=""
REPO=""
SLUG=""
TASK_NUM=""
MODEL="minimax/M3"
PRE_APPROVE=""
LEASE_HOST=""
PROVIDER="minimax"
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --goal) GOAL="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --slug) SLUG="$2"; shift 2 ;;
    --task-num) TASK_NUM="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --pre-approve) PRE_APPROVE="$2"; shift 2 ;;
    --lease-host) LEASE_HOST="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --dry-run) DRY_RUN="1"; shift ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) echo "unexpected positional arg: $1" >&2; exit 2 ;;
  esac
done

# ---- required arg check ----
if [[ -z "$GOAL" || -z "$REPO" || -z "$SLUG" ]]; then
  echo "usage: $0 --goal <text> --repo <abs-path> --slug <slug> [--task-num <N>] [--model <M>] [--pre-approve <text>] [--lease-host <host>] [--provider <minimax|claude|codex>] [--dry-run]" >&2
  exit 2
fi

# ---- validate repo ----
REPO="$(realpath -m "$REPO")"
if [[ ! -d "$REPO/.git" ]]; then
  echo "error: --repo $REPO is not a git repo" >&2
  exit 1
fi
REPO_NAME="$(basename "$REPO")"
echo "✓ repo $REPO"

# ---- auto-detect next TASK-NN if not given ----
if [[ -z "$TASK_NUM" ]]; then
  TASK_NUM="$( (
    # collect all TASK-NN references: docs/tasks/*.md across all worktrees, plus tmux sessions, plus ghosty briefs
    ls /home/jndoye/*/docs/tasks/ 2>/dev/null \
      | grep -hoE 'TASK-[0-9]+(-[a-z0-9-]+)?\.md' \
      | grep -oE 'TASK-[0-9]+' | grep -oE '[0-9]+'
    tmux ls 2>/dev/null \
      | awk '{print $1}' | grep -oE 'TASK[0-9]+' | grep -oE '[0-9]+'
    ls /home/jndoye/.local/state/ghosty/briefs/ 2>/dev/null \
      | grep -hoE 'TASK[0-9]+' | grep -oE '[0-9]+'
    # the repo's own docs/tasks/*.md
    find "$REPO/docs/tasks" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null \
      | grep -hoE 'TASK-[0-9]+' | grep -oE '[0-9]+'
  ) | sort -n -u | tail -1 )"
  TASK_NUM="$(( ${TASK_NUM:-0} + 1 ))"
fi
TASK_NUM="$(printf '%02d' "$TASK_NUM" 2>/dev/null || echo "$TASK_NUM")"
TASK_DOC="TASK-${TASK_NUM}-${SLUG}.md"

# ---- gap-check: TASK-NN must not collide ----
COLLIDES=""
# docs/tasks/*.md in any worktree
for f in /home/jndoye/*/docs/tasks/"TASK-${TASK_NUM}-"*.md; do
  [[ -e "$f" ]] || continue
  COLLIDES="${COLLIDES:+${COLLIDES} }${f}"
done
# tmux sessions (capture in a tmpfile to avoid subshell issues)
tmux ls 2>/dev/null | awk -v n="TASK${TASK_NUM}" '$1 ~ n {print "tmux:" $1}' > /tmp/_collides_tmux.txt || true
while IFS= read -r s; do COLLIDES="${COLLIDES:+${COLLIDES} }${s}"; done < /tmp/_collides_tmux.txt
rm -f /tmp/_collides_tmux.txt
# ghosty briefs
ls /home/jndoye/.local/state/ghosty/briefs/ 2>/dev/null | grep -i "TASK${TASK_NUM}" > /tmp/_collides_briefs.txt || true
while IFS= read -r b; do COLLIDES="${COLLIDES:+${COLLIDES} }brief:${b}"; done < /tmp/_collides_briefs.txt
rm -f /tmp/_collides_briefs.txt
# the repo's own docs/tasks/
test -f "$REPO/docs/tasks/$TASK_DOC" && COLLIDES="${COLLIDES:+${COLLIDES} }$REPO/docs/tasks/$TASK_DOC"
if [[ -n "$COLLIDES" ]]; then
  echo "error: TASK-$TASK_NUM already used: $COLLIDES" >&2
  echo "  pick --task-num $((10#$TASK_NUM + 1)) or higher" >&2
  exit 1
fi
echo "✓ TASK-$TASK_NUM unused"

# ---- validate slug ----
if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
  echo "error: --slug must be kebab-case (e.g. stream-latency, vpt-mobility)" >&2
  exit 1
fi
echo "✓ slug $SLUG"

# ---- validate model ----
if [[ ! "$MODEL" =~ ^(minimax/M3|minimax/M3\.1-Flash-Preview)$ ]]; then
  echo "error: --model must be minimax/M3 or minimax/M3.1-Flash-Preview" >&2
  exit 1
fi
echo "✓ model $MODEL"

# ---- pre-fetch manager info from MEMORY.md ----
MM_HOME="/home/jndoye/.claude/projects/-home-jndoye-vpt-manager"
MEMORY="$MM_HOME/MEMORY.md"
if [[ ! -f "$MEMORY" ]]; then
  echo "warn: $MEMORY not found; manager info will be empty" >&2
  MEMORY=""
fi

# ---- owner-only carve-outs: hardcoded list (MEMORY.md is mm-manager's own reference, not for the agent) ----
CARVE_OUTS="$(cat << 'EOF'
- push to any origin branch / merge to main
- open PR on GitHub
- change .env, secrets, customer data, money, lease registry, DB schema outside the task surface
- force-take a device another user is holding
- enable a feature flag in production .env
- install new system packages without justification in the PR
- restart services on production hosts (debug hosts only, and only when the owner names the host)
EOF
)"

# ---- reference index auto-build ----
REF_INDEX=""
# 1) AGENTS.md / CLAUDE.md
for f in AGENTS.md CLAUDE.md docs/agent/README.md docs/agent/INDEX.md; do
  if [[ -f "$REPO/$f" ]]; then
    REF_INDEX="${REF_INDEX}- \`${f}\` (worktree rule, deploy rule, STATUS line)\n"
  fi
done
# 2) the repo's docs/agent/{infra,validation,platform,navigation,devices}/*
for d in infra validation platform navigation; do
  for f in "$REPO/docs/agent/$d"/*.md; do
    [[ -f "$f" ]] || continue
    rel="${f#$REPO/}"
    REF_INDEX="${REF_INDEX}- \`${rel}\`\n"
  done | head -5
done
# 4) sibling TASK docs (last 5 by number)
SIBLINGS="$(find "$REPO/docs/tasks" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null | sort | tail -5)"
for f in $SIBLINGS; do
  rel="${f#$REPO/}"
  REF_INDEX="${REF_INDEX}- \`${rel}\`\n"
done
# 5) infra deploy + scripts docs
for f in scripts/CAPTURE_CONFIG.md scripts/run_ffmpeg.md infra/DEPLOY.md docs/agent/infra/DEPLOY.md; do
  [[ -f "$REPO/$f" ]] && REF_INDEX="${REF_INDEX}- \`${f}\`\n"
done

# ---- mm-manager recent actions (last 20) ----
MM_LOG="/home/jndoye/.local/state/ghosty/mm-manager-actions.jsonl"
RECENT_ACTIONS=""
if [[ -s "$MM_LOG" ]]; then
  RECENT_ACTIONS="$(tail -20 "$MM_LOG" | python3 -c "import sys,json; [print(f\"- {a.get('at','?')[:19]} {a.get('kind','?')} {a.get('session','?')}: {(a.get('detail') or '')[:100]}\") for a in (json.loads(l) for l in sys.stdin if l.strip()) if a.get('kind') != 'lease-release']" 2>/dev/null | head -20)"
fi
[[ -z "$RECENT_ACTIONS" ]] && RECENT_ACTIONS="- (no recent mm-manager actions)"

# ---- build the plan ----
WORKTREE="/home/jndoye/${REPO_NAME}-task${TASK_NUM}-${SLUG}"
BRANCH="task${TASK_NUM}-${SLUG}"
SESSION="TASK${TASK_NUM}-${SLUG}"
MD_PATH="$WORKTREE/docs/tasks/$TASK_DOC"

cat <<EOF
================================================================
PLAN
================================================================
goal        : $GOAL
repo        : $REPO  (basename $REPO_NAME)
TASK-NN     : $TASK_NUM  (md: $TASK_DOC)
slug        : $SLUG
worktree    : $WORKTREE  (creates if missing)
branch      : $BRANCH
session     : $SESSION  (model $MODEL)
MD path     : $MD_PATH
pre-approve : ${PRE_APPROVE:-<none>}
lease host  : ${LEASE_HOST:-<none>}
================================================================
EOF

if [[ "$DRY_RUN" == "1" ]]; then
  echo "(dry-run; no actions taken)"
  exit 0
fi

# ---- 1. worktree ----
if [[ ! -d "$WORKTREE" ]]; then
  ( cd "$REPO" && git worktree add "$WORKTREE" -b "$BRANCH" main ) | tail -3
else
  echo "✓ worktree exists: $WORKTREE"
fi

# ---- 2. TASK MD ----
PRE_APPROVE_BLOCK=""
[[ -n "$PRE_APPROVE" ]] && PRE_APPROVE_BLOCK="
## Pre-approvals (owner-authorized under Jev-down at spawn time)

The owner pre-approved the following items the moment this session spawned:

$PRE_APPROVE

Act on these. Do not re-ask. Anything outside this list stays owner-direct.
"

LEASE_BLOCK=""
[[ -n "$LEASE_HOST" ]] && LEASE_BLOCK="
## Lease (pre-claimed at spawn)

\`vpt-lease claim --host $LEASE_HOST --agent codebox:$SESSION --provider $PROVIDER --reason "task$([0#$TASK_NUM]) spawn"\`

Hold the lease through the task; release on session exit. If another agent has the lease, hold the script until it clears, do not retry.
"

cat > "$MD_PATH" <<EOF
# TASK-$TASK_NUM — $SLUG

## Goal

$GOAL

## Repo

\`$REPO\` (basename \`$REPO_NAME\`) on branch \`$BRANCH\` off \`main\`. Worktree: \`$WORKTREE\`.

## Done when

(Filled in by the session as it goes. Initial state: TODO.)

$PRE_APPROVE_BLOCK$LEASE_BLOCK

## Hard rules

- Read first, code second. Surface inspect findings + plan BEFORE any code.
- Branch for this task: \`$BRANCH\` off \`main\`. Local commits only. No push.
- Owner-only carve-outs (you do NOT do these):

\`\`\`
$CARVE_OUTS
\`\`\`

## Jev-down / ship-fast actions you MAY take (everything else stays owner-direct)

- Edit files inside the worktree on this branch.
- Stage explicit paths only (\`git add <path>\`), never \`git add -A\`.
- Run tests locally; capture before/after numbers; write a per-pick status sheet.
- Run the deploy to **the host the owner names** (NOT all hosts). Stay read-only on the others.
- Claim + release the lease named above (if any).
- Write/update the State table at the bottom of this MD.

## Reference index (read in this order)

$(printf "%b" "$REF_INDEX")

## Manager info (mm-manager context for this spawn)

Recent activity (last 20 mm-manager actions, excluding lease-release noise):

\`\`\`
$RECENT_ACTIONS
\`\`\`

The full mm-manager action log: \`$MM_LOG\`. Add a row for every action you take; format per the log.

## State

| Step | Status | Notes |
|---|---|---|
| 1. Inspect + plan | TODO | — |
| 2. (filled in by the session) | TODO | — |
| 3. (filled in by the session) | TODO | — |
| 4. (filled in by the session) | TODO | — |
| 5. (filled in by the session) | TODO | — |
| STATUS line | TODO | end with the required STATUS line |
EOF

echo "✓ wrote $MD_PATH"

# ---- 3. tmux session ----
if ! tmux ls 2>/dev/null | grep -q "^$SESSION:"; then
  tmux new-session -d -s "$SESSION" -c "$WORKTREE"
  sleep 1
  tmux send-keys -t "$SESSION" '/home/jndoye/.local/node-v24.21.0-linux-x64/bin/mcode' Enter
  sleep 4
  echo "✓ spawned $SESSION"
else
  echo "✓ $SESSION already exists; reusing"
fi

# ---- 4. initial prompt ----
cat > /tmp/mm-msg.txt <<EOF
TASK-$TASK_NUM starts. Open the MD at $MD_PATH and read it fully. The MD carries the owner's goal, the hard rules, the reference index, and the recent mm-manager activity. Your branch is \`$BRANCH\` off \`main\`. Local commits only. No push.

$([ -n "$LEASE_HOST" ] && echo "Before any remote command (other than ssh BatchMode echo ok): run \`vpt-lease claim --host \${LEASE_HOST} --agent codebox:$SESSION --provider $PROVIDER --reason 'task$TASK_NUM spawn'\`. Hold the lease through the task; release on session exit. If another agent has the lease, hold the script until it clears, do not retry.")

Inspect first, code second. Concretely:
1. Walk the reference index in the MD top-down. Note which file answers which question.
2. Record current commit SHA, model + engine version, any divergence from the owner's plan.
3. Surface the inspect findings + your plan BEFORE any code. The owner has authorized Jev-down for safe design decisions; everything else stays owner-direct.

When you finish each step, update the State table in the MD. When the whole task is done, end with the STATUS line per AGENTS.md / CLAUDE.md.

Owner-only carve-outs (re-listed so you cannot miss them): push to origin, open PR, change .env, secrets, customer data, money, lease, DB schema outside scope, restart services on production hosts, force-take a device another user holds.

Pre-approvals the owner authorized at spawn time:
$([ -n "$PRE_APPROVE" ] && echo "$PRE_APPROVE" || echo "(none — act only on safe Jev-down design decisions; everything else stays owner-direct)")

Stop and ask if anything in the spec contradicts what you find. Do not guess, do not invent APIs.
EOF
tmux load-buffer /tmp/mm-msg.txt
tmux paste-buffer -t "$SESSION"
sleep 2
tmux send-keys -t "$SESSION" Enter
sleep 2
echo "✓ sent initial prompt"

cat <<EOF

================================================================
DONE
================================================================
worktree   : $WORKTREE
branch     : $BRANCH
md         : $MD_PATH
session    : $SESSION (model $MODEL)
Next       : the session will read the MD, send inspect findings + plan, then start per the State table.
================================================================
EOF