#!/usr/bin/env bash
# =============================================================================
# PIT Market Intelligence Platform — Local CI Pipeline (T-41)
# Usage: bash scripts/ci-local.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_step() { echo -e "\n${GREEN}=== $1 ===${NC}"; }
log_fail() { echo -e "${RED}FAIL: $1${NC}"; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Step 1: Build images (no-cache for clean build)
log_step "Step 1/6: docker compose build --no-cache"
docker compose build --no-cache || log_fail "docker compose build"

# Step 2: Run Python tests inside container
log_step "Step 2/6: Python tests (pytest)"
docker compose run --rm pit-api pytest tests/ -x -q || log_fail "pytest"

# Step 3: Next.js production build
log_step "Step 3/6: Frontend build (next build)"
docker compose run --rm pit-api bash -c "cd /opt/pit/frontend && npm ci && npm run build" || log_fail "next build"

# Step 4: Start all services
log_step "Step 4/6: docker compose up -d"
docker compose up -d || log_fail "docker compose up"

# Wait for services to become healthy
echo "Waiting for services to start..."
sleep 15

# Step 5: Smoke test
log_step "Step 5/6: Smoke test"
bash scripts/smoke-test.sh || log_fail "smoke test"

# Step 6: Cleanup
log_step "Step 6/6: Cleanup (docker compose down)"
docker compose down

echo -e "\n${GREEN}=== CI Pipeline PASSED ===${NC}"
