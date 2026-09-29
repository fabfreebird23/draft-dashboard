#!/bin/bash
# Tap the phone ONLY if Bloody Sunday is the app in front.
# An adb tap goes wherever the screen is; if he has switched to another app,
# the tap lands in THAT app. So every tap checks the focused window first.
set -u
focus=$(adb shell dumpsys window | grep -m1 mCurrentFocus)
case "$focus" in
  *com.brandonclifton.bloodysunday*) adb shell input tap "$1" "$2" ;;
  *) echo "REFUSED: not our app in front -> $focus" >&2; exit 3 ;;
esac
