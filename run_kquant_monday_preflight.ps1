param(
  [int]$Port = 8001,
  [string]$HostName = "127.0.0.1",
  [string]$Universe = "default",
  [int]$AiLimit = 40,
  [int]$TopN = 8,
  [switch]$SkipAiDaily,
  [switch]$RestartBackend,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$DashboardUrl = "http://$HostName`:$Port"
$StartScript = Join-Path $Root "start_kquant_stock_terminal.ps1"
$ReadinessScript = Join-Path $Root "check_kquant_monday_pilot.ps1"

function Invoke-KquantJson {
  param(
    [string]$Path,
    [string]$Method = "GET",
    [object]$Body = $null,
    [int]$TimeoutSec = 90
  )

  $uri = "$DashboardUrl$Path"
  if ($Method -eq "POST") {
    $jsonBody = if ($null -eq $Body) { "{}" } else { $Body | ConvertTo-Json -Depth 8 }
    $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $uri -ContentType "application/json" -Body $jsonBody -TimeoutSec $TimeoutSec
  } else {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec $TimeoutSec
  }
  if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
    throw "HTTP $($response.StatusCode) for $Path"
  }
  return $response.Content | ConvertFrom-Json
}

function Test-KquantOnline {
  try {
    $health = Invoke-KquantJson "/api/health" -TimeoutSec 5
    return ($health.status -eq "online")
  } catch {
    return $false
  }
}

function Start-KquantBackend {
  if ($RestartBackend) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listenerPid in @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
      Write-Host "Stopping existing KQUANT backend on port $Port (PID $listenerPid)..." -ForegroundColor Yellow
      Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 800
  }

  if (Test-KquantOnline) {
    Write-Host "KQUANT backend is already online: $DashboardUrl" -ForegroundColor Green
    if (-not $RestartBackend) {
      Write-Host "Use -RestartBackend after code or API-key changes." -ForegroundColor DarkGray
    }
    return
  }

  Write-Host "Starting KQUANT backend in the background..." -ForegroundColor Cyan
  Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $StartScript,
    "-Port",
    $Port,
    "-HostName",
    $HostName,
    "-NoBrowser"
  ) -WorkingDirectory $Root -WindowStyle Hidden | Out-Null

  for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-KquantOnline) {
      Write-Host "KQUANT backend is online: $DashboardUrl" -ForegroundColor Green
      return
    }
    Write-Host "Waiting for backend... $i/30" -ForegroundColor DarkGray
  }
  throw "KQUANT backend did not become ready on $DashboardUrl."
}

function Refresh-AiDailyReport {
  if ($SkipAiDaily) {
    Write-Host "Skipping AI Daily refresh by request." -ForegroundColor Yellow
    return
  }

  $status = Invoke-KquantJson "/api/stocks/ai-review/status" -TimeoutSec 10
  if ($status.status -ne "available") {
    Write-Host "AI Daily refresh skipped: AI is not available ($($status.status))." -ForegroundColor Yellow
    Write-Host "Readiness will likely be NO_TRADE until OPENAI_API_KEY is loaded and backend restarted." -ForegroundColor DarkGray
    return
  }

  Write-Host "Refreshing AI Daily Opportunity report..." -ForegroundColor Cyan
  $payload = [ordered]@{
    trigger = "manual"
    cooldown_seconds = 0
    universe = $Universe
    limit = $AiLimit
    top_n = $TopN
    model_tier = "batch"
    profiles = @(
      "tactical_1w_v1",
      "swing_1_2m_v1",
      "position_6m_v1",
      "cycle_1_3y_v1",
      "high_beta_growth_v1"
    )
  }
  $report = Invoke-KquantJson "/api/stocks/ai-daily-agent" -Method "POST" -Body $payload -TimeoutSec 180
  Write-Host "AI Daily status: $($report.status); run_id=$($report.run_id); candidates=$($report.ai_context_candidate_count)" -ForegroundColor Green
  if ($report.last_error) {
    Write-Host "AI Daily last_error: $($report.last_error)" -ForegroundColor Yellow
  }
}

Write-Host "KQUANT Monday Preflight" -ForegroundColor Cyan
Write-Host "Dashboard: $DashboardUrl" -ForegroundColor DarkGray
Write-Host "Universe: $Universe / AI limit: $AiLimit / TopN: $TopN" -ForegroundColor DarkGray
Write-Host "Mode: read-only research; no broker, no account, no order path." -ForegroundColor DarkGray
Write-Host ""

Start-KquantBackend
Refresh-AiDailyReport

Write-Host ""
Write-Host "Running Monday readiness audit..." -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File $ReadinessScript -Port $Port
$readinessExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "Artifacts:" -ForegroundColor DarkGray
Write-Host "  outputs\monday-pilot-readiness.json" -ForegroundColor DarkGray
Write-Host "  outputs\monday-pilot-readiness.md" -ForegroundColor DarkGray

if (-not $NoBrowser) {
  Start-Process "$DashboardUrl/?v=monday-preflight"
}

if ($readinessExitCode -eq 0) {
  Write-Host "Preflight result: READY. Manual pilot risk limits still apply." -ForegroundColor Green
} elseif ($readinessExitCode -eq 2) {
  Write-Host "Preflight result: CAUTION. Treat as observation unless the caution is understood and journaled." -ForegroundColor Yellow
} else {
  Write-Host "Preflight result: NO_TRADE. Do not place real-money trades." -ForegroundColor Red
}

exit $readinessExitCode
