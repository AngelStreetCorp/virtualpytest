#!/usr/bin/env bash
# Publish the signed release APK built by apk-release.sh, with the `<apk>.json` sidecar the download page and the
# installed app's update check both read. The APK goes up first, so the sidecar never advertises
# a file that is not there yet. Release, not debug: phones run the release-signed build, and
# Android refuses to update an app with one signed by a different key ("package conflicts with
# an existing package").
# Target: `vpt.apkPublishTarget` in android/local.properties (git-ignored), an scp destination
# for the APK file itself, e.g. myhost:downloads/vpt-mobile-app-debug.apk — the file `vpt.apkUrl`
# serves.
set -euo pipefail
cd "$(dirname "$0")/../android"
target="${VPT_APK_PUBLISH_TARGET:-}"   # env override (auto-publish.sh uses it for releases/)
[ -n "$target" ] || target=$(sed -n 's/^vpt\.apkPublishTarget=//p' local.properties 2>/dev/null || true)
if [ -z "$target" ]; then
  echo "Set vpt.apkPublishTarget=<scp destination of the .apk> in android/local.properties." >&2
  exit 1
fi
apk=app/build/outputs/apk/release/app-release.apk
[ -f "$apk" ] || { echo "No $apk — run npm run apk:release first." >&2; exit 1; }
meta=app/build/outputs/apk/release/output-metadata.json
version=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['elements'][0]['versionName'])" "$meta")
code=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['elements'][0]['versionCode'])" "$meta")
size=$(wc -c < "$apk" | tr -d ' ')
commit="${VPT_APK_COMMIT_LABEL:-$(git rev-parse --abbrev-ref HEAD)}@$(git rev-parse --short=12 HEAD)"
sidecar=$(mktemp)
trap 'rm -f "$sidecar"' EXIT
printf '{"version":"%s","version_code":%s,"built":"%s","size_bytes":%s,"commit":"%s"}\n' \
  "$version" "$code" "$(date +%F)" "$size" "$commit" > "$sidecar"
scp "$apk" "$target"
scp "$sidecar" "$target.json"
echo "Published v$version ($code) to $target"
cat "$sidecar"
