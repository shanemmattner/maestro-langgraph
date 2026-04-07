#!/usr/bin/env bash
# Maestro Infrastructure — Watchdog
# Auto-stops the stack after IDLE_TIMEOUT seconds of inactivity.
# Reads ~/.cache/maestro/last_active (epoch timestamp) touched by core/services.py.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="${HOME:-$(eval echo ~)}"

IDLE_TIMEOUT="${MAESTRO_IDLE_TIMEOUT:-600}"   # 10 minutes default
POLL_INTERVAL=60
CACHE_DIR="$HOME/.cache/maestro"
PID_FILE="$CACHE_DIR/watchdog.pid"
LAST_ACTIVE_FILE="$CACHE_DIR/last_active"
LOG_FILE="$CACHE_DIR/watchdog.log"
INFRA_DIR="$(dirname "$0")"

mkdir -p "$CACHE_DIR"

# Logging
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Rotate log if over 1MB
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 1048576 ]; then
    tail -n 500 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# Write PID
echo $$ > "$PID_FILE"
log "Watchdog started (pid $$, idle_timeout=${IDLE_TIMEOUT}s)"

# Cleanup on exit
cleanup() {
    log "Watchdog stopping"
    rm -f "$PID_FILE"
}
trap cleanup EXIT SIGTERM SIGINT

# Escape hatch — disable without stopping watchdog
is_disabled() {
    [ -f "$CACHE_DIR/watchdog_disabled" ]
}

# Touch last_active if missing (first boot — don't immediately stop)
[ -f "$LAST_ACTIVE_FILE" ] || date +%s > "$LAST_ACTIVE_FILE"

# Grace period at startup — let Colima and Docker settle after login
log "Grace period: sleeping ${POLL_INTERVAL}s before first check"
sleep "$POLL_INTERVAL"

# Main loop
while true; do
    if is_disabled; then
        log "Watchdog disabled (sentinel file present), skipping"
        sleep "$POLL_INTERVAL"
        continue
    fi

    NOW=$(date +%s)
    LAST_ACTIVE=$(cat "$LAST_ACTIVE_FILE" 2>/dev/null || echo "$NOW")
    IDLE=$(( NOW - LAST_ACTIVE ))

    if [ "$IDLE" -ge "$IDLE_TIMEOUT" ]; then
        # Check if stack is actually running before trying to stop
        if docker compose -f "$INFRA_DIR/docker-compose.yml" ps --quiet 2>/dev/null | grep -q .; then
            log "Idle for ${IDLE}s (threshold ${IDLE_TIMEOUT}s) — stopping stack"
            docker compose -f "$INFRA_DIR/docker-compose.yml" down >> "$LOG_FILE" 2>&1 && \
                log "Stack stopped" || log "ERROR: docker compose down failed"
        else
            log "Idle for ${IDLE}s but stack already stopped"
        fi
    else
        REMAINING=$(( IDLE_TIMEOUT - IDLE ))
        log "Active (idle ${IDLE}s, will stop in ${REMAINING}s if no activity)"
    fi

    sleep "$POLL_INTERVAL"
done
