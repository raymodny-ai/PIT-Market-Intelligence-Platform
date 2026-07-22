# dev-stop.ps1 — stop background dev processes started by dev-start.ps1
# Usage:  .\scripts\dev-stop.ps1

$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $RepoRoot "logs"

$pidFiles = @("backend.pid", "frontend.pid")
foreach ($f in $pidFiles) {
  $p = Join-Path $logDir $f
  if (Test-Path $p) {
    $id = [int](Get-Content $p -Raw).Trim()
    if ($id -gt 0) {
      Write-Host "▶ stopping pid $id ($f) ..." -ForegroundColor Yellow
      try {
        Stop-Process -Id $id -Force -ErrorAction Stop
        Write-Host "  ✓ stopped" -ForegroundColor Green
      } catch {
        Write-Host "  already gone: $_" -ForegroundColor DarkYellow
      }
    }
    Remove-Item $p -Force
  }
}

# Catch-all: any straggler uvicorn / next dev processes
Get-Process -Name "uvicorn","node" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.MainWindowTitle -eq "" -and
    ($_.Path -like "*Python312*" -or $_.Path -like "*nodejs*")
  } |
  ForEach-Object {
    Write-Host "▶ cleaning pid $($_.Id) ($($_.ProcessName))" -ForegroundColor Yellow
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
  }

Write-Host "done." -ForegroundColor Green
