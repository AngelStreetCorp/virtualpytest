#!/bin/bash
# Make frontend/dist/ current, without ever taking the running site down.
#
# Single entry point for both callers:
#   - vpt-frontend-prod.service   ExecStartPre, on every start/restart
#   - setup/proxmox/node/update_core.sh, right after the rsync push
#
# The deploy runs it FIRST, while the old `serve` is still answering requests, so
# the 1m45s Vite build happens off the critical path and the `systemctl restart`
# that follows finds a fresh dist and comes back in about a second. Before this,
# ExecStartPre ran the whole build with the service already stopped: a restart
# meant 4+ minutes of hard downtime (BUG-0103).
#
# Two guards keep that safe:
#   - the bundle stamp — dist/.build-stamp holds the hash of everything Vite read
#     to produce it, so a restart that follows a deploy build skips the rebuild,
#     while a restart on a tree nobody built still rebuilds. Serving a stale
#     bundle is never a possible outcome.
#   - staging + swap — the build writes dist.new and only then replaces dist, so
#     a failed or killed build leaves the live bundle untouched.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$FRONTEND_DIR")"

# shellcheck source=lib/build_hashes.sh
. "$SCRIPT_DIR/lib/build_hashes.sh"

DIST="$FRONTEND_DIR/dist"
STAGING="$FRONTEND_DIR/dist.new"
PREVIOUS="$FRONTEND_DIR/dist.old"
STAMP_NAME=".build-stamp"

# Mirror the service environment so a deploy-time build and a systemd build
# produce the same bundle. The heap ceiling matters on the 1.9GB frontend VM:
# vite's gzip-size reporting OOMs under the default limit.
export NODE_ENV="${NODE_ENV:-production}"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1536}"
# bandit lives in the project venv. The unit puts it on PATH; a deploy-time
# `sudo -u vpt_user` does not, because sudo's secure_path wins — without this the
# deploy build would silently skip the security report that the systemd build
# generates, and the two would produce different bundles.
[ -d "$REPO_ROOT/venv/bin" ] && export PATH="$REPO_ROOT/venv/bin:$PATH"

cd "$FRONTEND_DIR" || exit 1

# 1. Documentation. Internally cached per step, so this is ~1s when nothing that
#    feeds public/docs has changed.
npm run prebuild

# 2. Does the bundle need rebuilding? Hashed AFTER prebuild, over public/ as it
#    now stands — a backend change whose rendered security report came out
#    identical must not cost a Vite rebuild.
WANT_STAMP="$(bundle_inputs_hash)" || WANT_STAMP=""
HAVE_STAMP="$(cat "$DIST/$STAMP_NAME" 2>/dev/null)"

if [ "${VPT_FORCE_BUILD:-0}" != "1" ] && [ -n "$WANT_STAMP" ] \
   && [ -s "$DIST/index.html" ] && [ "$WANT_STAMP" = "$HAVE_STAMP" ]; then
    echo "==> dist is current (${WANT_STAMP:0:12}) — skipping vite build"
    exit 0
fi

if [ -z "$HAVE_STAMP" ]; then
    echo "==> no build stamp in dist/ — building"
else
    echo "==> bundle inputs changed (${HAVE_STAMP:0:12} -> ${WANT_STAMP:0:12}) — building"
fi

# 3. Build into staging. dist/ keeps serving the whole time.
rm -rf "$STAGING"
if ! ./node_modules/.bin/vite build --outDir dist.new --emptyOutDir; then
    rm -rf "$STAGING"
    if [ -s "$DIST/index.html" ]; then
        echo "==> vite build FAILED — keeping the bundle already in dist/ (site stays up, but it is STALE)" >&2
        exit 0
    fi
    echo "==> vite build FAILED and there is no usable dist/ to fall back to" >&2
    exit 1
fi
printf '%s\n' "$WANT_STAMP" > "$STAGING/$STAMP_NAME"

# 4. Swap. `mv` cannot replace a non-empty directory in one call, so dist is
#    absent for the microsecond between the two renames; a request landing in
#    that window gets one 404 and the client retries. Every alternative (copying
#    into place, building straight into dist) leaves a half-written bundle
#    visible for the entire build instead.
rm -rf "$PREVIOUS"
[ -d "$DIST" ] && mv "$DIST" "$PREVIOUS"
mv "$STAGING" "$DIST"
rm -rf "$PREVIOUS"

echo "==> dist updated (${WANT_STAMP:0:12})"
