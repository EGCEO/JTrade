#!/bin/sh
set -e
cd /app

# Launch the trading bot in the background; capture all output to a log file.
# The bot prompts an interactive menu (input()); in a non-interactive container
# stdin is closed and input() raises EOFError, crashing the process. Feed it a
# menu choice (2 = auto trade) and keep stdin open with `tail -f /dev/null` so any
# later prompt blocks instead of hitting EOF.
(echo 2; tail -f /dev/null) | python3 run.py > /tmp/bot.log 2>&1 &
echo $! > /tmp/bot.pid
echo "Bot started (pid $(cat /tmp/bot.pid))"

# Run the status page in the foreground so the container stays alive and
# serves the preview on port 3000.
exec python3 /app/status_server.py
