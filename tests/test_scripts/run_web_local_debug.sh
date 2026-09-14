#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-smoke}" # smoke|full

echo "[web-local-debug] mode=$MODE"
echo "[web-local-debug] root=$ROOT_DIR"

FAILED=()

# VPT scripts always exit 0 and report their verdict as a `SCRIPT_SUCCESS:true|false` line on
# stdout (the platform's script_executor parses that marker). Gating on the exit code alone
# let CI run #340 show PASSED while both scripts printed SCRIPT_SUCCESS:false (BUG-0067).
run_script() {
  local name="$1"; shift
  echo "[web-local-debug] Running $name local-debug smoke..."
  local out
  out="$(mktemp)"
  python3 "$@" 2>&1 | tee "$out" || true
  if grep -q '^SCRIPT_SUCCESS:true' "$out"; then
    echo "[web-local-debug] ✅ $name: SCRIPT_SUCCESS:true"
  else
    echo "[web-local-debug] ❌ $name: $(grep -o '^SCRIPT_SUCCESS:[a-z]*' "$out" | tail -n1 || echo 'no SCRIPT_SUCCESS marker (script crashed?)')"
    FAILED+=("$name")
  fi
  rm -f "$out"
}

run_browser_task() {
  run_script browser_task test_scripts/web/browser_task.py \
    --local-debug \
    --url "https://example.com" \
    --task "Capture page title and top links" \
    --max_steps 5 \
    --headless true \
    --wait_seconds 2
}

# Dailymotion, not YouTube: from the CI runner's datacenter IP YouTube serves only
# "Sign in to confirm you're not a bot" (no <video>, media requests 403) whatever the
# browser, while Dailymotion's player plays fine headlessly (verified on VM 164,
# 2026-09-08, BUG-0067). youtube_video_check stays a host-tier script.
run_dailymotion_check() {
  run_script dailymotion_video_check test_scripts/web/dailymotion_video_check.py \
    --local-debug \
    --headless true \
    --preroll_wait 5 \
    --monitor_duration 10
}

# Always run the playback check in smoke/full.
run_dailymotion_check

# browser_task depends on OPENROUTER_API_KEY; run only when available.
if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  run_browser_task
else
  echo "[web-local-debug] ⚠️ OPENROUTER_API_KEY is not set - skipping browser_task"
fi

echo "[web-local-debug] Recent local-debug artifacts:"
find tmp/local_debug -maxdepth 3 -type d 2>/dev/null | sort | tail -n 20 || true

if (( ${#FAILED[@]} )); then
  echo "[web-local-debug] FAILED: ${FAILED[*]}"
  exit 1
fi
echo "[web-local-debug] all scripts reported SCRIPT_SUCCESS:true"
