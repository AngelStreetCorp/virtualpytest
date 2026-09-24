#!/bin/bash
# Shared content hashing for the frontend build pipeline.
#
# Every function here answers one question: "have the inputs of <step> changed
# since the last successful run of <step>?" Each step owns ONE hash covering ONLY
# what it actually reads. That separation is the fix for BUG-0103: the pipeline
# used to key every doc step off a single hash spanning docs/ + both backends, so
# a one-line backend change re-ran the 73s API-doc generation, and a failure in
# any step vetoed caching for all of them.
#
# Callers must set REPO_ROOT and FRONTEND_DIR before sourcing.

# hash_paths <path...> — sha1 over the contents of every regular file under the
# given paths. Missing paths are skipped (a tree without shared/src or without an
# overlay .env.production is normal, not an error). Returns 1 and prints nothing
# when no file matched at all, so a caller can never mistake "nothing found" for
# a real, stable hash.
hash_paths() {
    local listing
    listing="$(
        find "$@" -type f \
            ! -path '*/node_modules/*' \
            ! -path '*/__pycache__/*' \
            ! -path '*/docs/security/temp/*' \
            ! -name '*.pyc' \
            -print0 2>/dev/null \
        | sort -z \
        | xargs -0 sha1sum 2>/dev/null
    )"
    [ -z "$listing" ] && return 1
    printf '%s' "$listing" | sha1sum | awk '{print $1}'
}

# [2/5] API docs — redoc renders docs/api/specs/*.yaml into docs/api/docs/*.html.
# Nothing else is read, so nothing else may invalidate it.
api_docs_inputs_hash() {
    hash_paths \
        "$REPO_ROOT/docs/api/specs" \
        "$REPO_ROOT/scripts/generate_api_docs.py"
}

# [3/5] MCP docs — generated purely from the tool definitions.
mcp_docs_inputs_hash() {
    hash_paths \
        "$REPO_ROOT/backend_server/src/mcp/tool_definitions" \
        "$REPO_ROOT/scripts/generate_mcp_docs.py"
}

# [4/5] Security reports — bandit scans the three python trees, npm audit reads
# the frontend lockfile. This is the ONLY step a backend code change should cost.
security_inputs_hash() {
    hash_paths \
        "$REPO_ROOT/backend_host/src" \
        "$REPO_ROOT/backend_server/src" \
        "$REPO_ROOT/shared/src" \
        "$REPO_ROOT/backend_host/requirements.txt" \
        "$REPO_ROOT/backend_server/requirements.txt" \
        "$FRONTEND_DIR/package-lock.json" \
        "$REPO_ROOT/bandit.yaml" \
        "$REPO_ROOT/scripts/generate-security-docs.sh" \
        "$REPO_ROOT/scripts/parse-security-to-html.py"
}

# [5/5] Publish — copy-docs.sh reads the whole docs/ tree, GENERATED OUTPUT
# INCLUDED. Computed after steps 2-4 precisely so that a step which regenerated
# byte-identical output leaves this hash untouched and the copy is skipped too.
publish_inputs_hash() {
    hash_paths \
        "$REPO_ROOT/docs" \
        "$REPO_ROOT/VERSION.txt" \
        "$FRONTEND_DIR/scripts/copy-docs.sh"
}

# The published bundle — everything `vite build` turns into dist/. Deliberately
# hashes frontend/public AFTER prebuild has republished public/docs rather than
# the docs sources: a backend change that leaves the rendered report identical
# must not force a 1m45s Vite rebuild.
bundle_inputs_hash() {
    hash_paths \
        "$FRONTEND_DIR/src" \
        "$FRONTEND_DIR/public" \
        "$FRONTEND_DIR/index.html" \
        "$FRONTEND_DIR/vite.config.ts" \
        "$FRONTEND_DIR/vite.config.local.json" \
        "$FRONTEND_DIR/package.json" \
        "$FRONTEND_DIR/package-lock.json" \
        "$FRONTEND_DIR/tsconfig.json" \
        "$FRONTEND_DIR/tsconfig.node.json" \
        "$FRONTEND_DIR/postcss.config.js" \
        "$FRONTEND_DIR/.env.production" \
        "$FRONTEND_DIR/VERSION.txt"
}

# [6/6] Project metrics — the Analytics page's Project tab. Reads the bug files,
# the release note, VERSION.txt, and the source trees the line counter walks.
# Deliberately NOT the whole repo: the counter walks the TRACKED set, so a change
# to an untracked build artifact must not invalidate this step.
project_metrics_inputs_hash() {
    hash_paths \
        "$REPO_ROOT/docs/bugs" \
        "$REPO_ROOT/docs/release_note" \
        "$REPO_ROOT/VERSION.txt" \
        "$REPO_ROOT/scripts/count_lines.py" \
        "$REPO_ROOT/scripts/docs/build_project_metrics.py" \
        "$REPO_ROOT/backend_host/src" \
        "$REPO_ROOT/backend_server/src" \
        "$REPO_ROOT/shared/src" \
        "$FRONTEND_DIR/src"
}
