#!/bin/bash

# Pre-build script: Generate all documentation before Vite build
# Called automatically via npm prebuild hook or systemd ExecStartPre
# Ensures API reference, security reports, and markdown docs are available in public/docs/
#
# NOTE: intentionally NOT `set -e`. Documentation is NON-CRITICAL — a failing or
# missing doc tool must never abort `npm run build` (this runs as the npm
# `prebuild` hook, so a non-zero exit would skip the Vite app build). Every step
# is guarded individually, failures are tracked in DOC_OK, and we always exit 0.

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$FRONTEND_DIR")"

# ==================== DOC CACHE CONFIG ====================
# Persistent cache that survives deploys. MUST live OUTSIDE the deploy target
# (/opt/virtualpytest is wiped by `rsync --delete` on every update) and be
# writable by the service user (vpt_user). Override with VPT_DOCS_CACHE_DIR.
# Set VPT_DOCS_FORCE_REBUILD=1 to bypass the cache and rebuild unconditionally.
DOCS_CACHE_DIR="${VPT_DOCS_CACHE_DIR:-/opt/vpt-cache/docs}"
HASH_FILE="$DOCS_CACHE_DIR/docs.hash"
SNAPSHOT_DIR="$DOCS_CACHE_DIR/public_docs"   # cached copy of frontend/public/docs
PUBLIC_DOCS="$FRONTEND_DIR/public/docs"      # the single artifact the Vite build consumes

DOC_OK=1   # flipped to 0 if any doc step fails; gates caching + final status (never aborts)

# Global wall-clock budget for the WHOLE doc pipeline (steps 2-5). If generation
# exceeds this, the running step is killed and we continue to the Vite build with
# DOC_OK=0. Override with VPT_DOCS_TIMEOUT (seconds).
DOC_TIMEOUT="${VPT_DOCS_TIMEOUT:-120}"
DOC_DEADLINE=0   # set once the full pipeline starts (after the cache gate)

# Run a doc step under the remaining global budget. Returns 124 if the budget is
# already spent (step skipped) or the step is killed for exceeding it.
run_step() {
    # No `timeout` binary (e.g. non-GNU host) → run uncapped rather than skip docs.
    if ! command -v timeout >/dev/null 2>&1; then
        "$@"
        return $?
    fi
    local now remaining
    now=$(date +%s)
    remaining=$(( DOC_DEADLINE - now ))
    if [ "$remaining" -le 0 ]; then
        echo -e "  ${YELLOW}⚠${NC} Doc budget (${DOC_TIMEOUT}s) exhausted — skipping this step"
        return 124
    fi
    timeout -k 5 "$remaining" "$@"
}

# Content hash of every SOURCE that feeds the doc pipeline. Generated outputs
# (docs/api/docs, docs/security, the generated MCP md) are excluded so the hash
# stays stable across regenerations. Reading + sha1 of these files takes ~1-2s
# vs. the minutes of scanning/network the pipeline itself costs.
compute_inputs_hash() {
    {
        find \
            "$REPO_ROOT/docs" \
            "$REPO_ROOT/backend_host/src" \
            "$REPO_ROOT/backend_server/src" \
            "$REPO_ROOT/backend_host/requirements.txt" \
            "$REPO_ROOT/backend_server/requirements.txt" \
            "$FRONTEND_DIR/package-lock.json" \
            "$REPO_ROOT/VERSION.txt" \
            -type f \
            ! -path '*/node_modules/*' \
            ! -path '*/__pycache__/*' \
            ! -name '*.pyc' \
            ! -path '*/docs/api/docs/*' \
            ! -path '*/docs/security/*' \
            ! -name 'mcp_tools_generated.md' \
            -print0 2>/dev/null \
        | sort -z \
        | xargs -0 sha1sum 2>/dev/null
    } | sha1sum | awk '{print $1}'
}

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Frontend Pre-Build: Documentation Pipeline  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════╝${NC}"
echo ""

# ==================== 0. SYNC VERSION FILE ====================
echo -e "${YELLOW}[1/5]${NC} Sync version artifact"

VERSION_SOURCE=""
for candidate in "$REPO_ROOT/VERSION.txt" "$REPO_ROOT/version.txt" "$FRONTEND_DIR/VERSION.txt" "$FRONTEND_DIR/version.txt"; do
    if [ -f "$candidate" ]; then
        VERSION_SOURCE="$candidate"
        break
    fi
done

if [ -n "$VERSION_SOURCE" ]; then
    cp "$VERSION_SOURCE" "$FRONTEND_DIR/public/version.txt"
    cp "$VERSION_SOURCE" "$FRONTEND_DIR/VERSION.txt"
    echo -e "  ${GREEN}✓${NC} Version synced from $(basename "$VERSION_SOURCE")"
else
    echo -e "  ${YELLOW}⚠${NC} No VERSION.txt found, frontend build will fall back to unknown"
fi
echo ""

# ==================== CACHE GATE: skip steps 2-5 if doc sources unchanged ====================
INPUT_HASH="$(compute_inputs_hash)"
OLD_HASH="$(cat "$HASH_FILE" 2>/dev/null || true)"

if [ "${VPT_DOCS_FORCE_REBUILD:-0}" != "1" ] && \
   [ -n "$INPUT_HASH" ] && [ "$INPUT_HASH" = "$OLD_HASH" ] && [ -d "$SNAPSHOT_DIR" ]; then
    echo -e "${GREEN}✓ Doc sources unchanged${NC} (hash ${INPUT_HASH:0:12}) — restoring cached docs, skipping steps 2-5"
    mkdir -p "$FRONTEND_DIR/public"
    # Restore via a staging copy + swap: a failed/interrupted `cp -a` must not leave
    # public/docs deleted or half-written (same failure mode as BUG-0060 in copy-docs.sh).
    RESTORE_TMP="$FRONTEND_DIR/public/.docs-restore.$$"
    rm -rf "$RESTORE_TMP"
    if cp -a "$SNAPSHOT_DIR" "$RESTORE_TMP" && rm -rf "$PUBLIC_DOCS" && mv "$RESTORE_TMP" "$PUBLIC_DOCS"; then
        echo -e "  ${GREEN}✓${NC} Restored public/docs from $SNAPSHOT_DIR"
        echo ""
        echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║   Pre-build (cached) — ready for Vite build   ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
        exit 0
    fi
    rm -rf "$RESTORE_TMP"
    echo -e "  ${YELLOW}⚠${NC} Cache restore failed, falling through to full rebuild"
else
    echo -e "${YELLOW}→${NC} Doc sources changed (or no cache) — running full pipeline (budget ${DOC_TIMEOUT}s)"
fi
DOC_DEADLINE=$(( $(date +%s) + DOC_TIMEOUT ))
echo ""

# ==================== 1. GENERATE API DOCS ====================
echo -e "${YELLOW}[2/5]${NC} API Documentation (OpenAPI → HTML)"

if [ -d "$REPO_ROOT/docs/api/specs" ] && command -v npx &> /dev/null; then
    echo -e "  ${BLUE}→${NC} Generating HTML from OpenAPI YAML specs..."
    cd "$REPO_ROOT"
    # Stream live & unbuffered (-u) so per-spec progress [i/N] shows in real time
    # — never looks stuck, and a hang points at the exact spec.
    run_step python3 -u scripts/generate_api_docs.py 2>&1
    if [ "$?" -ne 0 ]; then
        DOC_OK=0; echo -e "  ${YELLOW}⚠${NC} API doc generation failed or timed out (non-blocking)"
    else
        echo -e "  ${GREEN}✓${NC} API docs generated"
    fi
elif [ -d "$REPO_ROOT/docs/api/docs" ]; then
    count=$(ls "$REPO_ROOT/docs/api/docs/"*.html 2>/dev/null | wc -l | tr -d ' ')
    echo -e "  ${YELLOW}⚠${NC} npx not available, using existing $count pre-generated HTML files"
else
    echo -e "  ${RED}✗${NC} No API specs or pre-generated docs found, skipping"
fi
echo ""

# ==================== 2. GENERATE MCP DOCS ====================
echo -e "${YELLOW}[3/5]${NC} MCP Documentation (tool definitions → markdown)"

if [ -d "$REPO_ROOT/backend_server/src/mcp/tool_definitions" ]; then
    echo -e "  ${BLUE}→${NC} Generating MCP tools reference..."
    cd "$REPO_ROOT"
    run_step python3 -u scripts/generate_mcp_docs.py 2>&1
    if [ "$?" -ne 0 ]; then
        DOC_OK=0; echo -e "  ${YELLOW}⚠${NC} MCP doc generation failed or timed out (non-blocking)"
    else
        echo -e "  ${GREEN}✓${NC} MCP docs generated"
    fi
else
    echo -e "  ${RED}✗${NC} MCP definitions directory not found, skipping"
fi
echo ""

# ==================== 3. GENERATE SECURITY REPORTS ====================
echo -e "${YELLOW}[4/5]${NC} Security Reports (Bandit + npm audit → HTML)"

if command -v bandit &> /dev/null; then
    echo -e "  ${BLUE}→${NC} Running security scans and generating report..."
    cd "$REPO_ROOT"
    # Slowest step (bandit + network scans) — stream live so its per-scan progress
    # is visible and it never appears hung.
    run_step bash scripts/generate-security-docs.sh 2>&1
    if [ "$?" -ne 0 ]; then
        DOC_OK=0; echo -e "  ${YELLOW}⚠${NC} Security report generation failed or timed out (non-blocking)"
    else
        echo -e "  ${GREEN}✓${NC} Security reports generated"
    fi
elif [ -f "$REPO_ROOT/docs/security/index.html" ]; then
    echo -e "  ${YELLOW}⚠${NC} bandit not available, using existing security report"
else
    echo -e "  ${RED}✗${NC} No security tools or pre-generated report found, skipping"
fi
echo ""

# ==================== 4. COPY DOCS TO PUBLIC ====================
echo -e "${YELLOW}[5/5]${NC} Copy docs to frontend/public/docs/"

cd "$FRONTEND_DIR"
# Deliberately NOT under run_step: copy-docs is the step that actually publishes
# public/docs, and running it on the *leftovers* of the shared budget is how it got
# killed mid-publish (BUG-0060) after the generators upstream ate all 120s. It is local
# file copying, so give it its own fixed budget instead of whatever remains.
COPY_DOCS_TIMEOUT="${VPT_COPY_DOCS_TIMEOUT:-90}"
if command -v timeout >/dev/null 2>&1; then
    timeout -k 5 "$COPY_DOCS_TIMEOUT" bash scripts/copy-docs.sh
else
    bash scripts/copy-docs.sh
fi
if [ "$?" -ne 0 ]; then
    DOC_OK=0; echo -e "  ${YELLOW}⚠${NC} copy-docs failed or timed out (non-blocking) — previous public/docs kept"
fi
echo ""

# ==================== SNAPSHOT: persist generated docs + hash for next run ====================
# Only cache a clean run — never snapshot partial/failed docs (next run would
# restore the broken state and skip regeneration).
if [ "$DOC_OK" = "1" ] && [ -d "$PUBLIC_DOCS" ] && [ -n "$INPUT_HASH" ]; then
    if mkdir -p "$DOCS_CACHE_DIR" 2>/dev/null; then
        rm -rf "$SNAPSHOT_DIR"
        if cp -a "$PUBLIC_DOCS" "$SNAPSHOT_DIR" 2>/dev/null; then
            echo "$INPUT_HASH" > "$HASH_FILE"
            echo -e "  ${GREEN}✓${NC} Cached docs snapshot + hash ${INPUT_HASH:0:12} → $DOCS_CACHE_DIR"
        else
            echo -e "  ${YELLOW}⚠${NC} Could not write doc snapshot to $DOCS_CACHE_DIR — next build will not be cached"
        fi
    else
        echo -e "  ${YELLOW}⚠${NC} Cache dir $DOCS_CACHE_DIR not writable — skipping cache (set VPT_DOCS_CACHE_DIR to a writable path)"
    fi
fi

echo ""
if [ "$DOC_OK" = "1" ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   Pre-build complete — ready for Vite build   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
else
    echo -e "${YELLOW}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  Pre-build finished WITH DOC WARNINGS          ║${NC}"
    echo -e "${YELLOW}║  Continuing to Vite build anyway (docs are     ║${NC}"
    echo -e "${YELLOW}║  non-critical; not caching this run).          ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════╝${NC}"
fi

# Always succeed: doc problems must not block the app build (npm prebuild hook).
exit 0
