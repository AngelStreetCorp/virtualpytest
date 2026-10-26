#!/usr/bin/env bash
# Every patch/*.sh must offer --check and --rollback and take a .patch-<N>.bak backup (docs/agent/release/PATCHES.md).
set -u
cd "$(dirname "$0")/.."
rc=0
for f in patch/patch_*.sh patch/_template.sh; do
  [ -e "$f" ] || continue
  grep -q -- '--check' "$f"    || { echo "FAIL $f: no --check"; rc=1; }
  grep -q -- '--rollback' "$f" || { echo "FAIL $f: no --rollback"; rc=1; }
  grep -Eq '\.(patch-[0-9]+|\$PATCH(_ID)?)\.bak|\$BAK|patch-[0-9]+\.bak' "$f" || { echo "FAIL $f: no .patch-<N>.bak backup"; rc=1; }
done
[ $rc = 0 ] && echo "patch_lint: ok"
exit $rc
