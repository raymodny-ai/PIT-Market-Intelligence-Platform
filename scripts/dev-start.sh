#!/usr/bin/env bash
# dev-start.sh — start PIT Market backend + frontend in background (Linux/NAS)
#
# Usage:  bash scripts/dev-start.sh
#
# Side effects:
#   - logs  → ./logs/backend.out.log and ./logs/frontend.out.log
#   - PIDs  → ./logs/backend.pid  and ./logs/frontend.pid
#   - default ports: backend 8700, frontend 8701 (override with PIT_API_PORT/PIT_FE_PORT env)
#
# Stop:   bash scripts/dev-stop.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

API_PORT="${PIT_API_PORT:-8700}"
FE_PORT="${PIT_FE_PORT:-8701}"

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

export PATH="/vol1/@apphome/trim.openclaw/data/home/.local/bin:$PATH"
export PYTHONPATH="src"
export PIT_CONFIG_DIR="config"
export PIT_MARKET_DATA="./data"
export GOLD_PANELS_DIR="./data/gold/pit_panels"
export PIT_MARKET_CACHE_BACKEND="${PIT_MARKET_CACHE_BACKEND:-cachetools}"
export PYTHONIOENCODING="utf-8"
export NEXT_PUBLIC_API_BASE="http://127.0.0.1:${API_PORT}"

# --- free target ports if already in use ---
free_port() {
  local port="$1"
  local pids
  pids=$(ss -tlnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $0}' | grep -oP 'pid=\K[0-9]+' | sort -u || true)
  for pid in $pids; do
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      echo "  freeing port $port (pid $pid) ..." >&2
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

echo "--- pre-clean ports ---"
free_port "$API_PORT"
free_port "$FE_PORT"

# --- backend ---
if [[ ! -d .venv ]]; then
  echo "ERROR: .venv not found. Run: uv venv --python 3.12 .venv && uv pip install -e '.[dev,etl,llm,research]'" >&2
  exit 2
fi

echo "▶ starting backend (uvicorn :${API_PORT}) ..."
nohup .venv/bin/python -m uvicorn pit_market.api.main:app \
  --host 0.0.0.0 --port "$API_PORT" --log-level info \
  > "$LOG_DIR/backend.out.log" 2>&1 &
echo $! > "$LOG_DIR/backend.pid"

# --- frontend ---
if [[ ! -d frontend/node_modules ]]; then
  echo "▶ installing frontend deps (first run) ..."
  (cd frontend && npm install --no-audit --no-fund)
fi

echo "▶ starting frontend (next dev :${FE_PORT}) ..."
(cd frontend && nohup npx next dev -p "$FE_PORT" > "$LOG_DIR/frontend.out.log" 2>&1 &)
echo $! > "$LOG_DIR/frontend.pid"

# --- wait + smoke ---
echo "--- waiting for services to be ready ---"
for i in {1..15}; do
  sleep 1
  api_ok=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${API_PORT}/health" 2>/dev/null || echo "000")
  fe_ok=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${FE_PORT}/" 2>/dev/null || echo "000")
  [[ "$api_ok" == "200" && "$fe_ok" == "200" ]] && break
done

echo ""
echo "──────────────────────────────────────────"
if [[ "$api_ok" == "200" ]]; then
  echo "  backend  →  http://127.0.0.1:${API_PORT}  (pid $(cat "$LOG_DIR/backend.pid"))"
else
  echo "  backend  →  NOT READY (check $LOG_DIR/backend.out.log)"
fi
if [[ "$fe_ok" == "200" ]]; then
  echo "  frontend →  http://127.0.0.1:${FE_PORT}  (pid $(cat "$LOG_DIR/frontend.pid"))"
else
  echo "  frontend →  NOT READY (check $LOG_DIR/frontend.out.log)"
fi
echo "──────────────────────────────────────────"
echo "stop:  bash scripts/dev-stop.sh"
echo "logs:  tail -f $LOG_DIR/backend.out.log"