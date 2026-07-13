param(
  [int]$Port = 8001
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardUrl = "http://127.0.0.1:$Port"
$Checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
  param([string]$Name, [bool]$Passed, [string]$Detail)
  $Checks.Add([pscustomobject]@{
    name = $Name
    passed = $Passed
    detail = $Detail
  })
}

function Get-TailscaleCli {
  $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $fallback = "C:\Program Files\Tailscale\tailscale.exe"
  if (Test-Path $fallback) {
    return $fallback
  }

  return $null
}

try {
  $healthResponse = Invoke-WebRequest -UseBasicParsing "$DashboardUrl/api/health" -TimeoutSec 5
  $health = $healthResponse.Content | ConvertFrom-Json
  Add-Check "dashboard_online" ($healthResponse.StatusCode -eq 200 -and $health.status -eq "online") "$DashboardUrl responded with $($healthResponse.StatusCode), status=$($health.status)"
  Add-Check "read_only_research" ([bool]$health.read_only_research) "read_only_research=$($health.read_only_research)"
  Add-Check "fixture_hidden" (-not [bool]$health.fixture_user_visible) "fixture_user_visible=$($health.fixture_user_visible)"
  Add-Check "broker_order_disabled" (-not [bool]$health.broker_order_wiring_enabled -and -not [bool]$health.order_submission_enabled) "broker_order_wiring_enabled=$($health.broker_order_wiring_enabled), order_submission_enabled=$($health.order_submission_enabled)"
  Add-Check "account_access_disabled" (-not [bool]$health.account_access_enabled) "account_access_enabled=$($health.account_access_enabled)"
  Add-Check "longbridge_configured" ($health.market_data.provider -eq "longbridge" -and $health.market_data.status -eq "available") "provider=$($health.market_data.provider), status=$($health.market_data.status)"
} catch {
  Add-Check "dashboard_online" $false $_.Exception.Message
  Add-Check "read_only_research" $false "Could not read KQUANT health payload."
  Add-Check "fixture_hidden" $false "Could not read KQUANT health payload."
  Add-Check "broker_order_disabled" $false "Could not read KQUANT health payload."
  Add-Check "account_access_disabled" $false "Could not read KQUANT health payload."
  Add-Check "longbridge_configured" $false "Could not read KQUANT health payload."
}

try {
  $outputs = Join-Path $Root "outputs"
  New-Item -ItemType Directory -Path $outputs -Force | Out-Null
  $probe = Join-Path $outputs ".pilot-journal-write-check.tmp"
  "ok" | Set-Content -Path $probe -Encoding UTF8
  Remove-Item -Path $probe -Force
  Add-Check "journal_writable" $true "outputs folder is writable."
} catch {
  Add-Check "journal_writable" $false $_.Exception.Message
}

try {
  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
  $localOnly = $listeners | Where-Object { $_.LocalAddress -in @("127.0.0.1", "::1") }
  Add-Check "dashboard_bound_localhost" ([bool]$localOnly) (($listeners | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress))
} catch {
  Add-Check "dashboard_bound_localhost" $false $_.Exception.Message
}

$tailscale = Get-TailscaleCli
Add-Check "tailscale_cli_installed" ([bool]$tailscale) ($(if ($tailscale) { $tailscale } else { "tailscale not found on PATH or Program Files" }))

if ($tailscale) {
  try {
    $statusRaw = & $tailscale status --json 2>$null
    $status = $statusRaw | ConvertFrom-Json
    Add-Check "tailscale_running" ($status.BackendState -eq "Running") "BackendState=$($status.BackendState)"
    if ($status.Self.DNSName) {
      Add-Check "tailscale_dns_name" $true $status.Self.DNSName.TrimEnd(".")
    } else {
      Add-Check "tailscale_dns_name" $false "No DNSName in tailscale status."
    }
  } catch {
    Add-Check "tailscale_running" $false $_.Exception.Message
  }

  try {
    $serveStatus = & $tailscale serve status 2>&1 | Out-String
    Add-Check "tailscale_serve_status" ($serveStatus -match "127\.0\.0\.1:$Port|localhost:$Port|:$Port") ($serveStatus.Trim())
  } catch {
    Add-Check "tailscale_serve_status" $false $_.Exception.Message
  }
} else {
  Add-Check "tailscale_running" $false "tailscale CLI missing."
  Add-Check "tailscale_dns_name" $false "tailscale CLI missing."
  Add-Check "tailscale_serve_status" $false "tailscale CLI missing."
}

$Checks | Format-Table -AutoSize
$failed = @($Checks | Where-Object { -not $_.passed })
if ($failed.Count) {
  Write-Host ""
  Write-Host "Private access check failed: $($failed.Count) item(s)." -ForegroundColor Yellow
  exit 1
}

Write-Host ""
Write-Host "Private access check passed." -ForegroundColor Green
