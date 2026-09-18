#!/bin/bash
# Build BloodySunday.app and install it into ~/Applications.
#
# Its own venv, and not the repo's: the dashboard runs on the system 3.9 and
# py2app wants a framework build, so the wrapper is packaged with Homebrew's
# 3.12 (what Sportsbot is built with). The two never meet — the bundle only
# ever shells out to the repo's interpreter.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PY:-/opt/homebrew/bin/python3.12}
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit py2app

[ -f BloodySunday.icns ] || ./.venv/bin/python make_icon.py

rm -rf build dist
./.venv/bin/python setup.py py2app >/dev/null

# py2app names the bundle after CFBundleName, so glob rather than guess.
BUILT=$(ls -d dist/*.app | head -1)
DEST="$HOME/Applications/$(basename "$BUILT")"
rm -rf "$DEST"
cp -R "$BUILT" "$DEST"
# Nothing we build locally is quarantined, but a stale signature from a previous
# build makes launchd refuse the new one.
codesign --force --deep --sign - "$DEST" 2>/dev/null || true
# The server itself runs under launchd, not under the app: keeping it warm all
# day is what makes the window open in a second instead of thirty, and it means
# quitting the app does not throw away the boards it just built.
AGENT="com.brandonclifton.bloodysunday-server"
PL="$HOME/Library/LaunchAgents/$AGENT.plist"
sed "s|__HOME__|$HOME|g" "$AGENT.plist" > "$PL"
# bootout is asynchronous, so a bootstrap right behind it fails with "Input/output
# error" while the old job is still on its way out. Wait for it to go, and if it
# is already loaded and healthy just restart it in place.
launchctl bootout "gui/$UID/$AGENT" 2>/dev/null || true
for _ in $(seq 1 20); do
  launchctl print "gui/$UID/$AGENT" >/dev/null 2>&1 || break
  sleep 0.5
done
launchctl bootstrap "gui/$UID" "$PL" 2>/dev/null \
  || launchctl kickstart -k "gui/$UID/$AGENT"
echo "installed $DEST"
echo "server agent loaded ($AGENT)"
