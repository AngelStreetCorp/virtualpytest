#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Environment defaults (override in shell/CI)
export E2E_BASE_URL="${E2E_BASE_URL:?E2E_BASE_URL is required (e.g. https://your-server)}"
export TEAM_ID="${TEAM_ID:-team_123}"

./node_modules/.bin/playwright test --config playwright.config.js \
  specs/viewport.desktop.spec.js \
  specs/viewport.mobile.spec.js
