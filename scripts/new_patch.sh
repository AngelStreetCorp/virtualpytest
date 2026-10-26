#!/usr/bin/env bash
# Create the next client patch from patch/_template.sh (backup + --check + --rollback built in).
# Usage: scripts/new_patch.sh <component> <slug> "<BUG/TASK ref>"   e.g. host irtrans-fix "BUG-0205"
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 2 ] || { echo "usage: $0 <component> <slug> [ref]" >&2; exit 2; }
comp=$1; slug=$2; ref=${3:-TASK-151}
last=$(ls patch/ | sed -n 's/^patch_[a-z]*_\([0-9]*\)_.*/\1/p' | sort -n | tail -1)
n=$(( ${last:-0} + 1 ))
file="patch/patch_${comp}_${n}_${slug}.sh"
sed -e "s/@N@/$n/g" -e "s/@SLUG@/$slug/g" -e "s/@REF@/$ref/g" -e "s#@FILE@#$(basename "$file")#g" patch/_template.sh > "$file"
chmod +x "$file"
echo "created $file (patch-$n). Fill the TODO functions, then: bash scripts/patch_lint.sh"
