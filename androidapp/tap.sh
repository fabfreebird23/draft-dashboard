#!/bin/bash
# Tap the phone ONLY if Bloody Sunday is the app in front.
# An adb tap goes wherever the screen is; if he has switched to another app,
# the tap lands in THAT app. So every tap checks what's in front first:
# the focused window, or — when focus reads null (it does between frames on
# this Pixel) — the top resumed activity. Anything else refuses.
set -u
focus=$(adb shell dumpsys window | grep -m1 mCurrentFocus)
case "$focus" in
  *com.brandonclifton.bloodysunday*) adb shell input tap "$1" "$2"; exit 0 ;;
  *=null*)
    top=$(adb shell dumpsys activity activities | grep -m1 topResumedActivity)
    case "$top" in
      *com.brandonclifton.bloodysunday*) adb shell input tap "$1" "$2"; exit 0 ;;
    esac ;;
esac
echo "REFUSED: not our app in front -> $focus" >&2; exit 3
