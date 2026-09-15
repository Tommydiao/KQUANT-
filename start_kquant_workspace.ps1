param(
  [switch]$KillExisting,
  [switch]$GatewayOnly,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CryptoRoot = Join-Path $Root "crypto"
Set-Location $Root

function Import-LocalEnv {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path -Encoding utf8 | ForEach-Object {
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

Import-LocalEnv (Join-Path $Root ".env")
Import-LocalEnv (Join-Path $CryptoRoot ".env")
$env:KQUANT_GATEWAY_WEB_DIST = Join-Path $Root "web\dist-unified"
$env:KQUANT_CRYPTO_PORT = if ($env:KQUANT_CRYPTO_PORT) { $env:KQUANT_CRYPTO_PORT } else { "8010" }
$env:KQUANT_GATEWAY_PORT = if ($env:KQUANT_GATEWAY_PORT) { $env:KQUANT_GATEWAY_PORT } else { "8020" }

if ($GatewayOnly) {
  $stockFallbackUrl = $null
  foreach ($candidatePort in @(8001, 8002)) {
    try {
      $candidateHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 2
      $candidateContract = [string]$candidateHealth.runtime.api_contract_version
      if (-not $stockFallbackUrl -and $candidateContract -like "kquant-api-*") {
        $stockFallbackUrl = "http://127.0.0.1:$candidatePort"
      }
      if ($candidateContract -eq "kquant-api-2026-09-14-options-tracking-v2") {
        $env:KQUANT_GATEWAY_STOCKS_URL = "http://127.0.0.1:$candidatePort"
        break
      }
    } catch { }
  }
  if (-not $env:KQUANT_GATEWAY_STOCKS_URL -and $stockFallbackUrl) {
    $env:KQUANT_GATEWAY_STOCKS_URL = $stockFallbackUrl
  }
  $cryptoGatewayReady = $false
  if ($env:KQUANT_GATEWAY_CRYPTO_URL) {
    try {
      $configuredHealth = Invoke-RestMethod -Uri "$($env:KQUANT_GATEWAY_CRYPTO_URL.TrimEnd('/'))/api/health" -TimeoutSec 2
      $cryptoGatewayReady = [string]$configuredHealth.api_contract_version -like "kquant-crypto-*"
    } catch { }
  }
  if (-not $cryptoGatewayReady) {
    foreach ($candidatePort in @([int]$env:KQUANT_CRYPTO_PORT, 8010, 8011) | Select-Object -Unique) {
      try {
        $candidateHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 2
        if ([string]$candidateHealth.api_contract_version -like "kquant-crypto-*") {
          $env:KQUANT_GATEWAY_CRYPTO_URL = "http://127.0.0.1:$candidatePort"
          $env:KQUANT_CRYPTO_PORT = [string]$candidatePort
          break
        }
      } catch { }
    }
  }
}

function New-ProcessToken {
  $bytes = New-Object byte[] 32
  $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
  return [Convert]::ToBase64String($bytes)
}

# These loopback-only tokens let the gateway share one browser session with
# both runtimes without copying a browser cookie into either backend. Always
# align inherited gateway aliases with the backend token so an old shell
# cannot create a split-brain local launch.
# Generate a fresh pair for every local stack launch. These are transport
# credentials between sibling processes, not user secrets; regenerating them
# prevents stale values inherited from an earlier PowerShell session from
# splitting the gateway and a backend into different trust domains.
if ($GatewayOnly) {
  if (-not $env:KQUANT_GATEWAY_STOCKS_API_TOKEN -and $env:KQUANT_API_AUTH_TOKEN) {
    $env:KQUANT_GATEWAY_STOCKS_API_TOKEN = $env:KQUANT_API_AUTH_TOKEN
  }
  if (-not $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN -and $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN) {
    $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN = $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN
  }
} else {
  $env:KQUANT_API_AUTH_TOKEN = New-ProcessToken
  $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN = New-ProcessToken
  $env:KQUANT_GATEWAY_STOCKS_API_TOKEN = $env:KQUANT_API_AUTH_TOKEN
  $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN = $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN
}

function Test-PythonExecutable {
  param([string]$Executable)
  if (-not $Executable) { return $false }
  try {
    & $Executable --version *> $null
    return $LASTEXITCODE -eq 0
  } catch { return $false }
}

function Resolve-Python {
  param([string]$ProjectRoot)
  foreach ($candidate in @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv-win\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root ".venv-win\Scripts\python.exe")
  )) {
    if ((Test-Path -LiteralPath $candidate) -and (Test-PythonExecutable $candidate)) { return $candidate }
  }
  if (Test-PythonExecutable "python") { return "python" }
  throw "No usable Python was found. Create .venv and install the project dependencies first."
}

function Get-ListenerProcesses {
  param([int]$Port)
  $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
  foreach ($listener in $listeners) {
    $process = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId = {0}' -f [int]$listener.OwningProcess) -ErrorAction SilentlyContinue
    if ($process) {
      [pscustomobject]@{ Port = $Port; ProcessId = [int]$process.ProcessId; CommandLine = [string]$process.CommandLine }
    }
  }
}

function Stop-KquantListener {
  param($Listener)
  $command = $Listener.CommandLine.ToLowerInvariant()
  if ($command -notmatch "kquant|uvicorn") {
    throw "Port $($Listener.Port) is occupied by a non-KQUANT process (PID $($Listener.ProcessId)); startup stopped."
  }
  Write-Host "Stopping old KQUANT process PID $($Listener.ProcessId) on port $($Listener.Port)..." -ForegroundColor Yellow
  Stop-Process -Id $Listener.ProcessId -Force -ErrorAction SilentlyContinue
}

$ports = if ($GatewayOnly) { @([int]$env:KQUANT_GATEWAY_PORT) } else { @(8001, [int]$env:KQUANT_CRYPTO_PORT, [int]$env:KQUANT_GATEWAY_PORT) | Select-Object -Unique }
foreach ($port in $ports) {
  foreach ($listener in @(Get-ListenerProcesses $port)) {
    if ($KillExisting) { Stop-KquantListener $listener }
    else { throw "Port $port is already in use. Re-run with -KillExisting to restart the unified workspace." }
  }
}
Start-Sleep -Milliseconds 500

$CryptoPython = Resolve-Python $CryptoRoot
$StockPython = if ($GatewayOnly) { $null } else { Resolve-Python $Root }
$LogRoot = Join-Path $Root "work\logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Start-KquantService {
  param(
    [string]$Name,
    [string]$Python,
    [string]$Arguments,
    [string]$WorkingDirectory
  )
  $stdout = Join-Path $LogRoot "$Name.out.log"
  $stderr = Join-Path $LogRoot "$Name.err.log"
  Write-Host "Starting $Name..." -ForegroundColor Cyan
  Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
}

if (-not $GatewayOnly) {
  $env:KQUANT_UNIFIED_UI_REDIRECT = "true"
  $env:KQUANT_UNIFIED_UI_URL = "http://127.0.0.1:$($env:KQUANT_GATEWAY_PORT)"
  Start-KquantService "stock" $StockPython "-m kquant.dashboard --host 127.0.0.1 --port 8001" $Root
  Start-KquantService "crypto" $CryptoPython "-m kquant_crypto serve" $CryptoRoot
}
Start-KquantService "gateway" $CryptoPython "-m kquant_crypto gateway" $CryptoRoot

function Wait-Healthy {
  param([string]$Url, [int]$Attempts = 30)
  for ($i = 0; $i -lt $Attempts; $i++) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
    } catch { }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

$gatewayUrl = "http://127.0.0.1:$($env:KQUANT_GATEWAY_PORT)/"
if (-not (Wait-Healthy "${gatewayUrl}api/workspace/health")) {
  Write-Host "The unified gateway did not respond. Check work\logs\gateway.err.log." -ForegroundColor Red
  throw "KQUANT workspace startup failed."
}

Write-Host ""
Write-Host "KQUANT unified workspace is running" -ForegroundColor Green
Write-Host "Unified URL: $gatewayUrl" -ForegroundColor Green
if ($GatewayOnly) { Write-Host "Gateway-only mode: existing stock and Crypto services were left untouched." -ForegroundColor DarkGray }
$stockFallback = if ($env:KQUANT_GATEWAY_STOCKS_URL) { $env:KQUANT_GATEWAY_STOCKS_URL } else { "http://127.0.0.1:8001" }
$cryptoFallback = if ($env:KQUANT_GATEWAY_CRYPTO_URL) { $env:KQUANT_GATEWAY_CRYPTO_URL } else { "http://127.0.0.1:$($env:KQUANT_CRYPTO_PORT)" }
Write-Host "Stock backend: $stockFallback/" -ForegroundColor DarkGray
Write-Host "Crypto backend: $cryptoFallback/" -ForegroundColor DarkGray
Write-Host "Unified frontend: web\dist-unified" -ForegroundColor DarkGray
Write-Host "Logs: work\logs" -ForegroundColor DarkGray
$loginStatus = "disabled (development mode)"
if ($env:KQUANT_WORKSPACE_LOGIN_ENABLED -eq "true") { $loginStatus = "email and password configured" }
Write-Host "Login: $loginStatus" -ForegroundColor DarkGray

if (-not $NoBrowser) { Start-Process $gatewayUrl }
Write-Host "Press Ctrl+C to stop this launcher; services log to work\logs." -ForegroundColor DarkGray
while ($true) { Start-Sleep -Seconds 3600 }
