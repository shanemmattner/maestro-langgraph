#!/usr/bin/env bash
# Maestro Infrastructure — Stop
# Stops the Langfuse observability stack. Data volumes are preserved.
set -euo pipefail

cd "$(dirname "$0")"

# Kill watchdog first so it doesn't restart the stack
PID_FILE="$HOME/.cache/maestro/watchdog.pid"
if [ -f "$PID_FILE" ]; then
    WPID=$(cat "$PID_FILE")
    if kill -0 "$WPID" 2>/dev/null; then
        kill "$WPID" && echo "Watchdog stopped (pid $WPID)"
    fi
    rm -f "$PID_FILE"
fi

echo "Stopping infrastructure..."
docker compose down
echo "Done. Data volumes preserved."
