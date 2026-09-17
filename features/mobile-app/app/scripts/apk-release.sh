#!/usr/bin/env bash
# Build the SIGNED release APK (TASK-19 P1 #6) with a JDK 21, whatever the machine's default
# `java` is. Same JDK resolution as apk.sh. Requires android/keystore.properties (git-ignored) -
# without it, build.gradle's `release` signingConfig is never assigned and this produces an
# unsigned, uninstallable app-release-unsigned.apk instead of failing loudly, so check for it
# here and fail fast with a clear message.
set -euo pipefail
cd "$(dirname "$0")/../android"

if [ ! -f keystore.properties ]; then
  echo "keystore.properties not found in $(pwd)." >&2
  echo "Generate a keystore first, e.g.:" >&2
  echo "  keytool -genkeypair -v -keystore keystore/release.jks -alias vpt-mobile-app \\" >&2
  echo "    -keyalg RSA -keysize 2048 -validity 10000" >&2
  echo "then write keystore.properties (storeFile/storePassword/keyAlias/keyPassword) - see" >&2
  echo "features/mobile-app/README.md." >&2
  exit 1
fi

jdk="${VPT_ANDROID_JDK:-}"
if [ -z "$jdk" ]; then
  for d in "$HOME"/.jdks/jdk-21*; do
    [ -d "$d" ] || continue
    jdk="$d"; [ -d "$d/Contents/Home" ] && jdk="$d/Contents/Home"; break
  done
fi
jdk="${jdk:-${JAVA_HOME:-}}"
if [ -z "$jdk" ] || [ ! -x "$jdk/bin/java" ]; then
  echo "No JDK 21 found. Set VPT_ANDROID_JDK=<jdk home> or install Temurin 21 under ~/.jdks (see README)." >&2
  exit 1
fi
echo "Using JDK: $jdk"
exec ./gradlew -Dorg.gradle.java.home="$jdk" assembleRelease "$@"
