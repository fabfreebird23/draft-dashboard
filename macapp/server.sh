#!/bin/bash
# The dashboard server, kept warm by launchd so the app window opens onto a
# process that has already built this week's boards (a cold first click cost
# 6–12s; a warm one is under a second). The Mac app attaches to this when it
# is running and starts its own only when it is not.
set -euo pipefail
DIR="${BLOODY_SUNDAY_DIR:-$HOME/draft-dashboard}"
cd "$DIR"
export PYTHONUTF8=1 LANG=en_US.UTF-8 DRAFTROOM_WARM=1
exec "$DIR/.venv/bin/python" -m streamlit run app.py \
  --server.port "${BLOODY_SUNDAY_PORT:-8599}" --server.address 127.0.0.1 \
  --server.headless true --server.fileWatcherType none \
  --browser.gatherUsageStats false
