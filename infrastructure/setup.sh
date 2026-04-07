#!/usr/bin/env bash
# Backwards-compat wrapper — delegates to start.sh
exec "$(dirname "$0")/start.sh" "$@"
