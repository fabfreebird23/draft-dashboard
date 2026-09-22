#!/bin/bash
# Build and install Bloody Sunday on the phone.
#
#   ./build.sh          debug APK into app/build/outputs/apk/debug/
#   ./build.sh install  the same, then adb install onto the attached device
#
# The JDK is the one the other Android projects here use; Gradle finds the SDK
# from ANDROID_HOME. Nothing about the dashboard is bundled — the app is a shell
# around the Cloud copy, so a change to the dashboard needs no rebuild at all.
set -euo pipefail
cd "$(dirname "$0")"
export JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}
export ANDROID_HOME=${ANDROID_HOME:-$HOME/Library/Android/sdk}
gradle --quiet assembleDebug
APK=app/build/outputs/apk/debug/app-debug.apk
echo "built $APK"
if [ "${1:-}" = "install" ]; then
  adb install -r "$APK"
  adb shell monkey -p com.brandonclifton.bloodysunday -c android.intent.category.LAUNCHER 1 >/dev/null
  echo "installed and launched"
fi
