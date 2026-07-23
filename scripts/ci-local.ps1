# =============================================================================
# PIT Market Intelligence Platform — Local CI Pipeline (T-41, Windows PowerShell)
# Usage: .\scripts\ci-local.ps1
# =============================================================================
$ErrorActionPreference = "Stop"

$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $PROJECT_ROOT

function Log-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Green }
function Log-Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }

# Step 1: Build images
Log-Step "Step 1/6: docker compose build --no-cache"
docker compose build --no-cache
if ($LASTEXITCODE -ne 0) { Log-Fail "docker compose build" }

# Step 2: Python tests
Log-Step "Step 2/6: Python tests (pytest)"
docker compose run --rm pit-api pytest tests/ -x -q
if ($LASTEXITCODE -ne 0) { Log-Fail "pytest" }

# Step 3: Frontend build
Log-Step "Step 3/6: Frontend build (next build)"
docker compose run --rm pit-api bash -c "cd /opt/pit/frontend && npm ci && npm run build"
if ($LASTEXITCODE -ne 0) { Log-Fail "next build" }

# Step 4: Start services
Log-Step "Step 4/6: docker compose up -d"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Log-Fail "docker compose up" }

Write-Host "Waiting for services to start..."
Start-Sleep -Seconds 15

# Step 5: Smoke test
Log-Step "Step 5/6: Smoke test"
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
if ($LASTEXITCODE -ne 0) { Log-Fail "smoke test" }

# Step 6: Cleanup
Log-Step "Step 6/6: Cleanup"
docker compose down

Write-Host "`n=== CI Pipeline PASSED ===" -ForegroundColor Green
