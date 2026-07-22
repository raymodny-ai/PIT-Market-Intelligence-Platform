# dev-start.ps1 — start PIT Market backend + frontend in background
# Usage:  .\scripts\dev-start.ps1
#
# Side effects:
#   - logs → .\logs\backend.log and .\logs\frontend.log
#   - PIDs → .\logs\backend.pid and .\logs\frontend.pid
#   - works in any PWD as long as the script sits in <repo>/scripts/

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# --- pre-clean: free target ports so we never hit "address in use" ---
function Free-Port {
  param([int]$Port)
  $pids = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($id in $pids) {
    Write-Host "  freeing port $Port (pid $id) ..." -ForegroundColor DarkYellow
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
  }
}
Free-Port 8000
Free-Port 3001
# Also clean up any stale pid files pointing at dead processes
foreach ($f in @("backend.pid","frontend.pid")) {
  $p = Join-Path $logDir $f
  if (Test-Path $p) {
    $id = [int](Get-Content $p -Raw).Trim()
    if ($id -gt 0 -and -not (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
      Remove-Item $p -Force
    }
  }
}

# --- env ---
$env:PYTHONPATH      = "src"
$env:PIT_CONFIG_DIR  = "config"
$env:GOLD_PANELS_DIR = "data\gold\pit_panels"
$env:PYTHONIOENCODING = "utf-8"
$env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8000"

# --- backend ---
$py = (Get-Command python).Source
$backendOutLog = Join-Path $logDir "backend.out.log"
$backendErrLog = Join-Path $logDir "backend.err.log"
$backendPidFile = Join-Path $logDir "backend.pid"

Write-Host "▶ starting backend (uvicorn :8000) ..." -ForegroundColor Cyan
$backendProc = Start-Process -FilePath $py `
  -ArgumentList @("-m","uvicorn","pit_market.api.main:app","--host","127.0.0.1","--port","8000","--log-level","info") `
  -RedirectStandardOutput $backendOutLog `
  -RedirectStandardError  $backendErrLog `
  -NoNewWindow -PassThru
$backendProc.Id | Out-File -FilePath $backendPidFile -Encoding ascii

# --- frontend ---
$feOutLog = Join-Path $logDir "frontend.out.log"
$feErrLog = Join-Path $logDir "frontend.err.log"
$fePidFile = Join-Path $logDir "frontend.pid"

# On Windows, `npm` resolves through npm.cmd; we explicitly use cmd.exe so
# Start-Process can find it without PATH gymnastics.
$npmCmd = (Get-Command "npm.cmd" -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) {
  # Fall back: locate node + run via node directly
  $nodeExe = (Get-Command "node" -ErrorAction SilentlyContinue).Source
  $npmPath = (Get-ChildItem -Path (Split-Path $nodeExe) -Filter "npm.cmd" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
  $npmCmd = $npmPath
}

Write-Host "▶ starting frontend (next dev :3001) ..." -ForegroundColor Cyan
$feProc = Start-Process -FilePath "cmd.exe" `
  -ArgumentList @("/c","cd /d `"$((Join-Path $RepoRoot 'frontend'))`" && npm run dev") `
  -RedirectStandardOutput $feOutLog `
  -RedirectStandardError  $feErrLog `
  -NoNewWindow -PassThru
$feProc.Id | Out-File -FilePath $fePidFile -Encoding ascii

# --- wait + smoke ---
Start-Sleep -Seconds 6
$backend = try { (Invoke-WebRequest "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 0 }
$frontend = try { (Invoke-WebRequest "http://127.0.0.1:3001/"      -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }

Write-Host ""
Write-Host "──────────────────────────────────────────" -ForegroundColor DarkGray
if ($backend -eq 200) {
  Write-Host "  backend  →  http://127.0.0.1:8000  (pid $($backendProc.Id))" -ForegroundColor Green
} else {
  Write-Host "  backend  →  NOT READY (check logs\backend.log)" -ForegroundColor Red
}
if ($frontend -eq 200) {
  Write-Host "  frontend →  http://127.0.0.1:3001  (pid $($feProc.Id))" -ForegroundColor Green
} else {
  Write-Host "  frontend →  NOT READY (check logs\frontend.log)" -ForegroundColor Red
}
Write-Host "──────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "stop:  .\scripts\dev-stop.ps1" -ForegroundColor Yellow
Write-Host "logs:  Get-Content logs\backend.log -Wait" -ForegroundColor Yellow
