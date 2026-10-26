#!/usr/bin/env bash
# Run the video builder (Claude Haiku, headless) on the owner's API key, in a video worktree, with a hard limit.
#   scripts/promo/run_builder.sh <worktree> <brief.md> <minutes>
# Writes ~/virtualpytest-promo/runs/<ts>.json (the claude -p result) and prints wall time, cost and the final report.
# Cost: the CLI does not know Haiku 5.5's price (costBasis unknown), so it is recomputed from modelUsage at
# $0.10 in / $0.50 out / $0.01 cache read / $0.20 cache write per million tokens. Log it in VIDEO_PRODUCTION_LOG.md.
set -uo pipefail
WT="$1"; BRIEF="$2"; MIN="${3:-45}"
RUNS="$HOME/virtualpytest-promo/runs"; mkdir -p "$RUNS"; TS=$(date -u +%Y%m%dT%H%M%S); OUT="$RUNS/$TS.json"
MAIN_ENV="$(cd "$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)/.env"   # the main checkout's .env
K=$(grep '^ANTHROPIC_API_KEY=' "$MAIN_ENV" | cut -d= -f2- | tr -d '"'"'"' \r')
[ -n "$K" ] || { echo "ANTHROPIC_API_KEY missing in the main checkout's .env"; exit 1; }
cp "$BRIEF" "$RUNS/$TS.brief.md"; t0=$(date +%s)
( cd "$WT" && ANTHROPIC_API_KEY="$K" timeout $((MIN * 60)) claude -p --model claude-haiku-5-5 --output-format json \
    --allowedTools "Bash Read Edit Write Glob Grep" --permission-mode acceptEdits < "$BRIEF" > "$OUT" 2> "$RUNS/$TS.err" )
echo "exit=$? wall=$(( ($(date +%s) - t0) / 60 )) min  result=$OUT"
python3 "$(dirname "$0")/../ai_report_claude_cli.py" "$OUT" --script promo/run_builder.sh   # ai_calls row (BUG-0721)
python3 - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); u = d["modelUsage"]["claude-haiku-5-5"]
c = u["inputTokens"]*0.10e-6 + u["outputTokens"]*0.50e-6 + u["cacheReadInputTokens"]*0.01e-6 + u["cacheCreationInputTokens"]*0.20e-6
print(f"cost ~${c:.3f} at Haiku prices (CLI says {d.get('total_cost_usd')})"); print(d.get("result", ""))
PY
