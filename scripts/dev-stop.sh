#!/usr/bin/env bash
# dev-stop.sh — stop PIT Market backend + frontend (Linux/NAS)
#
# Usage:  bash scripts/dev-stop.sh
#
# Reads PIDs from ./logs/backend.pid and ./logs/frontend.pid (set by dev-start.sh).
# Also frees ports 8700/8701 if stale processes are bound to them.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="$REPO_ROOT/logs"

stop_pid() {
  local label="$1"
  local pid_file="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file" | tr -d '[:space:]')
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      echo "▶ stopping $label (pid $pid) ..."
      kill "$pid" 2>/dev/null || true
      # Wait up to 5s for graceful shutdown
      for i in {1..5}; do
        sleep 1
        kill -0 "$pid" 2>/dev/null || break
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "  forcing $label (pid $pid) ..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      echo "  $label: pid $pid not running"
    fi
    rm -f "$pid_file"
  else
    echo "  $label: no pid file at $pid_file"
  fi
}

stop_pid "backend"  "$LOG_DIR/backend.pid"
stop_pid "frontend" "$LOG_DIR/frontend.pid"

# Belt-and-suspenders: free the default ports in case stale processes linger.
API_PORT="${PIT_API_PORT:-8700}"
FE_PORT="${PIT_FE_PORT:-8701}"
free_port() {
  local port="$1"
  local pids
  pids=$(ss -tlnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $0}' | grep -oP 'pid=\K[0-9]+' | sort -u || true)
  for pid in $pids; do
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      echo "  freeing stale port $port (pid $pid) ..."
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}
free_port "$API_PORT"
free_port "$FE_PORT"

echo "--- done ---"