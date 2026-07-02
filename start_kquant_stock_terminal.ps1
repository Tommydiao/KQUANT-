param(
  [int]$Port = 8001,
  [string]$HostName = "127.0.0.1",
  [switch]$KillExisting,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Import-LocalEnv {
  param([string]$Path)
  if (-not (Test-Path $Path)) {
    return
  }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
      return
    }
    $name, $value = $line.Split("=", 2)
    $name = $name.Trim()
    $value = $value.Trim().Trim('"').Trim("'")
    if ($name -and $value -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

Import-LocalEnv (Join-Path $Root ".env")

$Url = "http://$HostName`:$Port/"
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
  $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($KillExisting) {
    foreach ($listenerPid in $pids) {
      Write-Host "Stopping existing KQUANT listener on port $Port (PID $listenerPid)..." -ForegroundColor Yellow
      Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 700
  } else {
    Write-Host "KQUANT appears to already be running on $Url" -ForegroundColor Green
    Write-Host "Use -KillExisting if you need to restart after code or API key changes." -ForegroundColor DarkGray
    if (-not $NoBrowser) {
      Start-Process $Url
    }
    exit 0
  }
}

Write-Host "Starting KQUANT US Stock Signal Terminal..." -ForegroundColor Cyan
Write-Host "URL: $Url" -ForegroundColor Green
Write-Host "Database: work/kquant_us.sqlite3" -ForegroundColor DarkGray
Write-Host "Mode: read-only stock research" -ForegroundColor DarkGray
if ($env:OPENAI_API_KEY) {
  Write-Host "AI Review: enabled from backend environment" -ForegroundColor Green
  $researchModel = if ($env:KQUANT_AI_RESEARCH_MODEL) { $env:KQUANT_AI_RESEARCH_MODEL } elseif ($env:KQUANT_AI_DEEP_MODEL) { $env:KQUANT_AI_DEEP_MODEL } else { "gpt-5.5-pro" }
  Write-Host "Deep Research Chat: $researchModel" -ForegroundColor Green
} else {
  Write-Host "AI Review: missing OPENAI_API_KEY (manual review button will show setup guidance)" -ForegroundColor Yellow
}

if (-not $NoBrowser) {
  Start-Process $Url
}

python -m btc_eth_15m.dashboard.stdlib_server --host $HostName --port $Port
