#!/usr/bin/env bash
# Start both launchers in the background.
set -e
cd "$(dirname "$0")"

# virtual display for the browser
if ! pgrep -x Xvfb >/dev/null; then
  Xvfb :99 -screen 0 1280x1024x24 >/dev/null 2>&1 &
fi

mkdir -p logs
python3 mobile-launcher/server.py 9091 > logs/mobile.log 2>&1 &
MOBILE_PID=$!
python3 profile-launcher/server.py 9090 > logs/profile.log 2>&1 &
PANEL_PID=$!
echo "profile panel:  http://0.0.0.0:9090 (pid $PANEL_PID)"
echo "mobile launcher: http://0.0.0.0:9091 (pid $MOBILE_PID)"
wait
