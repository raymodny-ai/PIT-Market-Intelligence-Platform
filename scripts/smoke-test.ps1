# =============================================================================
# PIT Market Intelligence Platform — Smoke Test (T-41, Windows PowerShell)
# Usage: .\scripts\smoke-test.ps1
# =============================================================================

$API_BASE = if ($env:API_BASE) { $env:API_BASE } else { "http://localhost:8000" }
$FRONTEND_BASE = if ($env:FRONTEND_BASE) { $env:FRONTEND_BASE } else { "http://localhost:3000" }
$pass = 0
$fail = 0

function Check-Endpoint($label, $url, $expected = 200) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        $code = $response.StatusCode
    } catch {
        $code = 0
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
        }
    }
    if ($code -eq $expected) {
        Write-Host "  PASS $label ($code)" -ForegroundColor Green
        $script:pass++
    } else {
        Write-Host "  FAIL $label (got $code, expected $expected)" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "=== Smoke Test ==="
Write-Host "API: $API_BASE"
Write-Host "Frontend: $FRONTEND_BASE"
Write-Host ""

Check-Endpoint "API /health" "$API_BASE/health"
Check-Endpoint "API /api/v1/panels" "$API_BASE/api/v1/panels"
Check-Endpoint "Frontend /" "$FRONTEND_BASE"
Check-Endpoint "API /docs (Swagger)" "$API_BASE/docs"
Check-Endpoint "API /openapi.json" "$API_BASE/openapi.json"

Write-Host ""
Write-Host "Results: $pass passed, $fail failed"

if ($fail -gt 0) {
    Write-Host "Smoke test FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "Smoke test PASSED" -ForegroundColor Green
