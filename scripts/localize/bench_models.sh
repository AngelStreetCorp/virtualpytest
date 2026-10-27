#!/usr/bin/env bash
# Mac-runnable Localize model benchmark.
#
# Loads .env (the local checkout root, or /opt/virtualpytest/.env) then drives
# scripts/localize/bench_models.py.
#
# Examples:
#   scripts/localize/bench_models.sh pick --ui stb-<operator> --top 20
#   scripts/localize/bench_models.sh run --ui stb-<operator> --top 20 \
#       --models baseline,haiku,m3,m2.7,jev-1.14 --out /tmp/localize-models.jsonl
#
# Defaults to all five models. Add '--models baseline,haiku' to subset.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load .env from the local checkout (so the script works from this Mac without
# ssh'ing to vpt-pi1). /opt/virtualpytest/.env is the second-choice fallback.
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a; source "$REPO_ROOT/.env"; set +a
elif [[ -f /opt/virtualpytest/.env ]]; then
    set -a; source /opt/virtualpytest/.env; set +a
fi

# Translate the script's --lan flag into the env var the baseline runner reads.
if [[ "${*}" == *"--lan"* ]]; then
    export VPT_LOCALIZE_LAN=1
fi

exec python3 "$REPO_ROOT/scripts/localize/bench_models.py" "$@"