param(
  [int]$Port = 8001,
  [string]$HostName = "127.0.0.1",
  [switch]$KillExisting,
  [switch]$RequireLongbridge,
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

function Import-UserEnv {
  param([string[]]$Names)
  foreach ($name in $Names) {
    if ([Environment]::GetEnvironmentVariable($name, "Process")) {
      continue
    }
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

Import-UserEnv @(
  "OPENAI_API_KEY",
  "KQUANT_AI_REVIEW_MODEL",
  "KQUANT_AI_BATCH_MODEL",
  "KQUANT_AI_DEEP_MODEL",
  "KQUANT_AI_RESEARCH_MODEL",
  "KQUANT_MARKET_DATA_PROVIDER",
  "LONGBRIDGE_APP_KEY",
  "LONGBRIDGE_APP_SECRET",
  "LONGBRIDGE_ACCESS_TOKEN",
  "LONGBRIDGE_PRINT_QUOTE_PACKAGES",
  "KQUANT_LONGBRIDGE_TIMEOUT_SECONDS"
)
Import-LocalEnv (Join-Path $Root ".env")
if (-not $env:LONGBRIDGE_PRINT_QUOTE_PACKAGES) {
  $env:LONGBRIDGE_PRINT_QUOTE_PACKAGES = "false"
}
if (-not $env:KQUANT_MARKET_DATA_PROVIDER -and $env:LONGBRIDGE_APP_KEY -and $env:LONGBRIDGE_APP_SECRET -and $env:LONGBRIDGE_ACCESS_TOKEN) {
  $env:KQUANT_MARKET_DATA_PROVIDER = "longbridge"
}

$missingLongbridge = @(
  "LONGBRIDGE_APP_KEY",
  "LONGBRIDGE_APP_SECRET",
  "LONGBRIDGE_ACCESS_TOKEN"
) | Where-Object { -not [Environment]::GetEnvironmentVariable($_, "Process") }

if ($RequireLongbridge) {
  if ($missingLongbridge.Count -gt 0) {
    Write-Host "KQUANT realtime startup requires Longbridge credentials." -ForegroundColor Red
    Write-Host "Missing: $($missingLongbridge -join ', ')" -ForegroundColor Yellow
    Write-Host "Run .\KQUANT_SETUP_LONGBRIDGE.cmd, then start KQUANT again." -ForegroundColor Green
    throw "KQUANT realtime startup blocked: Longbridge credentials are missing."
  }
  $env:KQUANT_MARKET_DATA_PROVIDER = "longbridge"
}

function Test-PythonExecutable {
  param([string]$Executable)
  if (-not $Executable) {
    return $false
  }
  try {
    $result = & $Executable --version 2>&1
    return ($LASTEXITCODE -eq 0 -and ($result -join " ") -match "Python")
  } catch {
    return $false
  }
}

function Resolve-KquantPython {
  $venvPython = Join-Path $Root ".venv-win\Scripts\python.exe"
  if ((Test-Path $venvPython) -and (Test-PythonExecutable $venvPython)) {
    return $venvPython
  }

  if (Test-PythonExecutable "python") {
    return "python"
  }

  try {
    $pyList = & py -0p 2>$null
    if ($LASTEXITCODE -eq 0) {
      $candidate = @($pyList | Where-Object { $_ -match "python\.exe" } | Select-Object -First 1)
      if ($candidate -and (Test-PythonExecutable $candidate)) {
        return $candidate
      }
    }
  } catch {
    # Keep falling through to the setup guidance below.
  }

  Write-Host "No usable Python runtime was found for KQUANT." -ForegroundColor Red
  Write-Host "Install Python 3.12, then recreate the local environment:" -ForegroundColor Yellow
  Write-Host "  Remove-Item -Recurse -Force .\.venv-win" -ForegroundColor DarkGray
  Write-Host "  python -m venv .venv-win" -ForegroundColor DarkGray
  Write-Host "  .\.venv-win\Scripts\python -m pip install --upgrade pip" -ForegroundColor DarkGray
  Write-Host "  .\.venv-win\Scripts\python -m pip install -e `".[dev]`"" -ForegroundColor DarkGray
  throw "KQUANT startup blocked: Python runtime missing."
}

$Url = "http://$HostName`:$Port/"
function Test-KquantDashboardOnline {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "$Url/api/health" -TimeoutSec 3
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
      return $true
    }
  } catch {
    return $false
  }
  return $false
}

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

if (Test-KquantDashboardOnline) {
  Write-Host "KQUANT backend is already online at $Url" -ForegroundColor Green
  if ($KillExisting) {
    Write-Host "Could not identify the listener PID through Windows TCP APIs; reusing the online backend." -ForegroundColor Yellow
    Write-Host "If you need a hard restart after changing Python or API keys, close the existing KQUANT terminal window first." -ForegroundColor DarkGray
  }
  if (-not $NoBrowser) {
    Start-Process $Url
  }
  exit 0
}

$Python = Resolve-KquantPython

Write-Host "Starting KQUANT US Stock Signal Terminal..." -ForegroundColor Cyan
Write-Host "URL: $Url" -ForegroundColor Green
Write-Host "Database: work/kquant_us.sqlite3" -ForegroundColor DarkGray
Write-Host "Mode: read-only stock research" -ForegroundColor DarkGray
Write-Host "Python: $Python" -ForegroundColor DarkGray
if ($env:OPENAI_API_KEY) {
  Write-Host "AI Review: enabled from backend environment" -ForegroundColor Green
  $researchModel = if ($env:KQUANT_AI_RESEARCH_MODEL) { $env:KQUANT_AI_RESEARCH_MODEL } elseif ($env:KQUANT_AI_DEEP_MODEL) { $env:KQUANT_AI_DEEP_MODEL } else { "gpt-5.5-pro" }
  Write-Host "Deep Research Chat: $researchModel" -ForegroundColor Green
} else {
  Write-Host "AI Review: missing OPENAI_API_KEY (manual review button will show setup guidance)" -ForegroundColor Yellow
}
if ($env:KQUANT_MARKET_DATA_PROVIDER -eq "longbridge") {
  if ($env:LONGBRIDGE_APP_KEY -and $env:LONGBRIDGE_APP_SECRET -and $env:LONGBRIDGE_ACCESS_TOKEN) {
    Write-Host "Longbridge market data: available from backend environment" -ForegroundColor Green
  } else {
    Write-Host "Longbridge market data: missing one or more env vars" -ForegroundColor Yellow
    if ($RequireLongbridge) {
      throw "KQUANT realtime startup blocked: Longbridge credentials are incomplete."
    }
  }
} else {
  Write-Host "Market data provider: Yahoo public prototype (set KQUANT_MARKET_DATA_PROVIDER=longbridge for realtime)" -ForegroundColor Yellow
  if ($RequireLongbridge) {
    throw "KQUANT realtime startup blocked: Longbridge is not the active provider."
  }
}

if (-not $NoBrowser) {
  Start-Process $Url
}

& $Python -m btc_eth_15m.dashboard.stdlib_server --host $HostName --port $Port
