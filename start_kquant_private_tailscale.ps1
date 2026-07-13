param(
  [int]$Port = 8001,
  [switch]$NoServe
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv-win\Scripts\python.exe"
$DashboardUrl = "http://127.0.0.1:$Port"

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

function Test-LocalDashboard {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "$DashboardUrl/api/health" -TimeoutSec 5
    $health = $response.Content | ConvertFrom-Json
    return $response.StatusCode -eq 200 -and $health.status -eq "online"
  } catch {
    return $false
  }
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

if (-not (Test-Path $Python)) {
  throw "Python runtime not found: $Python"
}

Import-LocalEnv (Join-Path $Root ".env")

if (-not (Test-LocalDashboard)) {
  Start-Process -FilePath $Python `
    -ArgumentList @("-m", "btc_eth_15m.dashboard.stdlib_server", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden
  Start-Sleep -Seconds 3
}

if (-not (Test-LocalDashboard)) {
  throw "KQUANT stock terminal did not respond at $DashboardUrl/api/health"
}

$Tailscale = Get-TailscaleCli
if (-not $Tailscale) {
  throw "tailscale CLI is not installed or not on PATH. Install Tailscale and log in on this PC first."
}

$statusRaw = & $Tailscale status --json 2>$null
if (-not $statusRaw) {
  throw "tailscale status failed. Open Tailscale and sign in, then rerun this script."
}
$status = $statusRaw | ConvertFrom-Json
if ($status.BackendState -ne "Running") {
  if ($status.AuthURL) {
    Write-Host "Tailscale login required: $($status.AuthURL)" -ForegroundColor Yellow
  }
  throw "Tailscale is not running. Current state: $($status.BackendState)"
}

if (-not $NoServe) {
  & $Tailscale serve --bg --https=443 $DashboardUrl
}

$dnsName = $status.Self.DNSName
if ($dnsName) {
  $dnsName = $dnsName.TrimEnd(".")
  Write-Host "kquant private URL: https://$dnsName/"
} else {
  Write-Host "kquant local URL: $DashboardUrl"
  Write-Host "Tailscale DNS name was not available from tailscale status."
}
Write-Host "Private mode: Tailscale Serve only. Do not enable 'tailscale funnel' for this dashboard."
try {
  $marketData = (Invoke-WebRequest -UseBasicParsing "$DashboardUrl/api/stocks/market-data/status" -TimeoutSec 5).Content | ConvertFrom-Json
  Write-Host "Market data: $($marketData.provider) / $($marketData.status)" -ForegroundColor Cyan
} catch {
  Write-Host "Market data: unable to read provider status" -ForegroundColor Yellow
}
Write-Host "Safety: read-only research; no account, position, or order submission path." -ForegroundColor Green
