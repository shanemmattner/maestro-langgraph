#!/usr/bin/env bash
# Maestro Infrastructure — Start (idempotent)
# Starts Langfuse + Grafana + Prometheus stack if not already running.
set -euo pipefail

cd "$(dirname "$0")"

# Source .env if present
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# Ensure Docker daemon is running
if ! docker info &>/dev/null; then
    # Try Colima first, then Docker Desktop
    if command -v colima &>/dev/null; then
        if ! colima status 2>/dev/null | grep -q "Running"; then
            echo "Starting Colima..."
            colima start
        fi
    elif [ -d "/Applications/Docker.app" ]; then
        echo "Starting Docker Desktop..."
        open -a Docker
        sleep 10
    fi

    if ! docker info &>/dev/null; then
        echo "ERROR: Docker daemon not reachable."
        echo "Run './infrastructure/setup.sh' to install Docker, or start it manually."
        exit 1
    fi
fi

# Idempotency — skip if Langfuse already healthy
LANGFUSE_PORT="${LANGFUSE_PORT:-3100}"
if curl -sf "http://localhost:${LANGFUSE_PORT}/api/public/health" &>/dev/null; then
    echo "Langfuse already running."
    exit 0
fi

# Determine compose command
if docker compose version &>/dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found."
    exit 1
fi

# Check port conflicts
for port in 3100 3200 5432 8123 9000 9090 9091; do
    if lsof -i :"$port" &>/dev/null; then
        echo "WARNING: Port $port already in use"
    fi
done

echo "Starting infrastructure..."
$COMPOSE up -d

# Wait for Langfuse (up to 120s — ClickHouse can be slow on cold start)
echo -n "Waiting for Langfuse..."
for i in $(seq 1 60); do
    if curl -sf "http://localhost:${LANGFUSE_PORT}/api/public/health" &>/dev/null; then
        echo " ready"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo " TIMEOUT"
        echo "ERROR: Langfuse did not become healthy in 120s"
        exit 1
    fi
    sleep 2
    echo -n "."
done

# Wait for Grafana
echo -n "Waiting for Grafana..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${GRAFANA_PORT:-3200}/api/health" &>/dev/null; then
        echo " ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo " (timeout — Grafana may still be starting)"
        break
    fi
    sleep 2
    echo -n "."
done

echo ""
echo "┌──────────────┬───────────────────────────┐"
echo "│ Service      │ URL                       │"
echo "├──────────────┼───────────────────────────┤"
printf "│ Langfuse     │ http://localhost:%-8s │\n" "${LANGFUSE_PORT:-3100}"
printf "│ Grafana      │ http://localhost:%-8s │\n" "${GRAFANA_PORT:-3200}"
echo "│ Prometheus   │ http://localhost:9091      │"
echo "│ ClickHouse   │ http://localhost:8123      │"
echo "└──────────────┴───────────────────────────┘"
