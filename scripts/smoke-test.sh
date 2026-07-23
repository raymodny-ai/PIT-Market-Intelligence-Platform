#!/usr/bin/env bash
# =============================================================================
# PIT Market Intelligence Platform — Production Smoke Test (T-41)
# Checks all core endpoints return HTTP 200.
# Usage: bash scripts/smoke-test.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

API_BASE="${API_BASE:-http://localhost:8000}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:3000}"
PASS=0
FAIL=0

check() {
    local label="$1"
    local url="$2"
    local expected_code="${3:-200}"

    HTTP_CODE=$(curl -s -o /tmp/smoke_response.txt -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "$expected_code" ]; then
        echo -e "  ${GREEN}PASS${NC} $label ($HTTP_CODE)"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} $label (got $HTTP_CODE, expected $expected_code)"
        if [ -f /tmp/smoke_response.txt ]; then
            cat /tmp/smoke_response.txt
            echo
        fi
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Smoke Test ==="
echo "API: $API_BASE"
echo "Frontend: $FRONTEND_BASE"
echo ""

# API health check
check "API /health" "$API_BASE/health"

# PIT panels list
check "API /api/v1/panels" "$API_BASE/api/v1/panels"

# Frontend prod page
check "Frontend /" "$FRONTEND_BASE"

# OpenAPI Swagger UI
check "API /docs (Swagger)" "$API_BASE/docs"

# OpenAPI JSON schema
check "API /openapi.json" "$API_BASE/openapi.json"

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Smoke test FAILED${NC}"
    exit 1
fi

echo -e "${GREEN}Smoke test PASSED${NC}"
