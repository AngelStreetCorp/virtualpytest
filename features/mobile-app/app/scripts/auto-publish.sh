#!/usr/bin/env bash
# Automatic APK republish (run by a systemd timer on codebox; see features/mobile-app/app/README.md).
#
#   auto-publish.sh            check origin; rebuild + publish only what is due; no-op otherwise
#   auto-publish.sh --force    rebuild + publish the intermediary APK now, even if nothing changed
#
# Two outputs on the downloads host (target below), both signed with the release keystore:
#   downloads/vpt-mobile-app-debug.apk            the single INTERMEDIARY file, replaced on every
#                                                 push to main that touches features/mobile-app/ or
#                                                 frontend/ (the name the app's download link uses)
#   downloads/releases/vpt-mobile-app-<tag>.apk   one per `release-*` git tag, built from that tag,
#                                                 never overwritten, never pruned. No backfill: tags
#                                                 that exist the first time this runs are only recorded.
#
# Never touches ~/virtualpytest: it builds in its own detached worktree (BUILD_TREE).
# One run at a time (flock). Everything is logged to $STATE/auto-publish.log.
set -uo pipefail

STATE="${VPT_APK_STATE:-$HOME/.vpt-apk}"          # keystore/, last-commit, seen-tags, log, lock
SRC_REPO="${VPT_APK_SRC_REPO:-$HOME/virtualpytest}" # any clone of the repo; only its .git is used
BUILD_TREE="${VPT_APK_BUILD_TREE:-$HOME/vpt-apk-build}"
REMOTE_HOST="${VPT_APK_REMOTE_HOST:-proxy}"
REMOTE_DIR="${VPT_APK_REMOTE_DIR:-downloads}"
PUBLIC_APK_URL="${VPT_APK_URL:-https://virtualpytest.angelstreet.io/downloads/vpt-mobile-app-debug.apk}"
SDK="${ANDROID_HOME:-$HOME/android-sdk}"
WATCH=(features/mobile-app frontend)               # paths whose change means "rebuild"

mkdir -p "$STATE"
exec 9>"$STATE/lock"
flock -n 9 || { echo "$(date -Is) another run holds the lock, exiting" >> "$STATE/auto-publish.log"; exit 0; }
exec >> "$STATE/auto-publish.log" 2>&1
log() { echo "$(date -Is) $*"; }

force=0; [ "${1:-}" = "--force" ] && force=1
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"

git -C "$SRC_REPO" fetch -q origin main --tags || { log "fetch failed"; exit 1; }
head_sha=$(git -C "$SRC_REPO" rev-parse origin/main)
last_sha=$(cat "$STATE/last-commit" 2>/dev/null || true)

# --- what is due -----------------------------------------------------------
do_intermediary=0
if [ "$force" = 1 ] || [ -z "$last_sha" ]; then
  do_intermediary=1
elif [ "$head_sha" != "$last_sha" ] && [ -n "$(git -C "$SRC_REPO" diff --name-only "$last_sha" "$head_sha" -- "${WATCH[@]}")" ]; then
  do_intermediary=1
fi

new_tag=""
if [ ! -f "$STATE/seen-tags" ]; then            # first run: record, never backfill
  git -C "$SRC_REPO" tag -l 'release-*' | sort > "$STATE/seen-tags"
else
  new_tag=$(git -C "$SRC_REPO" tag -l 'release-*' | sort | comm -13 "$STATE/seen-tags" - | tail -n 1)
fi

# a build that failed is not retried until something new lands (or --force), so a broken main does not rebuild every run
failed=$(cat "$STATE/failed" 2>/dev/null || true)
[ "$force" = 0 ] && [ "$failed" = "$head_sha" ] && do_intermediary=0
[ "$force" = 0 ] && [ "$failed" = "$new_tag" ] && new_tag=""

if [ "$do_intermediary" = 0 ] && [ -z "$new_tag" ]; then
  [ "$head_sha" != "$last_sha" ] && echo "$head_sha" > "$STATE/last-commit"   # irrelevant push: just advance
  exit 0
fi

# --- build tree --------------------------------------------------------------
if [ ! -d "$BUILD_TREE/.git" ] && [ ! -f "$BUILD_TREE/.git" ]; then
  git -C "$SRC_REPO" worktree add --detach "$BUILD_TREE" origin/main || { log "worktree add failed"; exit 1; }
fi

# build <ref> <remote-path> <commit-label>: build the signed release APK of <ref> and publish it
build_and_publish() {
  local ref="$1" remote="$2" label="$3"
  log "building $ref -> $remote"
  git -C "$BUILD_TREE" checkout -q -f --detach "$ref" || return 1
  local app="$BUILD_TREE/features/mobile-app/app" fe="$BUILD_TREE/frontend"
  local android="$app/android"
  # the gradle daemon and the kotlin compile daemon together hold ~4 GB of RAM
  # on the shared 16 GB coding VM; stop them after every build attempt (success
  # or failure) so they don't sit idle for hours until the next run.
  local build_java_home="${JAVA_HOME:-}"
  trap '(cd "$android" && JAVA_HOME="$build_java_home" ./gradlew --stop) >/dev/null 2>&1 || true; trap - RETURN' RETURN
  export VPT_APK_VERSION_CODE; VPT_APK_VERSION_CODE=$(git -C "$BUILD_TREE" rev-list --count HEAD) || return 1
  # git-ignored build inputs: signing key kept in $STATE, SDK path, download URL baked into the app
  cp "$STATE/keystore.properties" "$android/keystore.properties" || { log "missing $STATE/keystore.properties"; return 1; }
  mkdir -p "$android/keystore" && cp "$STATE/release.jks" "$android/keystore/release.jks" || return 1
  printf 'sdk.dir=%s\nvpt.apkUrl=%s\n' "$SDK" "$PUBLIC_APK_URL" > "$android/local.properties"
  # dependencies only when their lockfile changed
  local h
  h=$(cat "$fe/package-lock.json" "$app/package-lock.json" | sha256sum | cut -c1-16)
  if [ "$h" != "$(cat "$STATE/deps-hash" 2>/dev/null)" ] || [ ! -d "$fe/node_modules" ] || [ ! -d "$app/node_modules" ]; then
    (cd "$fe" && npm ci --no-audit --no-fund) && (cd "$app" && npm ci --no-audit --no-fund) || return 1
    echo "$h" > "$STATE/deps-hash"
  fi
  (cd "$app" && npm run build:web && npm run sync && npm run apk:release) || return 1
  # an old tag may predate publish-apk.sh (or its env overrides): always publish with the current one
  git -C "$SRC_REPO" show origin/main:features/mobile-app/app/scripts/publish-apk.sh > "$app/scripts/publish-apk.sh" || return 1
  ssh "$REMOTE_HOST" "mkdir -p '$(dirname "$REMOTE_DIR/$remote")'" || return 1
  (cd "$app" && VPT_APK_PUBLISH_TARGET="$REMOTE_HOST:$REMOTE_DIR/$remote" VPT_APK_COMMIT_LABEL="$label" bash scripts/publish-apk.sh) || return 1
  log "published $remote"
}

rc=0
if [ -n "$new_tag" ]; then
  if build_and_publish "refs/tags/$new_tag" "releases/vpt-mobile-app-$new_tag.apk" "$new_tag"; then
    echo "$new_tag" >> "$STATE/seen-tags"; sort -o "$STATE/seen-tags" "$STATE/seen-tags"
  else
    log "RELEASE BUILD FAILED for $new_tag (not retried until --force)"; echo "$new_tag" > "$STATE/failed"; rc=1
  fi
fi
if [ "$do_intermediary" = 1 ]; then
  if build_and_publish "$head_sha" "vpt-mobile-app-debug.apk" "main"; then
    echo "$head_sha" > "$STATE/last-commit"
  else
    log "INTERMEDIARY BUILD FAILED at $head_sha (not retried until main moves or --force)"; echo "$head_sha" > "$STATE/failed"; rc=1
  fi
fi
exit $rc
