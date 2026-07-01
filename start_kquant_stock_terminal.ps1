param(
  [int]$Port = 8001,
  [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Starting KQUANT US Stock Signal Terminal..." -ForegroundColor Cyan
Write-Host "URL: http://$HostName`:$Port/" -ForegroundColor Green
Write-Host "Database: work/kquant_us.sqlite3" -ForegroundColor DarkGray
Write-Host "Mode: read-only stock research" -ForegroundColor DarkGray
if ($env:OPENAI_API_KEY) {
  Write-Host "AI Review: enabled from backend environment" -ForegroundColor Green
} else {
  Write-Host "AI Review: missing OPENAI_API_KEY (manual review button will show setup guidance)" -ForegroundColor Yellow
}

python -m btc_eth_15m.dashboard.stdlib_server --host $HostName --port $Port
