#!/usr/bin/env bash
# cron-watchdog-docker.sh — PIT Market Intelligence Docker stack watchdog.
#
# Health-checks the docker-compose dev stack (pit-api + pit-web on 8700/8701).
# On failure: `docker compose up -d` brings the stack back. Pushes Telegram
# alerts on state changes. Designed to run from OpenClaw cron every 5 min.
#
# Companion to cron-watchdog.sh (which handles the native dev profile via
# dev-start.sh). Use this script when the project is running under Docker.
#
# OpenClaw cron payload:
#   kind=agentTurn, message="Run this bash script and exit. Reply with
#   ONLY: NO_REPLY", toolsAllow=[exec]

set -uo pipefail

REPO_ROOT="/vol1/@apphome/trim.openclaw/data/workspace/PIT-Market-Intelligence-Platform"
COMPOSE_FILE="$REPO_ROOT/docker-compose.dev.yml"
API_PORT=8700
FE_PORT=8701
LOG_DIR="$REPO_ROOT/logs"
WATCHDOG_LOG="$LOG_DIR/watchdog-docker.log"

mkdir -p "$LOG_DIR"
TS() { date "+%Y-%m-%d %H:%M:%S%z"; }
log() { echo "[$(TS)] $*" >> "$WATCHDOG_LOG"; }

api_ok() { curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/health" > /dev/null 2>&1; }
fe_ok()  { curl -fsS -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${FE_PORT}/" 2>/dev/null | grep -q "^200$"; }

# Send a Telegram message via the OpenClaw-managed bot token.
tg_send() {
  local text="$1"
  local config="$HOME/.openclaw/openclaw.json"
  [[ -f "$config" ]] || return 0
  local token chat
  token=$(python3 -c "
import json
with open('$config') as f: cfg = json.load(f)
print(cfg.get('channels', {}).get('telegram', {}).get('botToken', ''))
" 2>/dev/null)
  chat=$(python3 -c "
import json
with open('$config') as f: cfg = json.load(f)
print(cfg.get('channels', {}).get('telegram', {}).get('defaultChatId', ''))
" 2>/dev/null)
  [[ -z "$token" || -z "$chat" ]] && return 0
  curl -fsS -m 5 -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    --data-urlencode "chat_id=${chat}" \
    --data-urlencode "text=${text}" > /dev/null 2>&1 || true
}

ACTION=""
if api_ok; then
  log "OK   backend :${API_PORT} 200"
else
  log "FAIL backend :${API_PORT}"
  tg_send "⚠️ PIT backend (:${API_PORT}) down — restarting Docker stack"
  ACTION="restart"
fi
if fe_ok; then
  log "OK   frontend :${FE_PORT} 200"
else
  log "FAIL frontend :${FE_PORT}"
  tg_send "⚠️ PIT frontend (:${FE_PORT}) down — restarting Docker stack"
  ACTION="restart"
fi

if [[ -n "$ACTION" ]]; then
  log "ACTION ${ACTION} — docker compose up -d"
  sg docker -c "docker compose -f '$COMPOSE_FILE' up -d" >> "$WATCHDOG_LOG" 2>&1
  rc=$?
  log "RESTART exit_code=${rc}"
  sleep 6
  if api_ok && fe_ok; then
    log "RECOVERED both services healthy after restart"
    tg_send "✅ PIT services recovered (backend :${API_PORT}, frontend :${FE_PORT})"
  else
    log "STILL_DOWN after restart — manual intervention needed"
    tg_send "🚨 PIT services STILL DOWN after watchdog restart — check logs at ${WATCHDOG_LOG}"
  fi
fi

# 14-day log rotation
find "$LOG_DIR" -maxdepth 1 -name "watchdog-docker.log" -mtime +14 -delete 2>/dev/null || true