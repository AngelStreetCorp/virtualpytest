#!/usr/bin/env bash
# A fresh worktree for one video, on the Mac, linked to the main checkout's secrets and Playwright.
#   scripts/promo/video_worktree.sh <slug>      e.g. 25c-zap  ->  ~/virtualpytest-video-25c-zap, branch feat/video-25c-zap
# Remove it after the merge with: git worktree remove --force <dir> (copy scripts/promo/out/ to
# ~/virtualpytest-promo/out/ first: raw takes and builds are gitignored and go with the worktree).
set -euo pipefail
SLUG="${1:?slug, e.g. 25c-zap}"; WT="$HOME/virtualpytest-video-$SLUG"
MAIN="$(cd "$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"   # the main checkout
cd "$MAIN" && git fetch -q origin main
git worktree add -q -b "feat/video-$SLUG" "$WT" origin/main
ln -s "$MAIN/tests/e2e/playwright/node_modules" "$WT/tests/e2e/playwright/node_modules"
ln -s "$MAIN/scripts/promo/.token" "$WT/scripts/promo/.token"
ln -s "$MAIN/.env" "$WT/.env"
grep -qx "tests/e2e/playwright/node_modules" "$(git rev-parse --git-common-dir)/info/exclude" || \
  echo "tests/e2e/playwright/node_modules" >> "$(git rev-parse --git-common-dir)/info/exclude"
echo "$WT  (branch feat/video-$SLUG)"
