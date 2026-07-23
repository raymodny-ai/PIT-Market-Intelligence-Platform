#!/usr/bin/env bash
# =============================================================================
# PIT Market Intelligence Platform — Pre-commit Hook (T-42)
# Quick checks (< 60s): ruff, mypy, eslint, pytest
# Install: bash scripts/install-pre-commit.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Pre-commit checks ==="

# 1. Python lint
echo -n "ruff check src/... "
if python -m ruff check src/ --quiet 2>/dev/null; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    python -m ruff check src/
    exit 1
fi

# 2. Type check
echo -n "mypy src/pit_market/... "
if python -m mypy src/pit_market/ --ignore-missing-imports --quiet 2>/dev/null; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    python -m mypy src/pit_market/ --ignore-missing-imports
    exit 1
fi

# 3. ESLint (frontend)
echo -n "eslint frontend/... "
if (cd frontend && npm run lint --silent 2>/dev/null); then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    (cd frontend && npm run lint)
    exit 1
fi

# 4. Python unit tests (quick, timeout 30s)
echo -n "pytest tests/backend/ -x -q... "
if python -m pytest tests/backend/ -x -q 2>/dev/null; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    python -m pytest tests/backend/ -x -q
    exit 1
fi

echo -e "\n${GREEN}All pre-commit checks passed${NC}"
