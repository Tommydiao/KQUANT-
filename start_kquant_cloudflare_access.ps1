param(
  [int]$Port = 8001,
  [string]$HostName = "",
  [string]$TunnelName = "",
  [switch]$NoDashboardStart
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardUrl = "http://127.0.0.1:$Port"

function Import-LocalEnv {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $name, $value = $line.Split("=", 2)
    $name = $name.Trim()
    $value = $value.Trim().Trim('"').Trim("'")
    if ($name -and $value -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

function Get-PythonRuntime {
  foreach ($candidate in @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root ".venv-win\Scripts\python.exe")
  )) {
    if (Test-Path $candidate) { return $candidate }
  }
  $command = Get-Command python -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  return $null
}

function Get-CloudflaredCli {
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $fallback = "C:\Program Files\cloudflared\cloudflared.exe"
  if (Test-Path $fallback) {
    return $fallback
  }

  return $null
}

function Test-LocalDashboard {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "$DashboardUrl/api/health" -TimeoutSec 6
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

Import-LocalEnv (Join-Path $Root ".env")
$Python = Get-PythonRuntime
if (-not $HostName) { $HostName = $env:KQUANT_CLOUDFLARE_HOSTNAME }
if (-not $TunnelName) { $TunnelName = $env:KQUANT_CLOUDFLARE_TUNNEL_NAME }

if (-not $HostName) {
  throw "Set KQUANT_CLOUDFLARE_HOSTNAME, for example kquant-api.yourdomain.com. Protect that hostname with Cloudflare Access before using it from Vercel."
}

if (-not $TunnelName) {
  throw "Set KQUANT_CLOUDFLARE_TUNNEL_NAME to your named Cloudflare Tunnel. Create it in Cloudflare Zero Trust > Networks > Tunnels."
}

if (-not $Python) {
  throw "Python runtime not found. Create .venv or install Python."
}

Set-Location $Root

if (-not $NoDashboardStart -and -not (Test-LocalDashboard)) {
  Start-Process -FilePath $Python `
    -ArgumentList @("-m", "kquant.dashboard", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden
  Start-Sleep -Seconds 3
}

if (-not (Test-LocalDashboard)) {
  throw "KQUANT dashboard API did not respond at $DashboardUrl/api/health"
}

$Cloudflared = Get-CloudflaredCli
if (-not $Cloudflared) {
  throw "cloudflared CLI is not installed or not on PATH. Install it from Cloudflare Tunnel downloads, then rerun this script."
}

Write-Host "KQUANT local API: $DashboardUrl" -ForegroundColor Cyan
Write-Host "Cloudflare hostname: https://$HostName" -ForegroundColor Green
Write-Host "Tunnel: $TunnelName" -ForegroundColor DarkGray
Write-Host "Required Vercel env: VITE_KQUANT_API_BASE_URL=https://$HostName" -ForegroundColor Yellow
Write-Host "Access policy reminder: protect $HostName with Cloudflare Access. Do not use an unprotected public hostname." -ForegroundColor Yellow

& $Cloudflared tunnel --url $DashboardUrl run $TunnelName
