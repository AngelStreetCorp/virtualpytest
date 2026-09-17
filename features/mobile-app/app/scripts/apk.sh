#!/usr/bin/env bash
# Build the debug APK with a JDK 21, whatever the machine's default `java` is.
# Resolution order: $VPT_ANDROID_JDK, first ~/.jdks/jdk-21*, then $JAVA_HOME.
# The JDK is passed as -Dorg.gradle.java.home because a global ~/.gradle/gradle.properties
# (common with Android Studio) picks the daemon JVM before the project file is read.
set -euo pipefail
cd "$(dirname "$0")/../android"
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
exec ./gradlew -Dorg.gradle.java.home="$jdk" assembleDebug "$@"
