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
if (-not $env:LONGBRIDGE_PRINT_QUOTE_PACKAGES) {
  $env:LONGBRIDGE_PRINT_QUOTE_PACKAGES = "false"
}
if (-not $env:KQUANT_MARKET_DATA_PROVIDER -and $env:LONGBRIDGE_APP_KEY -and $env:LONGBRIDGE_APP_SECRET -and $env:LONGBRIDGE_ACCESS_TOKEN) {
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
  $venvCandidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root ".venv-win\Scripts\python.exe")
  )
  foreach ($venvPython in $venvCandidates) {
    if ((Test-Path $venvPython) -and (Test-PythonExecutable $venvPython)) {
      return $venvPython
    }
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
  Write-Host "Install Python 3.12, then create the local environment:" -ForegroundColor Yellow
  Write-Host "  python -m venv .venv" -ForegroundColor DarkGray
  Write-Host "  .\.venv\Scripts\python -m pip install --upgrade pip" -ForegroundColor DarkGray
  Write-Host "  .\.venv\Scripts\python -m pip install -e `".[dev]`"" -ForegroundColor DarkGray
  throw "KQUANT startup blocked: Python runtime missing."
}

$Url = "http://$HostName`:$Port/"
$ExpectedApiContract = "kquant-api-2026-08-09-early-trend-push-v1"
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

function Get-KquantRuntimeProcessIds {
  param([int]$ListenerPid)
  $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $byId = @{}
  foreach ($process in $all) { $byId[[int]$process.ProcessId] = $process }
  $ids = [System.Collections.Generic.HashSet[int]]::new()
  $current = $byId[$ListenerPid]
  while ($null -ne $current) {
    if ([string]$current.CommandLine -match "kquant\.dashboard") {
      [void]$ids.Add([int]$current.ProcessId)
    }
    $current = $byId[[int]$current.ParentProcessId]
  }
  if ($ids.Count -eq 0) { [void]$ids.Add($ListenerPid) }
  return @($ids)
}

function Stop-KquantRuntime {
  param([int]$ListenerPid)
  foreach ($processId in (Get-KquantRuntimeProcessIds $ListenerPid)) {
    Write-Host "Stopping existing KQUANT runtime on port $Port (PID $processId)..." -ForegroundColor Yellow
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  }
}

function Get-ApiContractVersion {
  try {
    $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 3
    return [string]$health.runtime.api_contract_version
  } catch {
    return ""
  }
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
  $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($KillExisting) {
    foreach ($listenerPid in $pids) {
      Stop-KquantRuntime $listenerPid
    }
    Start-Sleep -Milliseconds 900
    if (@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
      throw "KQUANT startup blocked: port $Port is still in use. Close the old KQUANT terminal, then run this command again."
    }
  } else {
    Write-Host "KQUANT appears to already be running on $Url" -ForegroundColor Green
    $contract = Get-ApiContractVersion
    if ($contract -ne $ExpectedApiContract) {
      Write-Host "The running backend is an older build ($contract). Restart with -KillExisting to load the current KQUANT code." -ForegroundColor Yellow
    } else {
      Write-Host "Use -KillExisting if you need to restart after code or API key changes." -ForegroundColor DarkGray
    }
    if (-not $NoBrowser) {
      Start-Process $Url
    }
    exit 0
  }
}

if (Test-KquantDashboardOnline) {
  Write-Host "KQUANT backend is already online at $Url" -ForegroundColor Green
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
if ($env:KQUANT_LOGIN_ENABLED -eq "true") {
  if ($env:KQUANT_LOGIN_EMAIL -and $env:KQUANT_LOGIN_PASSWORD_HASH -and $env:KQUANT_SESSION_SECRET) {
    Write-Host "Local email-and-password login: enabled" -ForegroundColor Green
  } else {
    Write-Host "Local email-and-password login: enabled but incomplete. Run python -m kquant local-login-config." -ForegroundColor Yellow
  }
}
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
  }
} else {
  Write-Host "Market data provider: Yahoo public prototype (set KQUANT_MARKET_DATA_PROVIDER=longbridge for realtime)" -ForegroundColor Yellow
}

if (-not $NoBrowser) {
  Start-Process $Url
}

& $Python -m kquant.dashboard --host $HostName --port $Port
