#!/bin/bash

# Pre-build script: Generate all documentation before Vite build
# Called automatically via npm prebuild hook or by scripts/ensure_dist.sh
# Ensures API reference, security reports, and markdown docs are available in public/docs/
#
# NOTE: intentionally NOT `set -e`. Documentation is NON-CRITICAL — a failing or
# missing doc tool must never abort `npm run build` (this runs as the npm
# `prebuild` hook, so a non-zero exit would skip the Vite app build). Every step
# is guarded individually and we always exit 0.
#
# CACHING (rewritten for BUG-0103). Each of the generating steps owns its own input
# hash and its own time budget:
#   - a step is skipped when its inputs are unchanged AND its output is present,
#   - a step that fails or times out invalidates ONLY ITSELF.
# The previous design shared one hash and one 120s budget across all steps, so
# the security scan (which always exceeded the leftover budget) set DOC_OK=0 and
# vetoed the cache for every step — the hash file never advanced and all nine
# restarts on 2026-09-15 paid the full 2m34s pipeline.

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$FRONTEND_DIR")"

# shellcheck source=lib/build_hashes.sh
. "$SCRIPT_DIR/lib/build_hashes.sh"

# ==================== DOC CACHE CONFIG ====================
# Persistent cache that survives deploys. MUST live OUTSIDE the deploy target
# (/opt/virtualpytest is wiped by `rsync --delete` on every update) and be
# writable by the service user (vpt_user). Override with VPT_DOCS_CACHE_DIR.
# Set VPT_DOCS_FORCE_REBUILD=1 to bypass every gate and rebuild unconditionally.
DOCS_CACHE_DIR="${VPT_DOCS_CACHE_DIR:-/opt/vpt-cache/docs}"
SNAPSHOT_DIR="$DOCS_CACHE_DIR/public_docs"   # cached copy of frontend/public/docs
PUBLIC_DOCS="$FRONTEND_DIR/public/docs"      # the single artifact the Vite build consumes
FORCE_REBUILD="${VPT_DOCS_FORCE_REBUILD:-0}"

API_HASH_FILE="$DOCS_CACHE_DIR/api.hash"
MCP_HASH_FILE="$DOCS_CACHE_DIR/mcp.hash"
SEC_HASH_FILE="$DOCS_CACHE_DIR/security.hash"
PUBLISH_HASH_FILE="$DOCS_CACHE_DIR/publish.hash"
METRICS_HASH_FILE="$DOCS_CACHE_DIR/project_metrics.hash"
# Single coupled hash from the pre-BUG-0103 cache. Stale by definition now, and
# leaving it would be a trap for anyone debugging the cache later.
LEGACY_HASH_FILE="$DOCS_CACHE_DIR/docs.hash"

# Per-step wall-clock budgets. Each step gets its OWN: under the old shared 120s
# budget the two generators upstream decided how much time the security scan got,
# and the answer was "not enough, ever".
API_DOCS_TIMEOUT="${VPT_API_DOCS_TIMEOUT:-300}"
MCP_DOCS_TIMEOUT="${VPT_MCP_DOCS_TIMEOUT:-60}"
SECURITY_TIMEOUT="${VPT_SECURITY_TIMEOUT:-240}"
COPY_DOCS_TIMEOUT="${VPT_COPY_DOCS_TIMEOUT:-90}"
PROJECT_METRICS_TIMEOUT="${VPT_PROJECT_METRICS_TIMEOUT:-60}"

STEPS_RUN=()
STEPS_SKIPPED=()
STEPS_FAILED=()

# run_step <budget-seconds> <cmd...> — run one doc step under its own budget.
# Returns 124 when the step is killed for exceeding it.
run_step() {
    local budget="$1"; shift
    # No `timeout` binary (e.g. non-GNU host) → run uncapped rather than skip docs.
    if ! command -v timeout >/dev/null 2>&1; then
        "$@"
        return $?
    fi
    timeout -k 5 "$budget" "$@"
}

# can_skip <hash-file> <current-hash> <output-probe> — true when the step's
# inputs are unchanged AND the output it would produce is actually present.
# The probe matters: the deploy rsync can land a tree whose generated output was
# never committed, and a hash match must not be read as "output is there".
can_skip() {
    local hash_file="$1" current="$2" probe="$3"
    [ "$FORCE_REBUILD" = "1" ] && return 1
    [ -n "$current" ] || return 1
    [ "$current" = "$(cat "$hash_file" 2>/dev/null)" ] || return 1
    [ -s "$probe" ] || return 1
    return 0
}

# record_hash <hash-file> <hash> — persist a step's input hash after it succeeded.
record_hash() {
    local hash_file="$1" value="$2"
    [ -n "$value" ] || return 0
    mkdir -p "$DOCS_CACHE_DIR" 2>/dev/null || {
        echo -e "  ${YELLOW}⚠${NC} Cache dir $DOCS_CACHE_DIR not writable — this step will re-run next build"
        return 1
    }
    echo "$value" > "$hash_file"
}

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Frontend Pre-Build: Documentation Pipeline  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════╝${NC}"
echo ""

[ -f "$LEGACY_HASH_FILE" ] && rm -f "$LEGACY_HASH_FILE" 2>/dev/null

# ==================== 1. SYNC VERSION FILE ====================
echo -e "${YELLOW}[1/6]${NC} Sync version artifact"

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

# ==================== 2. GENERATE API DOCS ====================
echo -e "${YELLOW}[2/6]${NC} API Documentation (OpenAPI → HTML)"

API_HASH="$(api_docs_inputs_hash)" || API_HASH=""
if can_skip "$API_HASH_FILE" "$API_HASH" "$REPO_ROOT/docs/api/docs/index.html"; then
    echo -e "  ${GREEN}✓${NC} Specs unchanged (${API_HASH:0:12}) — keeping the HTML already in docs/api/docs"
    STEPS_SKIPPED+=("api-docs")
elif [ -d "$REPO_ROOT/docs/api/specs" ] && command -v npx &> /dev/null; then
    echo -e "  ${BLUE}→${NC} Generating HTML from OpenAPI YAML specs (budget ${API_DOCS_TIMEOUT}s)..."
    cd "$REPO_ROOT"
    # Stream live & unbuffered (-u) so per-spec progress [i/N] shows in real time
    # — never looks stuck, and a hang points at the exact spec.
    run_step "$API_DOCS_TIMEOUT" python3 -u scripts/generate_api_docs.py 2>&1
    if [ "$?" -ne 0 ]; then
        STEPS_FAILED+=("api-docs"); echo -e "  ${YELLOW}⚠${NC} API doc generation failed or timed out (non-blocking)"
    else
        echo -e "  ${GREEN}✓${NC} API docs generated"
        STEPS_RUN+=("api-docs")
        record_hash "$API_HASH_FILE" "$API_HASH"
    fi
elif [ -d "$REPO_ROOT/docs/api/docs" ]; then
    count=$(ls "$REPO_ROOT/docs/api/docs/"*.html 2>/dev/null | wc -l | tr -d ' ')
    echo -e "  ${YELLOW}⚠${NC} npx not available, using existing $count pre-generated HTML files"
    STEPS_SKIPPED+=("api-docs")
else
    echo -e "  ${RED}✗${NC} No API specs or pre-generated docs found, skipping"
    STEPS_SKIPPED+=("api-docs")
fi
echo ""

# ==================== 3. GENERATE MCP DOCS ====================
echo -e "${YELLOW}[3/6]${NC} MCP Documentation (tool definitions → markdown)"

MCP_HASH="$(mcp_docs_inputs_hash)" || MCP_HASH=""
if can_skip "$MCP_HASH_FILE" "$MCP_HASH" "$REPO_ROOT/docs/mcp/mcp_tools_generated.md"; then
    echo -e "  ${GREEN}✓${NC} Tool definitions unchanged (${MCP_HASH:0:12}) — keeping mcp_tools_generated.md"
    STEPS_SKIPPED+=("mcp-docs")
elif [ -d "$REPO_ROOT/backend_server/src/mcp/tool_definitions" ]; then
    echo -e "  ${BLUE}→${NC} Generating MCP tools reference..."
    cd "$REPO_ROOT"
    run_step "$MCP_DOCS_TIMEOUT" python3 -u scripts/generate_mcp_docs.py 2>&1
    if [ "$?" -ne 0 ]; then
        STEPS_FAILED+=("mcp-docs"); echo -e "  ${YELLOW}⚠${NC} MCP doc generation failed or timed out (non-blocking)"
    else
        echo -e "  ${GREEN}✓${NC} MCP docs generated"
        STEPS_RUN+=("mcp-docs")
        record_hash "$MCP_HASH_FILE" "$MCP_HASH"
    fi
else
    echo -e "  ${RED}✗${NC} MCP definitions directory not found, skipping"
    STEPS_SKIPPED+=("mcp-docs")
fi
echo ""

# ==================== 4. GENERATE SECURITY REPORTS ====================
echo -e "${YELLOW}[4/6]${NC} Security Reports (Bandit + npm audit → HTML)"

SEC_HASH="$(security_inputs_hash)" || SEC_HASH=""
if can_skip "$SEC_HASH_FILE" "$SEC_HASH" "$REPO_ROOT/docs/security/index.html"; then
    echo -e "  ${GREEN}✓${NC} Scanned sources unchanged (${SEC_HASH:0:12}) — keeping docs/security"
    STEPS_SKIPPED+=("security")
elif command -v bandit &> /dev/null; then
    # Slowest step (bandit over three python trees + npm audit) — stream live so
    # its per-scan progress is visible and it never appears hung. It now has its
    # OWN budget: under the shared one it was always the step that got starved,
    # killed mid-scan, and blamed for the whole cache being cold (BUG-0103).
    echo -e "  ${BLUE}→${NC} Running security scans and generating report (budget ${SECURITY_TIMEOUT}s)..."
    cd "$REPO_ROOT"
    run_step "$SECURITY_TIMEOUT" bash scripts/generate-security-docs.sh 2>&1
    if [ "$?" -ne 0 ]; then
        STEPS_FAILED+=("security"); echo -e "  ${YELLOW}⚠${NC} Security report generation failed or timed out (non-blocking, other steps unaffected)"
    else
        echo -e "  ${GREEN}✓${NC} Security reports generated"
        STEPS_RUN+=("security")
        record_hash "$SEC_HASH_FILE" "$SEC_HASH"
    fi
elif [ -f "$REPO_ROOT/docs/security/index.html" ]; then
    echo -e "  ${YELLOW}⚠${NC} bandit not available, using existing security report"
    STEPS_SKIPPED+=("security")
else
    echo -e "  ${RED}✗${NC} No security tools or pre-generated report found, skipping"
    STEPS_SKIPPED+=("security")
fi
echo ""

# ==================== 5. COPY DOCS TO PUBLIC ====================
echo -e "${YELLOW}[5/6]${NC} Copy docs to frontend/public/docs/"

cd "$FRONTEND_DIR"
# Hash computed HERE, after steps 2-4, over the docs/ tree copy-docs actually
# reads — generated output included. A regenerated-but-identical report therefore
# skips the copy as well.
PUBLISH_HASH="$(publish_inputs_hash)" || PUBLISH_HASH=""
COPY_NEEDED=1

if can_skip "$PUBLISH_HASH_FILE" "$PUBLISH_HASH" "$PUBLIC_DOCS/docs-manifest.json"; then
    echo -e "  ${GREEN}✓${NC} Published docs already current (${PUBLISH_HASH:0:12}) — nothing to copy"
    STEPS_SKIPPED+=("copy-docs")
    COPY_NEEDED=0
elif [ "$FORCE_REBUILD" != "1" ] && [ -n "$PUBLISH_HASH" ] && \
     [ "$PUBLISH_HASH" = "$(cat "$PUBLISH_HASH_FILE" 2>/dev/null)" ] && [ -d "$SNAPSHOT_DIR" ]; then
    # Same content as last publish, but public/docs itself is gone or truncated
    # (fresh VM, or a copy killed mid-flight). Restore the snapshot instead of
    # re-running the 34s copy. Staging + swap: a failed/interrupted `cp -a` must
    # not leave public/docs deleted or half-written (BUG-0060 in copy-docs.sh).
    echo -e "  ${BLUE}→${NC} public/docs missing but content unchanged — restoring snapshot"
    RESTORE_TMP="$FRONTEND_DIR/public/.docs-restore.$$"
    rm -rf "$RESTORE_TMP"
    if cp -a "$SNAPSHOT_DIR" "$RESTORE_TMP" && rm -rf "$PUBLIC_DOCS" && mv "$RESTORE_TMP" "$PUBLIC_DOCS"; then
        echo -e "  ${GREEN}✓${NC} Restored public/docs from $SNAPSHOT_DIR"
        STEPS_SKIPPED+=("copy-docs")
        COPY_NEEDED=0
    else
        rm -rf "$RESTORE_TMP"
        echo -e "  ${YELLOW}⚠${NC} Cache restore failed, falling through to a full copy"
    fi
fi

if [ "$COPY_NEEDED" = "1" ]; then
    # copy-docs is the step that actually publishes public/docs, so it gets a
    # fixed budget of its own rather than whatever an upstream generator left
    # over — being killed mid-publish is exactly BUG-0060.
    if command -v timeout >/dev/null 2>&1; then
        timeout -k 5 "$COPY_DOCS_TIMEOUT" bash scripts/copy-docs.sh
    else
        bash scripts/copy-docs.sh
    fi
    if [ "$?" -ne 0 ]; then
        STEPS_FAILED+=("copy-docs")
        echo -e "  ${YELLOW}⚠${NC} copy-docs failed or timed out (non-blocking) — previous public/docs kept"
    else
        STEPS_RUN+=("copy-docs")
        record_hash "$PUBLISH_HASH_FILE" "$PUBLISH_HASH"
        # Snapshot only a clean publish — never cache a partial tree, or the next
        # restore would hand the build broken docs and skip regenerating them.
        if [ -d "$PUBLIC_DOCS" ] && mkdir -p "$DOCS_CACHE_DIR" 2>/dev/null; then
            rm -rf "$SNAPSHOT_DIR"
            if cp -a "$PUBLIC_DOCS" "$SNAPSHOT_DIR" 2>/dev/null; then
                echo -e "  ${GREEN}✓${NC} Cached docs snapshot → $DOCS_CACHE_DIR"
            else
                echo -e "  ${YELLOW}⚠${NC} Could not write doc snapshot to $DOCS_CACHE_DIR"
            fi
        fi
    fi
fi
echo ""

# ==================== 6. PROJECT METRICS ====================
# The Analytics page's Project tab: lines of code, bugs per severity/status, and
# features + fixes per cut build. These are facts about the REPOSITORY, so they are
# computed once here rather than queried at runtime — which is also why that tab
# costs nothing to open.
echo -e "${YELLOW}[6/6]${NC} Project metrics (repo → public/analytics/project.json)"

METRICS_HASH="$(project_metrics_inputs_hash)" || METRICS_HASH=""
if can_skip "$METRICS_HASH_FILE" "$METRICS_HASH" "$FRONTEND_DIR/public/analytics/project.json"; then
    echo -e "  ${GREEN}✓${NC} Repo unchanged (${METRICS_HASH:0:12}) — keeping public/analytics/project.json"
    STEPS_SKIPPED+=("project-metrics")
elif [ -f "$REPO_ROOT/scripts/docs/build_project_metrics.py" ]; then
    echo -e "  ${BLUE}→${NC} Counting lines, bugs and releases (budget ${PROJECT_METRICS_TIMEOUT}s)..."
    cd "$REPO_ROOT"
    run_step "$PROJECT_METRICS_TIMEOUT" python3 -u scripts/docs/build_project_metrics.py 2>&1
    if [ "$?" -ne 0 ]; then
        STEPS_FAILED+=("project-metrics")
        echo -e "  ${YELLOW}⚠${NC} Project metrics failed or timed out (non-blocking) — the Project tab will show whatever is already published"
    else
        echo -e "  ${GREEN}✓${NC} Project metrics written"
        STEPS_RUN+=("project-metrics")
        record_hash "$METRICS_HASH_FILE" "$METRICS_HASH"
    fi
    cd "$FRONTEND_DIR"
else
    echo -e "  ${RED}✗${NC} scripts/docs/build_project_metrics.py not found, skipping"
    STEPS_SKIPPED+=("project-metrics")
fi
echo ""

# ==================== SUMMARY ====================
echo -e "  ran:     ${STEPS_RUN[*]:-none}"
echo -e "  cached:  ${STEPS_SKIPPED[*]:-none}"
if [ "${#STEPS_FAILED[@]}" -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   Pre-build complete — ready for Vite build   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
else
    echo -e "  failed:  ${STEPS_FAILED[*]}"
    echo ""
    echo -e "${YELLOW}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  Pre-build finished WITH DOC WARNINGS          ║${NC}"
    echo -e "${YELLOW}║  Continuing to Vite build anyway (docs are     ║${NC}"
    echo -e "${YELLOW}║  non-critical). Only the failed step above is  ║${NC}"
    echo -e "${YELLOW}║  left uncached; the others keep their cache.   ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════╝${NC}"
fi

# Always succeed: doc problems must not block the app build (npm prebuild hook).
exit 0
